import asyncio
import json
from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from core.tipos import CategoriaEvento, TipoAcao
from servicos.conversa import pedido_de_explicacao, ler_resposta_conversa, resposta_pendente


@pytest.mark.parametrize('texto', ['O que era pareidolia?', 'Por que o céu é azul?',
    'Como funciona um buraco negro?', 'Qual é a diferença entre RAM e SSD?',
    'Ollie, me explica fotossíntese', 'O que é mutar microfone?',
    'Quem foi Alan Turing?', 'Qual é o maior planeta do Sistema Solar?', 'E do que ele é feito?',
    'Explique o comando "abra YouTube e abra WhatsApp"'])
def test_explicacoes_nao_sao_comandos(texto):
    from agentes.agente_raciocinio import AgenteRaciocinio
    assert pedido_de_explicacao(texto)
    assert object.__new__(AgenteRaciocinio)._tentar_heuristica_local(texto) is None


@pytest.mark.parametrize('texto', ['Abra YouTube no PC', 'Apague a luz', 'Como está a luz do quarto?',
    'Qual é meu compromisso amanhã?', 'Como está a CPU do PC?',
    'O que é pareidolia e abra o YouTube no PC'])
def test_ordens_e_estado_da_casa_seguem_fluxo_existente(texto):
    assert not pedido_de_explicacao(texto)


@pytest.mark.parametrize('texto', ['', 'Comando recebido.', 'Pedido registrado!', 'Processando comando...',
    'Certo, comando recebido!', 'Comando processado com sucesso!', 'Vou pesquisar isso.'])
def test_recibo_sem_resposta_nao_conclui_conversa(texto):
    assert resposta_pendente(texto)
    with pytest.raises(ValueError): ler_resposta_conversa({'resposta': texto})


def test_explicacao_nao_autoriza_comandos_nem_memoria_permanente():
    data = ler_resposta_conversa({'resposta': 'Mutar é silenciar o microfone.', 'aguarda_resposta': 'true',
        'execucao_direta': [{'alvo': 'PC', 'comando': 'mutar_mic'}],
        'memoria_obsidian': {'fato': 'O usuário quer o microfone mudo.'}})
    assert data['execucao_direta'] == [] and 'memoria_obsidian' not in data
    assert data['aguarda_resposta'] is False


@pytest.fixture
async def modelo(monkeypatch):
    import servicos.llm as modulo
    monkeypatch.setattr(modulo.context_builder, 'construir_contexto', AsyncMock(return_value={
        'global_summary': '', 'session_summary': '', 'fatos_relevantes': []}))
    monkeypatch.setattr(modulo.semantic_cache_service, 'buscar', AsyncMock(return_value=None))
    monkeypatch.setattr(modulo.semantic_cache_service, 'inserir', AsyncMock())
    llm = modulo.ServicoLLM()
    monkeypatch.setattr(llm.ollama, 'disponivel', lambda: False)
    provider = SimpleNamespace(gerar=AsyncMock(return_value=json.dumps({
        'resposta': 'Pareidolia é perceber formas familiares em estímulos ambíguos, como rostos nas nuvens.',
        'aguarda_resposta': False})))
    monkeypatch.setattr(llm, '_pick_provider', lambda: provider)
    try:
        yield llm, provider, modulo
    finally:
        await llm.ollama.http_client.aclose()
        if llm.groq.client:
            await llm.groq.client.close()


async def test_curiosidade_usa_prompt_curto_com_historico_e_resposta_completa(modelo):
    llm, provider, modulo = modelo
    resultado = await llm.classificar_evento('SISTEMA_COMANDO_USUARIO', 'pc.chat', {'texto': 'O que era pareidolia?'},
        historico=['Ollie: Você reparou em um rosto na tomada?'], knowledge='Gosta de exemplos simples.')
    assert 'rostos nas nuvens' in resultado['mensagem_dinamica']
    assert resultado['execucao_direta'] == []
    provider.gerar.assert_awaited_once()
    prompt, system = provider.gerar.call_args.args
    assert 'rosto na tomada' in prompt and 'Gosta de exemplos simples' in prompt
    assert 'Ferramentas disponíveis no PC' not in system and len(system) < 2600
    assert provider.gerar.call_args.kwargs['max_tokens'] == 900
    modulo.context_builder.construir_contexto.assert_not_awaited()


