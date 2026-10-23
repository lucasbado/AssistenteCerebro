from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from core.evento import EventoCanonico
from core.kernel import kernel
from core.tipos import CategoriaEvento, OrigemEvento
from servicos.tarefas import Tarefas, tarefas, ConflitoTarefa
from servicos.linguagem_tarefas import interpretar_tarefa, pendencia_mensagem
from agentes.agente_tarefas import AgenteTarefas
from agentes.agente_agenda import AgenteAgenda
from agentes.agente_reflexo import AgenteReflexo
from api.tarefas import router


def evento(texto, externo=False, dispositivo='MOBILE'):
    return EventoCanonico(categoria=CategoriaEvento.NOTIFICACAO if externo else CategoriaEvento.TAREFA_SOLICITADA,
        origem=OrigemEvento.ANDROID if externo else OrigemEvento.USUARIO,
        pacote='com.whatsapp' if externo else 'pc.chat' if dispositivo == 'PC' else 'mobile.chat',
        payload={'texto': texto, 'titulo': 'Contato de teste'},
        metadados={'dispositivo_origem': dispositivo, 'pedido_usuario': not externo})


@pytest.mark.parametrize('texto,acao,alvo', [
    ('preciso pagar a conta sexta', 'criar', 'pagar a conta'),
    ('crie uma tarefa comprar pão', 'criar', 'comprar pão'),
    ('minhas tarefas', 'listar', ''),
    ('o que tenho pendente', 'listar', ''),
    ('conclua a tarefa comprar pão', 'concluir', 'comprar pao'),
    ('já paguei a conta', 'concluir', 'pagar conta'),
    ('adie pagar conta para amanhã às 15h', 'adiar', 'pagar conta'),
    ('descarte a tarefa comprar pão', 'descartar', 'comprar pao'),
])
def test_linguagem(texto, acao, alvo):
    pedido = interpretar_tarefa(texto)
    assert pedido['acao'] == acao
    assert pedido['alvo'] == alvo


@pytest.mark.parametrize('texto', ['não crie uma tarefa pagar conta', 'abra youtube no PC',
    'me lembra de tomar remédio amanhã às 15h', 'cancele o alarme', 'se eu precisar pagar sexta', 'exclua minha memória', 'cancele a música'])
def test_nao_intercepta_outros_dominios_ou_negacao(texto):
    assert interpretar_tarefa(texto) is None


def test_mensagens_exigem_acao_e_data():
    assert pendencia_mensagem('Pode enviar o relatório até sexta?')
    assert not pendencia_mensagem('Reunião sexta às 15h')
    assert not pendencia_mensagem('Não precisa enviar o relatório sexta')
    assert not pendencia_mensagem('Pode enviar o relatório?')


async def test_tarefa_sem_prazo_persiste_e_vencida_continua_aberta(banco_teste):
    item = await tarefas.salvar('Comprar pão', chave_evento='pedido-1')
    assert item['prazo'] is None and item['quando'] == 'Sem prazo'
    assert (await Tarefas().obter(item['id']))['titulo'] == 'Comprar pão'
    vencida = await tarefas.salvar('Pagar conta', datetime.now(timezone.utc) - timedelta(days=20))
    assert vencida['atrasada'] is True
    assert len(await tarefas.listar('pendente')) == 2


async def test_idempotencia_e_novo_pedido_apos_concluir(banco_teste):
    item = await tarefas.salvar('Comprar pão', chave_evento='original')
    assert (await tarefas.salvar('Comprar pão', chave_evento='repetido'))['id'] == item['id']
    await tarefas.alterar(item['id'], 'concluir', versao=1)
    assert (await tarefas.salvar('Comprar pão', chave_evento='original'))['estado'] == 'concluida'
    novo = await tarefas.salvar('Comprar pão', chave_evento='novo-pedido')
    assert novo['id'] != item['id']


