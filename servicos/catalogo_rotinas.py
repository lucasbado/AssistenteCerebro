"""Um catálogo transacional para descoberta, gestão e execução de rotinas."""
import asyncio
from copy import deepcopy
import json
import hashlib
import uuid
from datetime import datetime
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from banco.database import AsyncSessionLocal
from banco.models import CatalogoRotinasDB
from servicos.routine_paths import ACTIVE_PATH, DISCOVERED_PATH, REJECTED_PATH
from servicos.contrato_rotinas import chave_nome, assinatura_rotina, validar_rotina


class CatalogoRotinas:
    def __init__(self, caminhos=None):
        self.snapshot = Path(ACTIVE_PATH).parent / "migracao_rotinas.json" if caminhos is None else None
        self.caminhos = caminhos if caminhos is not None else {
            "ativas": ACTIVE_PATH, "descobertas": DISCOVERED_PATH, "rejeitadas": REJECTED_PATH}
        self._lock = asyncio.Lock()

    def _importar(self):
        snapshot = json.loads(self.snapshot.read_text(encoding="utf-8")) if self.snapshot and self.snapshot.exists() else None
        dados = {}
        for estado in ("ativas", "descobertas", "rejeitadas"):
            path = self.caminhos.get(estado)
            registros = snapshot[estado] if snapshot is not None else (
                json.loads(Path(path).read_text(encoding="utf-8")) if path and Path(path).exists() else [])
            if not isinstance(registros, list) or not all(isinstance(r, dict) and r.get("nome") for r in registros):
                raise ValueError(f"Catálogo inicial inválido: {estado}")
            dados[estado] = registros
        return dados

    async def _transacao(self, alterar=None):
        async with self._lock:
            for tentativa in range(2):
                try:
                    async with AsyncSessionLocal() as session, session.begin():
                        registro = (await session.execute(select(CatalogoRotinasDB)
                            .where(CatalogoRotinasDB.id == 1).with_for_update())).scalar_one_or_none()
                        if registro is None:
                            registro = CatalogoRotinasDB(id=1, versao=1, dados=self._importar())
                            session.add(registro)
                            await session.flush()
                        dados = deepcopy(registro.dados)
                        resultado = alterar(dados) if alterar else deepcopy(dados)
                        if alterar:
                            registro.dados = dados
                            registro.versao += 1
                        return resultado
                except IntegrityError:
                    if tentativa:
                        raise

    async def listar(self, estado):
        return (await self._transacao())[estado]

    async def existentes(self):
        dados = await self._transacao()
        return [r for estado in ("ativas", "descobertas", "rejeitadas") for r in dados[estado]]

    async def adicionar_sugestoes(self, novas):
        def alterar(dados):
            existentes = [r for estado in ("ativas", "descobertas", "rejeitadas") for r in dados[estado]]
            nomes = {chave_nome(r["nome"]) for r in existentes}
            assinaturas = {assinatura_rotina(r) for r in existentes}
            total = 0
            for nova in novas:
                nome, assinatura = chave_nome(nova["nome"]), assinatura_rotina(nova)
                if nome in nomes or assinatura in assinaturas:
                    continue
                dados["descobertas"].append({**deepcopy(nova), "ativa": False, "importancia_abertura": 0})
                nomes.add(nome); assinaturas.add(assinatura); total += 1
            return total
        return await self._transacao(alterar)

    @staticmethod
    def _encontrar(lista, nome):
        rotina = next((r for r in lista if chave_nome(r["nome"]) == chave_nome(nome)), None)
        if rotina is None:
            raise LookupError("Essa rotina não foi encontrada. Atualize a lista.")
        return rotina

    async def aprovar(self, nome):
        def alterar(dados):
            alvo = self._encontrar(dados["descobertas"], nome)
            rotina = validar_rotina(alvo)
            if any(chave_nome(r["nome"]) == chave_nome(nome) for r in dados["ativas"]):
                raise ValueError("Já existe uma rotina cadastrada com esse nome.")
            dados["ativas"].append({**rotina, "ativa": True, "importancia_abertura": 0})
            dados["descobertas"].remove(alvo)
            return {"status": "success", "message": "Rotina ativada. Ela aguardará o próximo gatilho compatível."}
        return await self._transacao(alterar)

    async def rejeitar(self, nome, estado="descobertas"):
        def alterar(dados):
            rotina = self._encontrar(dados[estado], nome)
            dados[estado].remove(rotina)
            dados["rejeitadas"].append({**rotina, "ativa": False})
            return {"status": "success", "message": "Rotina removida. Esse padrão não será sugerido novamente."}
        return await self._transacao(alterar)

    async def definir_ativa(self, nome, ativa, importancia_abertura=None):
        def alterar(dados):
            rotina = self._encontrar(dados["ativas"], nome)
            if importancia_abertura is not None:
                rotina["importancia_abertura"] = importancia_abertura
            if ativa:
                normalizada = validar_rotina(rotina)
                rotina.update(normalizada)
            rotina["ativa"] = ativa
            return {"status": "success", "message": "Rotina ativada." if ativa else "Rotina pausada."}
        return await self._transacao(alterar)

    async def adicionar(self, rotina):
        nova = validar_rotina(rotina)
        def alterar(dados):
            if any(chave_nome(r["nome"]) == chave_nome(nova["nome"]) for r in dados["ativas"]):
                raise ValueError("Já existe uma rotina cadastrada com esse nome.")
            dados["ativas"].append(nova)
            return {"status": "success", "message": "Rotina salva."}
        return await self._transacao(alterar)

    async def reservar_execucao(self, rotina, agora):
        """Reserva antes de publicar; o cooldown sobrevive a reinícios do executor."""
        from servicos.tempo import horario_local
        chave = hashlib.sha256(assinatura_rotina(rotina).encode()).hexdigest()
        token = str(uuid.uuid4())
        def alterar(dados):
            atual = next((r for r in dados["ativas"] if chave_nome(r["nome"]) == chave_nome(rotina["nome"])), None)
            if not atual or not atual.get("ativa") or assinatura_rotina(atual) != assinatura_rotina(rotina):
                return None
            execucoes = dados.setdefault("execucoes", {})
            antiga = execucoes.get(chave)
            if antiga:
                ultima = datetime.fromisoformat(antiga["timestamp"])
                if ((agora - ultima).total_seconds() < float(rotina.get("cooldown_segundos", 3600)) or
                      (rotina.get("uma_vez_por_dia") and horario_local(ultima).date() == horario_local(agora).date())):
                    return None
            execucoes[chave] = {"token": token, "timestamp": agora.isoformat(), "pendente": True}
            return chave, token
        return await self._transacao(alterar)

    async def concluir_reserva(self, reserva, encaminhada):
        chave, token = reserva
        def alterar(dados):
            execucoes = dados.setdefault("execucoes", {})
            registro = execucoes.get(chave)
            if not registro or registro["token"] != token:
                return
            if encaminhada:
                registro["pendente"] = False
            else:
                del execucoes[chave]
        await self._transacao(alterar)


catalogo_rotinas = CatalogoRotinas()
