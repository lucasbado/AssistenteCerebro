from core.tipos import CategoriaEvento
import json


class AgenteBotoes:
    """Publica a intenção derivada do toque, sem IA nem execução de hardware."""

    async def processar(self, evento):
        from core.kernel import kernel
        if evento.payload["comando"] == "casa_acao":
            await kernel.publicar(evento.clonar(
                categoria=CategoriaEvento.CASA_ACAO_SOLICITADA,
                payload=json.loads(evento.payload["parametro"])))
            return
        await kernel.publicar(evento.clonar(
            categoria=CategoriaEvento.SISTEMA_COMANDO_PC,
            payload={"comando": evento.payload["comando"],
                     "parametro": evento.payload["parametro"], "id_comando": evento.id}))
