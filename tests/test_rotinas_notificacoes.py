import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from core.evento import EventoCanonico
from core.tipos import CategoriaEvento, OrigemEvento, TipoAcao
from servicos.memoria_perfil import MemoriaPerfil, _get_time_slot
from servicos.routine_discovery_service import RoutineDiscoveryService
from servicos.routine_generator_service import RoutineGeneratorService
from servicos.routine_paths import salvar_json
from servicos.notificacoes import PoliticaNotificacoes
from agentes.agente_inferencia import AgenteInferencia
from agentes.agente_rotina import AgenteRotina


AGORA = datetime(2026, 10, 19, 18, tzinfo=timezone.utc)


def observacao(ts, alvo, pc=False, aninhado=False):
    payload = {"processo": alvo} if pc else {"pacote": alvo}
    if aninhado:
        payload = {"payload": payload}
    return SimpleNamespace(timestamp=ts, payload=payload,
                           tipo="PC_ACTIVITY" if pc else "APP_FOREGROUND",
                           origem="PC" if pc else "ANDROID")


def historico(sucessos=6, total=6, pc=False):
    eventos = []
    for dia in range(total):
        ts = AGORA - timedelta(days=dia + 1)
        eventos.append(observacao(ts, "com.trabalho"))
        if dia < sucessos:
            eventos.append(observacao(ts + timedelta(seconds=20), "code.exe" if pc else "com.agenda", pc, pc))
    return eventos


def evento(categoria=CategoriaEvento.APP_FOREGROUND, **kwargs):
    return EventoCanonico(categoria=categoria, origem=kwargs.pop("origem", OrigemEvento.ANDROID),
                          pacote=kwargs.pop("pacote", "com.trabalho"), **kwargs)


@pytest.mark.parametrize("pc", [False, True])
def test_associacao_exige_evidencia_e_conta_tentativas_sem_sucesso(pc):
    servico = RoutineDiscoveryService()
    skill = "automacao_cross" if pc else "automacao_fluxo"
    fortes = [s for s in servico.analisar(historico(pc=pc), agora=AGORA) if s["conteudo"]["skill_id"] == skill]
    assert len(fortes) == 1
    assert fortes[0]["conteudo"]["evidencia"]["dias_distintos"] == 6
    assert fortes[0]["conteudo"]["evidencia"]["confianca"] == 1
    fracas = servico.analisar(historico(5, 8, pc), agora=AGORA)
    assert not any(s["conteudo"]["skill_id"] == skill for s in fracas)


def test_burst_em_um_dia_e_eventos_ia_nao_formam_rotina():
    eventos = []
    for i in range(60):
        ts = AGORA - timedelta(hours=2) + timedelta(seconds=i * 20)
        eventos.extend([observacao(ts, "com.trabalho"), observacao(ts + timedelta(seconds=5), "com.agenda")])
    assert RoutineDiscoveryService().analisar(eventos, agora=AGORA) == []
    eventos = historico()
    for e in eventos:
        e.origem = "IA"
    assert RoutineDiscoveryService().analisar(eventos, agora=AGORA) == []


def test_temporal_deduplica_abas_e_usa_horario_local():
    eventos = []
    for dia in range(6):
        ts = AGORA.replace(hour=1) - timedelta(days=dia + 1)
        eventos.extend(observacao(ts + timedelta(seconds=i), "chrome.exe", True) for i in range(80))
    sugestoes = RoutineDiscoveryService().analisar(eventos, agora=AGORA)
    temporal = [s["conteudo"] for s in sugestoes if s["conteudo"]["skill_id"] == "automacao_temporal_pc"]
    assert len(temporal) == 1
    assert temporal[0]["periodo"] == "NOITE"
    assert temporal[0]["evidencia"]["amostras"] == 6
    assert _get_time_slot(AGORA.replace(hour=1)) == "NOITE"


