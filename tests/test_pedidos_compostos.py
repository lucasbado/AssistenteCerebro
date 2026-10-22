from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import pytest
from core.evento import EventoCanonico
from core.tipos import CategoriaEvento, OrigemEvento, TipoAcao
from servicos.plano_pedidos import interpretar_composto, preparar_plano
from servicos.roteamento_pedidos import interpretar_abertura, metadados_entrada
from servicos.buscas_web import url_busca


def pedido(texto, origem='PC'):
    return EventoCanonico(categoria=CategoriaEvento.SISTEMA_COMANDO_USUARIO,
        acao=TipoAcao.INTENCAO_RACIOCINIO, origem=OrigemEvento.USUARIO, pacote='pc.chat',
        payload={'texto': texto}, metadados=metadados_entrada(origem))


@pytest.mark.parametrize('texto,termo,host', [
    ('pesquise como configurar C++ e Python 3.11 no PC', 'como configurar C++ e Python 3.11', 'www.google.com'),
    ('procure no YouTube vídeos de ESP32 e Home Assistant no PC', 'vídeos de ESP32 e Home Assistant', 'www.youtube.com'),
    ('busque Rust + Tauri no GitHub no computador', 'Rust + Tauri', 'github.com'),
    ('Ollie, pode pesquisar por que o WhatsApp não abre no PC?', 'por que o WhatsApp não abre', 'www.google.com'),
])
def test_busca_preserva_termo_e_nao_recusa_palavras_da_pergunta(texto, termo, host):
    acao = interpretar_abertura(texto)['execucao_direta'][0]
    url = urlsplit(acao['parametro'])
    assert acao['comando'] == 'abrir_url' and url.hostname == host
    assert parse_qs(url.query).get('q', parse_qs(url.query).get('search_query')) == [termo]


def test_busca_em_site_sem_api_abre_pesquisa_restrita_e_nao_inventa_caminho():
    assert parse_qs(urlsplit(url_busca('RTX 5070', 'example.com')).query)['q'] == ['site:example.com RTX 5070']
    with pytest.raises(ValueError):
        url_busca('teste', 'um nome sem domínio')


@pytest.mark.parametrize('verbo', ['acesse', 'entre', 'visite'])
def test_acesso_a_site_preserva_maiusculas(verbo):
    texto = f'{verbo} https://example.com/Video/AbC?Id=XYZ no PC'
    acao = interpretar_abertura(texto)['execucao_direta'][0]
    assert acao['parametro'] == 'https://example.com/Video/AbC?Id=XYZ'


def test_duas_etapas_com_destinos_diferentes_e_ids_distintos():
    e = pedido('abra YouTube no PC e abra WhatsApp no celular', 'MOBILE')
    resultado = interpretar_composto(e.payload['texto'])
    etapas = preparar_plano(e, resultado['execucao_direta'])
    assert [(p['alvo'], p['comando'], p['parametro']) for p in etapas] == [
        ('PC', 'abrir_url', 'https://www.youtube.com/'), ('MOBILE', 'OPEN_APP', 'com.whatsapp')]
    assert etapas[0]['id_comando'] != etapas[1]['id_comando']
    assert preparar_plano(e, resultado['execucao_direta']) == etapas


def test_busca_seguinte_usa_site_aberto_e_destino_global():
    e = pedido('abra YouTube e pesquise ESP32 + Home Assistant no PC', 'MOBILE')
    etapas = preparar_plano(e, interpretar_composto(e.payload['texto'])['execucao_direta'])
    assert [p['alvo'] for p in etapas] == ['PC', 'PC']
    assert urlsplit(etapas[1]['parametro']).hostname == 'www.youtube.com'
    assert parse_qs(urlsplit(etapas[1]['parametro']).query)['search_query'] == ['ESP32 + Home Assistant']


