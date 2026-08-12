"""
servicos/catalogo_semantico.py

Responsável por fornecer conhecimento semântico aos agentes.

Fluxo:

RAM
 ↓
SQLite
 ↓
LLM
 ↓
Persistência
"""

from __future__ import annotations

import logging
from typing import Optional

from modelos.catalogo import EntidadeSemantica
from servicos.memoria_semantica import MemoriaSemantica
from servicos.llm import ServicoLLM

logger = logging.getLogger(__name__)

# servicos/catalogo_semantico.py

class CatalogoSemantico:
    def __init__(self):
        # Importações adiadas para evitar dependências circulares durante a inicialização.
        from servicos.memoria_semantica import MemoriaSemantica
        from servicos.llm import ServicoLLM
        self.memoria = MemoriaSemantica()
        self.llm = ServicoLLM()

    async def obter_artista(self, artista: str) -> Optional[EntidadeSemantica]:
        """Obtém um artista. Em nuvem, a classificação é postergada para economizar tokens."""
        entidade = await self.memoria.buscar("ARTISTA", artista)
        if not entidade:
            # Placeholder para economizar Groq API
            logger.info(f"Artista '{artista}' marcado para classificação futura.")
            entidade = EntidadeSemantica(
                tipo="ARTISTA", 
                chave=artista, 
                atributos={"nome": artista, "status": "PENDENTE_IA"}
            )
            await self.memoria.salvar(entidade)
        return entidade

    async def obter_app(self, pacote: str) -> Optional[EntidadeSemantica]:
        """Obtém um app. Classificação via IA apenas em lote ou sob demanda."""
        entidade = await self.memoria.buscar("APP", pacote)
        if not entidade:
            logger.info(f"App '{pacote}' marcado para classificação futura.")
            entidade = EntidadeSemantica(
                tipo="APP", 
                chave=pacote, 
                atributos={"pacote": pacote, "status": "PENDENTE_IA"}
            )
            await self.memoria.salvar(entidade)
        return entidade

    async def obter_contato(self, contato_nome: str) -> Optional[EntidadeSemantica]:
        # 🌟 CRUCIAL
        entidade = await self.memoria.buscar("CONTATO", contato_nome)
        if not entidade:
            # O método classificar_contato não usa LLM, é seguro, rápido e não precisa de try/except.
            entidade = await self.llm.classificar_contato(contato_nome)
            await self.memoria.salvar(entidade)
        return entidade


catalogo = CatalogoSemantico()