async def test_descoberta_usa_historico_persistido_e_respeita_rejeicao(banco_teste, catalogo_teste):
    from banco.models import EventoEpisodicoDB
    agora = datetime.now(timezone.utc)
    async with banco_teste() as session:
        for i, e in enumerate(historico(pc=True)):
            session.add(EventoEpisodicoDB(id=str(i), timestamp=agora + (e.timestamp - AGORA),
                                        tipo=e.tipo, origem=e.origem, payload=e.payload))
        await session.commit()
    servico = RoutineDiscoveryService()
    servico.catalogo = catalogo_teste
    sugestoes = await servico.discover_suggestions()
    assert any(s["conteudo"]["skill_id"] == "automacao_cross" for s in sugestoes)
    materializadas = [await RoutineGeneratorService()._materialize_routine(s["conteudo"]) for s in sugestoes]
    await catalogo_teste.adicionar_sugestoes(materializadas)
    for rotina in await catalogo_teste.listar("descobertas"):
        await catalogo_teste.rejeitar(rotina["nome"])
    assert await servico.discover_suggestions() == []


async def test_inferencia_registra_uma_vez_e_nao_reconta_historico(monkeypatch):
    from agentes import agente_inferencia as modulo
    memoria = SimpleNamespace(registrar_uso_por_periodo=AsyncMock())
    monkeypatch.setattr(modulo, "memoria_perfil", memoria)
    agente = AgenteInferencia()
    ts = datetime.now(timezone.utc)
    await agente.processar(evento(timestamp=ts))
    await agente.processar(evento(timestamp=ts + timedelta(seconds=3)))
    await agente.processar(evento(CategoriaEvento.PC_ACTIVITY, origem=OrigemEvento.PC,
                                 timestamp=ts, payload={"processo": "chrome.exe", "titulo": "A"}))
    await agente.processar(evento(CategoriaEvento.PC_ACTIVITY, origem=OrigemEvento.PC,
                                 timestamp=ts + timedelta(seconds=3), payload={"processo": "chrome.exe", "titulo": "B"}))
    assert memoria.registrar_uso_por_periodo.await_count == 2
    assert memoria.registrar_uso_por_periodo.call_args.args[:2] == ("PC_ROUTINE", "chrome.exe")


async def test_feedback_negativo_no_perfil_vazio_nao_quebra_logaritmo(banco_teste):
    from banco.models import PerfilUsuarioDB
    await MemoriaPerfil().registrar_feedback_negativo("APP_USO", "com.teste")
    async with banco_teste() as session:
        perfil = (await session.execute(select(PerfilUsuarioDB))).scalar_one()
        assert perfil.score == perfil.confianca == 0


async def test_materializacao_preserva_caminho_com_dois_pontos_e_evidencia():
    servico = RoutineGeneratorService()
    rotina = await servico._materialize_routine({"nome": "Minha rotina", "skill_id": "automacao_cross",
        "trigger_package": "com.trabalho", "action_parameter": "abrir_app:C:\\Apps\\editor.exe",
        "justificativa": "Uso observado", "evidencia": {"dias_distintos": 6}})
    assert rotina["acoes"][0]["parametro"] == "C:\\Apps\\editor.exe"
    assert rotina["evidencia"]["dias_distintos"] == 6 and rotina["ativa"] is False


async def test_aprovacao_recarrega_executor_sem_reiniciar_e_sem_duplicar(catalogo_teste, monkeypatch):
    import api.router_capabilities as api
    import agentes.agente_rotina as modulo
    publicar = AsyncMock()
    monkeypatch.setattr(modulo.kernel, "publicar", publicar)
    rotina = {"nome": "Agenda", "ativa": False, "gatilho": {"tipo": "APP_OPENED", "pacote": "com.trabalho"},
              "acoes": [{"alvo": "IA", "comando": "NOTIFICAR", "parametro": "Abrir agenda?"}],
              "justificativa": "Uso observado", "evidencia": {"dias_distintos": 6}}
    await catalogo_teste.adicionar_sugestoes([rotina])
    agente = AgenteRotina()
    await agente.processar(evento())
    publicar.assert_not_awaited()
    await api.approve_routine(req=api.RoutineNameRequest(nome="Agenda"))
    await asyncio.gather(*(agente.processar(evento()) for _ in range(5)))
    publicar.assert_awaited_once()
    assert agente.routines[0]["justificativa"] == "Uso observado"
    await api.delete_routine(req=api.RoutineNameRequest(nome="Agenda"))
    await agente.processar(evento())
    assert agente.routines == []


