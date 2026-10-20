import json
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import AuthMiddleware
from core.tipos import CategoriaEvento, OrigemEvento
from servicos.botoes import ServicoBotoes, ToqueBotao
from servicos.cenarios import ServicoCenarios
from servicos.confirmacao_pc import ConfirmacoesPC


@pytest.fixture
def botoes(tmp_path):
    path = tmp_path / "botoes.json"
    path.write_text(json.dumps([
        {"dispositivo": "esp", "botao": "ollie", "acao": "wake"},
        {"dispositivo": "esp", "botao": "cenarios", "acao": "cenario", "cenario": "foco"}
    ]), encoding="utf-8")
    return ServicoBotoes(path)


def toque(botao="ollie", identificador="toque-1"):
    return ToqueBotao(dispositivo="esp", botao=botao, evento_id=identificador)


@pytest.mark.asyncio
async def test_toque_deduplica_retenta_e_aplica_cooldown(botoes):
    agora = [100]
    botoes.relogio = lambda: agora[0]
    kernel = SimpleNamespace(publicar=AsyncMock())
    primeiro = await botoes.receber(toque(), kernel)
    evento = kernel.publicar.call_args.args[0]
    assert evento.categoria == CategoriaEvento.BOTAO_ACIONADO
    assert evento.origem == OrigemEvento.USUARIO
    assert evento.payload["comando"] == "wake_ollie"
    assert (await botoes.receber(toque(), kernel)) == {"status": "duplicado", "id": primeiro["id"]}
    assert (await botoes.receber(toque(identificador="novo"), kernel))["status"] == "ignorado_cooldown"
    agora[0] += 2
    assert (await botoes.receber(toque(), kernel))["status"] == "duplicado"
    assert (await botoes.receber(toque(identificador="novo"), kernel))["status"] == "aceito"
    assert kernel.publicar.await_count == 2


@pytest.mark.asyncio
async def test_falha_na_fila_permite_reenvio_do_mesmo_toque(botoes):
    kernel = SimpleNamespace(publicar=AsyncMock(side_effect=RuntimeError("fila")))
    with pytest.raises(RuntimeError):
        await botoes.receber(toque(), kernel)
    kernel.publicar.side_effect = None
    assert (await botoes.receber(toque(), kernel))["status"] == "aceito"


def test_webhook_autenticado_valida_e_preview_nao_publica(botoes, monkeypatch):
    import api.router_ha as modulo
    publicar = AsyncMock()
    monkeypatch.setattr(modulo, "servico_botoes", botoes)
    monkeypatch.setattr(modulo.kernel, "publicar", publicar)
    monkeypatch.setenv("OLLIE_API_TOKEN", "teste")
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.include_router(modulo.router)
    with TestClient(app) as c:
        assert c.post("/webhook", json=toque().model_dump()).status_code == 401
        c.headers["Authorization"] = "Bearer teste"
        assert c.post("/buttons/preview", json=toque().model_dump()).json()["comando"] == "wake_ollie"
        publicar.assert_not_awaited()
        assert c.post("/webhook", json={**toque().model_dump(), "codigo": "print('nao')"}).status_code == 422
        assert c.post("/webhook", json=toque("inexistente").model_dump()).status_code == 404
        r = c.post("/webhook", json=toque().model_dump())
        assert r.status_code == 202 and r.json()["status"] == "aceito"
        assert c.post("/webhook", json=toque().model_dump()).json()["status"] == "duplicado"
    publicar.assert_awaited_once()


@pytest.mark.asyncio
async def test_agente_preserva_correlacao_e_id_da_confirmacao(botoes, monkeypatch):
    from agentes.agente_botoes import AgenteBotoes
    from core.kernel import kernel
    publicar = AsyncMock()
    monkeypatch.setattr(kernel, "publicar", publicar)
    await botoes.receber(toque("cenarios"), kernel)
    original = publicar.call_args.args[0]
    await AgenteBotoes().processar(original)
    derivado = publicar.call_args.args[0]
    assert derivado.evento_pai == original.id and derivado.correlacao_id == original.correlacao_id
    assert derivado.categoria == CategoriaEvento.SISTEMA_COMANDO_PC
    assert derivado.payload == {"comando": "executar_cenario", "parametro": "foco", "id_comando": original.id}


