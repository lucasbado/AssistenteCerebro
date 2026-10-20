from core.evento import EventoCanonico
from servicos.memoria_episodica import MemoriaEpisodica
from api.websocket import central_alertas

class AgenteEpisodico:
    """
    Um agente passivo que atua como a sub-rotina do hipocampo.
    Ele escuta TODOS os eventos que sobrevivem ao Filtro de Atenção do Kernel.
    """
    def __init__(self):
        self.memoria = MemoriaEpisodica()

    async def processar(self, evento: EventoCanonico):
        # 1. Salva na persistência (banco de dados)
        await self.memoria.arquivar_evento(evento)
        
        # 2. Transmite via WebSocket para atualização da Timeline em tempo real
        # Filtramos eventos muito técnicos ou repetitivos para não poluir a UI
        if evento.categoria.value in {"NOTIFICACAO_PRONTA_PARA_ENVIO", "SISTEMA_COMANDO_PC"}:
            from servicos.servico import servico_timeline
            dados = evento.model_dump()
            dados["resumo"], _ = servico_timeline._formatar_resumo_evento(
                {"tipo": evento.categoria.value, "dados": evento.payload})
            await central_alertas.enviar_evento_log(dados)
