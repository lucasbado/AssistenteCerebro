import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from servicos.controle_celular import interpretar_controle, validar_acao
from servicos.ponte_celular import PonteCelular
from core.evento import EventoCanonico
from core.tipos import CategoriaEvento, OrigemEvento


@pytest.mark.parametrize("texto,acao,args", [
    ("Ei Ollie, ligue a lanterna", "flashlight.set", {"estado": True}),
    ("Desligue o flash no celular", "flashlight.set", {"estado": False}),
    ("Desative o não perturbe", "dnd.set", {"estado": False}),
    ("Ative o não perturbe", "dnd.set", {"estado": True}),
    ("Coloque o volume de mídia em 40%", "volume.set", {"canal": "media", "valor": 40}),
    ("Ajuste o volume do alarme para 60 por cento", "volume.set", {"canal": "alarm", "valor": 60}),
    ("Ajuste o brilho para 10%", "brightness.set", {"valor": 10}),
    ("Coloque o celular no modo vibrar", "sound.mode", {"modo": "vibrate"}),
    ("Ative o modo silencioso", "sound.mode", {"modo": "silent"}),
    ("Ative o GPS", "settings.open", {"painel": "location", "estado_desejado": True}),
    ("Desative o Wi-Fi", "settings.open", {"painel": "wifi", "estado_desejado": False}),
    ("Ative o Bluetooth", "settings.open", {"painel": "bluetooth", "estado_desejado": True}),
    ("Crie um timer de 1 hora e 5 minutos", "timer.create", {"segundos": 3900}),
    ("Coloque um despertador para 7:30", "alarm.create", {"hora": 7, "minuto": 30}),
    ("Crie um alarme às 0:00", "alarm.create", {"hora": 0, "minuto": 0}),
    ("Volte uma tela", "navigation", {"destino": "back"}),
    ("Abra as notificações", "navigation", {"destino": "notifications"}),
    ("Abra os controles do celular", "controls.open", {}),
])
def test_ordens_validas_parametros_exatos(texto, acao, args):
    plano = interpretar_controle(texto)
    assert plano == {"acoes": [{"acao": acao, "parametros": args}]}
    validar_acao(acao, args)


@pytest.mark.parametrize("texto", ["Não ligue a lanterna", "Nunca desligue o flash", "Se eu sair ligue a lanterna",
    "Como funciona a lanterna?", "Ontem ligue a lanterna", "Quanto tempo dura um timer?", "Ligue a lanterna no PC",
    "Crie um alarme para amanhã às 7", "Me explique o GPS"])
def test_nao_confunde_conversa_negacao_condicao_destino_e_data(texto):
    assert interpretar_controle(texto) is None


def test_plano_completo_sem_execucao_parcial_e_origem():
    plano = interpretar_controle("Ligue a lanterna e coloque o brilho em 50%")
    assert len(plano["acoes"]) == 2
    assert interpretar_controle("Ligue a lanterna e abra uma coisa desconhecida").get("esclarecimento")
    assert interpretar_controle("Coloque o volume em 50%", "PC") is None
    assert interpretar_controle("Coloque o volume em 50% no celular", "PC")["acoes"]
    assert interpretar_controle("Ligue a lanterna", "PC")["acoes"]


def test_mensagem_preserva_texto_literal_sem_executar_seu_conteudo():
    body = 'Não desligue a luz e abra https://example.com/Case?A=B no PC e no celular, às 7!'
    plano = interpretar_controle('Mande mensagem para Ana no WhatsApp dizendo ' + body)
    assert plano == {"acoes": [{"acao": "message.prepare", "parametros": {"app": "whatsapp", "destinatario": "Ana", "texto": body}}]}
    assert interpretar_controle("Envie uma mensagem para João no Instagram dizendo oi")["acoes"][0]["parametros"]["app"] == "instagram"
    assert interpretar_controle("Mande uma mensagem para Ana")["esclarecimento"]


@pytest.mark.parametrize("acao,args", [
    ("flashlight.set", {"estado": "false"}), ("flashlight.set", {"estado": 1}),
    ("volume.set", {"canal": "media", "valor": True}), ("volume.set", {"canal": "media", "valor": 101}),
    ("volume.set", {"canal": "all", "valor": 50}), ("timer.create", {"segundos": 0}),
    ("timer.create", {"segundos": 86401}), ("alarm.create", {"hora": 24, "minuto": 0}),
    ("brightness.set", {"valor": 50, "shell": "ls"}), ("message.send", {"texto": "envie sem confirmar"}),
    ("settings.open", {"painel": "location"}), ("message.prepare", {"app": "instagram", "destinatario": "", "texto": "x"}),
])
def test_contrato_recusa_coercao_chaves_extras_e_envio_remoto(acao, args):
    with pytest.raises(ValueError):
        validar_acao(acao, args)


def socket():
    return SimpleNamespace(client_state=SimpleNamespace(value=1))


