"""Executor de rotinas aprovadas, com recarga e proteção contra repetição."""
import asyncio
import logging
import os
from datetime import datetime, timezone

from core.evento import EventoCanonico
from core.kernel import kernel
from core.tipos import CategoriaEvento, OrigemEvento, TipoAcao
from servicos.atividade import processo_pc
from servicos.catalogo_rotinas import catalogo_rotinas
from servicos.contrato_rotinas import validar_rotina
from servicos.tempo import horario_local, utc

logger = logging.getLogger("AgenteRotina")


class AgenteRotina:
    def __init__(self):
        self.catalogo = catalogo_rotinas
        self.routines = []
        self._lock = asyncio.Lock()

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
            self.routines = await self.catalogo.listar("ativas")
            if evento.payload.get("comando") == "criar_rotina":
                rotina = evento.payload.get("rotina")
                if rotina:
                    await self.catalogo.adicionar(rotina)
                return
            agora = utc(evento.timestamp)
            for rotina in self.routines:
                try:
                    if not rotina.get("ativa", False):
                        continue
                    rotina = validar_rotina(rotina)
                    if not self._validar_gatilho(rotina.get("gatilho", {}), evento):
                        continue
                    reserva = await self.catalogo.reservar_execucao(rotina, agora)
                    if reserva is None:
                        continue
                    encaminhada = False
                    try:
                        encaminhada = await self._executar_acoes(rotina.get("acoes", []), evento, rotina.get("nome", "Rotina"))
                    finally:
                        await self.catalogo.concluir_reserva(reserva, encaminhada)
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
        from api.websocket import central_alertas
        nuvem = os.getenv("RENDER", "false").lower() in {"true", "1", "yes"} or os.name != "nt"
        destinos = {acao.get("alvo") for acao in acoes}
        if (("PC" in destinos and nuvem and not central_alertas.pc_master) or
                ("MOBILE" in destinos and not central_alertas.mobile_client)):
            logger.info("Rotina %s aguarda os dispositivos necessários; nenhuma ação foi encaminhada", nome)
            return False
        from servicos.intervention_governor import e_abertura, intervention_governor
        from servicos.abertura_apps import sugerir_abertura, metadados_abertura
        acoes = [a for a in acoes if not (
            a.get("alvo") == "PC" and a.get("comando") == "abrir_app"
            and evento_origem.categoria == CategoriaEvento.PC_ACTIVITY
            and processo_pc(evento_origem.payload) == str(a.get("parametro")).lower())]
        aberturas = [(i, a) for i, a in enumerate(acoes) if e_abertura(a.get("comando"))]
        if len(aberturas) > 1:
            # Não reservar uma abertura e abandonar a rotina ao negar a seguinte.
            primeira = aberturas[0][1]
            await sugerir_abertura(evento_origem, primeira.get("alvo"), primeira.get("comando"),
                                   primeira.get("parametro"), "rotina_com_varias_aberturas")
            return True
        autorizacoes = {}
        rotina = next((r for r in self.routines if r.get("nome") == nome), {})
        for indice, acao in enumerate(acoes):
            if e_abertura(acao.get("comando")):
                decisao = await intervention_governor.avaliar_abertura(acao.get("parametro"), acao.get("alvo"),
                    rotina.get("importancia_abertura", 0))
                if not decisao["permitida"]:
                    await sugerir_abertura(evento_origem, acao.get("alvo"), acao.get("comando"), acao.get("parametro"), decisao["motivo"])
                    return True
                autorizacoes[indice] = metadados_abertura(decisao)
        executou = False
        for indice, acao in enumerate(acoes):
            try:
                alvo, comando, param = acao.get("alvo"), acao.get("comando"), acao.get("parametro")
                if alvo == "PC":
                    if comando == "abrir_app" and evento_origem.categoria == CategoriaEvento.PC_ACTIVITY and processo_pc(evento_origem.payload) == str(param).lower():
                        continue
                    await kernel.publicar(evento_origem.clonar(
                        categoria=CategoriaEvento.SISTEMA_COMANDO_PC, acao=TipoAcao.NORMAL,
                        origem=OrigemEvento.SISTEMA, pacote="sistema.rotina",
                        payload={"comando": comando, "parametro": param},
                        metadados={"rotina_aprovada": nome, **autorizacoes.get(indice, {})}))
                elif alvo == "IA":
                    payload = {"titulo": nome, "texto": param, "tipo_ws": "NOTIFICACAO",
                               "tipo_interacao": comando, "chave_deduplicacao": f"rotina:{nome}"}
                    payload.update({k: acao[k] for k in ("acao_tipo", "acao_parametro", "acao_texto") if acao.get(k)})
                    await kernel.publicar(evento_origem.clonar(
                        categoria=CategoriaEvento.INTENCAO_NOTIFICACAO, acao=TipoAcao.INTENCAO_INTERACAO,
                        origem=OrigemEvento.IA, pacote="sistema.rotina", payload=payload,
                        metadados={"tipo_destino": "NOTIFICACAO", "rotina_aprovada": nome}))
                elif alvo == "CASA":
                    from servicos.controle_casa import ACOES
                    await kernel.publicar(evento_origem.clonar(
                        categoria=CategoriaEvento.CASA_ACAO_SOLICITADA, origem=OrigemEvento.SISTEMA,
                        payload={"acao": ACOES[comando.lower()], "alvo": param},
                        metadados={"rotina_aprovada": nome}))
                elif alvo == "MOBILE":
                    await central_alertas._enviar_direto(central_alertas.mobile_client,
                        {"tipo_ws": "COMANDO_SISTEMA", "acao": comando, "parametro": param,
                         "id_comando": evento_origem.id, **autorizacoes.get(indice, {})})
                else:
                    continue
                executou = True
            except Exception:
                logger.exception("Erro ao executar ação da rotina %s", nome)
        return executou