@pytest.mark.parametrize('incompleta', [{'tipo_interacao': 'IGNORAR'}, {'mensagem_dinamica': 'Comando recebido.'},
    {'mensagem_dinamica': ''}])
async def test_outras_perguntas_tambem_recuperam_classificacao_sem_resposta(modelo, incompleta):
    llm, provider, _ = modelo
    provider.gerar.side_effect = [json.dumps(incompleta), json.dumps({'resposta': 'Júpiter é o maior planeta do Sistema Solar.'})]
    resultado = await llm.classificar_evento('SISTEMA_COMANDO_USUARIO', 'pc.chat', {'texto': 'Você sabe qual é o maior planeta do Sistema Solar?'})
    assert 'Júpiter' in resultado['mensagem_dinamica'] and resultado['execucao_direta'] == []
    assert provider.gerar.await_count == 2


async def test_recibo_no_cache_nao_impede_nova_resposta(modelo):
    llm, provider, modulo = modelo
    modulo.semantic_cache_service.buscar.return_value = json.dumps({'mensagem_dinamica': 'Comando recebido.'})
    provider.gerar.return_value = json.dumps({'mensagem_dinamica': 'Júpiter é o maior planeta do Sistema Solar.'})
    resultado = await llm.classificar_evento('SISTEMA_COMANDO_USUARIO', 'pc.chat', {'texto': 'Você sabe qual o maior planeta?'})
    assert 'Júpiter' in resultado['mensagem_dinamica']
    provider.gerar.assert_awaited_once()


async def test_limite_da_ia_nao_finge_trabalho_nem_repete_requisicao(modelo):
    llm, provider, modulo = modelo
    erro = RuntimeError('rate_limit_exceeded 429')
    provider.gerar.side_effect = erro
    resultado = await llm.classificar_evento('SISTEMA_COMANDO_USUARIO', 'pc.chat', {'texto': 'O que era pareidolia?'})
    assert 'limite de uso' in resultado['mensagem_dinamica'] and 'não consegui responder' in resultado['mensagem_dinamica']
    assert resultado['aguarda_resposta'] is False and not resultado['execucao_direta']
    provider.gerar.assert_awaited_once()
    modulo.semantic_cache_service.inserir.assert_not_awaited()


async def test_reparo_de_json_e_recibos_e_limitado_e_nao_cacheia_falha(modelo):
    llm, provider, modulo = modelo
    provider.gerar.side_effect = ['[]', '{"resposta":"Comando recebido"}']
    resultado = await llm.classificar_evento('SISTEMA_COMANDO_USUARIO', 'pc.chat', {'texto': 'O que é uma galáxia?'})
    assert provider.gerar.await_count == 2
    assert resultado['intencao_captada'] == 'FALLBACK_ERRO'
    assert 'Não consegui gerar uma resposta' in resultado['mensagem_dinamica']
    modulo.semantic_cache_service.inserir.assert_not_awaited()


