"""Leitura de rótulos de controles da janela solicitada via Windows UI Automation."""
from concurrent.futures import ThreadPoolExecutor

from servicos.foco_janelas import COMANDOS_OBSERVACAO_JANELAS, MAX_TITULO, _rotulo

COMANDO_INTERFACE = 'listar_controles'
COMANDOS_OBSERVACAO_PC = COMANDOS_OBSERVACAO_JANELAS | {COMANDO_INTERFACE}
MAX_CONTROLES = 10
MAX_ROTULO = 100
TIPOS_UIA = {
    'Button': 'botão', 'SplitButton': 'botão', 'Hyperlink': 'link', 'TabItem': 'aba',
    'MenuItem': 'menu', 'CheckBox': 'caixa de seleção', 'RadioButton': 'opção',
}
ESTADOS_SEM_LEITURA = {'sem_janela', 'ambigua', 'minimizada', 'mudou', 'indisponivel'}


def _ler_cache(hwnd):
    import comtypes.client

    uia = comtypes.client.GetModule('UIAutomationCore.dll')
    cliente = comtypes.client.CreateObject(uia.CUIAutomation8, interface=uia.IUIAutomation2)
    cliente.ConnectionTimeout = 2000
    cliente.TransactionTimeout = 2500
    raiz = cliente.ElementFromHandle(hwnd)
    tipos = {getattr(uia, f'UIA_{tipo}ControlTypeId'): nome for tipo, nome in TIPOS_UIA.items()}
    tipos_cond = cliente.CreateOrConditionFromArray([
        cliente.CreatePropertyCondition(uia.UIA_ControlTypePropertyId, tipo) for tipo in tipos])
    visivel = cliente.CreatePropertyCondition(uia.UIA_IsOffscreenPropertyId, False)
    nao_senha = cliente.CreatePropertyCondition(uia.UIA_IsPasswordPropertyId, False)
    condicao = cliente.CreateAndCondition(tipos_cond, cliente.CreateAndCondition(visivel, nao_senha))
    cache = cliente.CreateCacheRequest()
    cache.TreeScope = uia.TreeScope_Element
    cache.AutomationElementMode = uia.AutomationElementMode_None
    for propriedade in (uia.UIA_ControlTypePropertyId, uia.UIA_NamePropertyId, uia.UIA_IsEnabledPropertyId):
        cache.AddProperty(propriedade)

    achados = raiz.FindAllBuildCache(uia.TreeScope_Descendants, condicao, cache)
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


def _ler_windows(hwnd):
    import pythoncom

    pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
    try:
        from comtypes import COMError
        try:
            return _ler_cache(hwnd)
        except COMError as erro:
            raise OSError('A janela não respondeu à UI Automation.') from erro
    finally:
        pythoncom.CoUninitialize()


def observar_interface(foco, termo, leitor=None):
    estado, janela = foco.alvo_interface(termo)
    if janela is None:
        return {'estado': estado}
    try:
        if leitor is None:
            # A importação inicial do comtypes inicializa COM na thread chamadora.
            import comtypes.client
            leitor = _ler_windows
        # As chamadas de UI Automation rodam numa thread MTA separada.
        with ThreadPoolExecutor(max_workers=1) as executor:
            itens, parcial = executor.submit(leitor, janela.id).result()
    except (ImportError, OSError):
        return {'estado': 'indisponivel'}
    if foco.alvo_interface(termo)[1] != janela:
        return {'estado': 'mudou'}
    titulo = _rotulo(janela.titulo, MAX_TITULO)
    if not titulo:
        return {'estado': 'sem_janela'}
    return {'estado': 'lida', 'janela': titulo, 'itens': itens, 'parcial': parcial}


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
