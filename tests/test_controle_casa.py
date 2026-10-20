import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from core.evento import EventoCanonico
from core.tipos import CategoriaEvento, OrigemEvento, TipoAcao
from servicos.controle_casa import ControleCasa, controle_casa


@pytest.mark.parametrize("texto,acao", [
    ("Ollie, apaga a luz", "desligar"),
    ("Pode desligar as luzes do quarto pra mim?", "desligar"),
    ("Quero que você acenda a lâmpada do meu quarto", "ligar"),
    ("Por favor, ligue a luz", "ligar"),
    ("Como está a luz?", "consultar"),
    ("A luz está acesa?", "consultar"),
    ("Qual o estado da luz do quarto?", "consultar"),
])
def test_pedidos_naturais_resolvem_dispositivo_cadastrado(texto, acao):
    pedido = controle_casa.interpretar(texto)
    assert pedido["acao"] == acao
    assert controle_casa.resolver(pedido["alvo"])["entity_id"] == "light.yeelink_color5_027d_light"


@pytest.mark.parametrize("texto", ["não apague a luz", "se eu dormir apaga a luz",
    "ontem você apagou a luz", "apaga a luz e abre o vscode", "a música é luz do sol"])
def test_frases_que_nao_sao_ordens_simples_nao_acionam_heuristica(texto):
    pedido = controle_casa.interpretar(texto)
    assert pedido is None or pedido["acao"] == "consultar"


def test_catalogo_nao_inventa_comodo_e_recusa_nome_ambiguo(tmp_path):
    with pytest.raises(LookupError):
        controle_casa.resolver("luz da sala")
    path = tmp_path / "casa.json"
    path.write_text(json.dumps({
        "a": {"nome": "luz A", "entity_id": "light.a", "apelidos": ["luz"]},
        "b": {"nome": "luz B", "entity_id": "light.b", "apelidos": ["luz"]}}))
    with pytest.raises(LookupError):
        ControleCasa(path).resolver("luz")


@pytest.mark.asyncio
async def test_reflexo_encaminha_casa_sem_llm_e_preserva_canal(monkeypatch):
    import agentes.agente_reflexo as modulo
    publicar = AsyncMock()
    monkeypatch.setattr(modulo.kernel, "publicar", publicar)
    original = EventoCanonico(categoria=CategoriaEvento.SISTEMA_COMANDO_USUARIO,
        origem=OrigemEvento.ANDROID, pacote="com.example.assistentecell.voice", payload={"texto": "apaga a luz"})
    await modulo.AgenteReflexo().processar(original)
    derivado = publicar.call_args.args[0]
    assert derivado.categoria == CategoriaEvento.CASA_ACAO_SOLICITADA
    assert derivado.correlacao_id == original.correlacao_id and derivado.pacote == original.pacote
    assert derivado.payload == {"acao": "desligar", "alvo": "luz"}


@pytest.mark.asyncio
@pytest.mark.parametrize("acao,inicial,final,posts", [("desligar", "on", "off", 1),
    ("desligar", "off", "off", 0), ("consultar", "on", "on", 0), ("alternar", "off", "on", 1)])
async def test_home_assistant_confirma_estado_real(monkeypatch, acao, inicial, final, posts):
    import servicos.home_assistant_service as modulo
    estado = [inicial]
    comandos = []
    def responder(req):
        assert req.headers["Authorization"] == "Bearer teste-ha"
        if req.method == "POST":
            comandos.append(req.url.path)
            assert json.loads(req.content)["entity_id"] == "light.quarto"
            assert req.url.path.endswith("turn_on" if final == "on" else "turn_off")
            estado[0] = final
            return httpx.Response(200, json=[])
        return httpx.Response(200, json={"state": estado[0]})
    cliente = httpx.AsyncClient
    monkeypatch.setattr(modulo.httpx, "AsyncClient", lambda **kw: cliente(transport=httpx.MockTransport(responder)))
    service = modulo.HomeAssistantService()
    service.base_url, service.token = "http://ha.test", "teste-ha"
    assert await service.controlar_luz_confirmada(acao, "light.quarto") == {"entity_id": "light.quarto", "state": final}
    assert len(comandos) == posts


