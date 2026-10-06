# servicos/semantic_cache.py
import logging
import hashlib
from sqlalchemy.future import select
from banco.database import AsyncSessionLocal
from banco.models import SemanticCacheDB, MetaDB

logger = logging.getLogger("SemanticCache")

class SemanticCacheService:
    async def _obter_facts_version(self, session, user_id: str) -> int:
        stmt = select(MetaDB).where(MetaDB.key == f"facts_version_{user_id}")
        result = await session.execute(stmt)
        meta = result.scalar_one_or_none()
        return int(meta.value) if meta else 1

    async def buscar(self, query: str, user_id: str = "default") -> str | None:
        """
        Busca resposta no cache semântico considerando a versão atual dos fatos.
        """
        query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()

        async with AsyncSessionLocal() as session:
            current_version = await self._obter_facts_version(session, user_id)

            stmt = select(SemanticCacheDB).where(
                SemanticCacheDB.user_id == user_id,
                SemanticCacheDB.query_hash == query_hash,
                SemanticCacheDB.facts_version == current_version
            )
            result = await session.execute(stmt)
            cache = result.scalar_one_or_none()

            if cache:
                resp = cache.response
                from sqlalchemy import update
                await session.execute(
                    update(SemanticCacheDB)
                    .where(SemanticCacheDB.id == cache.id)
                    .values(hits=SemanticCacheDB.hits + 1)
                )
                await session.commit()
                logger.info(f"⚡ [SemanticCache] Cache HIT para query hash {query_hash[:8]}")
                return resp

        return None

    async def inserir(self, query: str, response: str, user_id: str = "default"):
        """
        Armazena resposta no cache associando-a à versão atual dos fatos.
        """
        query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()

        async with AsyncSessionLocal() as session:
            current_version = await self._obter_facts_version(session, user_id)

            # Remove cache antigo com mesmo hash
            stmt = select(SemanticCacheDB).where(
                SemanticCacheDB.user_id == user_id,
                SemanticCacheDB.query_hash == query_hash
            )
            result = await session.execute(stmt)
            existente = result.scalar_one_or_none()

            if existente:
                existente.response = response
                existente.facts_version = current_version
                existente.hits = 0
            else:
                novo_cache = SemanticCacheDB(
                    user_id=user_id,
                    query_hash=query_hash,
                    facts_version=current_version,
                    response=response
                )
                session.add(novo_cache)

            await session.commit()
            logger.info(f"💾 [SemanticCache] Resposta armazenada no cache para hash {query_hash[:8]}")

semantic_cache_service = SemanticCacheService()
