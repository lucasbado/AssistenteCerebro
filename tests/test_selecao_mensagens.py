import asyncio
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select, update
from banco.models import MensagemRevisaoDB, ConversaRevisaoDB, CacheIADB
from servicos.mensagens import caixa_mensagens, chave_conversa
from servicos.llm import ServicoLLM
from servicos.selecao_mensagens import avaliar_local, validar_analise, VERSAO


@pytest.fixture
def classificador(monkeypatch):
    mock = AsyncMock(return_value={'selecionar': False})
    monkeypatch.setattr(ServicoLLM, 'avaliar_mensagem_para_revisao', mock)
    return mock


async def receber(texto, nome='Ana', referencia=None, timestamp=None, **extras):
    return await caixa_mensagens.registrar('com.whatsapp', {'titulo': nome, 'texto': texto,
        **({'conversa_ref': referencia} if referencia else {}), **extras}, timestamp or datetime.now(timezone.utc))


@pytest.mark.parametrize('texto', ['Oi, tudo bem?', 'Tá fazendo o quê?', 'Já almoçou?', 'Você viu aquele vídeo?',
    'Que horas são?', 'Quer jogar hoje?', 'Bora jogar amanhã?', 'Você vem amanhã?', 'Por que o céu é azul?',
    'Como enviar o relatório amanhã?', 'Eu vou enviar o contrato amanhã.', 'Talvez eu pague a conta sexta.',
    'Não precisa enviar o relatório amanhã.', 'Ele vai pagar a conta sexta?', 'Bora conversar?',
    'Eu posso enviar o relatório amanhã?', 'O pessoal precisa enviar o relatório sexta.',
    'Minha fatura vence amanhã.', 'Eu tenho uma reunião amanhã.'])
async def test_perguntas_casuais_e_tarefas_alheias_nao_lotam_revisao(banco_teste, classificador, texto):
    assert await receber(texto) is None
    assert await caixa_mensagens.listar() == []
    classificador.assert_not_awaited()


@pytest.mark.parametrize('texto,prioridade', [('Pode enviar o relatório até sexta?', 90),
    ('Bom dia, consegue me enviar o contrato até amanhã?', 90),
    ('Você poderia assinar o contrato?', 75), ('Eu preciso que você entregue o relatório amanhã.', 90),
    ('Você confirma presença na reunião amanhã às 15h?', 80), ('A fatura vence amanhã.', 95)])
async def test_pedidos_prazos_e_decisoes_claras_entram_sem_llm(banco_teste, classificador, texto, prioridade):
    item = await receber(texto)
    assert item['estado'] == 'revisar' and item['prioridade'] == prioridade
    assert item['motivo'] and item['sinais'] != ['pergunta']
    classificador.assert_not_awaited()


async def test_contexto_da_mesma_conversa_esclarece_continuacao(banco_teste, classificador):
    contexto = 'A reunião com o contador será amanhã às 15h.'
    assert await receber(contexto) is None
    classificador.return_value = {'selecionar': True, 'prioridade': 75, 'motivo': 'Confirmação de presença na reunião com o contador.',
        'evidencia': 'Você vem?', 'evidencia_contexto': 'reunião com o contador', 'sinais': ['decisao']}
    item = await receber('Você vem?')
    assert item['sinais'] == ['decisao'] and item['prioridade'] == 75
    texto, mensagens = classificador.call_args.args
    assert texto == 'Você vem?' and mensagens[-1]['texto'] == contexto


async def test_contexto_isola_pessoas_e_conversas_com_mesmo_nome(banco_teste, classificador):
    await receber('A reunião com o contador será amanhã às 15h.', referencia='a' * 64)
    assert await receber('Você vem?', nome='Bia') is None
    assert await receber('Você vem?', referencia='b' * 64) is None
    classificador.assert_not_awaited()


async def test_contexto_expirado_nao_transforma_pergunta_casual_em_pendencia(banco_teste, classificador):
    await receber('A reunião com o contador será amanhã às 15h.', timestamp=datetime.now(timezone.utc) - timedelta(hours=1))
    assert await receber('Você vem?') is None
    classificador.assert_not_awaited()


