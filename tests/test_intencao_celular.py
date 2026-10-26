import asyncio
from types import SimpleNamespace
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from core.evento import EventoCanonico
from core.tipos import CategoriaEvento, OrigemEvento
from servicos.controle_celular import interpretar_controle, validar_acao
from servicos.dialogo_controles import DialogoControles
from servicos.catalogo_apps_mobile import CatalogoAppsMobile

AGORA = datetime(2026, 10, 26, 23, 0, tzinfo=timezone.utc)  # 20h em São Paulo


@pytest.mark.parametrize('texto,hora,minuto', [
    ('me acorde amanhã às sete', 7, 0),
    ('coloca pra despertar às 7h30', 7, 30),
    ('preciso acordar às seis e meia da manhã', 6, 30),
    ('me acorde sete e quarenta e cinco', 7, 45),
    ('me acorde amanhã sete e meia', 7, 30),
    ('me acorde daqui a dez minutos', 20, 10),
    ('me acorde ao meio dia', 12, 0),
])
def test_despertador_falado_sem_agenda(texto, hora, minuto):
    assert interpretar_controle(texto, referencia=AGORA) == {'acoes': [
        {'acao': 'alarm.create', 'parametros': {'hora': hora, 'minuto': minuto}}]}


def test_data_amanha_nao_vira_hoje_e_repeticao_explicita():
    cedo = AGORA.replace(hour=8)  # 5h
    plano = interpretar_controle('me acorde amanhã às sete', referencia=cedo)
    assert plano['acoes'][0]['acao'] == 'clock.open'
    assert 'data específica' in plano['nota']
    assert interpretar_controle('me acorde hoje às sete', referencia=AGORA)['pergunta']
    for texto, dias in [('me acorde às sete todos os dias', list(range(1, 8))),
                        ('me acorde às sete de segunda a sexta', [2, 3, 4, 5, 6])]:
        assert interpretar_controle(texto, referencia=AGORA)['acoes'][0]['parametros']['dias'] == dias


def test_falta_horario_e_continuacao_temporaria_sem_sql():
    now = [0]
    d = DialogoControles(lambda: now[0])
    p = interpretar_controle('me acorde amanhã', referencia=AGORA)
    assert p['pergunta']
    d.guardar('MOBILE', p)
    assert d.continua('MOBILE', 'sete e meia')
    assert interpretar_controle(d.resolver('MOBILE', 'sete e meia'), referencia=AGORA)['acoes'][0]['parametros'] == {'hora': 7, 'minuto': 30}
    assert d.resolver('PC', 'sete e meia') == 'sete e meia'
    assert d.cancelar('MOBILE', 'cancela')
    d.guardar('MOBILE', p); now[0] = 181
    assert not d.continua('MOBILE', 'sete e meia')


def test_pergunta_semantica_continua_sem_impor_palavra_chave():
    d = DialogoControles()
    d.guardar_semantico('MOBILE', 'Tenho que levantar cedo amanhã', {'esclarecimento': 'Que horas?', 'pergunta': True})
    texto = d.resolver('MOBILE', 'às seis e meia')
    from servicos.linguagem_relogio import interpretar_relogio
    assert interpretar_relogio('me acorde ' + texto, AGORA, True)['acoes'][0]['parametros'] == {'hora': 6, 'minuto': 30}
    assert d.resolver('MOBILE', 'abra a calculadora') == 'abra a calculadora'


def test_catalogo_autenticado_nao_mistura_aparelhos_e_nao_inventa_apps():
    c = CatalogoAppsMobile(); a, b = object(), object()
    c.vincular(a)
    assert not c.receber(b, [{'n': 'Falso', 'p': 'com.falso'}])
    assert c.receber(a, [{'n': 'WhatsApp', 'p': 'com.whatsapp'}, {'n': 'X', 'p': 'x; shell'}, {'n': 'WhatsApp', 'p': 'com.whatsapp'}])
    assert c.resolver('WhatsApp')['p'] == 'com.whatsapp'
    assert len(c.apps) == 1
    c.vincular(b)
    assert not c.apps


