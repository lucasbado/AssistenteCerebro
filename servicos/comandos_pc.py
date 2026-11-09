"""Contratos dos controles compartilhados pelo executor local e pelo Ollie Desk."""
from servicos.arquivos_pc import COMANDOS_ARQUIVOS, executar_arquivo
from servicos.foco_janelas import MAX_TITULO
from servicos.interface_pc import COMANDO_INTERFACE, COMANDOS_OBSERVACAO_PC
from servicos.ordens_pc import COMANDOS_JANELAS


MACROS_PC = {
    'alt_tab': ['alt', 'tab'], 'win_d': ['win', 'd'], 'print_screen': ['printscreen'],
    'task_mgr': ['ctrl', 'shift', 'esc'], 'alt_f4': ['alt', 'f4'], 'win_tab': ['win', 'tab'],
    'media_play_pause': ['playpause'], 'media_next': ['nexttrack'], 'media_prev': ['prevtrack'],
    'win_left': ['win', 'left'], 'win_right': ['win', 'right'], 'win_up': ['win', 'up'],
    'enter': ['enter'],
}
COMANDOS_MOUSE = {'mouse_move', 'mouse_click', 'mouse_scroll'}
COMANDOS_ENTRADA = COMANDOS_MOUSE | {'win_left', 'win_right', 'win_up', 'enter'}
COMANDOS_ENERGIA = {'bloquear_pc': 'bloquear_pc', 'dormir_pc': 'dormir_pc', 'suspender_pc': 'dormir_pc',
                    'hibernar_pc': 'hibernar_pc', 'desligar_pc': 'desligar_pc', 'reiniciar_pc': 'reiniciar_pc'}
COMANDOS_SPOTIFY = {'spotify_next': 'spotify_next', 'spotify_prev': 'spotify_prev',
                     'spotify_play_pause': 'spotify_pause', 'spotify_like': 'spotify_like'}
COMANDOS_COMPARTILHADOS = (COMANDOS_ARQUIVOS | COMANDOS_JANELAS | COMANDOS_OBSERVACAO_PC | MACROS_PC.keys() | COMANDOS_MOUSE
                           | COMANDOS_ENERGIA.keys() | COMANDOS_SPOTIFY.keys() | {'executar_macro', 'macro', 'system_status'})


def validar_status_pc(resultado):
    if not isinstance(resultado, dict) or set(resultado) != {'sistema'}:
        return False
    dados = resultado['sistema']
    return (isinstance(dados, dict) and set(dados) == {'cpu', 'ram', 'disco'}
            and all(type(valor) in {int, float} and 0 <= valor <= 100
                    for valor in dados.values()))


def _inteiro(valor, minimo, maximo):
    if isinstance(valor, bool) or not isinstance(valor, (int, str)):
        raise ValueError('Movimento do mouse inválido.')
    valor = int(valor)
    if not minimo <= valor <= maximo:
        raise ValueError('Movimento do mouse fora do limite.')
    return valor


def executar_compartilhado(comando, parametro, service):
    if comando in COMANDOS_ARQUIVOS:
        return executar_arquivo(comando, parametro, service)
    if comando == 'system_status':
        return {'sistema': service.status_sistema()}
    if comando in COMANDOS_OBSERVACAO_PC:
        if not isinstance(parametro, str) or len(parametro) > MAX_TITULO or comando == 'janela_ativa' and parametro:
            raise ValueError('Filtro de janelas inválido.')
        if comando == COMANDO_INTERFACE:
            return service.observar_interface(parametro)
        return service.observar_janelas(comando, parametro)
    if comando in COMANDOS_JANELAS:
        service.controlar_janela(comando, parametro)
    elif comando in COMANDOS_MOUSE:
        if comando == 'mouse_move':
            dx, dy = str(parametro).split(',', 1)
            service.mouse_move(_inteiro(dx, -3000, 3000), _inteiro(dy, -3000, 3000))
        elif comando == 'mouse_click':
            botao = str(parametro or 'left').lower()
            if botao not in {'left', 'right', 'middle'}:
                raise ValueError('Botão do mouse inválido.')
            service.mouse_click(botao)
        else:
            service.mouse_scroll(_inteiro(parametro, -60, 60))
    elif comando in MACROS_PC:
        service.executar_macro(comando)
    elif comando in {'executar_macro', 'macro'}:
        service.executar_macro(parametro)
    elif comando in COMANDOS_ENERGIA:
        getattr(service, COMANDOS_ENERGIA[comando])()
    elif comando in COMANDOS_SPOTIFY:
        service.inicializar()
        getattr(service, COMANDOS_SPOTIFY[comando])()
    else:
        raise ValueError(f'Comando não permitido: {comando}')
    return {'status': 'ok'}