@pytest.mark.parametrize('dispositivo', ['PC', 'MOBILE'])
@pytest.mark.parametrize('limite', [False, True])
async def test_pergunta_api_kernel_raciocinio_websocket_volta_a_origem(modelo, monkeypatch, dispositivo, limite):
    from core.kernel import KernelCognitivo
    from core.motor_atencao import PipelineAtencao
    from api.auth import AuthMiddleware
    from servicos.agenda import agenda
    from servicos.tarefas import tarefas
    import api.eventos as entrada
    import api.websocket as websocket
    import agentes.agente_reflexo as reflexo
    import agentes.agente_roteador_cognitivo as roteador
    import agentes.agente_raciocinio as raciocinio
    import agentes.agente_notificacoes as notificacoes
    llm, provider, _ = modelo
    if limite:
        provider.gerar.side_effect = RuntimeError('rate_limit_exceeded 429')
    kernel = KernelCognitivo()
    central = websocket.GerenciadorNotificacoes()
    pc, mobile = (SimpleNamespace(send_text=AsyncMock(), client_state=SimpleNamespace(value=1)),
                  SimpleNamespace(send_text=AsyncMock(), client_state=SimpleNamespace(value=1)))
    central.pc_master, central.mobile_client = pc, mobile
    monkeypatch.setattr(entrada, 'DEDUPLICATION_CACHE', OrderedDict())
    monkeypatch.setattr(entrada, 'pipeline_atencao', PipelineAtencao())
    monkeypatch.setattr(notificacoes, 'central_alertas', central)
    for modulo in (entrada, reflexo, roteador, raciocinio, notificacoes):
        monkeypatch.setattr(modulo, 'kernel', kernel)
    monkeypatch.setenv('OLLIE_API_TOKEN', 'token-curiosidade')
    monkeypatch.setattr(agenda, 'rascunho', AsyncMock(return_value=None))
    monkeypatch.setattr(tarefas, 'contexto', AsyncMock(return_value=None))
    monkeypatch.setattr(raciocinio.obsidian_service, 'listar_conhecimento_essencial', lambda _: '')
    brain = raciocinio.AgenteRaciocinio()
    brain.llm = llm
    brain._harvest_current_habits = AsyncMock(return_value=[])
    brain._registrar_log_cognitivo = lambda *args: None
    brain.memoria_trabalho = SimpleNamespace(atualizar_conversa=AsyncMock(), obter_contexto=AsyncMock(return_value=[]))
    kernel.registrar(lambda e: e.categoria == CategoriaEvento.SISTEMA_COMANDO_USUARIO and e.acao == TipoAcao.NORMAL, reflexo.AgenteReflexo().processar)
    kernel.registrar(lambda e: e.acao == TipoAcao.EVENTO_COMPLEXO, roteador.AgenteRoteadorCognitivo().processar)
    kernel.registrar(lambda e: e.acao == TipoAcao.INTENCAO_RACIOCINIO, brain.processar)
    kernel.registrar(lambda e: e.categoria == CategoriaEvento.INTENCAO_NOTIFICACAO, notificacoes.AgenteNotificacoes().processar)
    app = FastAPI(); app.add_middleware(AuthMiddleware); app.include_router(entrada.router)
    worker = asyncio.create_task(kernel.iniciar())
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://teste') as cliente:
            resposta = await cliente.post('/eventos', headers={'Authorization': 'Bearer token-curiosidade'}, json={
                'categoria': 'SISTEMA_COMANDO_USUARIO', 'pacote': 'pc.chat' if dispositivo == 'PC' else 'com.example.assistentecell.voice',
                'correlacao_id': 'curiosidade-integracao', 'payload': {'texto': 'O que era pareidolia?', 'canal': 'voz'}})
        assert resposta.status_code == 202
        assert resposta.json()['status'] == 'enfileirado'
        await asyncio.wait_for(kernel._fila.join(), timeout=4)
        destino, outro = (pc, mobile) if dispositivo == 'PC' else (mobile, pc)
        destino.send_text.assert_awaited_once()
        outro.send_text.assert_not_awaited()
        mensagem = json.loads(destino.send_text.call_args.args[0])
        assert mensagem['tipo_ws'] == 'CHAT_RESPONSE'
        assert ('limite de uso' if limite else 'Pareidolia') in mensagem['texto']
        assert mensagem['correlacao_id'] == 'curiosidade-integracao'
        assert mensagem['dispositivo_destino'] == dispositivo and mensagem['canal_origem'] == 'voz'
        assert mensagem['aguarda_resposta'] is False
        provider.gerar.assert_awaited_once()
        tarefas.contexto.assert_not_awaited()
        agenda.rascunho.assert_not_awaited()
    finally:
        worker.cancel(); await asyncio.gather(worker, return_exceptions=True)


@pytest.mark.parametrize('texto', [None, '', '   ', {'comando': 'recebido'}])
async def test_chat_vazio_nao_vira_confirmacao_falsa_de_sucesso(texto):
    from api.websocket import GerenciadorNotificacoes
    central = GerenciadorNotificacoes()
    central.pc_master = SimpleNamespace(send_text=AsyncMock(), client_state=SimpleNamespace(value=1))
    await central.enviar_alerta({'payload': {'tipo_ws': 'CHAT_RESPONSE', 'aguarda_resposta': True, 'texto': texto},
        'metadados': {'dispositivo_origem': 'PC'}})
    mensagem = json.loads(central.pc_master.send_text.call_args.args[0])
    assert 'Não recebi uma resposta válida' in mensagem['texto']
    assert mensagem['aguarda_resposta'] is False
