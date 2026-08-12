"""
core/kernel.py
Kernel Cognitivo - Refatorado para Alta Performance
"""

from __future__ import annotations
import asyncio
import logging
from typing import Awaitable, Callable
from core.evento import EventoCanonico
from core.tipos import EstadoEvento, TipoAcao, CategoriaEvento, PrioridadeEvento

logger = logging.getLogger("Kernel")

Callback = Callable[[EventoCanonico], Awaitable[None]]
Filtro = Callable[[EventoCanonico], bool]

class KernelCognitivo:
    def __init__(self):
        self._listeners: list[tuple[Filtro, Callback]] = []
        self._fila = asyncio.PriorityQueue()
        self.eventos_recebidos = 0
        self.eventos_processados = 0
        self._contador = 0

    def limpar_listeners(self):
        if self._listeners:
            logger.info(f"[Kernel] Limpando {len(self._listeners)} listeners antigos.")
            self._listeners.clear()

    def registrar(self, filtro: Filtro, callback: Callback):
        self._listeners.append((filtro, callback))
        logger.info(f"[Kernel] Listener registrado: {callback.__qualname__}")

    async def publicar(self, evento: EventoCanonico):
        self.eventos_recebidos += 1
        self._contador += 1

        # Aumenta a prioridade se for um comando imediato do usuário
        if evento.categoria in [CategoriaEvento.SISTEMA_COMANDO_PC, CategoriaEvento.SISTEMA_COMANDO_USUARIO]:
            evento.prioridade = PrioridadeEvento.ALTA
            
        # asyncio.PriorityQueue usa o menor valor como maior prioridade
        prioridade_valor = -evento.prioridade.value
        
        await self._fila.put((prioridade_valor, self._contador, evento))
        logger.info(f"[Kernel] Evento enfileirado: {evento.categoria.value} ({evento.id[:8]})")

    async def iniciar(self):
        logger.info("🚀 Kernel em modo Concorrente (Alta Performance) iniciado.")
        while True:
            # Obtém o evento da fila
            _, _, evento = await self._fila.get()
            evento.estado = EstadoEvento.PROCESSANDO
            
            # --- MUDANÇA CRÍTICA: NÃO USAMOS 'AWAIT' NO DESPACHO ---
            # Disparamos uma Task e voltamos imediatamente para pegar o próximo da fila.
            # Isso impede que um agente lento (como a LLM) trave o sistema.
            asyncio.create_task(self._processar_seguro(evento))
            self.eventos_processados += 1

    async def _processar_seguro(self, evento: EventoCanonico):
        """Wrapper para despachar e gerenciar o ciclo de vida da tarefa."""
        try:
            logger.info(f"[Kernel] Processando {evento.categoria.value} | Ação: {evento.acao.value}")
            await self._despachar(evento)
        except Exception as e:
            logger.error(f"❌ Erro ao processar evento {evento.id[:8]}: {e}")
        finally:
            self._fila.task_done()

    async def _despachar(self, evento: EventoCanonico):
        tarefas = []
        for filtro, callback in self._listeners:
            if filtro(evento):
                tarefas.append(callback(evento))
        
        if tarefas:
            # Aqui sim usamos gather, mas apenas dentro desta task específica do evento
            await asyncio.gather(*tarefas, return_exceptions=True)
            logger.info(f"✅ Evento {evento.id[:8]} finalizado por {len(tarefas)} ouvintes.")

    def estatisticas(self):
        return {
            "fila": self._fila.qsize(),
            "recebidos": self.eventos_recebidos,
            "processados": self.eventos_processados,
            "listeners_registrados": len(self._listeners),
        }

kernel = KernelCognitivo()