def test_gatilho_exato_intervalo_noturno_e_relogio_explicito():
    agente = AgenteRotina()
    pc = evento(CategoriaEvento.PC_ACTIVITY, payload={"processo": "vscode.exe"})
    assert not agente._validar_gatilho({"tipo": "PC_ACTIVITY", "processo": "code.exe"}, pc)
    assert not agente._validar_gatilho({"tipo": "PC_ACTIVITY", "processo": ""}, pc)
    gatilho = {"tipo": "TIME_RANGE", "inicio": "22:00", "fim": "02:00"}
    tick = evento(CategoriaEvento.SISTEMA_COMANDO_INTERNO, timestamp=AGORA.replace(hour=1), payload={"tipo": "TICK_ROTINA"})
    assert agente._validar_gatilho(gatilho, tick)
    assert not agente._validar_gatilho(gatilho, evento(timestamp=tick.timestamp))
    assert not agente._validar_gatilho({"tipo": "TIME_RANGE", "inicio": "inválido"}, tick)


async def test_rotina_temporal_nao_depende_de_login_inexistente():
    sugestoes = RoutineDiscoveryService().analisar(historico(pc=True), agora=AGORA)
    servico = RoutineGeneratorService()
    for sugestao in sugestoes:
        rotina = await servico._materialize_routine(sugestao["conteudo"])
        assert rotina and not rotina["ativa"]
        if sugestao["conteudo"]["skill_id"] == "automacao_temporal_pc":
            assert rotina["gatilho"]["evento"] == "PC_ACTIVITY"
        if sugestao["conteudo"]["skill_id"] == "automacao_temporal_mobile":
            assert rotina["gatilho"]["evento"] == "TICK_ROTINA"
            assert rotina["acoes"][0]["acao_tipo"] == "OPEN_APP"


def test_notificacoes_normalizam_conteudo_e_preservam_acao():
    politica = PoliticaNotificacoes()
    e = evento(CategoriaEvento.INTENCAO_NOTIFICACAO, origem=OrigemEvento.IA,
               payload={"conteudo": {"title": "Agenda", "text": "Quer abrir?"},
                        "acao_tipo": "OPEN_APP", "acao_parametro": "com.agenda"})
    payload, _ = politica.preparar(e)
    assert payload["tipo_ws"] == "NOTIFICACAO"
    assert payload["titulo"] == "Agenda" and payload["texto"] == "Quer abrir?"
    assert payload["acao_parametro"] == "com.agenda"
    assert politica.preparar(e)[1] == "repetida_na_ultima_hora"
    assert "texto" not in e.payload


def test_orcamento_silencia_spam_sem_bloquear_chat_e_urgencia():
    relogio = [1000.0]
    politica = PoliticaNotificacoes(lambda: relogio[0])
    def notificacao(texto, **extras):
        return evento(CategoriaEvento.INTENCAO_NOTIFICACAO, payload={"texto": texto, **extras})
    assert politica.preparar(notificacao("A"))[0]
    assert politica.preparar(notificacao("B"))[1] == "orcamento_de_interrupcoes"
    for i in range(2):
        relogio[0] += 601
        assert politica.preparar(notificacao(f"C{i}"))[0]
    relogio[0] += 601
    assert politica.preparar(notificacao("D"))[0] is None
    assert politica.preparar(notificacao("Resposta", tipo_ws="CHAT_RESPONSE"))[0]
    assert politica.preparar(notificacao("Alerta crítico", urgencia="ALTA"))[0]
    assert politica.preparar(notificacao("Alerta crítico", urgencia="ALTA"))[0] is None
    assert politica.preparar(notificacao("   "))[1] == "conteudo_vazio"


