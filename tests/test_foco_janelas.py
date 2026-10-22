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
