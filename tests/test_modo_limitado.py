import asyncio
import sys
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from servicos.disponibilidade import quota_excedida


class QuotaBancoError(Exception):
    pass


@pytest.fixture
def aplicativo(monkeypatch):
    import main
    from core.kernel import KernelCognitivo
    import core.kernel as modulo_kernel
    kernel_anterior = modulo_kernel.kernel
    kernel = KernelCognitivo()
    def banco_proibido(*args, **kwargs):
        raise AssertionError('O modo limitado tentou abrir uma sessão de banco')
    for nome, modulo in tuple(sys.modules.items()):
        if nome == 'main' or nome.startswith(('core.', 'api.', 'servicos.', 'agentes.')):
            if hasattr(modulo, 'kernel'):
                monkeypatch.setattr(modulo, 'kernel', kernel)
            if hasattr(modulo, 'AsyncSessionLocal'):
                monkeypatch.setattr(modulo, 'AsyncSessionLocal', banco_proibido)
    from api import websocket
    import agentes.agente_notificacoes as notificacoes
    central = websocket.GerenciadorNotificacoes()
    monkeypatch.setattr(websocket, 'central_alertas', central)
    monkeypatch.setattr(notificacoes, 'central_alertas', central)
    iniciar = AsyncMock(side_effect=QuotaBancoError('Your account or project has exceeded the quota. Upgrade your plan to increase limits.'))
    monkeypatch.setattr(main, 'inicializar_banco', iniciar)
    monkeypatch.setenv('RENDER', 'true')
    monkeypatch.setenv('OLLIE_API_TOKEN', 'token-limitado')
    monkeypatch.delenv('OLLIE_MODO_LIMITADO', raising=False)
    return main.app, iniciar, kernel, central


def test_quota_identificada_na_causa_sem_confundir_erro_de_senha():
    error = RuntimeError('falha na conexão')
    error.__cause__ = QuotaBancoError('Your account or project has exceeded the quota.')
    assert quota_excedida(error)
    assert not quota_excedida(RuntimeError('password authentication failed'))
    assert not quota_excedida(RuntimeError('quota is 100'))


def test_servidor_sobe_sem_banco_home_honesta_e_recursos_protegidos(aplicativo):
    app, iniciar, kernel, _ = aplicativo
    with TestClient(app) as client:
        health = client.get('/health')
        assert health.status_code == 200
        assert health.json()['modo'] == 'limitado'
        assert health.json()['persistencia_disponivel'] is False
        assert health.json()['motivo'] == 'quota_banco_excedida'
        assert client.get('/api/v1/agenda').status_code == 401
        client.headers.update({'Authorization': 'Bearer token-limitado'})
        home = client.get('/api/v1/home')
        assert home.status_code == 200
        assert 'modo limitado' in home.json()['cards'][0]['conteudo']['texto']
        from api.dto import HomeDTO
        HomeDTO.model_validate(home.json())
        for path in ['/api/v1/agenda', '/api/v1/tarefas', '/api/v1/mensagens', '/api/v1/memory', '/api/v1/timeline', '/api/v1/ia', '/api/v1/calendario', '/api/v1/capabilities']:
            response = client.get(path)
            assert response.status_code == 503, path
            assert response.json()['codigo'] == 'persistencia_indisponivel'
        assert client.post('/api/v1/agenda', json={}).status_code == 503
        assert client.post('/api/v1/pc/intervention/policy', json={}).status_code == 503
        assert client.get('/api/v1/pc/intervention/policy').json()['auto_open_enabled'] is False
        assert client.get('/api/v1/status/').json()['status_geral'] == 'LIMITADO'
        assert client.post('/eventos', json={'categoria': 'NOTIFICACAO', 'pacote': 'com.whatsapp', 'payload': {'texto': 'mensagem'}}).status_code == 503
        assert kernel.estatisticas()['recebidos'] == 0  # Nenhum tick ou evento descartado é fingido como armazenado.
    iniciar.assert_awaited_once()


def test_falha_nao_relacionada_a_quota_continua_fechando_o_startup(aplicativo):
    app, iniciar, _, _ = aplicativo
    iniciar.side_effect = RuntimeError('schema inválido')
    with pytest.raises(RuntimeError, match='schema inválido'):
        with TestClient(app): pass