def configurar_cenario(tmp_path, passos, ativo=True):
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "scripts/cenarios").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config/cenarios.json").write_text(
        json.dumps({"teste": {"ativo": ativo, "passos": passos}}), encoding="utf-8")
    return ServicoCenarios(tmp_path)


def test_cenario_executa_python_cadastrado_e_passos_em_ordem(tmp_path):
    service = configurar_cenario(tmp_path, [
        {"comando": "snapshot"}, {"comando": "python", "script": "passo.py", "argumentos": ["ok"]},
        {"comando": "abrir_app", "parametro": "vscode"}])
    (tmp_path / "scripts/cenarios/passo.py").write_text(
        "from pathlib import Path\nimport sys\nPath('marcador').write_text(sys.argv[1])", encoding="utf-8")
    chamadas = []
    def executar(comando, parametro):
        if comando == "abrir_app":
            assert (tmp_path / "marcador").read_text() == "ok"
        chamadas.append(comando)
    assert service.executar("teste", executar)["passos_concluidos"] == 3
    assert chamadas == ["snapshot", "abrir_app"]


def test_cenario_valida_todos_os_caminhos_antes_de_qualquer_efeito(tmp_path):
    service = configurar_cenario(tmp_path, [{"comando": "abrir_app", "parametro": "vscode"},
                                          {"comando": "python", "script": "../../fora.py"}])
    (tmp_path / "fora.py").write_text("raise RuntimeError('nao executar')")
    executar = Mock()
    with pytest.raises(ValueError, match="scripts/cenarios"):
        service.executar("teste", executar)
    executar.assert_not_called()


@pytest.mark.parametrize("nome", ["../teste", "print('codigo')", "desconhecido"])
def test_cenario_recusa_nome_arbitrario(tmp_path, nome):
    service = configurar_cenario(tmp_path, [{"comando": "snapshot"}])
    with pytest.raises(ValueError):
        service.executar(nome, Mock())


def test_cenario_desativado_e_timeout_interrompem_sequencia(tmp_path, monkeypatch):
    service = configurar_cenario(tmp_path, [{"comando": "snapshot"}], ativo=False)
    with pytest.raises(ValueError, match="desativado"):
        service.executar("teste", Mock())
    configurar_cenario(tmp_path, [{"comando": "python", "script": "lento.py", "timeout_segundos": 1},
                                 {"comando": "snapshot"}])
    (tmp_path / "scripts/cenarios/lento.py").write_text("pass")
    executar = Mock()
    def demorado(*args, **kwargs):
        assert kwargs["shell"] is False and kwargs["timeout"] == 1
        raise subprocess.TimeoutExpired(args[0], 1)
    monkeypatch.setattr(subprocess, "run", demorado)
    with pytest.raises(RuntimeError, match="passo 1"):
        service.executar("teste", executar)
    executar.assert_not_called()


def test_confirmacao_expira_sem_inventar_sucesso_e_historico_limitado():
    agora = [0]
    confirmacoes = ConfirmacoesPC(lambda: agora[0])
    assert confirmacoes.registrar("a", "snapshot")
    assert not confirmacoes.registrar("a", "outro")
    agora[0] = 361
    assert confirmacoes.consultar("a")["status"] == "sem_confirmacao"
    confirmacoes.atualizar("a", "concluido")
    assert confirmacoes.consultar("a")["status"] == "concluido"
    for i in range(205):
        confirmacoes.registrar(str(i), "snapshot")
    assert confirmacoes.consultar("a") is None and len(confirmacoes._comandos) == 200


