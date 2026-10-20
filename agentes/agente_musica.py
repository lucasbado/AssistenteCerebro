"""Mantém o catálogo musical sem interromper a cada faixa ou artista favorito."""
from core.evento import EventoCanonico
from core.tipos import CategoriaEvento
from servicos.catalogo_semantico import catalogo


class AgenteMusica:
    async def processar(self, evento: EventoCanonico):
        if evento.categoria != CategoriaEvento.MEDIA:
            return
        artista = evento.payload.get("artista")
        if artista:
            await catalogo.obter_artista(artista)
