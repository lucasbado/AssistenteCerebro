from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from core.evento import EventoCanonico
from core.tipos import CategoriaEvento, OrigemEvento
from core.kernel import kernel
from servicos.agenda import Agenda, agenda
from servicos.datas_agenda import extrair_data, titulo_sem_data, intencao_agenda, data_importante
from agentes.agente_agenda import AgenteAgenda
from agentes.agente_reflexo import AgenteReflexo
from api.agenda import router

REF = datetime(2030, 10, 22, 13, tzinfo=timezone.utc)


@pytest.mark.parametrize('texto,esperado,inteiro', [
    ('amanhã às 15h30', '2030-10-23T18:30:00+00:00', False),
    ('depois de amanhã às 7 da manhã', '2030-10-24T10:00:00+00:00', False),
    ('23/10/2030 às 3 da tarde', '2030-10-23T18:00:00+00:00', False),
    ('dia 5 de novembro às 19:20', '2030-11-05T22:20:00+00:00', False),
    ('em 20 minutos', '2030-10-22T13:20:00+00:00', False),
    ('amanhã', '2030-10-23T03:00:00+00:00', True),
    ('às 7h', '2030-10-23T10:00:00+00:00', False),
    ('amanhã às 7 e meia da noite', '2030-10-23T22:30:00+00:00', False),
    ('amanhã às 7 e 15', '2030-10-23T10:15:00+00:00', False),
])
def test_datas_ptbr(texto, esperado, inteiro, monkeypatch):
    monkeypatch.setenv('OLLIE_TIMEZONE', 'America/Sao_Paulo')
    data = extrair_data(texto, REF, True)
    assert data['inicio'].isoformat() == esperado
    assert data['dia_inteiro'] is inteiro


@pytest.mark.parametrize('texto', ['31/02/2030', 'amanhã às 25h', 'hoje ou amanhã às 15h', 'amanhã às 15h ou 16h'])
def test_datas_invalidas_ou_ambiguas_nao_chutam(texto):
    with pytest.raises(ValueError): extrair_data(texto, REF)


def test_titulo_e_intencao():
    assert titulo_sem_data('me lembra de tomar remédio amanhã às 15h') == 'tomar remédio'
    assert titulo_sem_data('me lembra de beber água em 20 minutos') == 'beber água'
    assert intencao_agenda('me acorde amanhã às 7h') == 'alarme'
    assert intencao_agenda('cria um alarme amanhã às 7h') == 'alarme'
    assert intencao_agenda('pode me lembrar de beber água amanhã às 15h') == 'lembrete'
    assert intencao_agenda('guarda 5 de novembro como uma data importante') == 'compromisso'
    assert intencao_agenda('não crie um alarme às 7h') is None
    assert not data_importante('não tenho consulta amanhã')
    assert data_importante('tenho uma consulta amanhã às 15h')


def evento(texto, externo=False, dispositivo='MOBILE'):
    return EventoCanonico(categoria=CategoriaEvento.NOTIFICACAO if externo else CategoriaEvento.AGENDA_SOLICITADA,
        origem=OrigemEvento.ANDROID if externo else OrigemEvento.USUARIO,
        pacote='com.whatsapp' if externo else 'pc.chat' if dispositivo == 'PC' else 'mobile.chat',
        payload={'texto': texto}, metadados={'dispositivo_origem': dispositivo, 'pedido_usuario': not externo})


async def test_persistencia_deduplicacao_aprovacao_cancelamento(banco_teste):
    inicio = datetime.now(timezone.utc) + timedelta(days=2)
    item = await agenda.salvar('compromisso', 'Consulta', inicio)
    assert item['estado'] == 'sugestao'
    assert (await Agenda().salvar('compromisso', 'Consulta', inicio))['id'] == item['id']
    assert (await agenda.alterar_estado(item['id'], 'agendado'))['estado'] == 'agendado'
    assert (await agenda.alterar_estado(item['id'], 'cancelado'))['estado'] == 'cancelado'
    assert await agenda.listar() == []
    with pytest.raises(ValueError): await agenda.alterar_estado(item['id'], 'agendado')


