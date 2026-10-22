"""Foco local independente dos motores de áudio; não envia teclas nem fixa janelas."""
import os
import re
import time
from dataclasses import dataclass

BROWSERS = {'chrome.exe', 'msedge.exe', 'firefox.exe', 'opera.exe', 'brave.exe', 'vivaldi.exe', 'zen.exe'}


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


class WindowsJanelas:
    def __init__(self):
        import win32gui
        import win32con
        import win32process
        import psutil
        import ctypes
        from ctypes import wintypes
        self.gui, self.con, self.process, self.psutil = win32gui, win32con, win32process, psutil
        self.show_async = ctypes.WinDLL('user32', use_last_error=True).ShowWindowAsync
        self.show_async.argtypes = [wintypes.HWND, ctypes.c_int]
        self.show_async.restype = wintypes.BOOL

    def listar(self):
        janelas = []
        def visitar(hwnd, _):
            try:
                if not self.gui.IsWindowVisible(hwnd) or self.gui.GetWindow(hwnd, self.con.GW_OWNER):
                    return
                titulo = self.gui.GetWindowText(hwnd)
                _, pid = self.process.GetWindowThreadProcessId(hwnd)
                if titulo:
                    janelas.append(Janela(hwnd, self.psutil.Process(pid).name().lower(), titulo))
            except Exception:
                pass
        self.gui.EnumWindows(visitar, None)
        return janelas

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
