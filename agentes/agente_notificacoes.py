# agentes/agente_notificacoes.py
import logging
from core.evento import EventoCanonico
from core.tipos import CategoriaEvento
from core.kernel import kernel
from api.websocket import central_alertas
from servicos.notificacoes import PoliticaNotificacoes

logger = logging.getLogger("AgenteNotificacoes")


class AgenteNotificacoes:
    def __init__(self):
        self.politica = PoliticaNotificacoes()

    async def processar(self, evento: EventoCanonico):
        payload, motivo = self.politica.preparar(evento)
        if payload is None:
            logger.info("Notificação %s suprimida: %s", evento.id, motivo)
            return
        dados = evento.model_dump()
        dados["payload"] = payload
        await central_alertas.enviar_alerta(dados)
        # Registra o encaminhamento após o filtro. Intenção suprimida não é entrega.
        await kernel.publicar(evento.clonar(
            categoria=CategoriaEvento.NOTIFICACAO_PRONTA_PARA_ENVIO,
            payload={**payload, "status_envio": "encaminhada"}))

        logger.info(f"🔔 Notificação enviada ao dispositivo: {evento.payload.get('titulo', 'Assistente')}")