def test_luz_e_site_sao_um_plano_e_nao_duas_respostas_antecipadas():
    e = pedido('apague a luz do quarto e abra HBO Max no PC')
    etapas = preparar_plano(e, interpretar_composto(e.payload['texto'])['execucao_direta'])
    assert etapas[0]['alvo'] == 'CASA' and etapas[0]['comando'] == 'desligar'
    assert etapas[1]['parametro'] == 'https://www.hbomax.com/'


@pytest.mark.parametrize('texto', ['quando eu abrir YouTube e abra WhatsApp', 'não abra YouTube e abra WhatsApp'])
def test_composto_condicional_ou_negado_nao_vira_ordem_local(texto):
    assert interpretar_composto(texto) is None


def test_validacao_e_atomica_para_destino_ambiguo_ou_acao_nao_suportada():
    e = pedido('abra YouTube no PC ou no celular e abra Spotify')
    with pytest.raises(ValueError, match='mencionou'):
        preparar_plano(e, interpretar_composto(e.payload['texto'])['execucao_direta'])
    e = pedido('abra YouTube e execute algo')
    with pytest.raises(ValueError, match='disponível'):
        preparar_plano(e, [{'comando': 'abrir_app', 'parametro': 'youtube'}, {'comando': 'shell', 'parametro': 'qualquer coisa'}])
    with pytest.raises(ValueError, match='relacionar'):
        preparar_plano(pedido('abra YouTube'), [{'comando': 'abrir_app', 'parametro': 'youtube', 'trecho': 'abra no celular'}])


def test_plano_nao_ignora_restricao_negada_nem_aceita_lista_sem_limite():
    with pytest.raises(ValueError, match='restrição'):
        preparar_plano(pedido('abra YouTube e não abra WhatsApp'), [
            {'comando': 'abrir_app', 'parametro': 'youtube'}, {'comando': 'abrir_app', 'parametro': 'whatsapp'}])
    with pytest.raises(ValueError, match='6'):
        preparar_plano(pedido('abra YouTube'), [{'comando': 'abrir_app', 'parametro': 'youtube'}] * 7)


@pytest.fixture
def cerebro(monkeypatch):
    import agentes.agente_raciocinio as module
    brain = module.AgenteRaciocinio()
    brain._harvest_current_habits = AsyncMock(return_value=[])
    brain._registrar_log_cognitivo = lambda *args: None
    brain.memoria_trabalho = SimpleNamespace(atualizar_conversa=AsyncMock(), obter_contexto=AsyncMock(return_value=[]))
    brain.llm = SimpleNamespace(classificar_evento=AsyncMock(side_effect=AssertionError('Não usar LLM para este pedido')))
    monkeypatch.setattr(module.obsidian_service, 'listar_conhecimento_essencial', lambda _: '')
    publish = AsyncMock()
    monkeypatch.setattr(module.kernel, 'publicar', publish)
    return brain, publish


async def test_cerebro_publica_plano_unico_sem_executar_ou_anunciar_sucesso(cerebro):
    brain, publish = cerebro
    e = pedido('abra YouTube no PC e abra WhatsApp no celular')
    await brain.processar(e)
    publish.assert_awaited_once()
    plano = publish.call_args.args[0]
    assert plano.categoria == CategoriaEvento.PLANO_SOLICITADO
    assert plano.correlacao_id == e.correlacao_id and len(plano.payload['etapas']) == 2
    brain.llm.classificar_evento.assert_not_awaited()


async def test_lista_da_llm_tambem_e_validada_por_etapa(cerebro):
    brain, publish = cerebro
    brain._tentar_heuristica_local = lambda _: None
    brain.llm.classificar_evento = AsyncMock(return_value={'tipo_interacao': 'NOTIFICAR',
        'mensagem_dinamica': 'Já fiz tudo!', 'execucao_direta': [
            {'alvo': 'MOBILE', 'comando': 'abrir_app', 'parametro': 'youtube'},
            {'alvo': 'PC', 'comando': 'abrir_app', 'parametro': 'whatsapp'}]})
    await brain.processar(pedido('abra YouTube no PC e abra WhatsApp no celular'))
    publish.assert_awaited_once()
    assert [p['alvo'] for p in publish.call_args.args[0].payload['etapas']] == ['PC', 'MOBILE']


