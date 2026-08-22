"""
agentes/agente_bem_estar.py

Agente focado em saúde digital e equilíbrio.
Monitora o tempo de uso contínuo de aplicativos e sugere pausas ou mudanças de hábito.
"""
import logging
from datetime import datetime, timedelta

from core.evento import EventoCanonico
from core.tipos import CategoriaEvento, TipoAcao, OrigemEvento, PrioridadeEvento
from core.kernel import kernel
from servicos.catalogo_semantico import catalogo

logger = logging.getLogger("AgenteBemEstar")

class AgenteBemEstar:
    def __init__(self):
        # Dicionário para rastrear o início do uso de cada app
        self._uso_atual = {} # {pacote: timestamp_inicio}
        self._limite_alerta = 30 # minutos para o primeiro alerta

    async def processar(self, evento: EventoCanonico):
        if evento.categoria != CategoriaEvento.APP_FOREGROUND:
            return

        pacote = evento.payload.get("pacote")
        if not pacote:
            return

        # 1. Obter categoria do app para decidir se monitoramos
        entidade = await catalogo.obter_app(pacote)
        categoria = entidade.atributos.get("categoria", "").lower() if entidade else ""

        # Apps de entretenimento e redes sociais são os alvos principais
        monitorar = any(c in categoria for e in ["social", "entretenimento", "jogos", "vídeo", "lazer"])
        
        if monitorar:
            await self._monitorar_uso(pacote, evento)
        else:
            # Se mudou para um app de produtividade ou utilitário, limpa o rastreio anterior
            self._uso_atual.clear()

    async def _monitorar_uso(self, pacote: str, evento: EventoCanonico):
        agora = datetime.now()
        
        if pacote not in self._uso_atual:
            self._uso_atual[pacote] = agora
            return

        inicio = self._uso_atual[pacote]
        tempo_uso = (agora - inicio).total_seconds() / 60

        if tempo_uso > self._limite_alerta:
            logger.info(f"🧘 AgenteBemEstar: Usuário no app {pacote} há {tempo_uso:.1f} minutos. Sugerindo pausa via IA.")
            
            # Eleva para um evento complexo para que a IA gere a mensagem
            await kernel.publicar(
                evento.clonar(
                    id=None,
                    categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
                    acao=TipoAcao.INTENCAO_INTERACAO,
                    origem=OrigemEvento.IA,
                    payload={
                        "titulo": "Equilíbrio Digital",
                        "texto": f"Você já está no {pacote.split('.')[-1].capitalize()} há {int(tempo_uso)} minutos.",
                        "contexto_extra": {"minutos": int(tempo_uso), "pacote": pacote, "tipo": "BEM_ESTAR"},
                        "tipo_ws": "NOTIFICACAO"
                    }
                )
            )
            # Aumenta o limite para o próximo alerta ser mais espaçado
            self._limite_alerta += 20