@pytest.mark.asyncio
async def test_ponte_confirma_mesmo_socket_id_e_acao_sem_broadcast():
    ponte = PonteCelular()
    ws, other = socket(), socket()
    async def send(dest, msg):
        assert dest is ws and msg["pedido_usuario"] is True
        ack = {"id_comando": msg["id_comando"], "acao": msg["acao"], "status": "concluido", "texto": "Lanterna ligada."}
        assert not ponte.confirmar(other, ack)
        assert not ponte.confirmar(ws, {**ack, "id_comando": "outro"})
        assert not ponte.confirmar(ws, {**ack, "acao": "message.send"})
        assert not ponte.confirmar(ws, {**ack, "status": "aceito"})
        assert ponte.confirmar(ws, ack)
        assert not ponte.confirmar(ws, ack)
        return True
    assert (await ponte.executar(ws, send, "flashlight.set", {"estado": True}))["texto"] == "Lanterna ligada."
    assert ponte.pendentes == {}


@pytest.mark.asyncio
async def test_timeout_desconexao_e_cancelamento_nao_repetem():
    ponte = PonteCelular()
    enviar = AsyncMock(return_value=True)
    ws = socket()
    assert (await ponte.executar(ws, enviar, "timer.create", {"segundos": 1}, timeout=.01))["status"] == "sem_confirmacao"
    enviar.assert_awaited_once()
    assert not ponte.pendentes
    task = asyncio.create_task(ponte.executar(ws, enviar, "timer.create", {"segundos": 1}))
    await asyncio.sleep(0)
    ponte.desconectar(ws)
    assert (await task)["status"] == "sem_confirmacao"
    task = asyncio.create_task(ponte.executar(ws, enviar, "timer.create", {"segundos": 1}))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    assert not ponte.pendentes


@pytest.mark.asyncio
async def test_reflexo_nao_usa_llm_e_agente_nao_executa_notificacao(monkeypatch):
    from agentes.agente_reflexo import AgenteReflexo
    from agentes.agente_celular import AgenteCelular
    from core.kernel import kernel
    from api.websocket import central_alertas
    publish, execute = AsyncMock(), AsyncMock(return_value={"status": "concluido", "texto": "Lanterna ligada."})
    monkeypatch.setattr(kernel, "publicar", publish)
    monkeypatch.setattr(central_alertas, "executar_celular", execute)
    pedido = EventoCanonico(categoria=CategoriaEvento.SISTEMA_COMANDO_USUARIO, origem=OrigemEvento.USUARIO,
        pacote="pc.chat", metadados={"dispositivo_origem": "PC", "canal_origem": "voz"}, payload={"texto": "Ligue a lanterna"})
    await AgenteReflexo().processar(pedido)
    derivado = publish.call_args.args[0]
    assert derivado.categoria == CategoriaEvento.CELULAR_ACAO_SOLICITADA
    await AgenteCelular().processar(derivado)
    execute.assert_awaited_once_with("flashlight.set", {"estado": True})
    resposta = publish.call_args.args[0]
    assert resposta.payload["texto"] == "Lanterna ligada."
    assert resposta.correlacao_id == pedido.correlacao_id and resposta.metadados["dispositivo_origem"] == "PC"
    execute.reset_mock()
    await AgenteCelular().processar(derivado.clonar(origem=OrigemEvento.IA))
    await AgenteCelular().processar(derivado.clonar(categoria=CategoriaEvento.NOTIFICACAO))
    execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_plano_para_na_primeira_permissao_ou_interacao(monkeypatch):
    from agentes.agente_celular import AgenteCelular
    from api.websocket import central_alertas
    from core.kernel import kernel
    execute = AsyncMock(return_value={"status": "permissao", "texto": "Autorize a câmera."})
    publish = AsyncMock()
    monkeypatch.setattr(central_alertas, "executar_celular", execute)
    monkeypatch.setattr(kernel, "publicar", publish)
    evento = EventoCanonico(categoria=CategoriaEvento.CELULAR_ACAO_SOLICITADA, origem=OrigemEvento.USUARIO,
        pacote="mobile.chat", payload={"texto": "Ligue a lanterna e coloque o brilho em 50%"})
    await AgenteCelular().processar(evento)
    execute.assert_awaited_once()
    assert "Parei as próximas" in publish.call_args.args[0].payload["texto"]


