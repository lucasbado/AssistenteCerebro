from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from servicos.intervention_governor import InterventionGovernor, InterventionPolicy
from servicos.abertura_apps import pedido_explicito_de_abertura
from core.evento import EventoCanonico
from core.tipos import CategoriaEvento, OrigemEvento, TipoAcao


@pytest.mark.parametrize("text,expected", [("abre o Spotify", True), ("Ollie, pode abrir o WhatsApp?", True),
    ("quero abrir o Instagram", True), ("não abra o Instagram", False),
    ("como abrir o banco?", False), ("quando eu abrir o banco", False), ("chegou mensagem", False)])
def test_pedido_explicito(text, expected):
    assert pedido_explicito_de_abertura(text) is expected


def test_importancia_whitelist_e_bloqueio_sao_reais():
    policy = InterventionPolicy(auto_open_enabled=True).model_dump()
    assert InterventionGovernor.motivo(policy, "com.whatsapp", .95) is None
    for score in [None, 0, .7, float("nan"), float("inf"), 8]:
        assert InterventionGovernor.motivo(policy, "com.whatsapp", score)
    assert InterventionGovernor.motivo(policy, "evil.whatsapp.fake", .99) == "aplicativo_nao_permitido"
    assert InterventionGovernor.motivo(policy, "instagram", .99) == "aplicativo_nao_permitido"
    policy["min_priority_score"] = 0
    assert InterventionGovernor.motivo(policy, "whatsapp", 0) == "importancia_insuficiente"
    assert InterventionGovernor.motivo(policy, "com.google.android.youtube", 1) == "aplicativo_bloqueado"
    policy["blacklist"] = ["com.whatsapp"]
    assert InterventionGovernor.motivo(policy, "whatsapp", .99) == "aplicativo_bloqueado"
    policy["auto_open_enabled"] = False
    assert InterventionGovernor.motivo(policy, "vscode", 1) == "abertura_automatica_desativada"


async def test_politica_e_limites_persistem_apos_reiniciar(banco_teste):
    now = [datetime.now(timezone.utc)]
    first = InterventionGovernor(lambda: now[0])
    await first.atualizar_politica({"auto_open_enabled": True, "whitelist": ["whatsapp", "telegram"]})
    assert (await first.avaliar_abertura("com.whatsapp", "MOBILE", .95))["permitida"]
    second = InterventionGovernor(lambda: now[0])
    assert (await second.obter_politica())["auto_open_enabled"]
    assert not (await second.avaliar_abertura("com.whatsapp", "MOBILE", .95))["permitida"]
    assert not (await second.avaliar_abertura("telegram", "MOBILE", .95))["permitida"]
    now[0] += timedelta(minutes=11)
    assert (await second.avaliar_abertura("telegram", "MOBILE", .95))["permitida"]
    assert (await second.avaliar_abertura("qualquer", "MOBILE", explicito=True))["permitida"]


async def test_rotina_ativa_nao_contorna_global_desligado(catalogo_teste, monkeypatch):
    from agentes.agente_rotina import AgenteRotina
    from api.websocket import central_alertas
    from core.kernel import kernel
    monkeypatch.setattr(central_alertas, "mobile_client", object())
    send = AsyncMock()
    monkeypatch.setattr(central_alertas, "_enviar_direto", send)
    publish = AsyncMock()
    monkeypatch.setattr(kernel, "publicar", publish)
    await catalogo_teste.adicionar({"nome": "Banco para rede social", "ativa": True, "importancia_abertura": .99,
        "gatilho": {"tipo": "APP_OPENED", "pacote": "com.banco"},
        "acoes": [{"alvo": "MOBILE", "comando": "OPEN_APP", "parametro": "com.instagram.android"}]})
    await AgenteRotina().processar(EventoCanonico(categoria=CategoriaEvento.APP_FOREGROUND,
        origem=OrigemEvento.ANDROID, pacote="com.banco", payload={}))
    send.assert_not_awaited()
    suggestion = publish.call_args.args[0]
    assert suggestion.payload["tipo_ws"] == "NOTIFICACAO"
    assert suggestion.payload["acao_parametro"] == "com.instagram.android"


