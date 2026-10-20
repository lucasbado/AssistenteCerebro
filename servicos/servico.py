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
        # Aumentamos para 24h para garantir que a home não fique vazia nos primeiros testes
        eventos_brutos = await agregador_timeline.obter_eventos_recentes(minutos=1440)
        logger.info(f"📓 [Timeline] Recuperados {len(eventos_brutos)} eventos das últimas 24h.")
        
        timeline_items = []
        for evento in eventos_brutos:
            if evento.get("tipo") not in {"NOTIFICACAO_PRONTA_PARA_ENVIO", "SISTEMA_COMANDO_PC"}:
                continue
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

        if categoria == "NOTIFICACAO_PRONTA_PARA_ENVIO":
            prefixo = "Resposta" if payload.get("tipo_ws") == "CHAT_RESPONSE" else "Sugestão encaminhada"
            return f"{prefixo}: {payload.get('texto', '')}", "message-circle" if prefixo == "Resposta" else "bell"
        if categoria == "SISTEMA_COMANDO_PC":
            comando = payload.get("comando") or "abrir_app"
            alvo = payload.get("parametro") or payload.get("programa") or ""
            return f"Ação solicitada no PC: {comando} {alvo}".strip(), "monitor"
        
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