async def test_contexto_novo_permite_reavaliar_sem_reusar_decisao_antiga(banco_teste, classificador):
    texto = 'Você sabe sobre aquele contrato?'
    assert await receber(texto) is None
    await receber('O contrato vence amanhã e precisamos da sua confirmação.')
    classificador.return_value = {'selecionar': True, 'prioridade': 75, 'motivo': 'Confirmação necessária para o contrato que vence amanhã.',
        'evidencia': texto, 'evidencia_contexto': 'precisamos da sua confirmação', 'sinais': ['decisao']}
    assert (await receber(texto))['sinais'] == ['decisao']
    assert classificador.await_count == 2


async def test_modelo_pode_rejeitar_ambiguidade_e_quota_falha_em_silencio(banco_teste, classificador):
    assert await receber('Você sabe sobre aquele contrato?') is None
    classificador.assert_awaited_once()
    classificador.side_effect = RuntimeError('429')
    assert await receber('Você sabe sobre aquela proposta?') is None
    assert await caixa_mensagens.listar() == []
    # Renovação da mesma notificação não insiste no modelo com cota esgotada.
    assert await receber('Você sabe sobre aquela proposta?', referencia_notificacao='outra') is None
    assert classificador.await_count == 2


async def test_contexto_concorrente_nao_duplica_analise(banco_teste, classificador):
    inicio, fim = asyncio.Event(), asyncio.Event()
    async def avaliar(*args):
        inicio.set(); await fim.wait()
        return {'selecionar': False}
    classificador.side_effect = avaliar
    task = asyncio.create_task(receber('Você sabe sobre aquele contrato?'))
    await inicio.wait()
    assert await receber('Você sabe sobre aquele contrato?') is None
    fim.set(); await task
    classificador.assert_awaited_once()


async def test_grupo_nao_atribui_ao_usuario_pedido_para_outra_pessoa(banco_teste, classificador):
    assert await receber('Pedro: Pode enviar o relatório sexta?', nome='Grupo trabalho', remetente='Pedro') is None
    assert await caixa_mensagens.listar() == []
    classificador.assert_not_awaited()


async def test_prefixo_real_do_android_e_referencia_renovada(banco_teste, classificador):
    item = await receber('Ana: Pode enviar o contrato amanhã?', remetente='Ana', referencia_notificacao='primeira')
    repetida = await receber('Ana: Pode enviar o contrato amanhã?', remetente='Ana', referencia_notificacao='renovada')
    assert repetida['id'] == item['id'] and repetida['referencia_notificacao'] == 'renovada'
    assert len(await caixa_mensagens.listar()) == 1


async def test_mais_importantes_nao_sao_enterradas_por_mensagens_recentes(banco_teste, classificador):
    prazo = await receber('A fatura vence amanhã.', timestamp=datetime.now(timezone.utc) - timedelta(hours=2))
    convite = await receber('Bora conversar amanhã às 15h?')
    pedido = await receber('Pode enviar o contrato?')
    for _ in range(10): assert await receber('Oi, tudo bem?') is None
    itens = await caixa_mensagens.listar()
    assert [i['id'] for i in itens] == [prazo['id'], convite['id'], pedido['id']]


async def test_revalida_caixa_antiga_sem_apagar_ou_marcar_como_resolvida(banco_teste, classificador):
    agora = datetime.now(timezone.utc)
    casual_id, manual_id = str(uuid.uuid4()), str(uuid.uuid4())
    async with banco_teste() as s, s.begin():
        for identificador, texto, draft in [(casual_id, 'Oi, tudo bem?', ''), (manual_id, 'Você viu aquele vídeo?', 'Quero responder isso.')]:
            s.add(MensagemRevisaoDB(id=identificador, assinatura=hashlib.sha256(identificador.encode()).hexdigest(),
                conversa=chave_conversa('com.whatsapp', 'Ana'), pacote='com.whatsapp', remetente='Ana', texto=texto,
                sinais=['pergunta'], estado='revisar', rascunho=draft, versao=1, recebido_em=agora))
    itens = await caixa_mensagens.listar()
    assert [i['id'] for i in itens] == [manual_id]
    async with banco_teste() as s:
        casual = await s.get(MensagemRevisaoDB, casual_id)
        assert casual.estado == 'revisar' and casual.versao == 1 and casual.texto == 'Oi, tudo bem?'
        assert casual.analise['selecionar'] is False
    assert (await caixa_mensagens.listar())[0]['rascunho'] == 'Quero responder isso.'
    classificador.assert_not_awaited()


