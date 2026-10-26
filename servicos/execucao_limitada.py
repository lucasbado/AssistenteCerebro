"""Composição mínima sem persistência, IA, aprendizado ou tarefas periódicas de banco."""
import asyncio
from contextlib import asynccontextmanager

from core.kernel import kernel
from core.tipos import CategoriaEvento


@asynccontextmanager
async def executar_modo_limitado(app, motivo):
    from agentes.agente_modo_limitado import AgenteModoLimitado
    from agentes.agente_casa import AgenteCasa
    from agentes.agente_celular import AgenteCelular
    from agentes.agente_plano import AgentePlano
    from agentes.agente_botoes import AgenteBotoes
    from agentes.agente_pc_executor import AgentePcExecutor
    from agentes.agente_notificacoes import AgenteNotificacoes
    from api.websocket import central_alertas
    from banco.database import async_engine
    app.state.modo_limitado = True
    app.state.motivo_limitado = motivo
    agentes = {
        CategoriaEvento.SISTEMA_COMANDO_USUARIO: AgenteModoLimitado(),
        CategoriaEvento.CASA_ACAO_SOLICITADA: AgenteCasa(),
        CategoriaEvento.CELULAR_ACAO_SOLICITADA: AgenteCelular(),
        CategoriaEvento.PLANO_SOLICITADO: AgentePlano(),
        CategoriaEvento.BOTAO_ACIONADO: AgenteBotoes(),
        CategoriaEvento.SISTEMA_COMANDO_PC: AgentePcExecutor(),
        CategoriaEvento.INTENCAO_NOTIFICACAO: AgenteNotificacoes(),
    }
    for categoria, agente in agentes.items():
        kernel.registrar(lambda e, categoria=categoria: e.categoria == categoria, agente.processar)
    tasks = [asyncio.create_task(kernel.iniciar()), asyncio.create_task(central_alertas.iniciar_monitor())]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await async_engine.dispose()
