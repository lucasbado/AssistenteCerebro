# servicos/summary_service.py
import logging
from datetime import datetime, timezone
from sqlalchemy.future import select
from banco.database import AsyncSessionLocal
from banco.models import SummaryDB

logger = logging.getLogger("SummaryService")

class SummaryService:
    async def gerar_resumo_sessao(self, session_id: str, mensagens: list[str], user_id: str = "default"):
        """
        Gera ou atualiza o rolling summary de uma sessão a cada 10 mensagens.
        Budget reservado: ~150 tokens.
        """
        if not mensagens: return

        resumo_texto = f"Sessão {session_id}: Discutido sobre {mensagens[0][:40]}... com {len(mensagens)} interações."

        async with AsyncSessionLocal() as session:
            stmt = select(SummaryDB).where(SummaryDB.user_id == user_id, SummaryDB.scope == f"session:{session_id}")
            result = await session.execute(stmt)
            sum_db = result.scalar_one_or_none()

            if sum_db:
                sum_db.text = resumo_texto
                sum_db.created_at = datetime.now(timezone.utc)
            else:
                sum_db = SummaryDB(
                    user_id=user_id,
                    scope=f"session:{session_id}",
                    text=resumo_texto
                )
                session.add(sum_db)
            
            await session.commit()
            logger.info(f"📝 [SummaryService] Resumo de sessão atualizado para '{session_id}'.")

    async def obter_resumos_para_prompt(self, session_id: str, user_id: str = "default") -> tuple[str, str]:
        """
        Retorna (global_summary, session_summary) dentro do budget estrito de 300 tokens.
        """
        async with AsyncSessionLocal() as session:
            # Global summary
            stmt_g = select(SummaryDB).where(SummaryDB.user_id == user_id, SummaryDB.scope == "global")
            res_g = await session.execute(stmt_g)
            global_sum = res_g.scalar_one_or_none()
            g_text = global_sum.text if global_sum else "Usuário ativo no ecossistema Ollie."

            # Session summary
            stmt_s = select(SummaryDB).where(SummaryDB.user_id == user_id, SummaryDB.scope == f"session:{session_id}")
            res_s = await session.execute(stmt_s)
            session_sum = res_s.scalar_one_or_none()
            s_text = session_sum.text if session_sum else "Início da sessão atual."

            return g_text[:300], s_text[:300]

summary_service = SummaryService()
