import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from core.evento import EventoCanonico
from core.tipos import CategoriaEvento, OrigemEvento, TipoAcao
from servicos.roteamento_pedidos import (
    resolver_abertura, interpretar_abertura, metadados_entrada, dispositivo_origem)


def pedido(texto, origem="MOBILE"):
    return EventoCanonico(categoria=CategoriaEvento.SISTEMA_COMANDO_USUARIO,
        acao=TipoAcao.INTENCAO_RACIOCINIO, origem=OrigemEvento.USUARIO,
        pacote="pc.chat" if origem == "PC" else "com.example.assistentecell.voice",
        payload={"texto": texto}, metadados=metadados_entrada(origem, "voz"))


@pytest.mark.parametrize("source,text,target", [
    ("PC", "abrir youtube", "PC"), ("MOBILE", "abrir youtube", "MOBILE"),
    ("PC", "abre o YouTube no celular", "MOBILE"),
    ("MOBILE", "abre o YouTube no PC", "PC"),
    ("MOBILE", "Ollie, pode abrir o YouTube no meu computador?", "PC"),
])
def test_destino_usa_texto_explicito_ou_origem(source, text, target):
    command = interpretar_abertura(text)
    assert command
    action = command["execucao_direta"][0]
    device, command, value = resolver_abertura(pedido(text, source), action["comando"], action["parametro"])
    assert device == target
    assert (command, value) == (("abrir_url", "https://www.youtube.com/") if target == "PC" else
                                 ("OPEN_APP", "com.google.android.youtube"))


def test_destino_ambiguo_nao_executa_e_app_exclusivo_nao_vaza_para_mobile():
    with pytest.raises(ValueError, match="mencionou"):
        resolver_abertura(pedido("abre YouTube no PC ou no celular"), "abrir_app", "youtube")
    with pytest.raises(ValueError, match="aplicativo é de PC"):
        resolver_abertura(pedido("abre o VS Code"), "abrir_app", "code.exe")
    assert resolver_abertura(pedido("abre Spotify no PC"), "OPEN_APP", "com.spotify.music") == ("PC", "abrir_app", "spotify")
    assert interpretar_abertura("quando eu abrir youtube") is None
    assert interpretar_abertura("não abra youtube") is None


@pytest.mark.parametrize("source,target,online", [
    ("PC", "PC", True), ("MOBILE", "MOBILE", True),
    ("PC", "MOBILE", True), ("MOBILE", "PC", True),
    ("PC", "MOBILE", False), ("MOBILE", "PC", False),
])
@pytest.mark.parametrize("use_llm", [False, True])
async def test_comando_so_vai_ao_destino_e_resposta_volta_a_origem(source, target, online, use_llm, monkeypatch):
    import agentes.agente_raciocinio as brain_module
    import agentes.agente_notificacoes as notification_module
    import api.websocket as ws_module
    from agentes.agente_pc_executor import AgentePcExecutor
    from core.kernel import kernel
    central = ws_module.GerenciadorNotificacoes()
    pc = SimpleNamespace(client_state=SimpleNamespace(value=1), send_text=AsyncMock())
    mobile = SimpleNamespace(client_state=SimpleNamespace(value=1), send_text=AsyncMock())
    central.pc_master, central.mobile_client = pc, mobile
    if not online:
        if target == "PC": central.pc_master = None
        else: central.mobile_client = None
    monkeypatch.setattr(ws_module, "central_alertas", central)
    monkeypatch.setattr(notification_module, "central_alertas", central)
    monkeypatch.setenv("RENDER", "true")  # Never execute on the real PC during tests.
    queue = []
    async def publish(event): queue.append(event)
    monkeypatch.setattr(kernel, "publicar", AsyncMock(side_effect=publish))
    brain = brain_module.AgenteRaciocinio()
    brain._harvest_current_habits = AsyncMock(return_value=[])
    brain._registrar_log_cognitivo = lambda *args: None
    brain.memoria_trabalho = SimpleNamespace(atualizar_conversa=AsyncMock(), obter_contexto=AsyncMock(return_value=[]))
    brain.llm = SimpleNamespace(classificar_evento=AsyncMock(side_effect=AssertionError("Simple opening must not use LLM")))
    if use_llm:
        brain._tentar_heuristica_local = lambda _: None
        brain.llm.classificar_evento = AsyncMock(return_value={"tipo_interacao": "NOTIFICAR",
            "mensagem_dinamica": "Abrindo no outro aparelho!",
            "execucao_direta": {"alvo": "MOBILE" if target == "PC" else "PC",
                               "comando": "abrir_app_mobile", "parametro": "com.google.android.youtube"}})
    monkeypatch.setattr(brain_module.obsidian_service, "listar_conhecimento_essencial", lambda _: "")
    text = "abrir youtube" + (f" no {'PC' if target == 'PC' else 'celular'}" if target != source else "")
    event = pedido(text, source)
    await brain.processar(event)
    executor, notifications = AgentePcExecutor(), notification_module.AgenteNotificacoes()
    while queue:
        output = queue.pop(0)
        if output.categoria == CategoriaEvento.SISTEMA_COMANDO_PC:
            await executor.processar(output)
        elif output.categoria == CategoriaEvento.INTENCAO_NOTIFICACAO:
            await notifications.processar(output)
    messages = {"PC": [json.loads(c.args[0]) for c in pc.send_text.call_args_list],
                "MOBILE": [json.loads(c.args[0]) for c in mobile.send_text.call_args_list]}
    commands = [(device, msg) for device, msgs in messages.items() for msg in msgs if msg["tipo_ws"] in {"COMANDO_PC", "COMANDO_SISTEMA"}]
    assert len(commands) == int(online)
    if online:
        device, command = commands[0]
        assert device == target and command["abertura_modo"] == "pedido"
        assert command["parametro"] == ("https://www.youtube.com/" if target == "PC" else "com.google.android.youtube")
    responses = [(device, msg) for device, msgs in messages.items() for msg in msgs if msg["tipo_ws"] == "CHAT_RESPONSE"]
    assert len(responses) == 1
    assert responses[0][0] == source
    assert responses[0][1]["correlacao_id"] == event.correlacao_id
    assert responses[0][1]["dispositivo_destino"] == source
    assert ("desconectado" in responses[0][1]["texto"]) is not online
    if use_llm:
        brain.llm.classificar_evento.assert_awaited_once()
    else:
        brain.llm.classificar_evento.assert_not_awaited()