@pytest.mark.asyncio
async def test_http_200_nao_equivale_a_luz_desligada(monkeypatch):
    import servicos.home_assistant_service as modulo
    def responder(req):
        return httpx.Response(200, json={"state": "on"} if req.method == "GET" else [])
    cliente = httpx.AsyncClient
    monkeypatch.setattr(modulo.httpx, "AsyncClient", lambda **kw: cliente(transport=httpx.MockTransport(responder)))
    service = modulo.HomeAssistantService()
    service.base_url, service.token = "http://ha.test", "teste-ha"
    with pytest.raises(RuntimeError, match="não confirmou"):
        await service.controlar_luz_confirmada("desligar", "light.quarto")


@pytest.mark.asyncio
async def test_casa_sem_ponte_e_confirmacao_de_origem_errada():
    from api.websocket import GerenciadorNotificacoes
    central = GerenciadorNotificacoes()
    assert (await central.executar_casa("id", "desligar", "light.quarto"))["status"] == "sem_ponte"
    class Socket:
        client_state = SimpleNamespace(value=1)
    pc, outro = Socket(), Socket()
    central.pc_master = pc
    central._capacidades[pc] = {"CASA"}
    async def enviar(msg):
        dados = json.loads(msg)
        assert dados["comando"] == "casa_acao"
        ack = {"id_comando": "id", "status": "concluido", "resultado": {"entity_id": "light.quarto", "state": "off"}}
        central.confirmar_casa(outro, ack)
        assert not central._pedidos_casa["id"][2].done()
        central.confirmar_casa(pc, ack)
    pc.send_text = enviar
    assert (await central.executar_casa("id", "desligar", "light.quarto"))["resultado"]["state"] == "off"
    assert not central._pedidos_casa


@pytest.mark.asyncio
async def test_celular_pode_ser_ponte_sem_pc_e_timeout_nao_retenta():
    from api.websocket import GerenciadorNotificacoes
    central = GerenciadorNotificacoes()
    class Socket:
        client_state = SimpleNamespace(value=1)
    mobile = Socket()
    central.mobile_client = mobile
    central._capacidades[mobile] = {"CASA"}
    mobile.send_text = AsyncMock()
    resultado = await central.executar_casa("id", "desligar", "light.quarto", timeout=0.02)
    assert resultado["status"] == "sem_confirmacao"
    assert json.loads(mobile.send_text.call_args.args[0])["tipo_ws"] == "COMANDO_CASA"
    mobile.send_text.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("resultado,trecho", [
    ({"status": "concluido", "resultado": {"state": "off"}}, "apagada"),
    ({"status": "sem_confirmacao"}, "não recebi confirmação"),
    ({"status": "sem_ponte"}, "conexão local"),
    ({"status": "erro"}, "Não consegui confirmar")])
async def test_agente_responde_apos_resultado_sem_sucesso_inventado(monkeypatch, resultado, trecho):
    import agentes.agente_casa as modulo
    from api.websocket import central_alertas
    publicar = AsyncMock()
    monkeypatch.setattr(modulo.kernel, "publicar", publicar)
    monkeypatch.setattr(central_alertas, "executar_casa", AsyncMock(return_value=resultado))
    evento = EventoCanonico(categoria=CategoriaEvento.CASA_ACAO_SOLICITADA, origem=OrigemEvento.USUARIO,
        pacote="pc.chat", payload={"acao": "desligar", "alvo": "luz"})
    await modulo.AgenteCasa().processar(evento)
    resposta = publicar.call_args.args[0]
    assert trecho in resposta.payload["texto"]
    assert resposta.pacote == "pc.chat" and resposta.correlacao_id == evento.correlacao_id