@pytest.mark.asyncio
async def test_chat_pc_volta_ao_pc_com_mobile_conectado():
    from api.websocket import GerenciadorNotificacoes
    central = GerenciadorNotificacoes()
    pc = SimpleNamespace(client_state=SimpleNamespace(value=1), send_text=AsyncMock())
    mobile = SimpleNamespace(client_state=SimpleNamespace(value=1), send_text=AsyncMock())
    central.pc_master, central.mobile_client = pc, mobile
    await central.enviar_alerta({"pacote": "pc.chat", "payload": {"tipo_ws": "CHAT_RESPONSE", "texto": "ok"}})
    pc.send_text.assert_awaited_once()
    mobile.send_text.assert_not_awaited()


def test_confirmacao_somente_do_pc_e_comando_nao_reexecutado(monkeypatch):
    import api.websocket as modulo
    central = modulo.GerenciadorNotificacoes()
    monkeypatch.setattr(modulo, "central_alertas", central)
    app = FastAPI()
    app.include_router(modulo.router)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/alertas") as pc, client.websocket_connect("/ws/alertas") as observador:
            pc.receive_json()
            observador.receive_json()
            pc.send_json({"tipo_ws": "REGISTRO", "id": "PC_MASTER"})
            assert pc.receive_json()["tipo_ws"] == "REGISTRO_OK"
            observador.send_json({"tipo_ws": "COMANDO_PC", "comando": "snapshot", "id_comando": "um"})
            assert pc.receive_json()["id_comando"] == "um"
            assert observador.receive_json()["status"] == "enviado"
            observador.send_json({"tipo_ws": "COMANDO_RESULTADO", "id_comando": "um", "status": "concluido"})
            observador.send_json({"tipo_ws": "COMANDO_PC", "comando": "snapshot", "id_comando": "um"})
            assert observador.receive_json()["status"] == "enviado"
            pc.send_json({"tipo_ws": "COMANDO_RESULTADO", "id_comando": "um", "status": "concluido"})
            pc.send_json({"tipo_ws": "STATUS_PC", "stats": {"cpu": 1, "ram": 2}})
            assert pc.receive_json()["tipo_ws"] == "STATUS_PC"  # Não houve segundo comando.
            assert central.confirmacoes.consultar("um")["status"] == "concluido"


def test_luz_cloud_usa_ponte_e_informa_pc_offline(monkeypatch):
    import api.router_ha as ha
    from api.websocket import central_alertas
    monkeypatch.setenv("RENDER", "true")
    conectado = Mock(return_value={"pc": {"conectado": True}})
    monkeypatch.setattr(central_alertas, "estado_conexoes", conectado)
    publicar = AsyncMock()
    monkeypatch.setattr(ha.kernel, "publicar", publicar)
    local = AsyncMock()
    monkeypatch.setattr(ha.home_assistant_service, "ligar_luz", local)
    app = FastAPI()
    app.include_router(ha.router)
    with TestClient(app) as c:
        r = c.post("/light/on")
        assert r.status_code == 202 and r.json()["id"]
        publicado = publicar.call_args.args[0]
        assert publicado.id == r.json()["id"]
        assert publicado.payload == {"comando": "ligar_luz", "parametro": "light.yeelink_color5_027d_light"}
        local.assert_not_awaited()
        conectado.return_value = {"pc": {"conectado": False}}
        assert c.post("/light/on").status_code == 503
        assert c.post("/light/on?entity_id=switch.pc").status_code == 422


@pytest.mark.asyncio
async def test_ha_sem_configuracao_nao_envia_requisicoes(monkeypatch):
    from servicos.home_assistant_service import HomeAssistantService
    monkeypatch.delenv("HA_TOKEN", raising=False)
    monkeypatch.delenv("HA_URL", raising=False)
    service = HomeAssistantService()
    assert (await service.verificar_conexao())["motivo"] == "configuracao_ausente"
    assert not await service.ligar_luz()