async def test_notificacao_ia_chega_como_notificacao_no_transporte(monkeypatch):
    from agentes.agente_notificacoes import AgenteNotificacoes
    from api.websocket import central_alertas
    broadcast = AsyncMock()
    monkeypatch.setattr(central_alertas, "_broadcast", broadcast)
    monkeypatch.setattr(central_alertas, "mobile_client", None)
    from core.kernel import kernel
    publicar = AsyncMock()
    monkeypatch.setattr(kernel, "publicar", publicar)
    await AgenteNotificacoes().processar(evento(CategoriaEvento.INTENCAO_NOTIFICACAO,
        origem=OrigemEvento.IA, payload={"titulo": "Agenda", "texto": "Hora da reunião"}))
    assert broadcast.call_args.args[0]["tipo_ws"] == "NOTIFICACAO"
    assert publicar.call_args.args[0].categoria == CategoriaEvento.NOTIFICACAO_PRONTA_PARA_ENVIO


async def test_foco_nao_abre_app_por_associacao_antiga_nem_inventa_musica(monkeypatch):
    import agentes.agente_foco as modulo
    entidade = SimpleNamespace(atributos={"categoria": "mapas", "associacoes": {"pc_default": {"programa": "chrome.exe"}}})
    monkeypatch.setattr(modulo.catalogo, "obter_app", AsyncMock(return_value=entidade))
    monkeypatch.setattr(modulo.memoria_perfil, "obter_top_entidades", AsyncMock(return_value=[]))
    publicar = AsyncMock()
    monkeypatch.setattr(modulo.kernel, "publicar", publicar)
    await modulo.AgenteFoco().processar(evento())
    publicar.assert_not_awaited()


async def test_geracao_concorrente_nao_duplica_sugestoes(catalogo_teste, monkeypatch):
    import servicos.routine_generator_service as modulo
    servico = RoutineGeneratorService()
    servico.catalogo = catalogo_teste
    sugestoes = RoutineDiscoveryService().analisar(historico(pc=True), agora=AGORA)
    monkeypatch.setattr(modulo.routine_discovery_service, "discover_suggestions", AsyncMock(return_value=sugestoes))
    quantidades = await asyncio.gather(servico.run_batch_generation(), servico.run_batch_generation())
    assert quantidades == [len(sugestoes), 0]
    salvas = await catalogo_teste.listar("descobertas")
    assert len(salvas) == len(sugestoes)
    assert all(not r["ativa"] for r in salvas)


async def test_rejeitar_impede_regeneracao(catalogo_teste):
    import api.router_capabilities as api
    rotina = {"nome": "Minha sugestao", "gatilho": {"tipo": "APP_OPENED", "pacote": "com.a"},
              "acoes": [{"alvo": "IA", "comando": "NOTIFICAR", "parametro": "Agenda?"}]}
    await catalogo_teste.adicionar_sugestoes([rotina])
    await api.reject_routine(req=api.RoutineNameRequest(nome="Minha sugestao"))
    servico = RoutineGeneratorService()
    servico.catalogo = catalogo_teste
    assert "minha sugestao" in await servico._get_all_existing_names()
    assert await api.list_discovered() == []


async def test_rotina_pc_aprovada_emite_comando_uma_vez_e_ignora_replay(catalogo_teste, monkeypatch):
    import agentes.agente_rotina as modulo
    from api.websocket import central_alertas
    monkeypatch.setattr(central_alertas, "pc_master", object())
    publicar = AsyncMock()
    monkeypatch.setattr(modulo.kernel, "publicar", publicar)
    await catalogo_teste.adicionar({"nome": "Editor", "ativa": True, "uma_vez_por_dia": True,
        "gatilho": {"tipo": "TIME_RANGE", "inicio": "00:00", "fim": "23:59", "evento": "PC_ACTIVITY"},
        "acoes": [{"alvo": "PC", "comando": "abrir_app", "parametro": "code.exe"}]})
    agente = AgenteRotina()
    ts = datetime.now(timezone.utc)
    await agente.processar(evento(CategoriaEvento.PC_ACTIVITY, timestamp=ts - timedelta(hours=1), payload={"processo": "chrome.exe"}))
    publicar.assert_not_awaited()
    await agente.processar(evento(CategoriaEvento.PC_ACTIVITY, timestamp=ts, payload={"processo": "code.exe"}))
    publicar.assert_not_awaited()
    await asyncio.gather(*(agente.processar(evento(CategoriaEvento.PC_ACTIVITY, payload={"processo": "chrome.exe"})) for _ in range(5)))
    publicar.assert_awaited_once()
    comando = publicar.call_args.args[0]
    assert comando.payload == {"comando": "abrir_app", "parametro": "code.exe"}
    assert comando.metadados["rotina_aprovada"] == "Editor"
    assert comando.evento_pai and comando.origem == OrigemEvento.SISTEMA