@pytest.mark.asyncio
async def test_comando_de_luz_da_llm_tambem_passa_pela_central(monkeypatch):
    import agentes.agente_raciocinio as modulo
    publicar = AsyncMock()
    monkeypatch.setattr(modulo.kernel, "publicar", publicar)
    monkeypatch.setattr(modulo.obsidian_service, "listar_conhecimento_essencial", lambda _: "")
    agente = object.__new__(modulo.AgenteRaciocinio)
    agente._locks_ativos = set()
    agente._harvest_current_habits = AsyncMock(return_value=[])
    agente._registrar_log_cognitivo = Mock()
    agente._tentar_heuristica_local = lambda _: None
    agente.memoria_trabalho = SimpleNamespace(atualizar_conversa=AsyncMock(), obter_contexto=AsyncMock(return_value=[]))
    agente.llm = SimpleNamespace(classificar_evento=AsyncMock(return_value={
        "mensagem_dinamica": "Pronto, apaguei!", "tipo_interacao": "NOTIFICAR",
        "execucao_direta": [{"alvo": "MOBILE", "comando": "TURN_OFF_LIGHT", "parametro": "quarto"}]}))
    evento = EventoCanonico(categoria=CategoriaEvento.SISTEMA_COMANDO_USUARIO, acao=TipoAcao.INTENCAO_RACIOCINIO,
        origem=OrigemEvento.USUARIO, pacote="pc.chat", payload={"texto": "quero diminuir a iluminação agora"})
    await agente.processar(evento)
    publicar.assert_awaited_once()
    assert publicar.call_args.args[0].categoria == CategoriaEvento.CASA_ACAO_SOLICITADA
    assert publicar.call_args.args[0].payload == {"acao": "desligar", "alvo": "quarto"}


@pytest.mark.asyncio
async def test_botao_esp_pode_chamar_mesmo_controlador_da_conversa(tmp_path, monkeypatch):
    from servicos.botoes import ServicoBotoes, ToqueBotao
    from agentes.agente_botoes import AgenteBotoes
    from core.kernel import kernel
    path = tmp_path / "botoes.json"
    path.write_text(json.dumps([{"dispositivo": "esp", "botao": "luz", "acao": "casa",
                                 "alvo": "luz_quarto", "operacao": "desligar"}]))
    publicar = AsyncMock()
    monkeypatch.setattr(kernel, "publicar", publicar)
    service = ServicoBotoes(path)
    await service.receber(ToqueBotao(dispositivo="esp", botao="luz", evento_id="1"), kernel)
    recebido = publicar.call_args.args[0]
    await AgenteBotoes().processar(recebido)
    pedido = publicar.call_args.args[0]
    assert pedido.categoria == CategoriaEvento.CASA_ACAO_SOLICITADA
    assert pedido.payload == {"acao": "desligar", "alvo": "luz_quarto"}
    assert pedido.correlacao_id == recebido.correlacao_id