@pytest.mark.asyncio
async def test_replay_do_pedido_nao_cria_outro_timer(monkeypatch):
    from agentes.agente_celular import AgenteCelular
    from api.websocket import central_alertas
    from core.kernel import kernel
    execute = AsyncMock(return_value={"status": "sem_confirmacao"})
    publish = AsyncMock()
    monkeypatch.setattr(central_alertas, "executar_celular", execute)
    monkeypatch.setattr(kernel, "publicar", publish)
    evento = EventoCanonico(categoria=CategoriaEvento.CELULAR_ACAO_SOLICITADA, origem=OrigemEvento.USUARIO,
        pacote="mobile.chat", payload={"texto": "Crie um timer de 5 minutos"})
    agent = AgenteCelular()
    await asyncio.gather(agent.processar(evento), agent.processar(evento.clonar()))
    await agent.processar(evento)
    execute.assert_awaited_once()
    publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_versao_antiga_offline_e_diagnostico_casa():
    from api.websocket import GerenciadorNotificacoes
    central = GerenciadorNotificacoes()
    assert (await central.executar_celular("flashlight.set", {"estado": True}))["status"] == "offline"
    class Socket:
        client_state = SimpleNamespace(value=1)
    ws = Socket()
    central.mobile_client = ws
    assert (await central.executar_celular("flashlight.set", {"estado": True}))["status"] == "atualizar"
    assert not central.estado_conexoes()["casa"]["ponte_disponivel"]
    central._capacidades[ws] = {"CASA", "CONTROLE_MOBILE"}
    assert central.estado_conexoes()["casa"]["mobile_configurado"]
    assert central.estado_conexoes()["mobile"]["controle_disponivel"]


def test_fluxo_api_kernel_android_confirmacao_e_resposta_no_pc(monkeypatch):
    from contextlib import asynccontextmanager
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.auth import AuthMiddleware
    from core.kernel import KernelCognitivo
    import core.kernel as kernel_module
    import api.eventos as entrada
    import api.websocket as ws_module
    import agentes.agente_reflexo as reflexo
    import agentes.agente_notificacoes as notificacoes
    from agentes.agente_celular import AgenteCelular
    from servicos import roteamento_pedidos
    kernel = KernelCognitivo()
    central = ws_module.GerenciadorNotificacoes()
    monkeypatch.setenv("OLLIE_API_TOKEN", "teste-mobile")
    monkeypatch.setattr(ws_module, "central_alertas", central)
    monkeypatch.setattr(notificacoes, "central_alertas", central)
    for module in (kernel_module, entrada, reflexo, notificacoes):
        monkeypatch.setattr(module, "kernel", kernel)
    kernel.registrar(lambda e: e.categoria == CategoriaEvento.SISTEMA_COMANDO_USUARIO, reflexo.AgenteReflexo().processar)
    kernel.registrar(lambda e: e.categoria == CategoriaEvento.CELULAR_ACAO_SOLICITADA, AgenteCelular().processar)
    kernel.registrar(lambda e: e.categoria == CategoriaEvento.INTENCAO_NOTIFICACAO, notificacoes.AgenteNotificacoes().processar)
    @asynccontextmanager
    async def lifespan(app):
        job = asyncio.create_task(kernel.iniciar())
        try: yield
        finally:
            job.cancel()
            await asyncio.gather(job, return_exceptions=True)
    app = FastAPI(lifespan=lifespan)
    app.add_middleware(AuthMiddleware)
    app.include_router(entrada.router)
    app.include_router(ws_module.router)
    async def wait_mobile():
        async with asyncio.timeout(2):
            while not central.mobile_client:
                await asyncio.sleep(.001)
    with TestClient(app) as client:
        assert client.post("/eventos", json={}).status_code == 401
        with client.websocket_connect("/ws/alertas?token=teste-mobile") as pc, client.websocket_connect("/ws/alertas?token=teste-mobile") as mobile:
            pc.receive_json(); mobile.receive_json()
            pc.send_json({"tipo_ws": "REGISTRO", "id": "PC_MASTER"})
            assert pc.receive_json()["tipo_ws"] == "REGISTRO_OK"
            mobile.send_json({"tipo_ws": "REGISTRO", "id": "MOBILE", "capacidades": ["CONTROLE_MOBILE"]})
            client.portal.call(wait_mobile)
            for text, action, status, reply in [
                ("Ligue a lanterna no celular", "flashlight.set", "concluido", "Lanterna ligada."),
                ("Mande mensagem para Ana no WhatsApp dizendo Não ligue a lanterna", "message.prepare", "revisao", "Preparei para revisão. Confira o destinatário e toque para enviar."),
            ]:
                response = client.post("/eventos", headers={"Authorization": "Bearer teste-mobile"}, json={
                    "categoria": "SISTEMA_COMANDO_USUARIO", "pacote": "pc.chat", "correlacao_id": "fluxo-" + action,
                    "payload": {"texto": text}})
                assert response.status_code == 202
                command = mobile.receive_json()
                assert command["tipo_ws"] == "CELULAR_EXECUTAR" and command["acao"] == action
                ack = {"tipo_ws": "CELULAR_RESULTADO", "id_comando": command["id_comando"], "acao": action, "status": status, "texto": reply}
                pc.send_json({**ack, "texto": "Confirmação do aparelho errado"})
                mobile.send_json(ack)
                result = pc.receive_json()
                assert result["tipo_ws"] == "CHAT_RESPONSE" and result["texto"] == reply
                assert result["correlacao_id"] == "fluxo-" + action