async def test_timeline_exibe_encaminhamento_e_nao_telemetria_ou_intencao_suprimida(monkeypatch):
    import servicos.servico as modulo
    ts = datetime.now(timezone.utc)
    eventos = [{"id": str(i), "timestamp": ts, "origem": "IA", "tipo": tipo,
                "dados": {"texto": "Abrir agenda?", "tipo_ws": "NOTIFICACAO"}}
               for i, tipo in enumerate(["APP_FOREGROUND", "NOTIFICACAO", "INTENCAO_NOTIFICACAO", "NOTIFICACAO_PRONTA_PARA_ENVIO"])]
    monkeypatch.setattr(modulo.agregador_timeline, "obter_eventos_recentes", AsyncMock(return_value=eventos))
    timeline = await modulo.ServicoTimeline().gerar_timeline()
    assert len(timeline.eventos) == 1
    assert timeline.eventos[0].resumo == "Sugestão encaminhada: Abrir agenda?"


async def test_home_mantem_contrato_das_sugestoes(monkeypatch):
    import api.servico as modulo
    from api.status import LLMStatusDTO
    sugestoes = RoutineDiscoveryService().analisar(historico(pc=True), agora=AGORA)
    monkeypatch.setattr(modulo.routine_discovery_service, "discover_suggestions", AsyncMock(return_value=sugestoes))
    monkeypatch.setattr(modulo.servico_perfil, "gerar_perfil_cognitivo", AsyncMock(return_value=SimpleNamespace(cards_dinamicos=[], resumo_comportamental="N/A")))
    monkeypatch.setattr(modulo.servico_timeline, "gerar_timeline", AsyncMock(return_value=SimpleNamespace(eventos=[])))
    monkeypatch.setattr(modulo.servico_status, "gerar_status_sistema", AsyncMock(return_value=SimpleNamespace(llm=LLMStatusDTO(modelo_carregado="teste"))))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    home = await modulo.ServicoHome().gerar_home(request)
    cards = [c for c in home.cards if c.tipo == "sugestao_regra"]
    assert len(cards) == len(sugestoes)
    assert any(c.conteudo.sugestao_regra.action_parameter == "abrir_app:code.exe" for c in cards)


async def test_bem_estar_nao_soma_sessoes_separadas(monkeypatch):
    import agentes.agente_bem_estar as modulo
    monkeypatch.setattr(modulo.catalogo, "obter_app", AsyncMock(return_value=SimpleNamespace(atributos={"categoria": "social"})))
    publicar = AsyncMock()
    monkeypatch.setattr(modulo.kernel, "publicar", publicar)
    agente = modulo.AgenteBemEstar()
    ts = datetime.now(timezone.utc)
    for pacote, minutos in [("com.a", 0), ("com.b", 1), ("com.a", 32), ("com.a", 64)]:
        await agente.processar(evento(pacote=pacote, timestamp=ts + timedelta(minutes=minutos)))
    publicar.assert_not_awaited()


async def test_perfil_nao_confunde_notificacao_com_uso_e_deduplica_telemetria(monkeypatch):
    import agentes.agente_perfil as modulo
    memoria = SimpleNamespace(registrar_uso_app=AsyncMock(), registrar_interacao_contato=AsyncMock())
    monkeypatch.setattr(modulo, "memoria_perfil", memoria)
    monkeypatch.setattr(modulo.catalogo, "obter_app", AsyncMock(return_value=SimpleNamespace(atributos={"nome": "Trabalho"})))
    agente = modulo.AgentePerfil()
    await agente.processar(evento(CategoriaEvento.NOTIFICACAO, payload={"titulo": "Trabalho"}))
    memoria.registrar_uso_app.assert_not_awaited()
    memoria.registrar_interacao_contato.assert_not_awaited()
    ts = datetime.now(timezone.utc)
    await agente.processar(evento(timestamp=ts))
    await agente.processar(evento(timestamp=ts + timedelta(seconds=4)))
    memoria.registrar_uso_app.assert_awaited_once_with("com.trabalho")


