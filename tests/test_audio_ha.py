import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth import AuthMiddleware
from api.disponibilidade import DisponibilidadeMiddleware
from api.router_ha import router
from servicos.entrada_audio import EntradaAudioService


@pytest.fixture
def app_audio(monkeypatch):
    import api.router_ha as routes
    import api.websocket as websocket
    from api.pc_control import router as pc_router
    central = websocket.GerenciadorNotificacoes()
    monkeypatch.setattr(websocket, 'central_alertas', central)
    monkeypatch.setattr(routes, 'entrada_audio', EntradaAudioService())
    monkeypatch.setenv('OLLIE_API_TOKEN', 'audio-test')
    app = FastAPI()
    app.state.modo_limitado = True
    app.add_middleware(DisponibilidadeMiddleware)
    app.add_middleware(AuthMiddleware)
    app.include_router(router, prefix='/api/v1/ha')
    app.include_router(pc_router, prefix='/api/v1/pc')
    app.include_router(websocket.router, prefix='/api/v1')
    return app, central


def test_entrada_https_auth_validacao_e_offline(app_audio):
    app, central = app_audio
    with TestClient(app, base_url='https://ollie.test') as c:
        req = {'evento_id': 'id-1', 'action_name': 'media.next_track', 'gesture': 'double_click'}
        assert c.post('/api/v1/ha/audio', json=req).status_code == 401
        c.headers['Authorization'] = 'Bearer audio-test'
        assert c.post('/api/v1/ha/audio', json=req).status_code == 503
        assert c.post('/api/v1/ha/audio', json={**req, 'gesture': 'triple_click'}).status_code == 422
        assert c.post('/api/v1/ha/audio', json={**req, 'shell': 'x'}).status_code == 422
        assert c.post('/api/v1/ha/audio', json={'evento_id': 'p', 'action_name': 'audio.profile'}).status_code == 422
        assert c.get('/api/v1/ha/audio').status_code == 405


def test_api_websocket_pc_resultado_estruturado_e_deduplicacao(app_audio):
    app, central = app_audio
    with TestClient(app, base_url='https://ollie.test') as c:
        c.headers['Authorization'] = 'Bearer audio-test'
        with c.websocket_connect('/api/v1/ws/alertas?token=audio-test') as pc:
            pc.receive_json()
            pc.send_json({'tipo_ws': 'REGISTRO', 'id': 'PC_MASTER'})
            assert pc.receive_json()['tipo_ws'] == 'REGISTRO_OK'
            req = {'evento_id': 'botao-1', 'action_name': 'media.play_pause', 'gesture': 'single_click'}
            first = c.post('/api/v1/ha/audio', json=req)
            assert first.status_code == 202
            command = pc.receive_json()
            assert command['comando'] == 'audio_controle'
            payload = json.loads(command['parametro'])
            assert payload['operacao'] == 'alternar_modo'
            assert payload['id_comando'] == first.json()['id'] == command['id_comando']
            assert c.post('/api/v1/ha/audio', json=req).json()['id'] == first.json()['id']
            assert c.post('/api/v1/ha/audio', json={**req, 'action_name': 'media.next_track', 'gesture': 'double_click'}).status_code == 409
            result = {'audio': {'status': 'bloqueado', 'codigo': 'sincronizacao_exige_cinema', 'alterado': False,
                                'perfil_audio': 'HEADSET', 'modo_controle': 'SINCRONIZACAO'}}
            pc.send_json({'tipo_ws': 'COMANDO_RESULTADO', 'id_comando': command['id_comando'], 'status': 'concluido', 'resultado': result})
            async def wait():
                async with asyncio.timeout(2):
                    while central.confirmacoes.consultar(command['id_comando'])['status'] == 'enviado':
                        await asyncio.sleep(.001)
            c.portal.call(wait)
            status = c.get(first.json()['consulta'])
            assert status.json()['resultado'] == result


@pytest.mark.asyncio
async def test_feedback_reutiliza_ha_autenticado_com_variavel_sem_chamar_lampada(monkeypatch):
    import servicos.home_assistant_service as module
    service = module.HomeAssistantService()
    service.base_url, service.token = 'http://ha.test', 'ha-token-test'
    requests = []
    def responder(request):
        requests.append(request)
        return httpx.Response(200, json=[])
    original = httpx.AsyncClient
    monkeypatch.setattr(module.httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(responder), **kwargs))
    assert await service.feedback_audio('SINCRONIZACAO')
    assert len(requests) == 1
    assert str(requests[0].url) == 'http://ha.test/api/services/script/turn_on'
    assert requests[0].headers['authorization'] == 'Bearer ha-token-test'
    assert json.loads(requests[0].content) == {'entity_id': 'script.ollie_feedback_visual', 'variables': {'modo_controle': 'SINCRONIZACAO'}}


def test_ponte_python_nao_inicializa_spotify_nem_altera_comandos_antigos(monkeypatch):
    from scripts.pc_command import executar
    import servicos.controle_audio as m
    fake = Mock(return_value={'status': 'concluido', 'codigo': 'estado_consultado'})
    monkeypatch.setattr(m, 'executar_audio', fake)
    service = Mock()
    pedido = {'id_comando': 'test', 'operacao': 'consultar'}
    assert executar('audio_controle', json.dumps(pedido), service)['codigo'] == 'estado_consultado'
    service.inicializar.assert_not_called()
    executar('media_next', '', service)
    service.executar_macro.assert_called_once_with('media_next')


def test_conexao_audio_nao_lanca_mixer_ou_spotify(monkeypatch):
    import servicos.pc_control_service as m
    service = object.__new__(m.PcControlService); service.vm = None
    vm = Mock(); vm.type = 'banana'; vm.call.return_value = 0
    monkeypatch.setattr(m, 'voicemeeterlib', SimpleNamespace(api=Mock(return_value=vm)))
    assert service.obter_vm_audio() is vm
    assert service.obter_vm_audio() is vm
    vm.call.assert_called_once()
    vm.login.assert_not_called()
    vm.run_voicemeeter.assert_not_called()
    service.vm = None; vm.call.return_value = 1
    with pytest.raises(RuntimeError): service.obter_vm_audio()
    vm.run_voicemeeter.assert_not_called()


def test_resultado_audio_rejeita_dados_arbitrarios_e_nao_finitos():
    from servicos.resultado_audio import resultado_audio_valido
    base = {'status': 'concluido', 'codigo': 'ajuste_confirmado'}
    assert resultado_audio_valido({'audio': base})
    assert not resultado_audio_valido({'audio': {**base, 'comando': 'shell'}})
    assert not resultado_audio_valido({'audio': {**base, 'status': []}})
    assert not resultado_audio_valido({'audio': {**base, 'depois': {'Bus[1].Gain': float('nan')}}})
