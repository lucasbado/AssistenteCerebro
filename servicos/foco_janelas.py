"""Observação e foco de janelas locais do Windows."""
import os
import re
import time
from dataclasses import dataclass
from servicos.controle_casa import normalizar

BROWSERS = {'chrome.exe', 'msedge.exe', 'firefox.exe', 'opera.exe', 'brave.exe', 'vivaldi.exe', 'zen.exe'}
COMANDOS_OBSERVACAO_JANELAS = frozenset({'janela_ativa', 'listar_janelas'})
MAX_JANELAS = 8
MAX_TITULO = 140
MAX_PROCESSO = 80
CLASSES_SHELL = {'Progman', 'WorkerW', 'Shell_TrayWnd', 'Shell_SecondaryTrayWnd'}
PROCESSOS_APLICATIVOS = {
    'bloco de notas': 'notepad.exe', 'explorador de arquivos': 'explorer.exe',
    'vs code': 'code.exe', 'visual studio code': 'code.exe', 'vscode': 'code.exe',
    'android studio': 'studio64.exe', 'android_studio': 'studio64.exe',
    'ollie': 'ollie-master-next.exe',
}


@dataclass(frozen=True)
class Janela:
    id: int
    processo: str
    titulo: str


def navegador_padrao():
    if os.name != 'nt':
        return set()
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice') as key:
            progid = winreg.QueryValueEx(key, 'ProgId')[0]
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, progid + r'\shell\open\command') as key:
            comando = winreg.QueryValueEx(key, '')[0]
        executable = re.match(r'\s*(?:"([^"]+\.exe)"|([^"\s]+\.exe))', comando, re.I)
        if executable:
            nome = os.path.basename(executable[1] or executable[2]).lower()
            if nome == 'launcher.exe' and 'opera' in comando.lower():
                nome = 'opera.exe'
            return {nome}
    except OSError:
        pass
    return set()


def _combina(janela, termo):
    processo = janela.processo.casefold()
    return (processo == PROCESSOS_APLICATIVOS.get(termo)
            or termo in {processo, processo.removesuffix('.exe')}
            or re.search(r'\b' + re.escape(termo) + r'\b', normalizar(janela.titulo)))


def _rotulo(texto, limite):
    texto = ' '.join(''.join(c if c.isprintable() else ' ' for c in texto).split())
    return texto if len(texto) <= limite else texto[:limite - 1] + '…'


def validar_observacao_janelas(comando, resultado):
    if not isinstance(resultado, dict) or set(resultado) != {'janelas', 'total'}:
        return False
    janelas, total = resultado['janelas'], resultado['total']
    limite = 1 if comando == 'janela_ativa' else MAX_JANELAS
    if (not isinstance(janelas, list) or type(total) is not int or not 0 <= total <= 65535
            or len(janelas) != min(total, limite) or comando == 'janela_ativa' and total > 1):
        return False
    return all(isinstance(item, dict) and set(item) == {'titulo', 'processo'}
               and all(isinstance(item[chave], str) and 0 < len(item[chave]) <= tamanho
                       and _rotulo(item[chave], tamanho) == item[chave]
                       for chave, tamanho in (('titulo', MAX_TITULO), ('processo', MAX_PROCESSO)))
               for item in janelas)