async def test_llm_nao_abre_app_por_mensagem_externa_mas_pedido_de_voz_abre(monkeypatch):
    import agentes.agente_raciocinio as modulo
    from api.websocket import central_alertas
    agent = modulo.AgenteRaciocinio()
    agent._harvest_current_habits = AsyncMock(return_value=[])
    agent._registrar_log_cognitivo = lambda *args: None
    agent._tentar_heuristica_local = lambda _: None
    agent.memoria_trabalho = SimpleNamespace(atualizar_conversa=AsyncMock(), obter_contexto=AsyncMock(return_value=[]))
    agent.llm = SimpleNamespace(classificar_evento=AsyncMock(return_value={"tipo_interacao": "NOTIFICAR",
        "execucao_direta": {"alvo": "MOBILE", "comando": "abrir_app_mobile", "parametro": "com.spotify.music"}}))
    publish, broadcast, mobile = AsyncMock(), AsyncMock(), AsyncMock(return_value=True)
    monkeypatch.setattr(modulo.kernel, "publicar", publish)
    monkeypatch.setattr(central_alertas, "_broadcast", broadcast)
    monkeypatch.setattr(central_alertas, "enviar_comando_mobile", mobile)
    external = EventoCanonico(categoria=CategoriaEvento.NOTIFICACAO, acao=TipoAcao.INTENCAO_RACIOCINIO,
        origem=OrigemEvento.ANDROID, pacote="com.whatsapp", payload={"texto": "nova mensagem"})
    await agent.processar(external)
    broadcast.assert_not_awaited()
    mobile.assert_not_awaited()
    assert publish.call_args.args[0].payload["acao_tipo"] == "OPEN_APP"
    user = EventoCanonico(categoria=CategoriaEvento.SISTEMA_COMANDO_USUARIO, acao=TipoAcao.INTENCAO_RACIOCINIO,
        origem=OrigemEvento.USUARIO, pacote="com.example.assistentecell.voice", payload={"texto": "abre o Spotify"})
    await agent.processar(user)
    command = mobile.call_args.args[0]
    assert command["abertura_modo"] == "pedido"
    assert command["correlacao_id"] == user.correlacao_id


@pytest.mark.parametrize("kind", ["NOTIFICAR", "SUGERIR", "IGNORAR"])
async def test_link_whatsapp_sugere_video_exato_sem_abrir_tiktok_nem_repetir(kind, monkeypatch):
    import agentes.agente_raciocinio as modulo
    from api.websocket import central_alertas
    from servicos.notificacoes import PoliticaNotificacoes
    url = "https://vm.tiktok.com/ZMExactVideo/?share_id=123ABC#trecho"
    agent = modulo.AgenteRaciocinio()
    agent._harvest_current_habits = AsyncMock(return_value=[])
    agent._registrar_log_cognitivo = lambda *args: None
    agent._tentar_heuristica_local = lambda _: None
    agent.memoria_trabalho = SimpleNamespace(atualizar_conversa=AsyncMock(), obter_contexto=AsyncMock(return_value=[]))
    agent.llm = SimpleNamespace(classificar_evento=AsyncMock(return_value={"tipo_interacao": kind,
        "mensagem_dinamica": "Abrindo o TikTok para ver o video!",
        "execucao_direta": {"alvo": "MOBILE", "comando": "abrir_app_mobile", "parametro": "com.zhiliaoapp.musically"}}))
    publish, broadcast = AsyncMock(), AsyncMock()
    monkeypatch.setattr(modulo.kernel, "publicar", publish)
    monkeypatch.setattr(central_alertas, "_broadcast", broadcast)
    incoming = EventoCanonico(categoria=CategoriaEvento.NOTIFICACAO, acao=TipoAcao.INTENCAO_RACIOCINIO,
        origem=OrigemEvento.ANDROID, pacote="com.whatsapp", payload={
            "mensagens": [f"Contato: olha isso {url} (MSG)"],
            "contexto_historico": ["Contato: https://vm.tiktok.com/ZMAntigo/"]})
    policy = PoliticaNotificacoes()
    await agent.processar(incoming)
    broadcast.assert_not_awaited()
    if kind == "IGNORAR":
        publish.assert_not_awaited()
        return
    publish.assert_awaited_once()  # No misleading 'opening TikTok' message.
    suggestion = publish.call_args.args[0]
    assert suggestion.payload["acao_tipo"] == "OPEN_URL"
    assert suggestion.payload["acao_parametro"] == url
    assert suggestion.payload["acao_texto"] == "Abrir link"
    assert policy.preparar(suggestion)[0] is not None
    await agent.processar(incoming.clonar(payload=dict(incoming.payload)))
    broadcast.assert_not_awaited()
    assert policy.preparar(publish.call_args.args[0])[1] == "repetida_na_ultima_hora"


