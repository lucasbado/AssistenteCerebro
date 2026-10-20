"""Fixtures isoladas: nenhum teste usa o banco pessoal ou uma LLM remota."""
import sys
from unittest.mock import AsyncMock
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

@pytest.fixture
async def banco_teste(tmp_path, monkeypatch):
    from banco.database import _criar_motor, inicializar_banco
    from servicos.llm import ServicoLLM
    engine = _criar_motor("sqlite+aiosqlite:///" + (tmp_path / "teste.db").as_posix())
    await inicializar_banco(engine)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    for nome, modulo in list(sys.modules.items()):
        if nome.startswith(("banco.", "servicos.", "api.", "agentes.")) and hasattr(modulo, "AsyncSessionLocal"):
            monkeypatch.setattr(modulo, "AsyncSessionLocal", factory)
    monkeypatch.setattr(ServicoLLM, "resumir_perfil_usuario", AsyncMock(return_value={"resumo": "Perfil de teste", "cards": []}))
    monkeypatch.setenv("OLLIE_API_TOKEN", "token-de-teste")
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture
async def catalogo_teste(banco_teste, monkeypatch):
    import servicos.catalogo_rotinas as modulo
    from servicos.routine_discovery_service import routine_discovery_service
    from servicos.routine_generator_service import routine_generator_service
    from api import router_capabilities
    from agentes import agente_rotina
    catalogo = modulo.CatalogoRotinas(caminhos={})
    monkeypatch.setattr(modulo, "AsyncSessionLocal", banco_teste)
    monkeypatch.setattr(router_capabilities, "catalogo_rotinas", catalogo)
    monkeypatch.setattr(agente_rotina, "catalogo_rotinas", catalogo)
    monkeypatch.setattr(routine_discovery_service, "catalogo", catalogo)
    monkeypatch.setattr(routine_generator_service, "catalogo", catalogo)
    yield catalogo
