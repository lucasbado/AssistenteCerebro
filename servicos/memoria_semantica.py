from __future__ import annotations
from sqlalchemy.future import select
from banco.database import AsyncSessionLocal
from banco.models import EntidadeSemanticaDB
from modelos.catalogo import EntidadeSemantica

class MemoriaSemantica:

    def __init__(self):
        # Cache thread-safe em RAM (Leitura em O(1))
        self._cache: dict[str, EntidadeSemantica] = {}

    # =======================================================
    # Busca (RAM -> SQLite)
    # =======================================================

    async def buscar(self, tipo: str, chave: str) -> EntidadeSemantica | None:
        cache_key = self._cache_key(tipo, chave)

        # 1. Tenta recuperar da RAM de forma imediata
        if cache_key in self._cache:
            return self._cache[cache_key]

        # 2. Fallback Assíncrono para o SQLite
        async with AsyncSessionLocal() as session:
            # 🛡️ FIX: Ordenamos por ID decrescente e limitamos a 1 para evitar MultipleResultsFound
            stmt = select(EntidadeSemanticaDB).where(
                EntidadeSemanticaDB.tipo == tipo,
                EntidadeSemanticaDB.chave == chave
            ).order_by(EntidadeSemanticaDB.id.desc()).limit(1)
            
            resultado = await session.execute(stmt)
            entidade_db = resultado.scalars().first()

            if entidade_db is None:
                return None

            # Conversão segura usando o validador do Pydantic v2
            entidade = EntidadeSemantica.model_validate(entidade_db.dados_json)
            
            # Alimenta a RAM para a próxima busca
            self._cache[cache_key] = entidade
            return entidade

    # =======================================================
    # Salvar
    # =======================================================

    async def salvar(self, entidade: EntidadeSemantica) -> None:
        cache_key = self._cache_key(entidade.tipo, entidade.chave)

        # Atualiza a RAM imediatamente para consistência
        self._cache[cache_key] = entidade

        # Persiste assincronamente no banco de dados
        async with AsyncSessionLocal() as session:
            stmt = select(EntidadeSemanticaDB).where(
                EntidadeSemanticaDB.tipo == entidade.tipo,
                EntidadeSemanticaDB.chave == entidade.chave
            ).order_by(EntidadeSemanticaDB.id.desc())
            
            resultado = await session.execute(stmt)
            existente = resultado.scalars().first()

            payload_json = entidade.model_dump()

            if existente:
                existente.dados_json = payload_json
            else:
                novo = EntidadeSemanticaDB(
                    tipo=entidade.tipo,
                    chave=entidade.chave,
                    dados_json=payload_json
                )
                session.add(novo)
            
            await session.commit()

    # =======================================================
    # Remover
    # =======================================================

    async def remover(self, tipo: str, chave: str) -> None:
        cache_key = self._cache_key(tipo, chave)

        # Remove da RAM
        self._cache.pop(cache_key, None)

        # Remove do Banco
        async with AsyncSessionLocal() as session:
            stmt = select(EntidadeSemanticaDB).where(
                EntidadeSemanticaDB.tipo == tipo,
                EntidadeSemanticaDB.chave == chave
            ).order_by(EntidadeSemanticaDB.id.desc())
            
            resultado = await session.execute(stmt)
            existente = resultado.scalars().first()

            if existente:
                await session.delete(existente)
                await session.commit()

    # =======================================================
    # Gerenciamento de Cache
    # =======================================================

    def limpar_cache(self) -> None:
        self._cache.clear()

    def tamanho_cache(self) -> int:
        return len(self._cache)

    @staticmethod
    def _cache_key(tipo: str, chave: str) -> str:
        return f"{tipo.upper()}::{chave.lower()}"