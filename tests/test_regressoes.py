import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport
from pydantic import ValidationError
from sqlalchemy import text, select
from starlette.websockets import WebSocketDisconnect

from core.evento import EventoCanonico
from core.kernel import KernelCognitivo
from core.tipos import CategoriaEvento, OrigemEvento, TipoAcao
from api.auth import AuthMiddleware
from scripts.pc_command import executar

def evento(**kwargs):
    return EventoCanonico(categoria=CategoriaEvento.SISTEMA_COMANDO_PC,
                          origem=OrigemEvento.USUARIO, pacote="teste", **kwargs)

def test_evento_e_conteudo_imutaveis():
    original = {"itens": [{"valor": 1}]}
    e = evento(payload=original)
    original["itens"][0]["valor"] = 2
    assert e.payload["itens"][0]["valor"] == 1
    with pytest.raises(ValidationError):
        e.pacote = "alterado"
    with pytest.raises(TypeError):
        e.payload["itens"][0]["valor"] = 3
    with pytest.raises(TypeError):
        e.payload["itens"].append(4)
    clone = e.clonar(payload={"novo": True})
    assert clone.id != e.id and clone.evento_pai == e.id
    assert clone.correlacao_id == e.correlacao_id
    assert json.loads(e.model_dump_json())["payload"] == original | {"itens": [{"valor": 1}]}

@pytest.mark.asyncio
async def test_kernel_limita_concorrencia_e_registra_falha():
    kernel = KernelCognitivo(concorrencia=2)
    entrou = asyncio.Event()
    liberar = asyncio.Event()
    ativos = 0
    pico = 0
    async def lento(e):
        nonlocal ativos, pico
        ativos += 1
        pico = max(pico, ativos)
        if ativos == 2:
            entrou.set()
        await liberar.wait()
        ativos -= 1
    async def falha(e):
        raise RuntimeError("falha simulada")
    kernel.registrar(lambda e: True, lento)
    kernel.registrar(lambda e: True, falha)
    for _ in range(5):
        await kernel.publicar(evento())
    task = asyncio.create_task(kernel.iniciar())
    try:
        await asyncio.wait_for(entrou.wait(), 2)
        assert len(kernel._tarefas) == 2
        liberar.set()
        await asyncio.wait_for(kernel._fila.join(), 2)
        assert pico == 2
        assert kernel.eventos_processados == kernel.eventos_com_falha == 5
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert not kernel._tarefas

@pytest.mark.asyncio
async def test_kernel_cancela_listeners_ao_encerrar():
    kernel = KernelCognitivo(1)
    entrou = asyncio.Event()
    encerrou = asyncio.Event()
    async def listener(e):
        entrou.set()
        try:
            await asyncio.Event().wait()
        finally:
            encerrou.set()
    kernel.registrar(lambda e: True, listener)
    await kernel.publicar(evento())
    task = asyncio.create_task(kernel.iniciar())
    await asyncio.wait_for(entrou.wait(), 2)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert encerrou.is_set()
    await asyncio.wait_for(kernel._fila.join(), 2)

@pytest.mark.asyncio
async def test_auth_http_fail_closed(monkeypatch):
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    @app.get("/privado")
    async def privado():
        return {"ok": True}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        monkeypatch.delenv("OLLIE_API_TOKEN", raising=False)
        assert (await client.get("/privado")).status_code == 503
        monkeypatch.setenv("OLLIE_API_TOKEN", "segredo")
        assert (await client.get("/privado")).status_code == 401
        assert (await client.get("/privado", headers={"Authorization": "Bearer errado"})).status_code == 401
        assert (await client.get("/privado", headers={"Authorization": "Bearer segredo"})).status_code == 200

def test_websocket_autentica_e_chat_publica(monkeypatch):
    from api.websocket import router, central_alertas
    from core.kernel import kernel
    monkeypatch.setenv("OLLIE_API_TOKEN", "segredo")
    publicar = AsyncMock()
    monkeypatch.setattr(kernel, "publicar", publicar)
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.include_router(router)
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/alertas"):
                pass
        with client.websocket_connect("/ws/alertas?token=segredo") as ws:
            assert ws.receive_json()["tipo_ws"] == "SOLICITAR_IDENTIFICACAO"
            ws.send_json({"tipo_ws": "CHAT_MESSAGE", "texto": "oi", "pacote": "pc.chat"})
            ws.send_json({"tipo_ws": "REGISTRO", "id": "PC_MASTER"})
            assert ws.receive_json()["tipo_ws"] == "REGISTRO_OK"
    publicar.assert_awaited_once()
    assert publicar.call_args.args[0].payload["texto"] == "oi"
    assert not central_alertas.conexoes_ativas

