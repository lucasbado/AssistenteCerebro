from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from servicos.respostas_acoes import resumir_resultados, nome_abertura


def resultado(parametro, status='concluido', **outros):
    return {'etapa': {'alvo': 'PC', 'comando': 'abrir_url', 'parametro': parametro}, 'status': status, **outros}


def test_resumo_agrupa_nomes_reais_sem_repetir_relatorio_de_foco():
    texto = resumir_resultados([resultado('https://www.youtube.com/', foco=True), resultado('https://www.hbomax.com/', foco=True)])
    assert texto == 'Pronto, abri o YouTube e o HBO Max no PC.'


def test_busca_decodifica_termo_sem_anunciar_que_leu_resultados():
    texto = resumir_resultados([resultado('https://www.youtube.com/results?search_query=ESP32+%2B+Home+Assistant')])
    assert 'busca por “ESP32 + Home Assistant” no YouTube' in texto
    assert 'encontrei' not in texto.lower() and 'li ' not in texto.lower()


@pytest.mark.parametrize('status', ['erro', 'sem_confirmacao', 'pc_offline'])
def test_falha_parcial_nao_agrupa_acao_falha_com_aberturas_confirmadas(status):
    texto = resumir_resultados([resultado('https://www.youtube.com/'), resultado('https://www.hbomax.com/', status)],
        interrupcao='Parei por aqui.')
    assert texto.startswith('Abri o YouTube no PC.')
    assert 'abrir o HBO Max' in texto and 'abri o YouTube e o HBO Max' not in texto
    assert texto.endswith('Parei por aqui.')


def test_envio_ao_mobile_nao_vira_confirmacao_de_abertura():
    etapa = {'alvo': 'MOBILE', 'comando': 'OPEN_APP', 'parametro': 'com.whatsapp'}
    texto = resumir_resultados([{'etapa': etapa, 'status': 'enviado'}])
    assert texto == 'Mandei abrir o WhatsApp no celular.'
    assert 'Abri' not in texto


def test_foco_negado_continua_visivel_sem_apagar_sucesso_de_abertura():
    texto = resumir_resultados([resultado('https://www.netflix.com/', foco=False)])
    assert texto == 'Abri a Netflix no PC, mas não consegui trazer a janela pra frente.'


def test_casa_sem_confirmacao_nao_inventa_estado_nem_menciona_celular():
    texto = resumir_resultados([{'etapa': {'alvo': 'CASA', 'comando': 'desligar'}, 'status': 'sem_confirmacao'}])
    assert 'confirmar o estado da luz' in texto and 'apagada' not in texto and 'celular' not in texto


def test_url_desconhecida_nao_expoe_query_credenciais_ou_inventa_marca():
    nome = nome_abertura({'comando': 'abrir_url', 'parametro': 'https://user:secret@example.com/private?token=123'})
    assert nome == 'o site example.com'


async def test_personalidade_chega_ao_modelo_sem_adicionar_chamada_de_reescrita(monkeypatch):
    import servicos.llm as module
    monkeypatch.setattr(module.context_builder, 'construir_contexto', AsyncMock(return_value={
        'global_summary': '', 'session_summary': '', 'fatos_relevantes': []}))
    monkeypatch.setattr(module.semantic_cache_service, 'buscar', AsyncMock(return_value=None))
    monkeypatch.setattr(module.semantic_cache_service, 'inserir', AsyncMock())
    llm = module.ServicoLLM()
    provider = SimpleNamespace(gerar=AsyncMock(return_value='{"mensagem_dinamica":"Deixei o YouTube aqui."}'))
    monkeypatch.setattr(llm, '_pick_provider', lambda: provider)
    await llm.classificar_evento('SISTEMA_COMANDO_USUARIO', 'pc.chat', {'texto': 'valeu, porra!'})
    provider.gerar.assert_awaited_once()
    system = provider.gerar.call_args.args[1]
    assert 'palavrão' in system and 'Não é obrigação' in system
    assert 'Não xingue o usuário' in system
    assert 'sem fazer personagem' in system


async def test_resposta_da_llm_preserva_marcas_e_tom_sem_minusculizar(monkeypatch):
    import agentes.agente_raciocinio as module
    from core.evento import EventoCanonico
    from core.tipos import CategoriaEvento, OrigemEvento, TipoAcao
    brain = module.AgenteRaciocinio()
    brain._harvest_current_habits = AsyncMock(return_value=[])
    brain._registrar_log_cognitivo = lambda *args: None
    brain.memoria_trabalho = SimpleNamespace(atualizar_conversa=AsyncMock(), obter_contexto=AsyncMock(return_value=[]))
    brain.llm = SimpleNamespace(classificar_evento=AsyncMock(return_value={
        'tipo_interacao': 'NOTIFICAR', 'mensagem_dinamica': 'Boa, YouTube e HBO Max ficam no PC. WhatsApp no celular.'}))
    monkeypatch.setattr(module.obsidian_service, 'listar_conhecimento_essencial', lambda _: '')
    publish = AsyncMock()
    monkeypatch.setattr(module.kernel, 'publicar', publish)
    await brain.processar(EventoCanonico(categoria=CategoriaEvento.SISTEMA_COMANDO_USUARIO,
        acao=TipoAcao.INTENCAO_RACIOCINIO, origem=OrigemEvento.USUARIO, pacote='pc.chat', payload={'texto': 'Valeu pela ajuda'}))
    publish.assert_awaited_once()
    assert publish.call_args.args[0].payload['texto'] == 'Boa, YouTube e HBO Max ficam no PC. WhatsApp no celular.'