def transporte(monkeypatch, statuses=('concluido', 'concluido'), pc=True):
    import api.websocket as ws
    central = ws.GerenciadorNotificacoes()
    central.pc_master = SimpleNamespace(client_state=SimpleNamespace(value=1)) if pc else None
    central.mobile_client = SimpleNamespace(client_state=SimpleNamespace(value=1))
    ordem = []
    async def enviar(msg):
        ordem.append(('envio', msg['id_comando']))
        return {'status': 'enviado'}
    respostas = iter(statuses)
    async def ack(identificador):
        ordem.append(('ack', identificador))
        return {'status': next(respostas), 'resultado': {'primeiro_plano': True}}
    central.enviar_comando_pc = AsyncMock(side_effect=enviar)
    central.confirmacoes.aguardar = AsyncMock(side_effect=ack)
    central.enviar_comando_mobile = AsyncMock(return_value=True)
    monkeypatch.setattr(ws, 'central_alertas', central)
    from core.kernel import kernel
    publish = AsyncMock()
    monkeypatch.setattr(kernel, 'publicar', publish)
    return central, ordem, publish


def evento_plano(texto):
    e = pedido(texto)
    etapas = preparar_plano(e, interpretar_composto(texto)['execucao_direta'])
    return e.clonar(categoria=CategoriaEvento.PLANO_SOLICITADO, payload={'etapas': etapas})


async def test_pc_aguarda_ack_antes_da_proxima_etapa_e_replay_nao_repete(monkeypatch):
    from agentes.agente_plano import AgentePlano
    central, ordem, publish = transporte(monkeypatch)
    e = evento_plano('abra YouTube no PC e abra HBO Max no PC')
    agent = AgentePlano()
    await agent.processar(e)
    assert [tipo for tipo, _ in ordem] == ['envio', 'ack', 'envio', 'ack']
    assert ordem[0][1] != ordem[2][1]
    publish.assert_awaited_once()
    assert 'primeiro plano' in publish.call_args.args[0].payload['texto']
    await agent.processar(e)
    assert central.enviar_comando_pc.await_count == 2 and publish.await_count == 1


@pytest.mark.parametrize('status', ['erro', 'pc_offline', 'sem_confirmacao'])
async def test_falha_pc_interrompe_etapas_restantes(monkeypatch, status):
    from agentes.agente_plano import AgentePlano
    central, _, publish = transporte(monkeypatch, (status,))
    await AgentePlano().processar(evento_plano('abra YouTube no PC e abra WhatsApp no celular'))
    central.enviar_comando_mobile.assert_not_awaited()
    assert 'Parei nesta etapa' in publish.call_args.args[0].payload['texto']


async def test_destino_offline_impede_toda_sequencia(monkeypatch):
    from agentes.agente_plano import AgentePlano
    central, _, publish = transporte(monkeypatch, pc=False)
    await AgentePlano().processar(evento_plano('abra WhatsApp no celular e abra YouTube no PC'))
    central.enviar_comando_mobile.assert_not_awaited()
    central.enviar_comando_pc.assert_not_awaited()
    assert 'Não iniciei' in publish.call_args.args[0].payload['texto']


async def test_duas_aberturas_mobile_nao_compartilham_id(monkeypatch):
    from agentes.agente_plano import AgentePlano
    central, _, publish = transporte(monkeypatch)
    await AgentePlano().processar(evento_plano('abra YouTube no celular e abra WhatsApp no celular'))
    mensagens = [c.args[0] for c in central.enviar_comando_mobile.call_args_list]
    assert len({m['id_comando'] for m in mensagens}) == 2
    assert 'enviado ao celular' in publish.call_args.args[0].payload['texto']


