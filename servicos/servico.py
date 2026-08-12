import logging
from .agregador import agregador_timeline
from .dto import TimelineDTO, TimelineItemDTO

logger = logging.getLogger(__name__)

class ServicoTimeline:
    async def gerar_timeline(self) -> TimelineDTO:
        """
        Orquestra a busca de eventos e sua transformação em uma
        narrativa para a timeline.
        """
        eventos_brutos = await agregador_timeline.obter_eventos_recentes()
        
        timeline_items = []
        for evento in eventos_brutos:
            # O agregador retorna dados brutos; aqui transformamos em conhecimento.
            resumo, icone = self._formatar_resumo_evento(evento)
            
            item = TimelineItemDTO(
                id=evento["id"],
                timestamp=evento["timestamp"],
                categoria=evento["tipo"],
                origem=evento["origem"],
                resumo=resumo,
                icone=icone
            )
            timeline_items.append(item)
            
        # Garante que os eventos mais recentes apareçam primeiro.
        timeline_items.sort(key=lambda x: x.timestamp, reverse=True)

        return TimelineDTO(eventos=timeline_items)

    def _formatar_resumo_evento(self, evento: dict) -> tuple[str, str]:
        """
        Transforma um evento bruto em uma narrativa curta e um ícone.
        Esta é uma função chave na transformação de dados em conhecimento.
        """
        categoria = evento.get("tipo")
        payload = evento.get("dados", {})
        
        if categoria == "NOTIFICACAO":
            titulo = payload.get("titulo", "Notificação")
            texto = payload.get("texto", "...")
            return f"{titulo}: {texto}", "bell"
        
        if categoria == "MEDIA":
            artista = payload.get("artista", "Artista desconhecido")
            musica = payload.get("musica", "música desconhecida")
            return f"Ouvindo {artista} - {musica}", "music"

        if categoria == "APP_FOREGROUND":
            pacote = payload.get("pacote", "App desconhecido")
            return f"Foco no app: {pacote}", "eye"

        return f"Evento do sistema: {categoria}", "cog"

servico_timeline = ServicoTimeline()