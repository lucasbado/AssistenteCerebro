# servicos/context_builder.py
import logging
import os
import re
from sqlalchemy import or_, case
from sqlalchemy.future import select
from banco.database import AsyncSessionLocal
from banco.models import FactDB, MetaDB
from servicos.summary_service import summary_service

logger = logging.getLogger("ContextBuilder")

class ContextBuilder:
    def __init__(self, max_tokens: int = 2000):
        self.max_tokens = max_tokens

    async def _verificar_backfill(self, user_id: str) -> bool:
        async with AsyncSessionLocal() as session:
            stmt = select(MetaDB).where(MetaDB.key == f"backfill_complete_{user_id}")
            result = await session.execute(stmt)
            meta = result.scalar_one_or_none()
            return meta and meta.value.lower() == "true"

    async def construir_contexto(self, query: str, session_id: str, user_id: str = "default") -> dict:
        """
        Constrói o prompt enxuto respeitando a hierarquia de corte e budget de 2k tokens.
        """
        # 1. Obter resumos (Global + Session)
        global_sum, session_sum = await summary_service.obter_resumos_para_prompt(session_id, user_id)
        
        # Se backfill não completou, ignoramos o resumo global para não alucinar
        backfill_ok = await self._verificar_backfill(user_id)
        if not backfill_ok:
            global_sum = "Aguardando sincronização inicial de memória."

        # 2. Obter fatos relevantes (Top 5 ordenados por importância)
        fatos_relevantes = []
        async with AsyncSessionLocal() as session:
            termos = list(dict.fromkeys(re.findall(r"\w{3,}", query.lower())))[:12]
            stmt = select(FactDB).where(FactDB.user_id == user_id)
            if termos:
                condicoes = [FactDB.text.ilike(f"%{termo}%", escape="\\") for termo in termos]
                stmt = stmt.where(or_(*condicoes)).order_by(sum(case((c, 1), else_=0) for c in condicoes).desc())
            stmt = stmt.order_by(FactDB.importance.desc()).limit(5)
            result = await session.execute(stmt)
            facts_db = result.scalars().all()
            fatos_relevantes = [f"- {f.text}" for f in facts_db]

        fatos_str = "\n".join(fatos_relevantes) if fatos_relevantes else "Nenhum fato relevante indexado."

        # 3. Hierarquia de montagem (Budget estrito de 2000 tokens aprox. ~8000 caracteres)
        contexto_montado = {
            "system_prompt": "Ollie: Parceira inteligente, direta e humana.",
            "global_summary": global_sum,
            "session_summary": session_sum,
            "fatos_relevantes": fatos_str,
            "query": query
        }
        # Limite conservador por bytes UTF-8 (sem depender de tokenizer de provedor).
        restante = max(0, self.max_tokens - 100)
        for campo in ("system_prompt", "query", "session_summary", "fatos_relevantes", "global_summary"):
            dados = str(contexto_montado[campo]).encode("utf-8")[:restante]
            contexto_montado[campo] = dados.decode("utf-8", errors="ignore")
            restante -= len(contexto_montado[campo].encode("utf-8"))

        logger.info(f"🧱 [ContextBuilder] Contexto construído para query: '{query[:30]}...' (Fatos: {len(fatos_relevantes)})")
        return contexto_montado

context_builder = ContextBuilder()
