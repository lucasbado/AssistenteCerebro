"""Consulta e acionamento de controles de uma janela via Windows UI Automation."""
import json
import time
from concurrent.futures import ThreadPoolExecutor

from servicos.controle_casa import normalizar
from servicos.foco_janelas import COMANDOS_OBSERVACAO_JANELAS, MAX_TITULO, _rotulo

COMANDO_INTERFACE = 'listar_controles'
COMANDO_ACIONAR_CONTROLE = 'acionar_controle'
COMANDOS_OBSERVACAO_PC = COMANDOS_OBSERVACAO_JANELAS | {COMANDO_INTERFACE}
COMANDOS_INTERFACE_EXPLICITOS = COMANDOS_OBSERVACAO_PC | {COMANDO_ACIONAR_CONTROLE}
MAX_CONTROLES = 10
MAX_ROTULO = 100
TIPOS_UIA = {
    'Button': 'botão', 'SplitButton': 'botão', 'Hyperlink': 'link', 'TabItem': 'aba',
    'MenuItem': 'menu', 'CheckBox': 'caixa de seleção', 'RadioButton': 'opção',
}
ESTADOS_SEM_LEITURA = {'sem_janela', 'ambigua', 'minimizada', 'mudou', 'indisponivel'}
ESTADOS_ACIONAMENTO = ESTADOS_SEM_LEITURA | {
    'sem_controle', 'controle_ambiguo', 'desabilitado', 'sem_padrao', 'ocupado',
    'aba_selecionada', 'aba_ja_selecionada', 'mudanca_observada', 'enviada_sem_confirmacao', 'envio_incerto',
}


def parametros_acionar_controle(parametro):
    dados = json.loads(parametro)
    if not isinstance(dados, dict) or set(dados) != {'tipo', 'nome', 'janela'}:
        raise ValueError('Indique o tipo e o nome do controle e o título da janela.')
    if dados['tipo'] not in ('botão', 'aba'):
        raise ValueError('Escolha um botão ou uma aba.')
    for campo, limite in (('nome', MAX_ROTULO), ('janela', MAX_TITULO)):
        valor = dados[campo]
        if not isinstance(valor, str) or not normalizar(valor) or valor != _rotulo(valor, limite):
            raise ValueError('Use nomes de controle e janela completos e curtos.')
    if normalizar(dados['janela']) in {'ativa', 'a janela ativa', 'janela ativa'}:
        raise ValueError('Diga o título da janela ou o nome do aplicativo.')
    return dados


def _cliente_uia():
    import comtypes.client

    uia = comtypes.client.GetModule('UIAutomationCore.dll')
    cliente = comtypes.client.CreateObject(uia.CUIAutomation8, interface=uia.IUIAutomation2)
    cliente.ConnectionTimeout = 2000
    cliente.TransactionTimeout = 2500
    return uia, cliente


def _consultar_controles(uia, cliente, raiz, alvo=None):
    tipos = {getattr(uia, f'UIA_{tipo}ControlTypeId'): nome for tipo, nome in TIPOS_UIA.items()
             if alvo is None or nome == alvo['tipo']}
    tipos_cond = cliente.CreateOrConditionFromArray([
        cliente.CreatePropertyCondition(uia.UIA_ControlTypePropertyId, tipo) for tipo in tipos])
    visivel = cliente.CreatePropertyCondition(uia.UIA_IsOffscreenPropertyId, False)
    nao_senha = cliente.CreatePropertyCondition(uia.UIA_IsPasswordPropertyId, False)
    condicao = cliente.CreateAndCondition(tipos_cond, cliente.CreateAndCondition(visivel, nao_senha))
    cache = cliente.CreateCacheRequest()
    cache.TreeScope = uia.TreeScope_Element
    if alvo is None:
        cache.AutomationElementMode = uia.AutomationElementMode_None
    else:
        nome = cliente.CreatePropertyConditionEx(uia.UIA_NamePropertyId, alvo['nome'],
                                                  uia.PropertyConditionFlags_IgnoreCase)
        condicao = cliente.CreateAndCondition(condicao, nome)
    for propriedade in (uia.UIA_ControlTypePropertyId, uia.UIA_NamePropertyId, uia.UIA_IsEnabledPropertyId):
        cache.AddProperty(propriedade)

    return tipos, raiz.FindAllBuildCache(uia.TreeScope_Descendants, condicao, cache)


def _rotulos_visiveis(uia, cliente, raiz):
    tipos, achados = _consultar_controles(uia, cliente, raiz)
    if not achados:
        return [], False
    itens = []
    limite = min(achados.Length, 400)
    for indice in range(limite):
        item = achados.GetElement(indice)
        nome = _rotulo(item.CachedName or '', MAX_ROTULO)
        if nome:
            itens.append({'tipo': tipos[item.CachedControlType], 'nome': nome, 'habilitado': bool(item.CachedIsEnabled)})
        if len(itens) > MAX_CONTROLES:
            return itens[:MAX_CONTROLES], True
    return itens, achados.Length > limite


def _ler_cache(hwnd):
    uia, cliente = _cliente_uia()
    return _rotulos_visiveis(uia, cliente, cliente.ElementFromHandle(hwnd))