class WindowsJanelas:
    def __init__(self):
        import win32gui
        import win32con
        import win32process
        import win32api
        import psutil
        import ctypes
        from ctypes import wintypes
        self.gui, self.con, self.process, self.psutil = win32gui, win32con, win32process, psutil
        self.api = win32api
        self.show_async = ctypes.WinDLL('user32', use_last_error=True).ShowWindowAsync
        self.show_async.argtypes = [wintypes.HWND, ctypes.c_int]
        self.show_async.restype = wintypes.BOOL
        self._cloaked = ctypes.WinDLL('dwmapi').DwmGetWindowAttribute
        self._cloaked.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        self._cloaked.restype = ctypes.c_long

    def _descrever(self, hwnd):
        titulo = self.gui.GetWindowText(hwnd)
        if titulo.strip():
            _, pid = self.process.GetWindowThreadProcessId(hwnd)
            return Janela(hwnd, self.psutil.Process(pid).name().lower(), titulo)

    def listar(self):
        janelas = []
        def visitar(hwnd, _):
            try:
                if not self.gui.IsWindowVisible(hwnd) or self.gui.GetWindow(hwnd, self.con.GW_OWNER):
                    return
                janela = self._descrever(hwnd)
                if janela:
                    janelas.append(janela)
            except Exception:
                pass
        self.gui.EnumWindows(visitar, None)
        return janelas

    def _observavel(self, hwnd):
        import ctypes
        ocultada = ctypes.c_uint()
        try:
            if not hwnd or self.gui.GetClassName(hwnd) in CLASSES_SHELL:
                return False
            # DWMWA_CLOAKED inclui janelas de outras áreas de trabalho virtuais.
            return self._cloaked(hwnd, 14, ctypes.byref(ocultada), ctypes.sizeof(ocultada)) != 0 or not ocultada.value
        except self.gui.error:
            return False  # A janela pode ter sido fechada desde a enumeração.

    def observar(self, so_ativa):
        ativa = self.primeiro_plano()
        if so_ativa:
            if self._observavel(ativa):
                try:
                    janela = self._descrever(ativa)
                except (self.gui.error, self.psutil.NoSuchProcess):
                    return []
                return [janela] if janela else []
            return []
        janelas = [janela for janela in self.listar() if self._observavel(janela.id)]
        return sorted(janelas, key=lambda janela: janela.id != ativa)

    def ativar(self, hwnd):
        # Async restore preserves the user's maximized layout and avoids a hung target.
        if self.gui.IsIconic(hwnd):
            self.show_async(hwnd, self.con.SW_RESTORE)
        self.gui.SetWindowPos(hwnd, self.con.HWND_TOP, 0, 0, 0, 0,
            self.con.SWP_NOMOVE | self.con.SWP_NOSIZE | self.con.SWP_SHOWWINDOW | self.con.SWP_ASYNCWINDOWPOS)
        try:
            self.gui.SetForegroundWindow(hwnd)
        except Exception:
            pass  # Windows may refuse foreground rights. The caller verifies instead.

    def primeiro_plano(self):
        return self.gui.GetForegroundWindow()

    def estado(self, hwnd, comando):
        if comando == 'janela_fechar':
            return not self.gui.IsWindow(hwnd)
        if comando == 'janela_maximizar':
            return self.gui.GetWindowPlacement(hwnd)[1] == self.con.SW_SHOWMAXIMIZED
        if comando == 'janela_minimizar':
            return bool(self.gui.IsIconic(hwnd))
        if comando == 'janela_focar':
            return self.primeiro_plano() == hwnd
        monitor = self.api.GetMonitorInfo(self.api.MonitorFromWindow(hwnd, self.con.MONITOR_DEFAULTTONEAREST))['Monitor']
        _, _, largura, altura = self.gui.GetClientRect(hwnd)
        x, y = self.gui.ClientToScreen(hwnd, (0, 0))
        return (x, y, x + largura, y + altura) == monitor

    def agir(self, hwnd, comando):
        if comando == 'janela_fechar':
            self.gui.PostMessage(hwnd, self.con.WM_CLOSE, 0, 0)
        elif comando == 'janela_focar':
            self.ativar(hwnd)
        else:
            modo = self.con.SW_MAXIMIZE if comando == 'janela_maximizar' else self.con.SW_MINIMIZE
            if not self.show_async(hwnd, modo):
                raise RuntimeError('O Windows recusou a mudança da janela.')