@pytest.mark.parametrize('acao,args', [
    ('alarm.create', {'hora': 7, 'minuto': 0, 'dias': [True]}),
    ('alarm.create', {'hora': 7, 'minuto': 0, 'dias': [2, 2]}),
    ('app.open', {'pacote': 'com.app; shell'}),
    ('browser.open', {'url': 'javascript:alert(1)'}),
    ('browser.open', {'url': 'https://user:password@example.com'}),
    ('ui.tap', {'pacote': 'com.app', 'captura': 'x', 'node': 0}),
    ('ui.type', {'pacote': 'com.app', 'captura': 'a'*36, 'node': 0, 'texto': ''}),
    ('ui.tap', {'pacote': 'com.app', 'captura': 'a'*36, 'node': True}),
    ('sound.mode', {'modo': []}),
])
def test_contrato_estrito_sem_coercao(acao, args):
    with pytest.raises(ValueError): validar_acao(acao, args)


@pytest.fixture
def semantica(monkeypatch):
    import servicos.interpretacao_celular as m
    c = CatalogoAppsMobile(); ws = object(); c.vincular(ws)
    c.receber(ws, [{'n': 'Calculadora', 'p': 'com.calculator'}, {'n': 'Instagram', 'p': 'com.instagram.android'}])
    monkeypatch.setattr(m, 'catalogo_apps_mobile', c)
    monkeypatch.setattr(m, 'obter_catalogo', AsyncMock(return_value=c))
    gerar = AsyncMock()
    monkeypatch.setattr(m.cognicao_controles, 'gerar', gerar)
    return m, gerar


@pytest.mark.asyncio
async def test_pedido_livre_vira_plano_validado_sem_executar_na_ia(semantica):
    m, gerar = semantica
    gerar.return_value = {'acoes': [{'acao': 'alarm.create', 'parametros': {'hora': 9, 'minuto': 10}}]}
    e = EventoCanonico(categoria=CategoriaEvento.CELULAR_ACAO_SOLICITADA, origem=OrigemEvento.USUARIO,
                      pacote='mobile.chat', timestamp=AGORA, payload={})
    plano = await m.interpretar_intencao(e, 'amanhã tenho que levantar, me ajuda a não perder a hora às sete e meia')
    assert plano['acoes'][0]['parametros'] == {'hora': 7, 'minuto': 30}
    assert gerar.call_args.args[0]['pedido_usuario'].startswith('amanhã tenho')
    assert 'apps_instalados' in gerar.call_args.args[0]


def test_modelo_nao_inventa_horario_app_ou_corpo_de_mensagem(semantica):
    m, _ = semantica
    plano = m.validar_plano({'acoes': [{'acao': 'alarm.create', 'parametros': {'hora': 7, 'minuto': 0}}]}, 'quero despertar', AGORA)
    assert plano['pergunta'] and 'horas' in plano['esclarecimento']
    with pytest.raises(ValueError):
        m.validar_plano({'acoes': [{'acao': 'app.open', 'parametros': {'pacote': 'com.inventado'}}]}, 'abra um app', AGORA)
    with pytest.raises(ValueError):
        m.validar_plano({'acoes': [{'acao': 'message.prepare', 'parametros': {'app': 'whatsapp', 'destinatario': 'Ana', 'texto': 'inventado'}}]}, 'avise a Ana', AGORA)
    p = m.validar_plano({'pergunta': True, 'resposta': 'Qual dos dois?', 'acoes': [{'acao': 'app.open', 'parametros': {'pacote': 'com.calculator'}}]}, 'abra o app', AGORA)
    assert 'acoes' not in p
    with pytest.raises(ValueError):
        m.validar_plano({'acoes': [{'acao': 'ui.snapshot', 'parametros': {'pacote': 'com.calculator'}}]}, 'leia um app', AGORA)


