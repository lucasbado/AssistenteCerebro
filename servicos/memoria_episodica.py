from __future__ import annotations
from datetime import datetime, timedelta, timezone
from sqlalchemy.future import select
from banco.database import AsyncSessionLocal
from banco.models import EventoEpisodicoDB
from core.evento import EventoCanonico


class MemoriaEpisodica:
    """
    O Historiador do Sistema.
    Regista imutavelmente tudo o que atravessa o Kernel.
    """

    async def arquivar_evento(self, evento: EventoCanonico) -> None:
        async with AsyncSessionLocal() as session:
            pai_id = getattr(evento, "evento_pai", None)

            categoria_str = "DESCONHECIDO"
            if hasattr(evento, "categoria"):
                categoria_str = str(
                    evento.categoria.value
                    if hasattr(evento.categoria, "value")
                    else evento.categoria
                )

            origem_str = "SISTEMA"
            if hasattr(evento, "origem"):
                origem_str = str(
                    evento.origem.value
                    if hasattr(evento.origem, "value")
                    else evento.origem
                )

            score = 0.0
            if hasattr(evento, "metadados") and isinstance(evento.metadados, dict):
                score = evento.metadados.get("atencao", {}).get("score", 0.0)

            # 🌟 CORREÇÃO VITAL: Clonamos o payload e injetamos o pacote para não perder o contexto
            payload_historico = dict(evento.payload) if evento.payload else {}

            pacote_app = getattr(evento, "pacote", None)
            if pacote_app:
                payload_historico["pacote"] = pacote_app

            # Mapeamento para o BD
            registro = EventoEpisodicoDB(
                id=str(evento.id),
                correlacao_id=str(getattr(evento, "correlacao_id", evento.id)),
                evento_pai_id=str(pai_id) if pai_id else None,
                timestamp=evento.timestamp,
                origem=origem_str,
                tipo=categoria_str,
                score_atencao=score,
                payload=payload_historico,  # <-- Agora salva TUDO
            )

            session.add(registro)
            await session.commit()

    async def obter_contexto_recente(self, minutos: int = 5) -> list[dict]:
        """
        Recupera os eventos mais recentes.
        Crucial para injetar no Prompt da LLM e dar "consciência do agora" ao sistema.
        """
        # 🕒 COMPATIBILIDADE TOTAL: PostgreSQL/Neon usa DateTime(timezone=True)
        # O SQLAlchemy com asyncpg espera objetos aware se a coluna for aware.
        limite_tempo = datetime.now(timezone.utc) - timedelta(minutes=minutos)

        async with AsyncSessionLocal() as session:
            stmt = (
                select(EventoEpisodicoDB)
                .where(EventoEpisodicoDB.timestamp >= limite_tempo)
                .order_by(EventoEpisodicoDB.timestamp.asc())
            )

            resultado = await session.execute(stmt)
            eventos_db = resultado.scalars().all()

            # Retorna uma lista limpa para ser consumida pela LLM
            return [
                {
                    "id": e.id,
                    "timestamp": e.timestamp,
                    "origem": e.origem,
                    "tipo": e.tipo,
                    "dados": e.payload,
                }
                for e in eventos_db
            ]

    async def obter_evento_original_por_correlacao(self, correlacao_id: str) -> dict | None:
        """
        Recupera o primeiro evento (o original) de uma cadeia de correlação.
        Essencial para que agentes de síntese possam re-analisar o contexto inicial
        após receberem informações adicionais (ex: de uma pesquisa na web).
        """
        async with AsyncSessionLocal() as session:
            stmt = (
                select(EventoEpisodicoDB)
                .where(EventoEpisodicoDB.correlacao_id == correlacao_id)
                .order_by(EventoEpisodicoDB.timestamp.asc())
                .limit(1)
            )
            resultado = await session.execute(stmt)
            evento_db = resultado.scalars().first()

            if not evento_db:
                return None
            
            # Reconstroi um dicionário parecido com o EventoCanonico para o AgenteRaciocinio
            return {
                "id": evento_db.id,
                "categoria": evento_db.tipo,
                "pacote": evento_db.payload.get("pacote"),
                "payload": evento_db.payload,
            }