@pytest.mark.parametrize("payload,command,target,expected", [
    ({"texto": "olha (https://vm.tiktok.com/ZMA1/?x=42#video)."}, "OPEN_APP", "tiktok", "https://vm.tiktok.com/ZMA1/?x=42#video"),
    ({"texto": "https://tiktok.com.evil.test/video/1"}, "OPEN_APP", "tiktok", None),
    ({"contexto_historico": ["https://vm.tiktok.com/ZMOld/"]}, "OPEN_APP", "tiktok", None),
    ({"texto": "https://vm.tiktok.com/ZMA/ https://vm.tiktok.com/ZMB/"}, "OPEN_APP", "tiktok", None),
    ({"texto": "https://vm.tiktok.com/ZMActual/"}, "OPEN_URL", "https://vm.tiktok.com/ZMFake/", None),
    ({"texto": "https://vm.tiktok.com/ZMActual/"}, "OPEN_URL", "https://vm.tiktok.com/ZMActual/", "https://vm.tiktok.com/ZMActual/"),
])
def test_destino_de_link_vem_da_mensagem_atual(payload, command, target, expected):
    from servicos.links_notificacao import destino_de_link
    assert destino_de_link(payload, command, target) == (True, expected)


async def test_sem_link_verificavel_oferece_origem_em_vez_da_home_tiktok(monkeypatch):
    from servicos.abertura_apps import sugerir_abertura
    from core.kernel import kernel
    publish = AsyncMock()
    monkeypatch.setattr(kernel, "publicar", publish)
    incoming = EventoCanonico(categoria=CategoriaEvento.NOTIFICACAO,
        origem=OrigemEvento.ANDROID, pacote="com.whatsapp", payload={"texto": "te mandei um video"})
    await sugerir_abertura(incoming, "MOBILE", "OPEN_APP", "com.zhiliaoapp.musically", "inferencia_sem_pedido")
    action = publish.call_args.args[0].payload
    assert action["acao_tipo"] == "OPEN_APP"
    assert action["acao_parametro"] == "com.whatsapp"
    assert action["acao_texto"] == "Ver mensagem"


async def test_rotina_so_abre_com_importancia_permissao_e_sem_repeticao(catalogo_teste, monkeypatch):
    from agentes.agente_rotina import AgenteRotina
    from api.websocket import central_alertas
    from servicos.intervention_governor import intervention_governor
    from core.kernel import kernel
    monkeypatch.setattr(central_alertas, "mobile_client", object())
    send, publish = AsyncMock(), AsyncMock()
    monkeypatch.setattr(central_alertas, "_enviar_direto", send)
    monkeypatch.setattr(kernel, "publicar", publish)
    await intervention_governor.atualizar_politica({"auto_open_enabled": True, "whitelist": ["instagram"]})
    await catalogo_teste.adicionar({"nome": "Rede social", "ativa": True, "importancia_abertura": .95,
        "gatilho": {"tipo": "APP_OPENED", "pacote": "com.banco"},
        "acoes": [{"alvo": "MOBILE", "comando": "OPEN_APP", "parametro": "com.instagram.android"}]})
    agent = AgenteRotina()
    event = EventoCanonico(categoria=CategoriaEvento.APP_FOREGROUND,
        origem=OrigemEvento.ANDROID, pacote="com.banco", payload={})
    await agent.processar(event)
    await agent.processar(event)
    send.assert_awaited_once()
    assert send.call_args.args[1]["abertura_modo"] == "automatica"
    assert send.call_args.args[1]["importance_score"] == .95
    assert send.call_args.args[1]["id_comando"] == event.id
    publish.assert_not_awaited()


