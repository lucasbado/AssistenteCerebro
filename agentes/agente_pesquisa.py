"""
agentes/agente_pesquisa.py

Agente responsável por realizar buscas na web quando o conhecimento interno
do sistema não é suficiente. Utiliza DuckDuckGo para buscar e Trafilatura
para extrair o conteúdo principal das páginas.
"""
import logging
import asyncio
from duckduckgo_search import DDGS
from trafilatura import fetch_url, extract

from core.evento import EventoCanonico
from core.tipos import TipoAcao, OrigemEvento
from core.kernel import kernel

logger = logging.getLogger(__name__)

class AgentePesquisa:
    def __init__(self, max_results=2):
        self.max_results = max_results

    def _executar_busca(self, query: str):
        """Executa a busca síncrona no DuckDuckGo."""
        with DDGS(timeout=10) as ddgs:
            return list(ddgs.text(query, max_results=self.max_results))

    async def processar(self, evento: EventoCanonico):
        query = evento.payload.get("query")
        if not query:
            logger.warning("[Pesquisa] Recebida intenção de pesquisa sem query.")
            return

        logger.info(f"🌐 [Pesquisa] Iniciando busca na web por: '{query}'")
        
        try:
            # 1. Buscar links no DuckDuckGo
            search_results = await asyncio.to_thread(self._executar_busca, query)
            
            if not search_results:
                logger.warning(f"🌐 [Pesquisa] Nenhum resultado encontrado para '{query}'")
                await self._publicar_resultado(evento, "Não encontrei resultados para sua busca.", sucesso=False)
                return

            logger.info(f"🌐 [Pesquisa] Encontrados {len(search_results)} resultados. Extraindo conteúdos...")

            # 2. Extrair conteúdo das páginas em paralelo
            urls = [r['href'] for r in search_results]
            tasks = [self._extrair_conteudo(url) for url in urls]
            conteudos = await asyncio.gather(*tasks)
            
            conteudo_final = "\n\n---\n\n".join([c[:2000] for c in conteudos if c])

            if not conteudo_final:
                logger.warning(f"🌐 [Pesquisa] Falha ao extrair texto útil das URLs.")
                await self._publicar_resultado(evento, "Não consegui extrair conteúdo relevante dos sites.", sucesso=False)
                return

            logger.info(f"🌐 [Pesquisa] Sucesso! Enviando {len(conteudo_final)} caracteres para síntese.")
            await self._publicar_resultado(evento, conteudo_final, sucesso=True)

        except Exception as e:
            logger.error(f"🌐 [Pesquisa] Erro durante a busca ou extração: {e}")
            await self._publicar_resultado(evento, f"Ocorreu um erro ao pesquisar: {e}", sucesso=False)

    async def _extrair_conteudo(self, url: str) -> str | None:
        """Baixa e extrai o texto principal de uma URL."""
        try:
            downloaded = await asyncio.to_thread(fetch_url, url)
            if downloaded:
                return await asyncio.to_thread(extract, downloaded, include_comments=False, include_tables=False)
        except Exception as e:
            logger.warning(f"🌐 [Pesquisa] Falha ao extrair conteúdo de {url}: {e}")
        return None

    async def _publicar_resultado(self, evento_original: EventoCanonico, conteudo: str, sucesso: bool):
        """Publica o resultado da pesquisa para o próximo agente no pipeline."""
        novo_evento = evento_original.clonar(
            acao=TipoAcao.RESULTADO_PESQUISA,
            origem=OrigemEvento.SISTEMA,
            payload={
                "query": evento_original.payload.get("query"),
                "sucesso": sucesso,
                "conteudo": conteudo,
            }
        )
        logger.info(f"🌐 [Pesquisa] Publicando resultado final ({novo_evento.id[:8]}) para síntese.")
        await kernel.publicar(novo_evento)
