"""Sugestões contextuais com evidência; automações pertencem ao AgenteRotina."""
from core.evento import EventoCanonico
from core.kernel import kernel
from core.tipos import CategoriaEvento, OrigemEvento, TipoAcao
from servicos.catalogo_semantico import catalogo
from servicos.memoria_perfil import memoria_perfil
from servicos.tempo import periodo_do_dia


class AgenteFoco:
    async def processar(self, evento: EventoCanonico):
        if evento.categoria != CategoriaEvento.APP_FOREGROUND or evento.payload.get("heartbeat"):
            return
        entidade = await catalogo.obter_app(evento.pacote)
        if not entidade:
            return
        categoria = entidade.atributos.get("categoria", "").lower()
        if not any(c in categoria for c in ("navegação", "mapas")):
            return
        periodo = periodo_do_dia(evento.timestamp)
        artistas = await memoria_perfil.obter_top_entidades(
            categoria=f"ARTISTA_PREFERENCIA_{periodo}", limite=1)
        if not artistas or artistas[0].confianca < 0.8:
            return
        await kernel.publicar(evento.clonar(
            categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
            acao=TipoAcao.INTENCAO_INTERACAO, origem=OrigemEvento.IA,
            payload={"titulo": "Música para o caminho",
                     "texto": f"Você costuma ouvir {artistas[0].valor} neste período. Quer ouvir no caminho?",
                     "chave_deduplicacao": "musica_no_caminho", "tipo_ws": "NOTIFICACAO"}))