async def test_multiplas_aberturas_sao_sugeridas_sem_gastar_cota(catalogo_teste, monkeypatch):
    from agentes.agente_rotina import AgenteRotina
    from api.websocket import central_alertas
    from servicos.intervention_governor import intervention_governor
    from core.kernel import kernel
    monkeypatch.setattr(central_alertas, "mobile_client", object())
    send = AsyncMock()
    monkeypatch.setattr(central_alertas, "_enviar_direto", send)
    monkeypatch.setattr(kernel, "publicar", AsyncMock())
    await intervention_governor.atualizar_politica({"auto_open_enabled": True})
    agent = AgenteRotina()
    event = EventoCanonico(categoria=CategoriaEvento.APP_FOREGROUND,
        origem=OrigemEvento.ANDROID, pacote="com.banco", payload={})
    await agent._executar_acoes([{"alvo": "MOBILE", "comando": "OPEN_APP", "parametro": target}
        for target in ["com.whatsapp", "org.telegram.messenger"]], event)
    send.assert_not_awaited()
    assert (await intervention_governor.avaliar_abertura("com.whatsapp", "MOBILE", .95))["permitida"]


async def test_aprovacao_nao_confunde_confianca_aprendida_com_permissao(catalogo_teste):
    suggestion = {"nome": "Sugestao importante segundo LLM", "importancia_abertura": 1,
        "evidencia": {"confianca": 1}, "gatilho": {"tipo": "APP_OPENED", "pacote": "com.banco"},
        "acoes": [{"alvo": "MOBILE", "comando": "OPEN_APP", "parametro": "com.instagram.android"}]}
    await catalogo_teste.adicionar_sugestoes([suggestion])
    await catalogo_teste.aprovar(suggestion["nome"])
    approved = (await catalogo_teste.listar("ativas"))[0]
    assert approved["evidencia"]["confianca"] == 1
    assert approved["importancia_abertura"] == 0


async def test_api_persistencia_validacao_e_importancia_sem_ativar(catalogo_teste):
    import httpx
    from fastapi import FastAPI
    from api.pc_control import router as policy_router
    from api.router_capabilities import router as routines_router
    app = FastAPI()
    app.include_router(policy_router, prefix="/pc")
    app.include_router(routines_router, prefix="/routines")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as c:
        assert (await c.get("/pc/intervention/policy")).json()["controle_abertura_version"] == 1
        for invalid in [{"auto_open_enabled": "false"}, {"min_priority_score": 8}, {"unknown": True}]:
            assert (await c.post("/pc/intervention/policy", json=invalid)).status_code == 422
        policy = (await c.post("/pc/intervention/policy", json={"whitelist": ["instagram"]})).json()["policy"]
        assert not policy["auto_open_enabled"]
        assert (await c.get("/pc/intervention/policy")).json()["whitelist"] == ["instagram"]
        await catalogo_teste.adicionar({"nome": "Pausada", "ativa": False,
            "gatilho": {"tipo": "APP_OPENED", "pacote": "com.banco"},
            "acoes": [{"alvo": "MOBILE", "comando": "OPEN_APP", "parametro": "com.instagram.android"}]})
        response = await c.patch("/routines/routines", json={"nome": "Pausada", "ativa": False, "importancia_abertura": .95})
        assert response.status_code == 200
        saved = (await c.get("/routines/routines")).json()[0]
        assert not saved["ativa"] and saved["importancia_abertura"] == .95
        assert saved["controle_abertura_version"] == 1