@pytest.mark.asyncio
async def test_execucao_de_app_nao_continua_em_node_invalido(semantica, monkeypatch):
    m, gerar = semantica
    from api.websocket import central_alertas
    executar = AsyncMock(side_effect=[{'status': 'concluido'}, {'status': 'concluido', 'resultado': {'pacote': 'com.calculator', 'captura': 'a'*36, 'nodes': []}}])
    monkeypatch.setattr(central_alertas, 'executar_celular', executar)
    gerar.return_value = {'acao': 'tap', 'node': 99}
    resultado = await m.executar_tarefa_app(None, 'com.calculator', 'abra a calculadora')
    assert resultado['status'] == 'encaminhado'
    assert executar.await_count == 2


@pytest.mark.asyncio
async def test_tela_sem_autorizacao_nao_e_enviada_a_ia(semantica, monkeypatch):
    m, gerar = semantica
    from api.websocket import central_alertas
    executar = AsyncMock(side_effect=[{'status': 'concluido'}, {'status': 'permissao', 'texto': 'A leitura de telas está desligada.'}])
    monkeypatch.setattr(central_alertas, 'executar_celular', executar)
    resultado = await m.executar_tarefa_app(None, 'com.calculator', 'procure um cálculo')
    assert resultado['status'] == 'permissao'
    gerar.assert_not_awaited()
    assert executar.await_count == 2


@pytest.mark.asyncio
async def test_abertura_mobile_preserva_web_e_catalogo_real_sem_gastar_ia(semantica):
    m, gerar = semantica
    e = EventoCanonico(categoria=CategoriaEvento.CELULAR_ACAO_SOLICITADA, origem=OrigemEvento.USUARIO,
                      pacote='mobile.chat', timestamp=AGORA, payload={})
    plano = await m.interpretar_intencao(e, 'abra https://example.com no celular')
    assert plano['acoes'][0] == {'acao': 'browser.open', 'parametros': {'url': 'https://example.com'}}
    plano = await m.interpretar_intencao(e, 'abra Calculadora')
    assert plano['acoes'][0] == {'acao': 'app.open', 'parametros': {'pacote': 'com.calculator'}}
    gerar.assert_not_awaited()


@pytest.mark.asyncio
async def test_catalogo_antigo_e_atualizado_para_apps_instalados_depois(monkeypatch):
    import servicos.interpretacao_celular as m
    from api.websocket import central_alertas
    c = CatalogoAppsMobile(); ws = object(); c.vincular(ws)
    c.receber(ws, [{'n': 'Antigo', 'p': 'com.antigo'}]); c.atualizado = 10
    monkeypatch.setattr(m, 'catalogo_apps_mobile', c)
    monkeypatch.setattr(m, 'time', SimpleNamespace(monotonic=lambda: 600))
    monkeypatch.setattr(central_alertas, 'mobile_client', ws)
    monkeypatch.setattr(central_alertas, '_capacidades', {ws: {'APPS_MOBILE'}})
    async def enviar(cliente, msg):
        assert cliente is ws and msg['acao'] == 'ENVIAR_LISTA_APPS'
        c.receber(ws, [{'n': 'Novo', 'p': 'com.novo'}])
        return True
    enviar_mock = AsyncMock(side_effect=enviar)
    monkeypatch.setattr(central_alertas, '_enviar_direto', enviar_mock)
    assert (await m.obter_catalogo()).resolver('Novo')['p'] == 'com.novo'
    await m.obter_catalogo()
    enviar_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_orcamento_sem_banco_tem_cooldown_e_limite():
    from servicos.cognicao_controles import OrcamentoVolatil
    from servicos.consumo_ia import LimiteIA
    now = [0]; b = OrcamentoVolatil(lambda: now[0])
    for _ in range(6): await b.reservar('modelo', 'pedido', 'system', 100)
    with pytest.raises(LimiteIA): await b.reservar('modelo', 'pedido', 'system', 100)
    now[0] = 61
    await b.bloquear('modelo', 60)
    with pytest.raises(LimiteIA): await b.reservar('modelo', 'pedido', 'system', 100)
    now[0] = 122
    await b.reservar('modelo', 'pedido', 'system', 100)
