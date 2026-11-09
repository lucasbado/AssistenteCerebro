import json
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts.pc_command import executar
from servicos.arquivos_pc import executar_arquivo, validar_resultado_arquivo
from servicos.confirmacao_pc import ConfirmacoesPC
from servicos.foco_janelas import FocoJanelas, Janela
from servicos.ordens_pc import interpretar_ordem_pc
from servicos.pc_control_service import PcControlService


def test_ordem_composta_de_arquivo_com_destino_explicito():
    comando, parametro = interpretar_ordem_pc('Ache o PDF de teste em Downloads, abra no PC e me diga se abriu.')
    assert comando == 'abrir_arquivo'
    assert json.loads(parametro) == {'pasta': 'Downloads', 'extensao': '.pdf', 'nome': 'teste'}
    assert interpretar_ordem_pc('Não abra o arquivo teste.pdf') is None
    assert interpretar_ordem_pc('Procure o PDF de teste no Google') is None
    assert interpretar_ordem_pc('Abra YouTube no PC') is None


@pytest.mark.parametrize('verificada,estado', [(True, 'janela_confirmada'), (False, 'abertura_enviada')])
def test_abertura_distingue_arquivo_enviado_de_janela_verificada(tmp_path, verificada, estado):
    arquivo = tmp_path / 'teste.pdf'
    arquivo.touch()
    (tmp_path / 'teste.exe').touch()
    service = SimpleNamespace(abrir_documento_verificado=Mock(return_value=verificada))
    resultado = executar_arquivo('abrir_arquivo', {'pasta': 'Downloads', 'nome': 'teste'}, service, {'Downloads': tmp_path})
    assert resultado == {'arquivo': {'estado': estado, 'itens': ['Downloads/teste.pdf']}}
    service.abrir_documento_verificado.assert_called_once_with(arquivo)


def test_arquivo_ambiguo_e_caminho_fora_das_pastas_pessoais_nao_abrem(tmp_path):
    for nome in ('primeiro', 'segundo'):
        (tmp_path / nome).mkdir()
        (tmp_path / nome / 'teste.pdf').touch()
    service = SimpleNamespace(abrir_documento_verificado=Mock())
    pastas = {'Downloads': tmp_path}
    resultado = executar_arquivo('abrir_arquivo', {'pasta': 'Downloads', 'nome': 'teste.pdf'}, service, pastas)
    assert resultado['arquivo']['estado'] == 'ambiguo'
    assert resultado['arquivo']['itens'] == ['Downloads/primeiro/teste.pdf', 'Downloads/segundo/teste.pdf']
    for invalido in ('../teste.pdf', r'C:\Windows\teste.pdf', '/teste.pdf'):
        with pytest.raises(ValueError):
            executar_arquivo('abrir_arquivo', {'pasta': 'Downloads', 'nome': invalido}, service, pastas)
    service.abrir_documento_verificado.assert_not_called()


def test_resultado_arquivo_exige_contrato_e_rejeita_replay():
    confirmacoes = ConfirmacoesPC()
    assert confirmacoes.registrar('arquivo-1', 'abrir_arquivo')
    confirmacoes.atualizar('arquivo-1', 'concluido', {'primeiro_plano': True})
    assert confirmacoes.consultar('arquivo-1')['status'] == 'erro'
    valido = {'arquivo': {'estado': 'janela_confirmada', 'itens': ['Downloads/teste.pdf']}}
    assert validar_resultado_arquivo('abrir_arquivo', valido)
    assert confirmacoes.registrar('arquivo-2', 'abrir_arquivo')
    confirmacoes.atualizar('arquivo-2', 'concluido', valido)
    confirmacoes.atualizar('arquivo-2', 'erro')
    assert confirmacoes.consultar('arquivo-2')['resultado'] == valido
    assert confirmacoes.consultar('arquivo-2')['status'] == 'concluido'


def test_captura_grava_localmente_e_retorna_apenas_o_caminho_relativo(tmp_path):
    imagem = SimpleNamespace(save=lambda destino, format: destino.write(b'captura sintetica'))
    service = SimpleNamespace(capturar_tela=Mock(return_value=imagem))
    resultado = executar_arquivo('capturar_tela', '', service, {'Downloads': tmp_path})
    assert validar_resultado_arquivo('capturar_tela', resultado)
    assert resultado['arquivo']['estado'] == 'capturado'
    pasta, nome = resultado['arquivo']['itens'][0].split('/')
    assert pasta == 'Downloads'
    assert (tmp_path / nome).read_bytes() == b'captura sintetica'


def test_status_do_sistema_retorna_so_medicoes_validas():
    from servicos.comandos_pc import validar_status_pc

    sistema = {'cpu': 6, 'ram': 62.5, 'disco': 88}
    assert interpretar_ordem_pc('Como está o PC?') == ('system_status', '')
    assert validar_status_pc(executar('system_status', '', SimpleNamespace(status_sistema=lambda: sistema)))
    assert not validar_status_pc({'sistema': {**sistema, 'cpu': float('nan')}})


def test_janela_indicada_e_verificada_sem_focar_outra():
    sistema = SimpleNamespace(listar=Mock(return_value=[Janela(1, 'chrome.exe', 'Site'), Janela(2, 'notepad.exe', 'teste.txt')]),
                              estado=Mock(side_effect=[False, False, True]), agir=Mock())
    FocoJanelas(sistema, pausa=lambda _: None).controlar('janela_maximizar', 'notepad', Mock())
    sistema.agir.assert_called_once_with(2, 'janela_maximizar')


def test_documento_exige_janela_com_titulo_exato_ou_sufixo_de_aplicativo():
    antes = [Janela(1, 'chrome.exe', 'teste.pdf - Chrome')]
    sistema = SimpleNamespace(listar=Mock(return_value=antes + [Janela(2, 'msedge.exe', 'teste.pdf antigo - Edge')]))
    foco = FocoJanelas(sistema, pausa=lambda _: None)
    assert not foco.confirmar_documento({'teste.pdf', 'teste'}, antes, tentativas=1)
    sistema.listar.return_value = [Janela(1, 'chrome.exe', 'teste.pdf - Edge'), Janela(3, 'notepad.exe', ' teste.pdf - Bloco de notas')]
    assert foco.confirmar_documento({'teste.pdf', 'teste'}, antes, tentativas=1)


def test_reinicio_recusado_pelo_windows_sobe_erro(monkeypatch):
    run = Mock(side_effect=subprocess.CalledProcessError(1, ['shutdown.exe']))
    monkeypatch.setattr('servicos.pc_control_service.subprocess.run', run)
    with pytest.raises(subprocess.CalledProcessError):
        executar('reiniciar_pc', '', PcControlService())
    run.assert_called_once_with(['shutdown.exe', '/r', '/t', '60'], check=True)


def test_mouse_e_atalhos_do_relogio_passam_pelo_mesmo_executor():
    service = SimpleNamespace(mouse_move=Mock(), executar_macro=Mock())
    executar('mouse_move', '0,-12', service)
    executar('win_left', 'left', service)
    service.mouse_move.assert_called_once_with(0, -12)
    service.executar_macro.assert_called_once_with('win_left')
    with pytest.raises(ValueError):
        executar('mouse_move', '1,4000', service)
