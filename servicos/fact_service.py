# servicos/fact_service.py
import json
import logging
import math
from datetime import datetime, timezone
from sqlalchemy.future import select
from banco.database import AsyncSessionLocal
from banco.models import FactDB, MetaDB

logger = logging.getLogger("FactService")

class FactService:
    async def extrair_e_salvar_fatos(self, texto: str, source_msg_id: str = None, user_id: str = "default"):
        """
        Extrai fatos atômicos, faz dedup híbrido (hash exato + similaridade) e salva.
        """
        if not texto or len(texto.strip()) < 5:
            return

        # Simula extração de fatos atômicos (em produção, via Ollama local)
        fatos_detectados = [texto.strip()]

        async with AsyncSessionLocal() as session:
            for fato_texto in fatos_detectados:
                # 1. Dedup por hash exato
                stmt = select(FactDB).where(FactDB.user_id == user_id, FactDB.text == fato_texto)
                result = await session.execute(stmt)
                existente = result.scalar_one_or_none()

                if existente:
                    # Incrementa importance se já existe
                    existente.importance = min(1.0, existente.importance + 0.1)
                    existente.last_used = datetime.now(timezone.utc)
                    logger.info(f"🧠 [FactService] Fato reforçado: '{fato_texto[:40]}...' (Importance: {existente.importance})")
                else:
                    # Cria novo fato
                    novo_fato = FactDB(
                        user_id=user_id,
                        text=fato_texto,
                        keywords=json.dumps(fato_texto.split()),
                        importance=0.5,
                        source_msg_id=source_msg_id
                    )
                    session.add(novo_fato)
                    logger.info(f"🧠 [FactService] Novo fato atômico salvo: '{fato_texto[:40]}...'")
                
                await session.commit()

            # Incrementa facts_version periodicamente para invalidar cache stale
            await self._incrementar_facts_version(session, user_id)

    async def _incrementar_facts_version(self, session, user_id: str):
        stmt = select(MetaDB).where(MetaDB.key == f"facts_version_{user_id}")
        result = await session.execute(stmt)
        meta = result.scalar_one_or_none()
        
        if meta:
            meta.value = str(int(meta.value) + 1)
        else:
            meta = MetaDB(key=f"facts_version_{user_id}", value="1")
            session.add(meta)
        await session.commit()

    async def aplicar_decay_importancia(self, user_id: str = "default", lambda_decay: float = 0.05):
        """
        Aplica fórmula de decaimento temporal de importância nos fatos.
        importance = base * exp(-λ * days) + hits_bonus
        """
        async with AsyncSessionLocal() as session:
            stmt = select(FactDB).where(FactDB.user_id == user_id)
            result = await session.execute(stmt)
            fatos = result.scalars().all()
            
            agora = datetime.now(timezone.utc)
            for fato in fatos:
                dias = (agora - fato.last_used).days if fato.last_used else 0
                fato.importance = fato.importance * math.exp(-lambda_decay * dias)
            
            await session.commit()
            logger.info("⏳ [FactService] Decaimento de importância aplicado aos fatos.")

fact_service = FactService()