async def test_sugestao_nao_avisa_aceitar_e_descartar_sem_ressuscitar(banco_teste):
    prazo = datetime.now(timezone.utc) - timedelta(seconds=10)
    item = await tarefas.salvar('Enviar relatório', prazo, confirmar=False, chave_evento='mensagem-1')
    assert await tarefas.pendentes_aviso() == []
    with pytest.raises(ValueError): await tarefas.alterar(item['id'], 'concluir')
    aceita = await tarefas.alterar(item['id'], 'aceitar', versao=1)
    assert aceita['estado'] == 'pendente'
    assert len(await tarefas.pendentes_aviso()) == 1
    await tarefas.alterar(item['id'], 'descartar', versao=2)
    assert await tarefas.pendentes_aviso() == []
    repetida = await tarefas.salvar('Enviar relatório', prazo, confirmar=False, chave_evento='mensagem-1')
    assert repetida['estado'] == 'descartada'


async def test_adiar_invalida_aviso_antigo_e_concorrencia(banco_teste):
    item = await tarefas.salvar('Enviar relatório', datetime.now(timezone.utc) - timedelta(seconds=10))
    nova_data = datetime.now(timezone.utc) + timedelta(days=1)
    adiada = await tarefas.alterar(item['id'], 'adiar', nova_data, versao=1)
    assert adiada['versao'] == 2 and not adiada['atrasada']
    assert not await tarefas.marcar_aviso(item['id'], 1)
    assert await tarefas.pendentes_aviso() == []
    with pytest.raises(ConflitoTarefa): await tarefas.alterar(item['id'], 'concluir', versao=1)
    await tarefas.alterar(item['id'], 'concluir', versao=2)
    with pytest.raises(ConflitoTarefa): await tarefas.alterar(item['id'], 'adiar', nova_data, versao=3)


async def test_dia_inteiro_nao_vence_a_meia_noite_nem_inventa_hora(banco_teste):
    from servicos.tempo import horario_local
    from servicos.datas_agenda import extrair_data
    agora = datetime.now(timezone.utc)
    data = extrair_data('hoje', agora)
    item = await tarefas.salvar('Pagar conta', data['inicio'], dia_inteiro=True)
    assert not item['atrasada']
    assert await tarefas.pendentes_aviso() == []


async def test_mensagem_sugere_uma_vez_sem_duplicar_agenda(banco_teste, monkeypatch):
    saida = AsyncMock()
    monkeypatch.setattr(kernel, 'publicar', saida)
    entrada = evento('Preciso que você entregue o relatório amanhã às 15h', externo=True)
    await AgenteTarefas().processar(entrada)
    await AgenteAgenda().processar(entrada)
    assert saida.call_count == 1
    assert saida.call_args.args[0].payload['acao_tipo'] == 'TAREFA_REVISAR'
    assert (await tarefas.listar())[0]['estado'] == 'sugestao'
    await AgenteTarefas().processar(entrada)
    assert len(await tarefas.listar()) == 1


async def test_fluxo_por_voz_criar_adiar_completar_data_e_concluir(banco_teste, monkeypatch):
    saida = AsyncMock()
    monkeypatch.setattr(kernel, 'publicar', saida)
    agente = AgenteTarefas()
    await agente.processar(evento('preciso pagar conta'))
    assert 'sem prazo' in saida.call_args.args[0].payload['texto']
    await agente.processar(evento('adie pagar conta'))
    assert saida.call_args.args[0].payload['aguarda_resposta']
    await agente.processar(evento('amanhã às 15h'))
    assert 'Adiei' in saida.call_args.args[0].payload['texto']
    await agente.processar(evento('já paguei a conta'))
    assert 'concluída' in saida.call_args.args[0].payload['texto']
    assert await tarefas.listar('pendente') == []


async def test_alvo_ambiguo_pergunta_e_outra_tela_nao_herda_contexto(banco_teste, monkeypatch):
    saida = AsyncMock()
    monkeypatch.setattr(kernel, 'publicar', saida)
    for titulo in ['Pagar conta luz', 'Pagar conta água']: await tarefas.salvar(titulo)
    agente = AgenteTarefas()
    await agente.processar(evento('conclua pagar conta'))
    assert saida.call_args.args[0].payload['aguarda_resposta']
    assert len(await tarefas.listar('pendente')) == 2
    assert await tarefas.contexto('PC') is None
    await agente.processar(evento('a segunda'))
    assert len(await tarefas.listar('pendente')) == 1