@pytest.mark.asyncio
async def test_executor_local_sem_erro_escopo(monkeypatch):
    import agentes.agente_pc_executor as modulo
    monkeypatch.setenv("RENDER", "false")
    service = Mock()
    monkeypatch.setattr(modulo, "pc_control_service", service)
    await modulo.AgentePcExecutor().processar(evento(acao=TipoAcao.EXECUTAR_PROGRAMA, payload={"programa": "vscode"}))
    service.abrir_app.assert_called_once_with("vscode")

def test_ponte_nao_interpreta_parametro_como_codigo():
    service = Mock()
    entrada = "nome'); raise RuntimeError('injetado"
    executar("abrir_app", entrada, service)
    service.abrir_app.assert_called_once_with(entrada)
    with pytest.raises(ValueError, match="não permitido"):
        executar("cmd /c whoami", "", service)
    with pytest.raises(ValueError):
        executar("open_url", "file:///C:/Windows", service)
    executar("volume_sistema", "0", service)
    service.set_system_volume.assert_called_once_with(0)

@pytest.mark.asyncio
async def test_fts_mantem_insercao_atualizacao_e_exclusao(banco_teste):
    from banco.models import FactDB
    async with banco_teste() as session:
        fato = FactDB(text="cafe", keywords=[])
        session.add(fato)
        await session.commit()
        assert (await session.execute(text("SELECT rowid FROM facts_fts WHERE facts_fts MATCH 'cafe'"))).first()
        fato.text = "musica"
        await session.commit()
        assert not (await session.execute(text("SELECT rowid FROM facts_fts WHERE facts_fts MATCH 'cafe'"))).first()
        assert (await session.execute(text("SELECT rowid FROM facts_fts WHERE facts_fts MATCH 'musica'"))).first()
        await session.delete(fato)
        await session.commit()
        assert not (await session.execute(text("SELECT rowid FROM facts_fts WHERE facts_fts MATCH 'musica'"))).first()

@pytest.mark.asyncio
async def test_worker_recupera_reserva_expirada_e_nao_reserva_ativa(banco_teste):
    from banco.models import TaskQueueDB
    from servicos.queue_worker import QueueWorker
    async with banco_teste() as session:
        expirada = TaskQueueDB(task_type="extract_facts", payload={"texto": "teste"}, status="processing", attempts=1,
                               locked_until=datetime.now(timezone.utc) - timedelta(seconds=1))
        ativa = TaskQueueDB(task_type="extract_facts", payload={}, status="processing", attempts=1,
                           locked_until=datetime.now(timezone.utc) + timedelta(minutes=3))
        session.add_all([expirada, ativa])
        await session.commit()
        expirada_id, ativa_id = expirada.id, ativa.id
    worker = QueueWorker(banco_teste)
    worker._executar = AsyncMock()
    await worker._processar_proxima_tarefa()
    worker._executar.assert_awaited_once()
    async with banco_teste() as session:
        assert (await session.get(TaskQueueDB, expirada_id)).status == "done"
        assert (await session.get(TaskQueueDB, ativa_id)).attempts == 1

@pytest.mark.asyncio
async def test_worker_falha_apos_tres_tentativas(banco_teste):
    from banco.models import TaskQueueDB
    from servicos.queue_worker import QueueWorker
    async with banco_teste() as session:
        task = TaskQueueDB(task_type="inexistente", payload={})
        session.add(task)
        await session.commit()
        task_id = task.id
    worker = QueueWorker(banco_teste)
    for _ in range(3):
        await worker._processar_proxima_tarefa()
    async with banco_teste() as session:
        task = await session.get(TaskQueueDB, task_id)
        assert task.status == "dead" and task.attempts == 3