@pytest.mark.parametrize("texto", ["não desliga a luz", "luz", "liga a luz e abre o vscode"])
def test_heuristica_nao_transforma_mencao_a_luz_em_acionamento(texto):
    from agentes.agente_raciocinio import AgenteRaciocinio
    agente = object.__new__(AgenteRaciocinio)
    assert agente._tentar_heuristica_local(texto) is None


@pytest.mark.parametrize("texto,comando", [("desliga a luz", "desligar_luz"),
    ("ligue a luz do quarto", "ligar_luz"), ("Ollie, por favor acenda a lâmpada", "ligar_luz"),
    ("alterna a luz do meu quarto", "toggle_luz")])
def test_heuristica_luz_usa_controlador_da_casa(texto, comando):
    from agentes.agente_raciocinio import AgenteRaciocinio
    agente = object.__new__(AgenteRaciocinio)
    acao = agente._tentar_heuristica_local(texto)["execucao_direta"][0]
    assert acao["alvo"] == "CASA" and acao["comando"] == comando
    from servicos.controle_casa import controle_casa
    assert controle_casa.resolver(acao["parametro"])["id"] == "luz_quarto"


def test_ponte_nao_confirma_app_ou_volume_que_falharam():
    from scripts.pc_command import executar
    service = Mock()
    service.abrir_app.return_value = False
    service.set_system_volume.return_value = False
    with pytest.raises(RuntimeError, match="Aplicativo"):
        executar("abrir_app", "teste", service)
    with pytest.raises(RuntimeError, match="volume"):
        executar("volume_sistema", "50", service)


def test_hardware_ausente_nao_simula_sucesso(monkeypatch):
    import servicos.pc_control_service as modulo
    service = object.__new__(modulo.PcControlService)
    service.macros = {"media_next": ["nexttrack"]}
    service.vm = None
    monkeypatch.setattr(service, "_garantir_vm", lambda: None)
    monkeypatch.setattr(modulo, "pyautogui", None)
    with pytest.raises(RuntimeError):
        service.executar_macro("media_next")
    with pytest.raises(ValueError):
        service.executar_macro("nao_cadastrada")
    with pytest.raises(RuntimeError):
        service.mutar_mic()


def test_caminho_explicito_de_app_nao_passa_pela_busca_aproximada(tmp_path):
    from servicos.pc_control_service import PcControlService
    caminho = tmp_path / "programa.exe"
    caminho.touch()
    service = object.__new__(PcControlService)
    service.executar_comando_direto = Mock()
    service.match_inteligente = Mock(side_effect=AssertionError("não aproximar caminho explícito"))
    assert service.abrir_app(str(caminho))
    service.executar_comando_direto.assert_called_once_with(str(caminho))


@pytest.mark.asyncio
async def test_executor_cloud_preserva_canal_zero_macro_e_id_do_botao(monkeypatch):
    from agentes.agente_pc_executor import AgentePcExecutor
    from api.websocket import central_alertas
    from core.evento import EventoCanonico
    monkeypatch.setenv("RENDER", "true")
    enviar = AsyncMock()
    monkeypatch.setattr(central_alertas, "enviar_comando_pc", enviar)
    evento = EventoCanonico(categoria=CategoriaEvento.SISTEMA_COMANDO_PC,
                           origem=OrigemEvento.USUARIO, pacote="teste",
                           payload={"comando": "volume_canal", "canal": 4, "valor": 0,
                                    "macro": "exemplo", "id_comando": "id-do-toque"})
    await AgentePcExecutor().processar(evento)
    msg = enviar.call_args.args[0]
    assert msg["canal"] == 4 and msg["valor"] == 0 and msg["macro"] == "exemplo"
    assert msg["id_comando"] == "id-do-toque" and msg["correlacao_id"] == evento.correlacao_id