def test_voz_preserva_id_de_correlacao_no_websocket(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import api.websocket as modulo
    from core.kernel import kernel
    publicar = AsyncMock()
    monkeypatch.setattr(kernel, "publicar", publicar)
    monkeypatch.setattr(modulo, "central_alertas", modulo.GerenciadorNotificacoes())
    app = FastAPI()
    app.include_router(modulo.router)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/alertas") as ws:
            ws.receive_json()
            ws.send_json({"tipo_ws": "CHAT_MESSAGE", "texto": "apaga a luz",
                          "pacote": "com.example.assistentecell.voice", "correlacao_id": "pedido-voz-1"})
            ws.send_json({"tipo_ws": "REGISTRO", "id": "PC_MASTER"})
            assert ws.receive_json()["tipo_ws"] == "REGISTRO_OK"
    assert publicar.call_args.args[0].correlacao_id == "pedido-voz-1"


@pytest.mark.asyncio
async def test_acoes_da_mesma_luz_sao_serializadas(monkeypatch):
    import agentes.agente_casa as modulo
    from api.websocket import central_alertas
    ativos = 0
    pico = 0
    async def executar(*args):
        nonlocal ativos, pico
        ativos += 1
        pico = max(pico, ativos)
        await asyncio.sleep(0.01)
        ativos -= 1
        return {"status": "concluido", "resultado": {"state": "off"}}
    monkeypatch.setattr(central_alertas, "executar_casa", executar)
    monkeypatch.setattr(modulo.kernel, "publicar", AsyncMock())
    agente = modulo.AgenteCasa()
    def evento():
        return EventoCanonico(categoria=CategoriaEvento.CASA_ACAO_SOLICITADA,
            origem=OrigemEvento.USUARIO, pacote="pc.chat", payload={"acao": "desligar", "alvo": "luz"})
    await asyncio.gather(agente.processar(evento()), agente.processar(evento()))
    assert pico == 1


def test_conversa_completa_api_kernel_executor_e_resposta(monkeypatch):
    from contextlib import asynccontextmanager
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.kernel import KernelCognitivo
    from api.auth import AuthMiddleware
    import api.eventos as entrada
    import api.websocket as websocket
    import agentes.agente_reflexo as reflexo
    import agentes.agente_casa as casa
    import agentes.agente_notificacoes as notificacoes
    kernel = KernelCognitivo()
    central = websocket.GerenciadorNotificacoes()
    monkeypatch.setattr(websocket, "central_alertas", central)
    monkeypatch.setattr(notificacoes, "central_alertas", central)
    for modulo in [entrada, reflexo, casa, notificacoes]:
        monkeypatch.setattr(modulo, "kernel", kernel)
    monkeypatch.setenv("OLLIE_API_TOKEN", "teste-fluxo")
    kernel.registrar(lambda e: e.categoria == CategoriaEvento.SISTEMA_COMANDO_USUARIO, reflexo.AgenteReflexo().processar)
    kernel.registrar(lambda e: e.categoria == CategoriaEvento.CASA_ACAO_SOLICITADA, casa.AgenteCasa().processar)
    kernel.registrar(lambda e: e.categoria == CategoriaEvento.INTENCAO_NOTIFICACAO, notificacoes.AgenteNotificacoes().processar)
    @asynccontextmanager
    async def lifespan(app):
        tarefa = asyncio.create_task(kernel.iniciar())
        try:
            yield
        finally:
            tarefa.cancel()
            await asyncio.gather(tarefa, return_exceptions=True)
    app = FastAPI(lifespan=lifespan)
    app.add_middleware(AuthMiddleware)
    app.include_router(entrada.router)
    app.include_router(websocket.router)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/alertas?token=teste-fluxo") as pc, client.websocket_connect("/ws/alertas?token=teste-fluxo") as mobile:
            pc.receive_json()
            mobile.receive_json()
            pc.send_json({"tipo_ws": "REGISTRO", "id": "PC_MASTER", "capacidades": ["CASA"]})
            assert pc.receive_json()["tipo_ws"] == "REGISTRO_OK"
            mobile.send_json({"tipo_ws": "REGISTRO", "id": "MOBILE"})
            response = client.post("/eventos", headers={"Authorization": "Bearer teste-fluxo"}, json={
                "categoria": "SISTEMA_COMANDO_USUARIO", "pacote": "teste.casa.voz",
                "correlacao_id": "voz-integracao", "payload": {"texto": "apaga a luz"}})
            assert response.status_code == 202
            comando = pc.receive_json()
            pedido = json.loads(comando["parametro"])
            assert pedido == {"acao": "desligar", "entity_id": "light.yeelink_color5_027d_light"}
            pc.send_json({"tipo_ws": "COMANDO_RESULTADO", "id_comando": comando["id_comando"],
                          "status": "concluido", "resultado": {"entity_id": pedido["entity_id"], "state": "off"}})
            resposta = mobile.receive_json()
            assert resposta["tipo_ws"] == "CHAT_RESPONSE" and "apagada" in resposta["texto"]
            assert resposta["correlacao_id"] == "voz-integracao"