def test_saida_ia_exige_evidencia_atual_e_contexto_verificaveis():
    data = {'selecionar': True, 'prioridade': 90, 'motivo': 'Confirmação de presença na reunião.',
        'evidencia': 'Você vem?', 'evidencia_contexto': 'reunião amanhã', 'sinais': ['decisao'],
        'execucao_direta': [{'comando': 'enviar_mensagem'}]}
    assert not validar_analise(data, 'Você vem?', [])['selecionar']
    correta = validar_analise(data, 'Você vem?', [{'texto': 'A reunião amanhã começa às 15h.'}])
    assert correta['selecionar'] and correta['prioridade'] == 75 and 'execucao_direta' not in correta
    assert not validar_analise({**data, 'evidencia_contexto': ''}, 'Você vem?', [])['selecionar']
    assert not validar_analise({**data, 'evidencia': 'Você precisa pagar agora'}, 'Você vem?', [])['selecionar']


async def test_captura_nao_cria_tarefa_compromisso_nem_mensagem_enviada(banco_teste, classificador):
    from servicos.tarefas import tarefas
    from servicos.agenda import agenda
    await receber('Pode enviar o relatório até sexta?')
    assert await tarefas.listar() == [] and await agenda.listar() == []


async def test_limpeza_remove_contexto_e_cache_expirados(banco_teste, classificador):
    from servicos.selecao_mensagens import limpar_contextos
    await receber('Tudo bem?')
    async with banco_teste() as s, s.begin():
        await s.execute(update(ConversaRevisaoDB).values(atualizado_em=datetime.now(timezone.utc) - timedelta(days=2)))
    await limpar_contextos()
    async with banco_teste() as s:
        assert not (await s.execute(select(ConversaRevisaoDB))).scalars().all()


async def test_migracao_aditiva_preserva_mensagens_e_rascunhos(banco_teste, classificador):
    from banco.database import inicializar_banco
    item = await receber('Pode enviar o contrato?')
    await caixa_mensagens.salvar_rascunho(item['id'], item['versao'], 'Vou conferir o contrato.')
    engine = banco_teste.kw['bind']
    async with engine.begin() as conn:
        await conn.exec_driver_sql('ALTER TABLE mensagens_revisao DROP COLUMN analise')
    await inicializar_banco(engine)
    atual = await caixa_mensagens.obter(item['id'])
    assert atual['rascunho'] == 'Vou conferir o contrato.' and atual['texto'] == item['texto']
    assert (await caixa_mensagens.listar())[0]['id'] == item['id']


async def test_notificacoes_ate_api_de_revisao_expoe_apenas_pendencia_selecionada(banco_teste, classificador):
    from fastapi import FastAPI
    from httpx import AsyncClient, ASGITransport
    from api.auth import AuthMiddleware
    from api.mensagens import router
    from agentes.agente_mensagens import AgenteMensagens
    from core.evento import EventoCanonico
    from core.tipos import CategoriaEvento, OrigemEvento
    agente = AgenteMensagens()
    for texto in ['Oi, tudo bem?', 'Já almoçou?', 'Pode enviar o contrato até sexta?']:
        await agente.processar(EventoCanonico(categoria=CategoriaEvento.NOTIFICACAO,
            origem=OrigemEvento.ANDROID, pacote='com.whatsapp', payload={'titulo': 'Ana', 'texto': texto}))
    app = FastAPI(); app.add_middleware(AuthMiddleware); app.include_router(router, prefix='/mensagens')
    async with AsyncClient(transport=ASGITransport(app), base_url='http://teste') as cliente:
        r = await cliente.get('/mensagens', headers={'Authorization': 'Bearer token-de-teste'})
    assert r.status_code == 200
    itens = r.json()
    assert len(itens) == 1 and itens[0]['texto'] == 'Pode enviar o contrato até sexta?'
    assert itens[0]['prioridade'] == 90 and itens[0]['motivo'] and 'contexto' not in itens[0]