def _rodar_uia(funcao, *args):
    import pythoncom

    pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
    try:
        from comtypes import COMError
        try:
            return funcao(*args)
        except COMError as erro:
            raise OSError('A janela não respondeu à UI Automation.') from erro
    finally:
        pythoncom.CoUninitialize()


def _executar_uia(funcao, *args):
    # A importação inicial do comtypes inicializa COM na thread chamadora.
    import comtypes.client
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(_rodar_uia, funcao, *args).result()


def observar_interface(foco, termo, leitor=None):
    estado, janela = foco.alvo_interface(termo)
    if janela is None:
        return {'estado': estado}
    try:
        itens, parcial = leitor(janela.id) if leitor else _executar_uia(_ler_cache, janela.id)
    except (ImportError, OSError):
        return {'estado': 'indisponivel'}
    if foco.alvo_interface(termo)[1] != janela:
        return {'estado': 'mudou'}
    titulo = _rotulo(janela.titulo, MAX_TITULO)
    if not titulo:
        return {'estado': 'sem_janela'}
    return {'estado': 'lida', 'janela': titulo, 'itens': itens, 'parcial': parcial}


def _acionar_windows(janela, alvo, janela_atual):
    from comtypes import COMError

    uia, cliente = _cliente_uia()
    raiz = cliente.ElementFromHandle(janela.id)
    tipos, achados = _consultar_controles(uia, cliente, raiz, alvo)
    if not achados or achados.Length == 0:
        return 'sem_controle'
    if achados.Length != 1:
        return 'controle_ambiguo'
    item = achados.GetElement(0)
    if not item.CurrentIsEnabled:
        return 'desabilitado'
    aba = alvo['tipo'] == 'aba'
    if aba:
        padrao = item.GetCurrentPattern(uia.UIA_SelectionItemPatternId)
        interface = uia.IUIAutomationSelectionItemPattern
    else:
        padrao = item.GetCurrentPattern(uia.UIA_InvokePatternId)
        interface = uia.IUIAutomationInvokePattern
    if not padrao:
        return 'sem_padrao'
    acao = padrao.QueryInterface(interface)
    antes = None if aba else _rotulos_visiveis(uia, cliente, raiz)
    if (item.CurrentIsOffscreen or item.CurrentIsPassword or item.CurrentControlType not in tipos
            or (item.CurrentName or '').casefold() != alvo['nome'].casefold() or janela_atual() != janela):
        return 'mudou'
    if not item.CurrentIsEnabled:
        return 'desabilitado'
    if aba and acao.CurrentIsSelected:
        return 'aba_ja_selecionada'
    try:
        acionar = acao.Select if aba else acao.Invoke
        acionar()
    except COMError:
        # A chamada pode ter chegado ao aplicativo antes da falha do provedor.
        return 'envio_incerto'
    try:
        for _ in range(3):
            time.sleep(.2)
            if aba:
                if acao.CurrentIsSelected:
                    return 'aba_selecionada'
            elif janela_atual() == janela and _rotulos_visiveis(uia, cliente, raiz) != antes:
                return 'mudanca_observada'
    except COMError:
        pass
    return 'enviada_sem_confirmacao'


def acionar_controle(foco, alvo):
    def resolver():
        return foco.alvo_interface(alvo['janela'], exato=True)

    estado, janela = resolver()
    if janela is None:
        return {'estado': estado}
    try:
        import win32event

        trava = win32event.CreateMutex(None, False, r'Local\Ollie.AcaoInterface')
        try:
            espera = win32event.WaitForSingleObject(trava, 0)
            if espera == win32event.WAIT_TIMEOUT:
                return {'estado': 'ocupado'}
            try:
                estado = _executar_uia(_acionar_windows, janela, alvo, lambda: resolver()[1])
            finally:
                win32event.ReleaseMutex(trava)
        finally:
            trava.Close()
    except (ImportError, OSError):
        estado = 'indisponivel'
    return {'estado': estado}


def validar_resultado_acionamento(resultado):
    return (isinstance(resultado, dict) and set(resultado) == {'estado'}
            and isinstance(resultado['estado'], str) and resultado['estado'] in ESTADOS_ACIONAMENTO)


def validar_resultado_interface(resultado):
    if not isinstance(resultado, dict):
        return False
    estado = resultado.get('estado')
    if estado != 'lida':
        return set(resultado) == {'estado'} and isinstance(estado, str) and estado in ESTADOS_SEM_LEITURA
    if set(resultado) != {'estado', 'janela', 'itens', 'parcial'}:
        return False
    janela, itens = resultado['janela'], resultado['itens']
    if (not isinstance(janela, str) or not 0 < len(janela) <= MAX_TITULO or janela != _rotulo(janela, MAX_TITULO)
            or type(resultado['parcial']) is not bool or not isinstance(itens, list) or len(itens) > MAX_CONTROLES):
        return False
    return all(isinstance(item, dict) and set(item) == {'tipo', 'nome', 'habilitado'}
               and item['tipo'] in TIPOS_UIA.values() and type(item['habilitado']) is bool
               and isinstance(item['nome'], str) and 0 < len(item['nome']) <= MAX_ROTULO
               and item['nome'] == _rotulo(item['nome'], MAX_ROTULO) for item in itens)
