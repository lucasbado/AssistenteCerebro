from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from servicos.foco_janelas import FocoJanelas, Janela


def test_navegador_correto_prevalece_sobre_webview_e_outro_browser():
    antes = [Janela(1, 'chrome.exe', 'Página anterior')]
    janelas = [Janela(3, 'msedgewebview2.exe', 'Ollie'), Janela(2, 'firefox.exe', 'Outro navegador'),
               Janela(1, 'chrome.exe', 'Busca solicitada')]
    sistema = SimpleNamespace(listar=Mock(return_value=janelas), primeiro_plano=Mock(side_effect=[3, 1]), ativar=Mock())
    foco = FocoJanelas(sistema, pausa=lambda _: None)
    assert foco.trazer(processos={'chrome.exe'}, antes=antes)
    sistema.ativar.assert_called_once_with(1)


def test_janela_que_nasce_depois_do_lancamento_e_detectada_sem_reabrir_url():
    sistema = SimpleNamespace(listar=Mock(side_effect=[[], [Janela(9, 'chrome.exe', 'Site')]]),
        primeiro_plano=Mock(side_effect=[2, 9]), ativar=Mock())
    assert FocoJanelas(sistema, pausa=lambda _: None).trazer(processos={'chrome.exe'}, tentativas=2)
    sistema.ativar.assert_called_once_with(9)


def test_bloqueio_do_windows_nao_e_relatorio_de_sucesso():
    sistema = SimpleNamespace(listar=Mock(return_value=[Janela(9, 'chrome.exe', 'Site')]),
        primeiro_plano=Mock(return_value=2), ativar=Mock(side_effect=OSError('Foco negado')))
    assert not FocoJanelas(sistema, pausa=lambda _: None).trazer(processos={'chrome.exe'}, tentativas=2)
    assert sistema.ativar.call_count == 2


def test_sem_browser_padrao_nao_foca_um_navegador_inalterado():
    janelas = [Janela(1, 'firefox.exe', 'Outra tarefa')]
    sistema = SimpleNamespace(listar=Mock(return_value=janelas), primeiro_plano=Mock(return_value=2), ativar=Mock())
    assert not FocoJanelas(sistema, pausa=lambda _: None).trazer(processos={'firefox.exe'}, antes=janelas,
        somente_alteradas=True, tentativas=2)
    sistema.ativar.assert_not_called()


@pytest.mark.parametrize('focado', [True, False])
def test_abertura_url_registra_foco_e_abre_uma_aba_uma_vez(monkeypatch, focado):
    import servicos.pc_control_service as module
    monkeypatch.setattr(module.webbrowser, 'open', Mock(return_value=True))
    service = module.PcControlService()
    service.foco = SimpleNamespace(capturar=Mock(return_value=[]), trazer=Mock(return_value=focado))
    resultado = service.abrir_url('https://example.com/Video/ABC')
    assert resultado == {'status': 'ok', 'aberto': True, 'primeiro_plano': focado}
    module.webbrowser.open.assert_called_once_with('https://example.com/Video/ABC', new=2, autoraise=True)


def test_ponte_de_busca_chega_ao_navegador_com_consulta_codificada():
    from scripts.pc_command import executar
    service = SimpleNamespace(abrir_url=Mock(return_value={'status': 'ok', 'primeiro_plano': True}))
    assert executar('pesquisa_google', 'C++ e ESP32', service)['primeiro_plano'] is True
    service.abrir_url.assert_called_once_with('https://www.google.com/search?q=C%2B%2B+e+ESP32')


def test_observacao_filtra_por_aplicativo_ou_titulo_e_limita_a_lista():
    from servicos.foco_janelas import validar_observacao_janelas

    janelas = [Janela(i, 'code.exe', f'Edição {i}\n– VS Code') for i in range(10)]
    sistema = SimpleNamespace(observar=Mock(return_value=[*janelas, Janela(11, 'explorer.exe', 'Downloads')]))
    foco = FocoJanelas(sistema)
    resultado = foco.observar('listar_janelas', 'VS Code')
    assert resultado['total'] == 10
    assert len(resultado['janelas']) == 8
    assert resultado['janelas'][0] == {'titulo': 'Edição 0 – VS Code', 'processo': 'code.exe'}
    assert validar_observacao_janelas('listar_janelas', resultado)
    assert not validar_observacao_janelas('janela_ativa', resultado)
    assert foco.observar('listar_janelas', 'edicao 2')['total'] == 1
    assert foco.observar('listar_janelas', 'discord') == {'janelas': [], 'total': 0}


@pytest.mark.parametrize(('frase', 'ordem'), [
    ('Qual é a janela ativa no PC?', ('janela_ativa', '')),
    ('Qual janela está em primeiro plano?', ('janela_ativa', '')),
    ('Quais janelas estão abertas no PC?', ('listar_janelas', '')),
    ('Quais janelas do VS Code estão abertas no PC?', ('listar_janelas', 'vs code')),
    ('O aplicativo Chrome está aberto no PC?', ('listar_janelas', 'chrome')),
    ('O Chrome está aberto no PC?', ('listar_janelas', 'chrome')),
    ('O Chrome está aberto?', None),
    ('Mostre a lista de compras', None),
])
def test_pedidos_de_observacao_de_janelas(frase, ordem):
    from servicos.ordens_pc import interpretar_ordem_pc

    assert interpretar_ordem_pc(frase) == ordem


def test_interface_prefere_nome_do_app_e_recusa_observacao_se_a_janela_mudar():
    from servicos.interface_pc import observar_interface

    janela = Janela(12, 'ollie-master-next.exe', 'Ollie · Central do PC')
    outra = Janela(13, 'opera.exe', 'Ollie — Render')
    sistema = SimpleNamespace(observar=Mock(side_effect=[[outra, janela], [outra]]),
                              estado=Mock(return_value=False))
    leitor = Mock(return_value=([{'tipo': 'botão', 'nome': 'Conversa', 'habilitado': True}], False))
    assert observar_interface(FocoJanelas(sistema), 'Ollie', leitor) == {'estado': 'mudou'}
    leitor.assert_called_once_with(12)


def test_interface_nao_le_janela_minimizada_ou_alvo_ambiguo():
    from servicos.interface_pc import observar_interface

    janelas = [Janela(1, 'code.exe', 'Projeto A'), Janela(2, 'code.exe', 'Projeto B')]
    sistema = SimpleNamespace(observar=Mock(return_value=janelas), estado=Mock(return_value=True))
    leitor = Mock()
    assert observar_interface(FocoJanelas(sistema), 'VS Code', leitor) == {'estado': 'ambigua'}
    assert observar_interface(FocoJanelas(sistema), 'Projeto A', leitor) == {'estado': 'minimizada'}
    leitor.assert_not_called()


@pytest.mark.parametrize(('frase', 'ordem'), [
    ('Liste os controles da janela ativa no PC.', ('listar_controles', '')),
    ('Mostre os elementos da interface do Explorador de Arquivos no PC.', ('listar_controles', 'Explorador de Arquivos')),
    ('Liste os controles da janela do “Projeto A”.', ('listar_controles', 'Projeto A')),
    ('Mostre os elementos químicos', None),
])
def test_pedido_explicito_de_interface(frase, ordem):
    from servicos.ordens_pc import interpretar_ordem_pc

    assert interpretar_ordem_pc(frase) == ordem