async def test_pedidos_diretos_vs_mensagens(banco_teste, monkeypatch):
    saida = AsyncMock()
    monkeypatch.setattr(kernel, 'publicar', saida)
    agente = AgenteAgenda()
    await agente.processar(evento('Consulta importante amanhã às 15h', externo=True))
    item = (await agenda.listar())[0]
    assert item['estado'] == 'sugestao'
    assert saida.call_args.args[0].payload['acao_tipo'] == 'AGENDA_REVISAR'
    await agente.processar(evento('me lembra de tomar remédio amanhã às 16h'))
    resposta = saida.call_args.args[0]
    assert resposta.payload['acoes_agenda'][0]['id']
    assert 'Guardei' in resposta.payload['texto']
    assert len([i for i in await agenda.listar() if i['estado'] == 'agendado']) == 1
    await agente.processar(evento('me acorde amanhã às 7h'))
    assert 'Ainda não tenho confirmação' in saida.call_args.args[0].payload['texto']
    assert next(i for i in await agenda.listar() if i['tipo'] == 'alarme')['estado'] == 'preparado'


async def test_continuacao_isolada_por_dispositivo_e_cancelamento(banco_teste, monkeypatch):
    saida = AsyncMock()
    monkeypatch.setattr(kernel, 'publicar', saida)
    agente = AgenteAgenda()
    await agente.processar(evento('me lembra de tomar remédio'))
    assert saida.call_args.args[0].payload['aguarda_resposta'] is True
    assert await agenda.rascunho('MOBILE')
    assert await agenda.rascunho('PC') is None
    entrada = evento('amanhã às 15h').clonar(categoria=CategoriaEvento.SISTEMA_COMANDO_USUARIO)
    await AgenteReflexo().processar(entrada)
    assert saida.call_args.args[0].categoria == CategoriaEvento.AGENDA_SOLICITADA
    await agente.processar(saida.call_args.args[0])
    assert len(await agenda.listar()) == 1
    assert await agenda.rascunho('MOBILE') is None
    await agente.processar(evento('me acorde amanhã'))
    assert saida.call_args.args[0].payload['aguarda_resposta'] is True
    await agente.processar(evento('cancelar'))
    assert await agenda.rascunho('MOBILE') is None
    assert len(await agenda.listar()) == 1


async def test_sem_horario_lembrete_pergunta_em_vez_de_silenciar(banco_teste, monkeypatch):
    saida = AsyncMock()
    monkeypatch.setattr(kernel, 'publicar', saida)
    agente = AgenteAgenda()
    await agente.processar(evento('me lembra de beber água amanhã'))
    assert await agenda.listar() == []
    await agente.processar(evento('às 15h'))
    assert len(await agenda.listar()) == 1


async def test_tick_sem_conexao_nao_consume_lembrete_e_alarme_nao_notifica(banco_teste, monkeypatch):
    from api.websocket import central_alertas
    agora = datetime.now(timezone.utc)
    await agenda.salvar('lembrete', 'Água', agora + timedelta(seconds=20), confirmar=True, antecedencia_minutos=1)
    await agenda.salvar('alarme', 'Acordar', agora + timedelta(seconds=20), confirmar=True)
    envio = AsyncMock(return_value=False)
    monkeypatch.setattr(central_alertas, 'enviar_lembrete_agenda', envio)
    agente = AgenteAgenda()
    await agente.avisar_pendentes()
    assert len(await agenda.pendentes_aviso()) == 1
    envio.return_value = True
    await agente.avisar_pendentes()
    assert await agenda.pendentes_aviso() == []
    assert envio.call_count == 2
    assert envio.call_args.args[0]['acao_tipo'] == 'AGENDA_REVISAR'


