"""Executor de rotinas aprovadas, com recarga e proteção contra repetição."""
import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone

from core.evento import EventoCanonico
from core.kernel import kernel
from core.tipos import CategoriaEvento, OrigemEvento, TipoAcao
from servicos.atividade import processo_pc
from servicos.routine_paths import ACTIVE_PATH, salvar_json
from servicos.tempo import horario_local, utc

logger = logging.getLogger("AgenteRotina")


class AgenteRotina:
    def __init__(self):
        self.config_path = ACTIVE_PATH
        self.routines = []
        self._versao = None
        self._execucoes = {}
        self._lock = asyncio.Lock()
        self._carregar_rotinas()

    def _carregar_rotinas(self):
        try:
            stat = os.stat(self.config_path)
            versao = (stat.st_mtime_ns, stat.st_size)
            if versao == self._versao:
                return
            with open(self.config_path, encoding="utf-8") as arquivo:
                rotinas = json.load(arquivo)
            if not isinstance(rotinas, list):
                raise ValueError("O arquivo de rotinas deve conter uma lista.")
            self.routines = rotinas
            self._versao = versao
        except FileNotFoundError:
            self.routines = []
            self._versao = None
        except (ValueError, OSError):
            logger.exception("Falha ao recarregar rotinas; mantendo a última versão válida")

    def _salvar_rotinas(self):
        salvar_json(self.config_path, self.routines)
        self._versao = None

    async def processar(self, evento: EventoCanonico):
        if evento.payload.get("tipo") == "REFLEXAO_ROTINA":
            from servicos.routine_generator_service import routine_generator_service
            await routine_generator_service.run_batch_generation()
            return
        # Replays e respostas produzidas por agentes não são novas aberturas.
        if evento.acao != TipoAcao.NORMAL or evento.origem == OrigemEvento.IA:
            return
        if abs((datetime.now(timezone.utc) - utc(evento.timestamp)).total_seconds()) > 300:
            return
        async with self._lock:
            self._carregar_rotinas()
            if evento.payload.get("comando") == "criar_rotina":
                rotina = evento.payload.get("rotina")
                if rotina and not any(r.get("nome") == rotina.get("nome") for r in self.routines):
                    self.routines.append(dict(rotina))
                    self._salvar_rotinas()
                return
            agora = utc(evento.timestamp)
            self._execucoes = {k: ts for k, ts in self._execucoes.items() if agora - ts < timedelta(days=2)}
            for rotina in self.routines:
                try:
                    if not rotina.get("ativa", True) or not self._validar_gatilho(rotina.get("gatilho", {}), evento):
                        continue
                    chave = json.dumps([rotina.get("gatilho"), rotina.get("acoes")], sort_keys=True)
                    ultima = self._execucoes.get(chave)
                    cooldown = max(60, float(rotina.get("cooldown_segundos", 3600)))
                    if ultima and ((agora - ultima).total_seconds() < cooldown or
                            (rotina.get("uma_vez_por_dia") and horario_local(ultima).date() == horario_local(agora).date())):
                        continue
                    if await self._executar_acoes(rotina.get("acoes", []), evento, rotina.get("nome", "Rotina")):
                        self._execucoes[chave] = agora
                except (ValueError, TypeError, KeyError):
                    logger.exception("Rotina inválida: %s", rotina.get("nome"))

    def _validar_gatilho(self, gatilho, evento):
        tipo = gatilho.get("tipo")
        if tipo == "APP_OPENED":
            return (evento.categoria == CategoriaEvento.APP_FOREGROUND
                    and not evento.payload.get("heartbeat")
                    and bool(gatilho.get("pacote")) and evento.pacote == gatilho["pacote"])
        if tipo == "PC_ACTIVITY":
            processo = str(gatilho.get("processo") or "").lower()
            return bool(processo) and evento.categoria == CategoriaEvento.PC_ACTIVITY and processo_pc(evento.payload) == processo
        if tipo == "EVENTO_SISTEMA":
            return (bool(gatilho.get("evento")) and evento.categoria == CategoriaEvento.SISTEMA_COMANDO_INTERNO
                    and (evento.payload.get("alvo") or evento.payload.get("tipo")) == gatilho["evento"])
        if tipo == "TIME_RANGE":
            try:
                inicio = datetime.strptime(gatilho["inicio"], "%H:%M").time()
                fim = datetime.strptime(gatilho["fim"], "%H:%M").time()
            except (ValueError, KeyError, TypeError):
                return False
            agora = horario_local(evento.timestamp).time().replace(second=0, microsecond=0)
            dentro = inicio <= agora <= fim if inicio <= fim else agora >= inicio or agora <= fim
            secundario = gatilho.get("evento") or "TICK_ROTINA"
            if secundario == "PC_ACTIVITY":
                return dentro and evento.categoria == CategoriaEvento.PC_ACTIVITY
            return dentro and self._validar_gatilho({"tipo": "EVENTO_SISTEMA", "evento": secundario}, evento)
        return False

    async def _executar_acoes(self, acoes, evento_origem, nome="Rotina"):
        executou = False
        for acao in acoes:
            try:
                alvo, comando, param = acao.get("alvo"), acao.get("comando"), acao.get("parametro")
                if alvo == "PC":
                    from api.websocket import central_alertas
                    nuvem = os.getenv("RENDER", "false").lower() in {"true", "1", "yes"} or os.name != "nt"
                    if nuvem and not central_alertas.pc_master:
                        continue
                    if comando == "abrir_app" and evento_origem.categoria == CategoriaEvento.PC_ACTIVITY and processo_pc(evento_origem.payload) == str(param).lower():
                        continue
                    await kernel.publicar(evento_origem.clonar(
                        categoria=CategoriaEvento.SISTEMA_COMANDO_PC, acao=TipoAcao.NORMAL,
                        origem=OrigemEvento.SISTEMA, pacote="sistema.rotina",
                        payload={"comando": comando, "parametro": param},
                        metadados={"rotina_aprovada": nome}))
                elif alvo == "IA":
                    payload = {"titulo": nome, "texto": param, "tipo_ws": "NOTIFICACAO",
                               "tipo_interacao": comando, "chave_deduplicacao": f"rotina:{nome}"}
                    payload.update({k: acao[k] for k in ("acao_tipo", "acao_parametro", "acao_texto") if acao.get(k)})
                    await kernel.publicar(evento_origem.clonar(
                        categoria=CategoriaEvento.INTENCAO_NOTIFICACAO, acao=TipoAcao.INTENCAO_INTERACAO,
                        origem=OrigemEvento.IA, pacote="sistema.rotina", payload=payload,
                        metadados={"tipo_destino": "NOTIFICACAO", "rotina_aprovada": nome}))
                elif alvo == "MOBILE":
                    from api.websocket import central_alertas
                    if not central_alertas.mobile_client:
                        continue
                    await central_alertas._enviar_direto(central_alertas.mobile_client,
                        {"tipo_ws": "COMANDO_SISTEMA", "acao": comando, "parametro": param})
                else:
                    continue
                executou = True
            except Exception:
                logger.exception("Erro ao executar ação da rotina %s", nome)
        return executou