class FocoJanelas:
    def __init__(self, sistema=None, pausa=time.sleep):
        self.sistema, self.pausa = sistema, pausa

    def _sistema(self):
        if self.sistema is None and os.name == 'nt':
            self.sistema = WindowsJanelas()
        return self.sistema

    def capturar(self):
        try:
            sistema = self._sistema()
            return sistema.listar() if sistema else []
        except Exception:
            return []

    def observar(self, comando, termo=''):
        sistema = self._sistema()
        if sistema is None:
            raise RuntimeError('Observação de janelas indisponível.')
        termo = normalizar(termo or '')
        janelas = sistema.observar(so_ativa=comando == 'janela_ativa')
        if termo:
            janelas = [janela for janela in janelas if _combina(janela, termo)]
        rotulos = [(_rotulo(janela.titulo, MAX_TITULO), _rotulo(janela.processo, MAX_PROCESSO)) for janela in janelas]
        itens = [{'titulo': titulo, 'processo': processo} for titulo, processo in rotulos if titulo and processo]
        return {'janelas': itens[:MAX_JANELAS], 'total': len(itens)}

    def alvo_interface(self, termo, *, exato=False):
        sistema = self._sistema()
        if sistema is None:
            return 'indisponivel', None
        termo = normalizar(termo)
        janelas = sistema.observar(so_ativa=not termo)
        if termo:
            apelido = PROCESSOS_APLICATIVOS.get(termo)
            exatas = [janela for janela in janelas if normalizar(janela.titulo) == termo]
            por_app = [janela for janela in janelas if termo in {janela.processo, janela.processo.removesuffix('.exe')}
                       or apelido == janela.processo]
            janelas = por_app if exato and apelido else (exatas or por_app or
                ([] if exato else [janela for janela in janelas if _combina(janela, termo)]))
        if not janelas:
            return 'sem_janela', None
        if len(janelas) != 1:
            return 'ambigua', None
        janela = janelas[0]
        if sistema.estado(janela.id, 'janela_minimizar'):
            return 'minimizada', None
        return 'lida', janela

    def trazer(self, *, processos=(), termo=None, antes=(), tentativas=24, somente_alteradas=False):
        anteriores = {j.id: j.titulo for j in antes}
        for _ in range(tentativas):
            try:
                sistema = self._sistema()
                if sistema is None:
                    return False
                candidatos = [j for j in sistema.listar() if j.processo in processos or
                    (termo and re.search(r'\b' + re.escape(termo) + r'\b', j.titulo, re.I))]
                if somente_alteradas:
                    candidatos = [j for j in candidatos if anteriores.get(j.id) != j.titulo]
                candidatos.sort(key=lambda j: anteriores.get(j.id) == j.titulo)
                if candidatos:
                    alvo = candidatos[0]
                    if sistema.primeiro_plano() == alvo.id:
                        return True
                    sistema.ativar(alvo.id)
                    self.pausa(.1)
                    if sistema.primeiro_plano() == alvo.id:
                        return True
            except Exception:
                pass
            self.pausa(.15)
        return False

    def confirmar_documento(self, nomes, antes, tentativas=25):
        anteriores = {janela.id: janela.titulo for janela in antes}
        prefixos = tuple(nome + separador for nome in nomes for separador in (' - ', ' – ', ' — ', ' | '))
        for _ in range(tentativas):
            for janela in self.capturar():
                if anteriores.get(janela.id) == janela.titulo:
                    continue
                titulo = janela.titulo.strip().casefold()
                if titulo in nomes or titulo.startswith(prefixos):
                    return True
            self.pausa(.2)
        return False

    def controlar(self, comando, termo, tela_cheia):
        sistema = self._sistema()
        if not sistema:
            raise RuntimeError('Controle de janelas indisponível.')
        janelas = sistema.listar()
        termo = str(termo or '').strip().casefold()
        if termo:
            exatas = [j for j in janelas if termo in {j.titulo.casefold(), j.processo, j.processo.removesuffix('.exe')}]
            candidatos = exatas or [j for j in janelas if re.search(r'\b' + re.escape(termo) + r'\b', j.titulo, re.I)]
        else:
            ativa = sistema.primeiro_plano()
            candidatos = [j for j in janelas if j.id == ativa]
        if len(candidatos) != 1:
            raise ValueError('Identifique uma única janela pelo título.')
        alvo = candidatos[0]
        if comando == 'janela_fechar' and alvo.processo == 'ollie-master-next.exe':
            raise ValueError('Use o botão de fechar da Ollie para encerrar o executor.')
        desejado = True
        if comando == 'janela_fullscreen':
            if alvo.processo not in BROWSERS or sistema.primeiro_plano() != alvo.id:
                raise ValueError('A tela cheia está disponível no navegador em primeiro plano.')
            desejado = not sistema.estado(alvo.id, comando)
            tela_cheia()
        elif not sistema.estado(alvo.id, comando):
            sistema.agir(alvo.id, comando)
        for _ in range(16):
            if sistema.estado(alvo.id, comando) == desejado:
                return
            self.pausa(.125)
        raise RuntimeError('O Windows não confirmou a mudança da janela.')