async def test_resposta_pc_offline_nao_cai_no_celular():
    from api.websocket import GerenciadorNotificacoes
    central = GerenciadorNotificacoes()
    mobile = SimpleNamespace(client_state=SimpleNamespace(value=1), send_text=AsyncMock())
    central.mobile_client = mobile
    event = pedido("Como está a luz?", "PC").clonar(
        categoria=CategoriaEvento.INTENCAO_NOTIFICACAO, payload={"tipo_ws": "CHAT_RESPONSE", "texto": "Apagada"})
    assert not await central.enviar_alerta(event.model_dump())
    mobile.send_text.assert_not_awaited()


async def test_http_registra_origem_canal_e_correlacao(monkeypatch):
    import api.eventos as entry
    from core.kernel import kernel
    from fastapi import FastAPI
    import httpx
    publish = AsyncMock()
    monkeypatch.setattr(kernel, "publicar", publish)
    entry.DEDUPLICATION_CACHE.clear()
    app = FastAPI()
    app.include_router(entry.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.post("/eventos", json={"categoria": "SISTEMA_COMANDO_USUARIO",
            "pacote": "com.example.assistentecell.voice", "correlacao_id": "device-route-request",
            "payload": {"texto": "abrir youtube no PC", "canal": "voz"}})
    assert response.status_code == 202
    event = publish.call_args.args[0]
    assert dispositivo_origem(event) == "MOBILE"
    assert event.metadados["canal_origem"] == "voz"
    assert event.correlacao_id == "device-route-request"


def test_websocket_registrado_pc_nao_e_confundido_com_resposta_para_mobile(monkeypatch):
    import api.websocket as module
    from core.kernel import kernel
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    publish = AsyncMock()
    monkeypatch.setattr(kernel, "publicar", publish)
    monkeypatch.setattr(module, "central_alertas", module.GerenciadorNotificacoes())
    app = FastAPI()
    app.include_router(module.router)
    with TestClient(app) as client, client.websocket_connect("/ws/alertas") as ws:
        ws.receive_json()
        ws.send_json({"tipo_ws": "REGISTRO", "id": "PC_MASTER"})
        ws.receive_json()
        ws.send_json({"tipo_ws": "CHAT_MESSAGE", "id": "PC_MASTER", "pacote": "pc.master",
            "texto": "abrir youtube", "correlacao_id": "pc-request", "canal": "texto"})
        ws.send_json({"tipo_ws": "REGISTRO", "id": "PC_MASTER"})
        ws.receive_json()  # Barrier: the previous request has been processed.
        event = publish.call_args.args[0]
        assert event.metadados["dispositivo_origem"] == "PC"
        assert event.payload["texto"] == "abrir youtube"
        assert event.correlacao_id == "pc-request"


@pytest.mark.parametrize("opened", [True, False])
async def test_executor_local_responde_uma_vez_na_origem(monkeypatch, opened):
    import agentes.agente_pc_executor as module
    from core.kernel import kernel
    from unittest.mock import Mock
    monkeypatch.setenv("RENDER", "false")
    # Patch the module's OS reference rather than the operating system used by pytest.
    monkeypatch.setattr(module, "os", SimpleNamespace(name="nt", getenv=lambda key, default=None: "false" if key == "RENDER" else default))
    monkeypatch.setattr(module.pc_control_service, "abrir_app", Mock(return_value=opened))
    publish = AsyncMock()
    monkeypatch.setattr(kernel, "publicar", publish)
    event = pedido("abre Spotify no PC").clonar(categoria=CategoriaEvento.SISTEMA_COMANDO_PC,
        payload={"comando": "abrir_app", "parametro": "spotify"},
        metadados={**metadados_entrada("MOBILE", "voz"), "pedido_explicito": True})
    await module.AgentePcExecutor().processar(event)
    publish.assert_awaited_once()
    reply = publish.call_args.args[0]
    assert reply.metadados["dispositivo_origem"] == "MOBILE"
    assert reply.correlacao_id == event.correlacao_id
    assert ("Não consegui" in reply.payload["texto"]) is (not opened)
