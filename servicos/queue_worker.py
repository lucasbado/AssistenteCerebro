# servicos/queue_worker.py
import asyncio
import logging
import signal
from datetime import datetime, timezone
from sqlalchemy.future import select
from banco.database import AsyncSessionLocal
from banco.models import TaskQueueDB
from servicos.fact_service import fact_service

logger = logging.getLogger("QueueWorker")

class QueueWorker:
    def __init__(self):
        self.rodando = False
        self._shutdown_event = asyncio.Event()

    async def iniciar(self):
        self.rodando = True
        logger.info("⚙️ [QueueWorker] Worker de fila em segundo plano iniciado.")
        
        # Configura graceful shutdown
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.parar()))
            except NotImplementedError:
                pass # Sinais podem não ser suportados no Windows em alguns loops

        while self.rodando and not self._shutdown_event.is_set():
            try:
                await self._processar_proxima_tarefa()
            except Exception as e:
                logger.error(f"❌ [QueueWorker] Erro no loop da fila: {e}")
            
            # Aguarda 5 segundos antes de checar novas tarefas
            try:
                await asyncio.wait_for(self._shutdown_event.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass

    async def parar(self):
        logger.info("🛑 [QueueWorker] Sinal de parada recebido. Concluindo tarefa atual...")
        self._shutdown_event.set()
        self.rodando = False

    async def _processar_proxima_tarefa(self):
        async with AsyncSessionLocal() as session:
            stmt = select(TaskQueueDB).where(TaskQueueDB.status == "pending").order_by(TaskQueueDB.created_at.asc()).limit(1)
            result = await session.execute(stmt)
            task = result.scalar_one_or_none()

            if not task:
                return

            task.status = "processing"
            task.attempts += 1
            await session.commit()

            try:
                logger.info(f"⚙️ [QueueWorker] Processando tarefa #{task.id} [{task.task_type}] (Tentativa {task.attempts})...")
                
                if task.task_type == "extract_facts":
                    payload = task.payload if isinstance(task.payload, dict) else json.loads(task.payload)
                    texto = payload.get("texto", "")
                    await fact_service.extrair_e_salvar_fatos(texto, user_id=task.user_id)
                
                task.status = "done"
                await session.commit()
                logger.info(f"✅ [QueueWorker] Tarefa #{task.id} concluída com sucesso.")
            
            except Exception as e:
                logger.error(f"❌ [QueueWorker] Falha na tarefa #{task.id}: {e}")
                if task.attempts >= 3:
                    task.status = "dead"
                    logger.error(f"💀 [QueueWorker] Tarefa #{task.id} movida para Dead-Letter Queue (máx tentativas).")
                else:
                    task.status = "pending"
                await session.commit()

queue_worker = QueueWorker()
