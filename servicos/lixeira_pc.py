"""Envia um arquivo à Lixeira do Windows pelo Shell, com reciclagem explícita."""
import os
import time
from pathlib import Path

from servicos.arquivos_pc import _caminho_operacao, _resultado
from servicos.organizacao_pc import _identidade, _salvar, diario_da_pasta


def enviar_para_lixeira(caminho):
    if os.name != 'nt':
        raise ValueError('A Lixeira exige o executor Windows.')

    import pythoncom
    from win32com.shell import shell, shellcon

    pythoncom.CoInitialize()
    try:
        operacao = pythoncom.CoCreateInstance(shell.CLSID_FileOperation, None, pythoncom.CLSCTX_ALL,
                                              shell.IID_IFileOperation)
        reciclar = 0x00080000  # FOFX_RECYCLEONDELETE
        operacao.SetOperationFlags(reciclar | shellcon.FOF_SILENT | shellcon.FOF_NOERRORUI)
        item = shell.SHCreateItemFromParsingName(str(caminho), None, shell.IID_IShellItem)
        operacao.DeleteItem(item, None)
        resultado = operacao.PerformOperations()
        if resultado or operacao.GetAnyOperationsAborted() or os.path.lexists(caminho):
            raise OSError('O Windows não confirmou o envio para a Lixeira.')
    finally:
        pythoncom.CoUninitialize()


def _restaurar(caminho, identidade):
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    try:
        lixeira = win32com.client.Dispatch('Shell.Application').NameSpace(10)
        if lixeira is None:
            return False
        candidatos = []
        for item in lixeira.Items():
            if str(item.Name or '').casefold() not in {caminho.name.casefold(), caminho.stem.casefold()}:
                continue
            if Path(str(lixeira.GetDetailsOf(item, 1) or '')) != caminho.parent:
                continue
            try:
                if _identidade(Path(str(item.Path))) == identidade:
                    candidatos.append(item)
            except OSError:
                continue
        if len(candidatos) != 1:
            return False
        if os.path.lexists(caminho):
            raise FileExistsError(caminho)
        candidatos[0].InvokeVerb('undelete')
        for _ in range(30):
            if _identidade(caminho) == identidade:
                return True
            time.sleep(.1)
        return False
    finally:
        pythoncom.CoUninitialize()


def executar_lixeira(comando, pasta, rotulo, nome, diario_dir=None):
    with diario_da_pasta(pasta, rotulo, diario_dir) as (diario, estado):
        caminho = _caminho_operacao(pasta, nome)
        exibido = f'{rotulo}/{nome}'
        registros = estado.setdefault('lixeira', {})
        if comando == 'lixeira_arquivo':
            identidade = _identidade(caminho)
            if identidade is None:
                return _resultado('origem_ausente')
            anterior = registros.pop(nome.casefold(), None)
            registros[nome.casefold()] = identidade
            _salvar(diario, estado)
            try:
                if _identidade(caminho) != identidade:
                    raise ValueError('O arquivo mudou antes do envio à Lixeira.')
                enviar_para_lixeira(caminho)
            except Exception:
                if _identidade(caminho) == identidade:
                    registros.pop(nome.casefold())
                    if anterior is not None:
                        registros[nome.casefold()] = anterior
                    _salvar(diario, estado)
                raise
            if len(registros) > 100:
                registros.pop(next(iter(registros)))
                _salvar(diario, estado)
            return _resultado('na_lixeira', [exibido])

        identidade = registros.get(nome.casefold())
        if identidade is None:
            return _resultado('sem_item_lixeira')
        try:
            if os.path.lexists(caminho):
                return _resultado('destino_existe', [exibido])
            if not _restaurar(caminho, identidade):
                return _resultado('restauro_nao_confirmado')
        except FileExistsError:
            return _resultado('destino_existe', [exibido])
        registros.pop(nome.casefold())
        _salvar(diario, estado)
        return _resultado('restaurado', [exibido])