def test_modo_forcado_nao_tenta_conectar_e_nem_cria_banco_alternativo(aplicativo, monkeypatch):
    app, iniciar, _, _ = aplicativo
    monkeypatch.setenv('OLLIE_MODO_LIMITADO', 'true')
    with TestClient(app) as client:
        assert client.get('/health').json()['motivo'] == 'configurado'
    iniciar.assert_not_awaited()


def test_controles_conversa_e_feedback_funcionam_sem_sessao_sql(aplicativo, monkeypatch):
    from servicos.cognicao_controles import cognicao_controles
    monkeypatch.setattr(cognicao_controles, 'gerar', AsyncMock(return_value={'resposta': 'Pareidolia é perceber formas familiares em estímulos vagos.', 'acoes': []}))
    app, _, _, central = aplicativo
    async def aguardar_mobile():
        async with asyncio.timeout(2):
            while central.mobile_client is None:
                await asyncio.sleep(.001)
    with TestClient(app) as client:
        client.headers.update({'Authorization': 'Bearer token-limitado'})
        with client.websocket_connect('/api/v1/ws/alertas?token=token-limitado') as pc, client.websocket_connect('/api/v1/ws/alertas?token=token-limitado') as mobile:
            pc.receive_json(); mobile.receive_json()
            pc.send_json({'tipo_ws': 'REGISTRO', 'id': 'PC_MASTER', 'capacidades': ['CASA']})
            assert pc.receive_json()['tipo_ws'] == 'REGISTRO_OK'
            mobile.send_json({'tipo_ws': 'REGISTRO', 'id': 'MOBILE', 'capacidades': ['CONTROLE_MOBILE']})
            client.portal.call(aguardar_mobile)
            for text, kind in [('ligue a lanterna', 'mobile'), ('apague a luz', 'casa'), ('abra https://example.com no PC', 'pc')]:
                response = client.post('/eventos', json={'categoria': 'SISTEMA_COMANDO_USUARIO', 'pacote': 'teste.modo-limitado',
                    'correlacao_id': 'teste-' + kind, 'payload': {'texto': text}})
                assert response.status_code == 202
                command = (mobile if kind == 'mobile' else pc).receive_json()
                if kind == 'mobile':
                    assert command['tipo_ws'] == 'CELULAR_EXECUTAR'
                    assert command['parametros'] == {'estado': True}
                    mobile.send_json({'tipo_ws': 'CELULAR_RESULTADO', 'id_comando': command['id_comando'], 'acao': command['acao'], 'status': 'concluido', 'texto': 'Lanterna ligada.'})
                elif kind == 'casa':
                    assert command['comando'] == 'casa_acao'
                    pc.send_json({'tipo_ws': 'COMANDO_RESULTADO', 'id_comando': command['id_comando'], 'status': 'concluido', 'resultado': {'entity_id': 'light.yeelink_color5_027d_light', 'state': 'off'}})
                else:
                    assert command['comando'] == 'abrir_url' and command['parametro'] == 'https://example.com'
                    pc.send_json({'tipo_ws': 'COMANDO_RESULTADO', 'id_comando': command['id_comando'], 'status': 'concluido', 'resultado': {'primeiro_plano': True}})
                reply = mobile.receive_json()
                assert reply['tipo_ws'] == 'CHAT_RESPONSE'
                assert reply['correlacao_id'] == 'teste-' + kind
                assert 'indisponível' not in reply['texto']
            for text in ['me lembre de pagar a conta amanhã', 'o que é pareidolia?']:
                mobile.send_json({'tipo_ws': 'CHAT_MESSAGE', 'texto': text})
                reply = mobile.receive_json()
                assert reply['tipo_ws'] == 'CHAT_RESPONSE'
                if text.startswith('me lembre'):
                    assert 'modo limitado' in reply['texto'] and 'Não salvei' in reply['texto']
                else:
                    assert 'Pareidolia' in reply['texto']
            mobile.send_json({'tipo_ws': 'FEEDBACK', 'tipo_feedback': 'LIKE'})
            assert mobile.receive_json()['tipo_ws'] == 'RECURSO_INDISPONIVEL'