async def test_heartbeat_nao_dispara_abertura_nem_infla_aprendizado(monkeypatch):
    import agentes.agente_perfil as perfil
    import agentes.agente_inferencia as inferencia
    uso = AsyncMock()
    monkeypatch.setattr(perfil.memoria_perfil, "registrar_uso_app", uso)
    temporal = AsyncMock()
    monkeypatch.setattr(inferencia.memoria_perfil, "registrar_uso_por_periodo", temporal)
    e = evento(payload={"heartbeat": True})
    await perfil.AgentePerfil().processar(e)
    await inferencia.AgenteInferencia().processar(e)
    uso.assert_not_awaited()
    temporal.assert_not_awaited()
    assert not AgenteRotina()._validar_gatilho({"tipo": "APP_OPENED", "pacote": "com.trabalho"}, e)


async def test_feedback_aprende_sobre_app_sugerido_e_nao_sobre_gatilho(banco_teste, monkeypatch):
    from banco.models import EventoEpisodicoDB
    from agentes.agente_aprendizagem import AgenteAprendizagem
    import agentes.agente_aprendizagem as modulo
    async with banco_teste() as session:
        session.add_all([
            EventoEpisodicoDB(id="sensor", correlacao_id="conversa", timestamp=AGORA,
                tipo="APP_FOREGROUND", origem="ANDROID", payload={"pacote": "com.trabalho"}),
            EventoEpisodicoDB(id="sugestao", correlacao_id="conversa", timestamp=AGORA + timedelta(seconds=1),
                tipo="INTENCAO_NOTIFICACAO", origem="IA", payload={"pacote": "sistema.rotina",
                    "acao_tipo": "OPEN_APP", "acao_parametro": "com.agenda"})])
        await session.commit()
    negativo = AsyncMock()
    monkeypatch.setattr(modulo.memoria_perfil, "registrar_feedback_negativo", negativo)
    agente = AgenteAprendizagem()
    feedback = evento(CategoriaEvento.SISTEMA_COMANDO_USUARIO, acao=TipoAcao.FEEDBACK_USUARIO,
        payload={"correlacao_id": "conversa", "tipo_feedback": "SUGGESTION_REJECTED", "notificacao_id": "sugestao"})
    await agente.processar(feedback)
    negativo.assert_awaited_once_with("APP_USO", "com.agenda")
    await agente.processar(feedback.clonar(payload={"correlacao_id": "conversa", "tipo_feedback": "DISMISS"}))
    assert negativo.await_count == 1


def test_websocket_feedback_nao_vira_pedido_de_raciocinio(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.websocket import router
    from api.auth import AuthMiddleware
    from core.kernel import kernel
    monkeypatch.setenv("OLLIE_API_TOKEN", "teste")
    publicar = AsyncMock()
    monkeypatch.setattr(kernel, "publicar", publicar)
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.include_router(router)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/alertas", headers={"Authorization": "Bearer teste"}) as ws:
            ws.receive_json()
            ws.send_json({"tipo_ws": "FEEDBACK", "correlacao_id": "conversa", "tipo_feedback": "SUGGESTION_REJECTED",
                          "notificacao_id": "sugestao"})
            ws.send_json({"tipo_ws": "REGISTRO", "id": "PC_MASTER"})
            assert ws.receive_json()["tipo_ws"] == "REGISTRO_OK"
    publicar.assert_awaited_once()
    publicado = publicar.call_args.args[0]
    assert publicado.acao == TipoAcao.FEEDBACK_USUARIO
    assert publicado.payload["notificacao_id"] == "sugestao"