@pytest.mark.asyncio
async def test_migracao_banco_antigo_e_repetivel(tmp_path):
    from banco.database import _criar_motor, inicializar_banco
    engine = _criar_motor("sqlite+aiosqlite:///" + (tmp_path / "antigo.db").as_posix())
    try:
        async with engine.begin() as conn:
            await conn.exec_driver_sql("CREATE TABLE facts(id INTEGER PRIMARY KEY, text TEXT, keywords JSON)")
            await conn.exec_driver_sql("CREATE TABLE task_queue(id INTEGER PRIMARY KEY)")
        await inicializar_banco(engine)
        await inicializar_banco(engine)
        async with engine.connect() as conn:
            fatos = (await conn.exec_driver_sql("PRAGMA table_info(facts)")).all()
            tarefas = (await conn.exec_driver_sql("PRAGMA table_info(task_queue)")).all()
            assert {"source_file", "source_hash"} <= {linha[1] for linha in fatos}
            assert "locked_until" in {linha[1] for linha in tarefas}
    finally:
        await engine.dispose()

@pytest.mark.asyncio
async def test_cache_llm_separa_contexto_e_nao_reutiliza_acoes(monkeypatch):
    import servicos.llm as modulo
    cache = {}
    buscar = AsyncMock(side_effect=lambda key: cache.get(key))
    inserir = AsyncMock(side_effect=lambda key, value: cache.update({key: value}))
    monkeypatch.setattr(modulo.semantic_cache_service, "buscar", buscar)
    monkeypatch.setattr(modulo.semantic_cache_service, "inserir", inserir)
    monkeypatch.setattr(modulo.context_builder, "construir_contexto", AsyncMock(return_value={
        "global_summary": "global", "session_summary": "sessao", "fatos_relevantes": "fatos",
    }))
    monkeypatch.setattr(modulo.consciencia, "obter_resumo_para_llm", Mock(return_value="ambiente A"))
    provider = Mock()
    provider.gerar = AsyncMock(return_value=json.dumps({"mensagem_dinamica": "oi", "execucao_direta": []}))
    service = object.__new__(modulo.ServicoLLM)
    service._consecutive_failures = 0
    service._circuit_open_until = 0
    service._pick_provider = Mock(return_value=provider)
    service.ollama = provider
    data = datetime(2026, 1, 1, 10)
    async def chamar():
        return await service.classificar_evento("CHAT", "sessao-A", {"texto": "oi"}, timestamp_dispositivo=data)
    await chamar()
    await chamar()
    assert provider.gerar.await_count == 1
    monkeypatch.setattr(modulo.consciencia, "obter_resumo_para_llm", Mock(return_value="ambiente B"))
    provider.gerar.return_value = json.dumps({"execucao_direta": [{"comando": "abrir_app"}]})
    await chamar()
    await chamar()
    assert provider.gerar.await_count == 3
    assert inserir.await_count == 1

@pytest.mark.asyncio
async def test_embedding_persistido_sem_chamada_externa(banco_teste, monkeypatch):
    import servicos.queue_worker as modulo
    from banco.models import TaskQueueDB, FactDB
    response = Mock()
    response.json.return_value = {"embeddings": [[0.1] * 768]}
    client = AsyncMock()
    client.post.return_value = response
    context = AsyncMock()
    context.__aenter__.return_value = client
    monkeypatch.setattr(modulo.httpx, "AsyncClient", Mock(return_value=context))
    async with banco_teste() as session:
        fato = FactDB(text="gosta de cafe", keywords=[])
        task = TaskQueueDB(task_type="embed_fact", payload={"fact_text": "gosta de cafe"})
        session.add_all([fato, task])
        await session.commit()
        fato_id, task_id = fato.id, task.id
    await modulo.QueueWorker(banco_teste)._processar_proxima_tarefa()
    async with banco_teste() as session:
        assert len((await session.get(FactDB, fato_id)).embedding) == 768 * 4
        assert (await session.get(TaskQueueDB, task_id)).status == "done"

@pytest.mark.asyncio
async def test_contexto_relacionado_a_consulta_e_limitado(banco_teste):
    from banco.models import FactDB
    from servicos.context_builder import ContextBuilder
    async with banco_teste() as session:
        session.add_all([
            FactDB(text="prefere cafe " + "x" * 5000, importance=0.1),
            FactDB(text="gosta de futebol", importance=1.0),
        ])
        await session.commit()
    contexto = await ContextBuilder(max_tokens=500).construir_contexto("cafe", "sessao")
    assert "cafe" in contexto["fatos_relevantes"]
    assert "futebol" not in contexto["fatos_relevantes"]
    assert sum(len(str(v).encode("utf-8")) for v in contexto.values()) <= 500
