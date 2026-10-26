"""Fila durável com reserva atômica e recuperação de tarefas interrompidas."""
import asyncio
import json
import logging
import os
import struct
from datetime import datetime, timedelta, timezone
import httpx
from sqlalchemy import select, update, or_, and_
from banco.database import AsyncSessionLocal
from banco.models import TaskQueueDB, FactDB
from servicos.fact_service import fact_service

logger = logging.getLogger("QueueWorker")

class QueueWorker:
    def __init__(self, session_factory=None):
        self.session_factory = session_factory or AsyncSessionLocal
        self.rodando = False
        self._shutdown_event = asyncio.Event()
        self._intervalo_ocioso = 5

    async def iniciar(self):
        self._shutdown_event.clear()
        self.rodando = True
        try:
            while not self._shutdown_event.is_set():
                try:
                    processou = await self._processar_proxima_tarefa()
                    intervalo = 0 if processou else self._intervalo_ocioso
                    self._intervalo_ocioso = 5 if processou else min(900, self._intervalo_ocioso * 3)
                except Exception:
                    logger.exception("Erro no worker")
                    intervalo = 900
                    self._intervalo_ocioso = 900
                if intervalo == 0:
                    continue
                try:
                    await asyncio.wait_for(self._shutdown_event.wait(), timeout=intervalo)
                except asyncio.TimeoutError:
                    pass
        finally:
            self.rodando = False

    async def parar(self):
        self._shutdown_event.set()

    async def _processar_proxima_tarefa(self):
        agora = datetime.now(timezone.utc)
        disponivel = or_(TaskQueueDB.status == "pending", and_(
            TaskQueueDB.status == "processing",
            or_(TaskQueueDB.locked_until.is_(None), TaskQueueDB.locked_until < agora),
        ))
        async with self.session_factory() as session:
            # Fila vazia não precisa executar dois UPDATEs e COMMIT a cada sondagem.
            existe = (await session.execute(select(TaskQueueDB.id).where(disponivel).limit(1))).scalar_one_or_none()
            if existe is None:
                return False
            await session.execute(update(TaskQueueDB).where(disponivel, TaskQueueDB.attempts >= 3).values(status="dead", locked_until=None))
            candidato = select(TaskQueueDB.id).where(disponivel, TaskQueueDB.attempts < 3).order_by(TaskQueueDB.created_at, TaskQueueDB.id).limit(1).scalar_subquery()
            result = await session.execute(update(TaskQueueDB).where(TaskQueueDB.id == candidato, disponivel).values(
                status="processing", attempts=TaskQueueDB.attempts + 1,
                locked_until=agora + timedelta(minutes=5),
            ).returning(TaskQueueDB.id))
            task_id = result.scalar_one_or_none()
            await session.commit()
            if task_id is None:
                return False
            task = await session.get(TaskQueueDB, task_id)
            tentativa = task.attempts
            try:
                # O timeout é menor que a reserva; workers não processam a mesma tarefa ativa.
                await asyncio.wait_for(self._executar(session, task), timeout=120)
                status = "done"
            except asyncio.CancelledError:
                await session.rollback()
                raise
            except Exception:
                logger.exception("Falha na tarefa %s", task_id)
                await session.rollback()
                status = "dead" if tentativa >= 3 else "pending"
            await session.execute(update(TaskQueueDB).where(
                TaskQueueDB.id == task_id, TaskQueueDB.attempts == tentativa,
            ).values(status=status, locked_until=None))
            await session.commit()
            return True

    async def _executar(self, session, task):
        payload = task.payload if isinstance(task.payload, dict) else json.loads(task.payload)
        if task.task_type == "extract_facts":
            await fact_service.extrair_e_salvar_fatos(payload.get("texto", ""), user_id=task.user_id)
        elif task.task_type == "embed_fact":
            stmt = select(FactDB).where(FactDB.text == payload.get("fact_text", ""), FactDB.user_id == task.user_id)
            if payload.get("source_file"):
                stmt = stmt.where(FactDB.source_file == payload["source_file"])
            fatos = (await session.execute(stmt)).scalars().all()
            if not fatos:
                return
            async with httpx.AsyncClient(timeout=45) as client:
                response = await client.post(os.getenv("OLLAMA_EMBED_URL", "http://localhost:11434/api/embed"), json={
                    "model": os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text"),
                    "input": payload["fact_text"],
                })
                response.raise_for_status()
                vetor = response.json()["embeddings"][0]
            if len(vetor) != 768:
                raise ValueError("Embedding deve ter 768 dimensões")
            dados = struct.pack("<768f", *vetor)
            for fato in fatos:
                fato.embedding = dados
                if session.bind.dialect.name == "sqlite":
                    existe = (await session.execute(select(FactDB.id).where(FactDB.id == fato.id))).scalar_one()
                    from sqlalchemy import text
                    tem_vec = (await session.execute(text("SELECT name FROM sqlite_master WHERE name='facts_vec'"))).first()
                    if tem_vec:
                        await session.execute(text("DELETE FROM facts_vec WHERE rowid=:id"), {"id": existe})
                        await session.execute(text("INSERT INTO facts_vec(rowid,embedding) VALUES(:id,:embedding)"), {"id": existe, "embedding": dados})
        else:
            raise ValueError(f"Tipo de tarefa desconhecido: {task.task_type}")

queue_worker = QueueWorker()
