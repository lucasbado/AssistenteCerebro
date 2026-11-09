"""Mantém o contexto meteorológico atualizado e notifica sobre chuva."""
import logging

from agentes.agente_memoria_trabalho import AgenteMemoriaTrabalho
from core.evento import EventoCanonico
from core.kernel import kernel
from core.tipos import CategoriaEvento, TipoAcao, OrigemEvento
from servicos.clima_atual import consultar_clima_atual

logger = logging.getLogger("AgenteClima")


class AgenteClima:
    def __init__(self, memoria_trabalho: AgenteMemoriaTrabalho):
        self.memoria_trabalho = memoria_trabalho

    async def processar(self, evento: EventoCanonico):
        try:
            clima = await consultar_clima_atual()
            if clima["icon_code"] == "rain":
                await kernel.publicar(EventoCanonico(
                    categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
                    acao=TipoAcao.INTENCAO_INTERACAO,
                    origem=OrigemEvento.SISTEMA,
                    pacote="sistema.clima",
                    payload={
                        "titulo": "Alerta de Chuva",
                        "texto": f"Está chovendo agora ({clima['temperatura']}°C). Leve um guarda-chuva se for sair!",
                        "tipo_ws": "NOTIFICACAO",
                    },
                ))
            if hasattr(self.memoria_trabalho, "definir_contexto"):
                self.memoria_trabalho.definir_contexto("clima", clima)
            else:
                self.memoria_trabalho.contexto_atual = clima
        except Exception as erro:
            logger.warning("AgenteClima: falha ao atualizar contexto (%s).", type(erro).__name__)