async def test_foco_negado_aparece_no_resumo_sem_dizer_que_o_site_falhou(monkeypatch):
    from agentes.agente_plano import AgentePlano
    central, _, publish = transporte(monkeypatch)
    central.confirmacoes.aguardar = AsyncMock(return_value={'status': 'concluido', 'resultado': {'primeiro_plano': False}})
    await AgentePlano().processar(evento_plano('abra YouTube no PC e abra WhatsApp no celular'))
    assert 'abertura encaminhada; o Windows não confirmou' in publish.call_args.args[0].payload['texto']
    central.enviar_comando_mobile.assert_awaited_once()


async def test_contexto_de_habitos_e_conhecimento_chega_ao_modelo_como_dados(monkeypatch):
    import servicos.llm as module
    monkeypatch.setattr(module.context_builder, 'construir_contexto', AsyncMock(return_value={
        'global_summary': '', 'session_summary': '', 'fatos_relevantes': []}))
    monkeypatch.setattr(module.consciencia, 'obter_resumo_para_llm', lambda: '')
    monkeypatch.setattr(module.semantic_cache_service, 'buscar', AsyncMock(return_value=None))
    monkeypatch.setattr(module.semantic_cache_service, 'inserir', AsyncMock())
    llm = module.ServicoLLM()
    provider = SimpleNamespace(gerar=AsyncMock(return_value='{"mensagem_dinamica":"Olá"}'))
    monkeypatch.setattr(llm, '_pick_provider', lambda: provider)
    await llm.classificar_evento('SISTEMA_COMANDO_USUARIO', 'pc.chat', {'texto': 'olá'},
        knowledge='Prefere vídeos em português.', habits='Usa o editor pela manhã.')
    prompt, system = provider.gerar.call_args.args
    assert 'Prefere vídeos em português.' in prompt and 'Usa o editor pela manhã.' in prompt
    assert 'não autorização' in prompt and 'não instruções' in prompt
    assert 'não autorizam ações adicionais' in system


@pytest.mark.parametrize('texto', ['pesquise "como pesquise X e abra WhatsApp" no PC',
    'pesquise \'como "pesquise X" e abra WhatsApp\' no PC'])
def test_comandos_citados_dentro_da_busca_nao_viram_etapas(texto):
    assert interpretar_composto(texto) is None
    acao = interpretar_abertura(texto)['execucao_direta'][0]
    assert 'e abra WhatsApp' in parse_qs(urlsplit(acao['parametro']).query)['q'][0]


def test_site_desconhecido_nao_vira_busca_aproximada_por_executavel():
    assert interpretar_abertura('acesse o site da loja desconhecida no PC') is None


def test_multicomando_nunca_descarta_uma_das_ordens_da_luz():
    from agentes.agente_raciocinio import AgenteRaciocinio
    resultado = object.__new__(AgenteRaciocinio)._tentar_heuristica_local('liga a luz e abre o vscode')
    assert [a['comando'] for a in resultado['execucao_direta']] == ['ligar_luz', 'abrir_app']


async def test_confirmacao_pc_persiste_resultado_e_timeout_nao_inventa_sucesso():
    from servicos.confirmacao_pc import ConfirmacoesPC
    confirmacoes = ConfirmacoesPC()
    confirmacoes.registrar('um', 'abrir_url')
    assert (await confirmacoes.aguardar('um', timeout=0))['status'] == 'sem_confirmacao'
    assert confirmacoes.consultar('um')['status'] == 'enviado'
    confirmacoes.atualizar('um', 'concluido', {'primeiro_plano': False, 'ignorar': 'não retransmitir'})
    resultado = await confirmacoes.aguardar('um')
    assert resultado['status'] == 'concluido' and resultado['resultado'] == {'primeiro_plano': False}