async def test_reflexo_prioriza_tarefas_sem_roubar_novo_compromisso(banco_teste, monkeypatch):
    saida = AsyncMock()
    monkeypatch.setattr(kernel, 'publicar', saida)
    await AgenteReflexo().processar(evento('crie uma tarefa comprar pão').clonar(categoria=CategoriaEvento.SISTEMA_COMANDO_USUARIO))
    assert saida.call_args.args[0].categoria == CategoriaEvento.TAREFA_SOLICITADA
    await tarefas.guardar_contexto('MOBILE', {'pedido': {'acao': 'adiar', 'alvo': 'conta', 'texto': ''}, 'precisa': 'data'})
    await AgenteReflexo().processar(evento('agende consulta amanhã às 15h').clonar(categoria=CategoriaEvento.SISTEMA_COMANDO_USUARIO))
    assert saida.call_args.args[0].categoria == CategoriaEvento.AGENDA_SOLICITADA


async def test_tick_offline_nao_marca_e_conclusao_para_aviso(banco_teste, monkeypatch):
    from api.websocket import central_alertas
    item = await tarefas.salvar('Enviar relatório', datetime.now(timezone.utc) - timedelta(seconds=10))
    envio = AsyncMock(return_value=False)
    monkeypatch.setattr(central_alertas, 'enviar_lembrete_agenda', envio)
    agente = AgenteTarefas()
    await agente.avisar_pendentes()
    assert len(await tarefas.pendentes_aviso()) == 1
    envio.return_value = True
    await agente.avisar_pendentes()
    await agente.avisar_pendentes()
    assert envio.call_count == 2
    await tarefas.alterar(item['id'], 'concluir')
    assert await tarefas.pendentes_aviso() == []


async def test_api_datas_conflitos_autenticacao_e_sem_prazo(banco_teste):
    from api.auth import AuthMiddleware
    app = FastAPI()
    app.include_router(router, prefix='/tarefas')
    app.add_middleware(AuthMiddleware)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://teste') as client:
        assert (await client.get('/tarefas')).status_code == 401
        client.headers['Authorization'] = 'Bearer token-de-teste'
        resposta = await client.post('/tarefas', json={'titulo': 'Comprar pão'})
        assert resposta.status_code == 200
        item = resposta.json()
        assert item['prazo'] is None
        caminho = '/tarefas/' + item['id']
        assert (await client.patch(caminho, json={'acao': 'adiar'})).status_code == 422
        futuro = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        assert (await client.patch(caminho, json={'acao': 'adiar', 'prazo': futuro, 'versao': 1})).status_code == 200
        assert (await client.patch(caminho, json={'acao': 'concluir', 'versao': 1})).status_code == 409
        assert (await client.get('/tarefas/inexistente')).status_code == 404
        assert (await client.post('/tarefas', json={'titulo': 'x', 'prazo': '2030-10-23T15:00:00'})).status_code == 422


async def test_agenda_consulta_inclui_prazos_sem_duplicar_compromissos(banco_teste, monkeypatch):
    from servicos.agenda import agenda
    from servicos.datas_agenda import extrair_data
    saida = AsyncMock()
    monkeypatch.setattr(kernel, 'publicar', saida)
    data = extrair_data('amanhã às 15h', datetime.now(timezone.utc))
    item = await tarefas.salvar('Pagar conta', data['inicio'])
    await AgenteAgenda().processar(evento('qual minha agenda amanhã').clonar(categoria=CategoriaEvento.AGENDA_SOLICITADA))
    resposta = saida.call_args.args[0]
    assert 'Pagar conta' in resposta.payload['texto']
    assert resposta.payload['acoes_tarefas'][0]['id'] == item['id']
    assert await agenda.listar() == []


async def test_correcao_horario_da_tarefa_preserva_o_dia(banco_teste, monkeypatch):
    from servicos.tempo import horario_local
    saida = AsyncMock()
    monkeypatch.setattr(kernel, 'publicar', saida)
    agente = AgenteTarefas()
    await agente.processar(evento('preciso pagar conta depois de amanhã às 25h'))
    assert await tarefas.listar() == []
    await agente.processar(evento('às 15h'))
    item = (await tarefas.listar())[0]
    assert horario_local(datetime.fromisoformat(item['prazo'])).date() == horario_local(datetime.now(timezone.utc)).date() + timedelta(days=2)