def test_intencao_livre_e_pergunta_de_horario_funcionam_sem_sql(aplicativo, monkeypatch):
    from servicos.cognicao_controles import cognicao_controles
    from servicos.dialogo_controles import dialogo_controles
    monkeypatch.setattr(dialogo_controles, 'pendentes', {})
    monkeypatch.setattr(dialogo_controles, 'semanticos', {})
    gerar = AsyncMock(side_effect=[
        {'resposta': 'Que horas você quer acordar?', 'pergunta': True, 'acoes': []},
        {'acoes': [{'acao': 'alarm.create', 'parametros': {'hora': 7, 'minuto': 30}}]},
        {'acoes': [{'acao': 'app.open', 'parametros': {'pacote': 'com.calculator'}}]},
    ])
    monkeypatch.setattr(cognicao_controles, 'gerar', gerar)
    app, _, _, _ = aplicativo
    with TestClient(app) as client, client.websocket_connect('/api/v1/ws/alertas?token=token-limitado') as mobile:
        mobile.receive_json()
        mobile.send_json({'tipo_ws': 'REGISTRO', 'id': 'MOBILE', 'capacidades': ['CONTROLE_MOBILE', 'APPS_MOBILE']})
        assert mobile.receive_json()['acao'] == 'ENVIAR_LISTA_APPS'
        mobile.send_json({'tipo_ws': 'LISTA_APPS', 'apps': [{'n': 'Calculadora', 'p': 'com.calculator'}]})
        mobile.send_json({'tipo_ws': 'CHAT_MESSAGE', 'texto': 'Acordar cedo é difícil, cuida de me despertar?'})
        resposta = mobile.receive_json()
        assert resposta['texto'] == 'Que horas você quer acordar?' and resposta['aguarda_resposta'] is True
        mobile.send_json({'tipo_ws': 'CHAT_MESSAGE', 'texto': 'às sete e meia'})
        comando = mobile.receive_json()
        assert comando['acao'] == 'alarm.create' and comando['parametros'] == {'hora': 7, 'minuto': 30}
        mobile.send_json({'tipo_ws': 'CELULAR_RESULTADO', 'id_comando': comando['id_comando'], 'acao': comando['acao'], 'status': 'encaminhado', 'texto': 'Encaminhei o despertador ao Relógio.'})
        assert mobile.receive_json()['texto'] == 'Encaminhei o despertador ao Relógio.'
        mobile.send_json({'tipo_ws': 'CHAT_MESSAGE', 'texto': 'Quero usar a calculadora agora'})
        comando = mobile.receive_json()
        assert comando['acao'] == 'app.open' and comando['parametros'] == {'pacote': 'com.calculator'}
        mobile.send_json({'tipo_ws': 'CELULAR_RESULTADO', 'id_comando': comando['id_comando'], 'acao': comando['acao'], 'status': 'concluido', 'texto': 'Abri a Calculadora.'})
        assert mobile.receive_json()['texto'] == 'Abri a Calculadora.'
    assert 'Complemento do usuário' in gerar.call_args_list[1].args[0]['pedido_usuario']


@pytest.mark.asyncio
async def test_tick_nao_faz_gravacao_episodica(monkeypatch):
    import servicos.memoria_episodica as modulo
    from core.evento import EventoCanonico
    from core.tipos import CategoriaEvento, OrigemEvento
    factory = AsyncMock(side_effect=AssertionError('Tick abriu banco'))
    monkeypatch.setattr(modulo, 'AsyncSessionLocal', factory)
    for tick in ('TICK_AGENDA', 'TICK_TAREFAS', 'TICK_MENSAGENS', 'TICK_ROTINA'):
        event = EventoCanonico(categoria=CategoriaEvento.SISTEMA_COMANDO_INTERNO,
            origem=OrigemEvento.SISTEMA, pacote='sistema.relogio', payload={'tipo': tick})
        await modulo.MemoriaEpisodica().arquivar_evento(event)
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_fila_vazia_so_faz_select_sem_update_ou_commit(banco_teste):
    from servicos.queue_worker import QueueWorker
    from sqlalchemy import event
    async with banco_teste() as session:
        engine = session.bind
    statements = []
    def executar(conn, cursor, statement, parameters, context, executemany): statements.append(statement)
    event.listen(engine.sync_engine, 'before_cursor_execute', executar)
    try:
        assert await QueueWorker(banco_teste)._processar_proxima_tarefa() is False
    finally:
        event.remove(engine.sync_engine, 'before_cursor_execute', executar)
    assert len(statements) == 1 and statements[0].lstrip().startswith('SELECT')