async def test_api_datas_com_fuso_e_estados(banco_teste):
    app = FastAPI()
    app.include_router(router, prefix='/agenda')
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://teste') as client:
        data = {'titulo': 'Consulta', 'inicio': (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()}
        resposta = await client.post('/agenda', json=data)
        assert resposta.status_code == 200
        item = resposta.json()
        assert item['estado'] == 'agendado'
        assert (await client.patch('/agenda/' + item['id'], json={'estado': 'cancelado'})).status_code == 200
        assert (await client.get('/agenda/inexistente')).status_code == 404
        assert (await client.post('/agenda', json={**data, 'inicio': '2030-10-23T15:00:00'})).status_code == 422


async def test_correcao_da_data_preserva_titulo(banco_teste, monkeypatch):
    saida = AsyncMock()
    monkeypatch.setattr(kernel, 'publicar', saida)
    agente = AgenteAgenda()
    await agente.processar(evento('me lembra de tomar remédio dia 31 de fevereiro às 15h'))
    assert await agenda.rascunho('MOBILE')
    assert await agenda.listar() == []
    await agente.processar(evento('amanhã às 16h'))
    item = (await agenda.listar())[0]
    assert item['titulo'] == 'tomar remédio'
    assert '16:00' in item['quando']


async def test_metadados_e_acoes_chegam_ao_dispositivo_certo(banco_teste, monkeypatch):
    import json
    from types import SimpleNamespace
    from api.websocket import GerenciadorNotificacoes
    from servicos.notificacoes import PoliticaNotificacoes
    saida = AsyncMock()
    monkeypatch.setattr(kernel, 'publicar', saida)
    await AgenteAgenda().processar(evento('agende consulta amanhã às 15h', dispositivo='PC'))
    resposta = saida.call_args.args[0]
    payload, _ = PoliticaNotificacoes().preparar(resposta)
    central = GerenciadorNotificacoes()
    pc = SimpleNamespace(client_state=SimpleNamespace(value=1), send_text=AsyncMock())
    mobile = SimpleNamespace(client_state=SimpleNamespace(value=1), send_text=AsyncMock())
    central.pc_master, central.mobile_client = pc, mobile
    await central.enviar_alerta({**resposta.model_dump(), 'payload': payload})
    recebido = json.loads(pc.send_text.call_args.args[0])
    assert recebido['acoes_agenda'][0]['id']
    assert recebido['dispositivo_destino'] == 'PC'
    mobile.send_text.assert_not_called()
    await AgenteAgenda().processar(evento('Consulta amanhã às 16h', externo=True).clonar(
        metadados={'atencao': {'pode_interagir': False}}))
    assert PoliticaNotificacoes().preparar(saida.call_args.args[0])[0] is None


async def test_falha_banco_nao_afirma_que_salvou(banco_teste, monkeypatch):
    saida = AsyncMock()
    monkeypatch.setattr(kernel, 'publicar', saida)
    monkeypatch.setattr(agenda, 'salvar', AsyncMock(side_effect=RuntimeError('banco indisponível')))
    await AgenteAgenda().processar(evento('agende consulta amanhã às 15h'))
    assert 'Não consegui salvar' in saida.call_args.args[0].payload['texto']
    assert not saida.call_args.args[0].payload['acoes_agenda']


async def test_api_protegida_e_dia_inteiro_nao_vira_alarme(banco_teste):
    from api.auth import AuthMiddleware
    app = FastAPI()
    app.include_router(router, prefix='/agenda')
    app.add_middleware(AuthMiddleware)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://teste') as client:
        assert (await client.get('/agenda')).status_code == 401
        client.headers['Authorization'] = 'Bearer token-de-teste'
        assert (await client.get('/agenda')).status_code == 200
        response = await client.post('/agenda', json={'tipo': 'alarme', 'titulo': 'Acordar',
            'inicio': (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(), 'dia_inteiro': True})
        assert response.status_code == 422
