"""Barramento com concorrência limitada e tarefas supervisionadas."""
from __future__ import annotations
import asyncio
import logging
from typing import Awaitable, Callable
from core.evento import EventoCanonico

logger = logging.getLogger("Kernel")
Callback = Callable[[EventoCanonico], Awaitable[None]]
Filtro = Callable[[EventoCanonico], bool]

class KernelCognitivo:
    def __init__(self, concorrencia: int = 8):
        if concorrencia < 1:
            raise ValueError("concorrencia deve ser positiva")
        self._concorrencia = concorrencia
        self._listeners: list[tuple[Filtro, Callback]] = []
        self._fila = asyncio.PriorityQueue()
        self._tarefas: set[asyncio.Task] = set()
        self.eventos_recebidos = 0
        self.eventos_processados = 0
        self.eventos_com_falha = 0
        self._contador = 0

    def limpar_listeners(self):
        self._listeners.clear()

    def registrar(self, filtro: Filtro, callback: Callback):
        self._listeners.append((filtro, callback))

    async def publicar(self, evento: EventoCanonico):
        self.eventos_recebidos += 1
        self._contador += 1
        await self._fila.put((-evento.prioridade.value, self._contador, evento))

    async def iniciar(self):
        limite = asyncio.Semaphore(self._concorrencia)
        try:
            while True:
                await limite.acquire()
                try:
                    _, _, evento = await self._fila.get()
                except BaseException:
                    limite.release()
                    raise
                tarefa = asyncio.create_task(self._processar_seguro(evento, limite))
                self._tarefas.add(tarefa)
                tarefa.add_done_callback(self._tarefas.discard)
        finally:
            tarefas = list(self._tarefas)
            for tarefa in tarefas:
                tarefa.cancel()
            await asyncio.gather(*tarefas, return_exceptions=True)

    async def _processar_seguro(self, evento, limite):
        try:
            if not await self._despachar(evento):
                self.eventos_com_falha += 1
            self.eventos_processados += 1
        except Exception:
            self.eventos_com_falha += 1
            logger.exception("Erro ao processar evento %s", evento.id)
        finally:
            self._fila.task_done()
            limite.release()

    async def _despachar(self, evento: EventoCanonico):
        callbacks = []
        sucesso = True
        for filtro, callback in tuple(self._listeners):
            try:
                if filtro(evento):
                    callbacks.append(callback)
            except Exception:
                sucesso = False
                logger.exception("Erro no filtro do evento %s", evento.id)
        resultados = await asyncio.gather(*(cb(evento) for cb in callbacks), return_exceptions=True)
        for callback, resultado in zip(callbacks, resultados):
            if isinstance(resultado, BaseException):
                sucesso = False
                logger.error("Listener %s falhou no evento %s: %s", callback, evento.id, resultado)
        return sucesso

    def estatisticas(self):
        return {
            "fila": self._fila.qsize(), "recebidos": self.eventos_recebidos,
            "processados": self.eventos_processados, "falhas": self.eventos_com_falha,
            "em_processamento": len(self._tarefas), "listeners_registrados": len(self._listeners),
        }

kernel = KernelCognitivo()
