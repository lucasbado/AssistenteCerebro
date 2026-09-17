import os
import subprocess
import psutil
import toml
import logging
import webbrowser
import threading
import difflib
import re
from typing import List

logger = logging.getLogger("PCControl")

# 🌍 CONFIGURAÇÃO DE AMBIENTE
# Forçamos local se não houver variável RENDER (padrão do sistema)
is_render = os.getenv("RENDER", "False").lower() in ["true", "1", "yes"]

# Declaramos as variáveis globais que serão preenchidas pelos imports
pyautogui = None
gw = None
win32gui = None
win32con = None
AudioUtilities = None
IAudioEndpointVolume = None
CLSCTX_ALL = None
cast = None
POINTER = None
voicemeeterlib = None
spotipy = None
SpotifyOAuth = None

def carregar_bibliotecas():
    global pyautogui, gw, win32gui, win32con, AudioUtilities, IAudioEndpointVolume, CLSCTX_ALL, cast, POINTER, voicemeeterlib, spotipy, SpotifyOAuth
    
    if is_render:
        logger.info("[PCControl] Rodando em modo CLOUD (Render). Bibliotecas de hardware desativadas.")
        return

    logger.info("[PCControl] Carregando motores de hardware locais...")

    # ⌨️ Teclado e Mouse
    try:
        import pyautogui as pg
        pyautogui = pg
        # Configurações de segurança
        pyautogui.PAUSE = 0.1
        pyautogui.FAILSAFE = False
        logger.info("✅ PyAutoGUI: OK")
    except Exception as e:
        logger.error(f"❌ PyAutoGUI: Falha -> {e}")

    # 🪟 Janelas
    try:
        import pygetwindow as _gw
        import win32gui as _w32g
        import win32con as _w32c
        gw = _gw
        win32gui = _w32g
        win32con = _w32c
        logger.info("✅ Win32GUI/GetWindow: OK")
    except Exception as e:
        logger.error(f"❌ Win32: Falha -> {e}")

    # 🔊 Áudio
    try:
        from pycaw.pycaw import AudioUtilities as _AU, IAudioEndpointVolume as _IAEV
        from comtypes import CLSCTX_ALL as _CLS
        from ctypes import cast as _cast, POINTER as _PTR
        AudioUtilities = _AU
        IAudioEndpointVolume = _IAEV
        CLSCTX_ALL = _CLS
        cast = _cast
        POINTER = _PTR
        logger.info("✅ PyCaw (Áudio Sistema): OK")
    except Exception as e:
        logger.error(f"❌ PyCaw: Falha -> {e}")

    # 🎙️ Voicemeeter
    try:
        import voicemeeterlib as _vml
        voicemeeterlib = _vml
        logger.info("✅ Voicemeeter Lib: OK")
    except Exception as e:
        logger.warning(f"⚠️ Voicemeeter Lib: Não disponível ({e})")
        
    # 🎵 Spotify
    try:
        import spotipy as _spot
        from spotipy.oauth2 import SpotifyOAuth as _SOAuth
        spotipy = _spot
        SpotifyOAuth = _SOAuth
        logger.info("✅ Spotify API: OK")
    except Exception as e:
        logger.warning(f"⚠️ Spotify API: Não disponível ({e})")

# Executa a carga imediata
carregar_bibliotecas()

class PcControlService:
    def __init__(self):
        self.vm = None
        self.sp = None
        self.fator_vol = 0.72
        self.mobile_apps = [] 
        self.indexed_apps = {}
        
        # Mapeamentos Base
        self.app_paths = {
            "vscode": "code",
            "spotify": "C:\\Users\\lucba\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu\\Programs\\Spotify.lnk",
            "lol": "C:\\Riot Games\\League of Legends\\LeagueClient.exe",
            "android_studio": "C:\\Program Files\\Android\\Android Studio\\bin\\studio64.exe",
            "pasta_jogos": "D:\\games",
            "discord": "C:\\Users\\lucba\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu\\Programs\\Discord Inc\\Discord.lnk"
        }
        self.app_paths = {k.lower(): v for k, v in self.app_paths.items()}
        
        self._carregar_config()
        
        self.macros = {
            "alt_tab": ["alt", "tab"],
            "win_d": ["win", "d"],
            "print_screen": ["printscreen"],
            "task_mgr": ["ctrl", "shift", "esc"],
            "alt_f4": ["alt", "f4"],
            "win_tab": ["win", "tab"],
            "media_play_pause": ["playpause"],
            "media_next": ["nexttrack"],
            "media_prev": ["prevtrack"],
        }

    def _carregar_config(self):
        try:
            path = "D:/Programacao/AssistenteCell/config.toml"
            if not os.path.exists(path): path = "config.toml" 
            
            if os.path.exists(path):
                config = toml.load(path)
                self.spot_id = config.get("spotify", {}).get("client_id")
                self.spot_secret = config.get("spotify", {}).get("client_secret")
                self.spot_uri = config.get("spotify", {}).get("redirect_uri", "http://127.0.0.1:8888/callback")
                
                apps_extras = config.get("apps_mapeados", {})
                for k, v in apps_extras.items():
                    self.app_paths[k.lower()] = v
            else:
                self.spot_id = None
        except Exception as e:
            logger.error(f"Erro ao carregar config.toml: {e}")

    def salvar_mapeamento(self, nome, path_alvo):
        try:
            config_path = "D:/Programacao/AssistenteCell/config.toml"
            if not os.path.exists(config_path): config_path = "config.toml"
            config = toml.load(config_path) if os.path.exists(config_path) else {}
            if "apps_mapeados" not in config: config["apps_mapeados"] = {}
            config["apps_mapeados"][nome.lower()] = path_alvo
            with open(config_path, "w", encoding="utf-8") as f:
                toml.dump(config, f)
            logger.info(f"[PCControl] Mapeamento salvo: {nome}")
        except Exception as e:
            logger.error(f"Erro ao salvar mapeamento: {e}")

    def mapear_todos_apps(self):
        logger.info("[PCControl] 🔍 Neural App Scan iniciado...")
        search_paths = [
            os.path.join(os.environ.get('APPDATA', ''), 'Microsoft', 'Windows', 'Start Menu', 'Programs'),
            os.path.join(os.environ.get('PROGRAMDATA', ''), 'Microsoft', 'Windows', 'Start Menu', 'Programs'),
            os.path.join(os.path.expanduser('~'), 'Desktop'),
            'C:\\Users\\Public\\Desktop'
        ]
        novos_apps = {}
        for base_path in search_paths:
            if not os.path.exists(base_path): continue
            try:
                for root, _, files in os.walk(base_path):
                    for file in files:
                        ext = file.lower()
                        if ext.endswith(('.lnk', '.exe', '.url')):
                            name = file.rsplit('.', 1)[0].lower()
                            if any(x in name for x in ['uninstall', 'setup', 'helper']): continue
                            path = os.path.join(root, file)
                            if name not in novos_apps or ext.endswith('.lnk'):
                                novos_apps[name] = path
            except: pass
        self.indexed_apps.update(novos_apps)
        logger.info(f"✅ [PCControl] Scan concluído: {len(self.indexed_apps)} apps prontos.")

    def match_inteligente(self, termo: str, candidatos: List[str]) -> str:
        if not candidatos: return None
        termo = termo.lower().replace("_", " ").replace("-", " ").strip()
        palavras_termo = set(re.findall(r'[a-zA-Z0-9]+', termo))
        palavras_primarias = {p for p in palavras_termo if not p.isdigit() and len(p) > 1}
        melhor_match, highest_score = None, -1
        min_rigor = 0.4 if len(palavras_primarias) <= 1 else 0.6
        for cand in candidatos:
            cand_norm = cand.lower().replace("_", " ").replace("-", " ")
            palavras_cand = set(re.findall(r'[a-zA-Z0-9]+', cand_norm))
            seq_match = difflib.SequenceMatcher(None, termo, cand_norm).ratio()
            overlap = len(palavras_termo.intersection(palavras_cand))
            keyword_score = overlap / len(palavras_termo) if palavras_termo else 0
            if palavras_primarias:
                overlap_primario = len(palavras_primarias.intersection(palavras_cand))
                if (overlap_primario / len(palavras_primarias)) < min_rigor:
                    keyword_score *= 0.1
            final_score = (keyword_score * 0.8) + (seq_match * 0.2)
            if final_score > highest_score:
                highest_score = final_score
                melhor_match = cand
        return melhor_match if highest_score >= 0.60 else None

    def deep_search_disk(self, nome: str) -> str:
        drives = ['D:', 'G:', 'C:', 'E:', 'F:']
        termo = nome.lower().strip()
        for drive in drives:
            drive_path = drive + "\\"
            if not os.path.exists(drive_path): continue
            bibliotecas = ['games', 'Jogos', 'SteamLibrary\\steamapps\\common', 'Program Files (x86)', 'Program Files', 'Epic Games', 'Riot Games']
            for lib in bibliotecas:
                base_lib = os.path.join(drive_path, lib)
                if not os.path.exists(base_lib): continue
                try:
                    pastas = [d for d in os.listdir(base_lib) if os.path.isdir(os.path.join(base_lib, d))]
                    match_pasta = self.match_inteligente(termo, pastas)
                    if match_pasta:
                        pasta_alvo = os.path.join(base_lib, match_pasta)
                        melhor_exe = self._encontrar_executavel_principal(pasta_alvo, termo)
                        if melhor_exe: return melhor_exe
                except: continue
        return None

    def _encontrar_executavel_principal(self, pasta: str, termo: str) -> str:
        candidatos = []
        for root, _, files in os.walk(pasta):
            if any(x in root.lower() for x in ['engine', 'redist', 'anticheat', 'tools', 'crash']): continue
            for file in files:
                if file.lower().endswith('.exe'):
                    name = file.rsplit('.', 1)[0].lower()
                    if any(x in name for x in ['unins', 'crash', 'setup', 'helper', 'dxwebsetup']): continue
                    candidatos.append(os.path.join(root, file))
        if not candidatos: return None
        best_path, highest_score = None, -1
        nome_pasta_pai = os.path.basename(pasta).lower()
        for path in candidatos:
            name = os.path.basename(path).lower().rsplit('.', 1)[0]
            score = 0
            if name == nome_pasta_pai: score += 30
            elif name in nome_pasta_pai or nome_pasta_pai in name: score += 15
            if termo in name: score += 10
            if name in ['launcher', 'game', 'play', 'start', 'client']: score -= 5
            if score > highest_score:
                highest_score = score
                best_path = path
        return best_path

    def inicializar(self):
        try:
            if voicemeeterlib:
                if self.vm:
                    try: self.vm.logout()
                    except: pass
                self.vm = voicemeeterlib.api('banana')
                self.vm.login()
                logger.info("[PCControl] Voicemeeter conectado.")
            self._init_spotify()
            if not is_render:
                threading.Thread(target=self.mapear_todos_apps, daemon=True).start()
            return True
        except Exception as e:
            logger.error(f"[PCControl] Erro inicialização: {e}")
            return False

    def _init_spotify(self):
        if not spotipy or not self.spot_id: return
        try:
            scope = "user-modify-playback-state,user-read-currently-playing,user-read-playback-state,user-library-modify,user-library-read"
            auth = SpotifyOAuth(client_id=self.spot_id, client_secret=self.spot_secret, redirect_uri=self.spot_uri, scope=scope, open_browser=True)
            self.sp = spotipy.Spotify(auth_manager=auth)
            logger.info("[PCControl] Spotify conectado.")
        except Exception as e:
            logger.warning(f"[PCControl] Spotify offline: {e}")

    def spotify_next(self):
        if self.sp: self.sp.next_track()

    def spotify_prev(self):
        if self.sp: self.sp.previous_track()

    def spotify_pause(self):
        if self.sp:
            current = self.sp.current_playback()
            if current and current.get('is_playing'): self.sp.pause_playback()
            else: self.sp.start_playback()

    def tocar_spotify(self, query: str):
        if self.sp:
            results = self.sp.search(q=query, limit=1)
            if results['tracks']['items']:
                self.sp.start_playback(uris=[results['tracks']['items'][0]['uri']])

    def spotify_like(self):
        if self.sp:
            current = self.sp.current_playback()
            if current and current.get('item'):
                self.sp.current_user_saved_tracks_add(tracks=[current['item']['id']])

    def set_vm_param(self, param, valor):
        if self.vm: self.vm.set(param, valor)

    def set_gain(self, canal, valor_porcentagem):
        if self.vm:
            db = -60.0 + (valor_porcentagem * self.fator_vol)
            self.vm.set(f"Strip[{canal}].Gain", db)

    def toggle_rota(self, canal, saida, estado):
        if self.vm: self.vm.set(f"Strip[{canal}].{saida.upper()}", 1 if estado else 0)

    def mutar_mic(self):
        if self.vm:
            curr = int(self.vm.get('Strip[0].Mute'))
            self.vm.set('Strip[0].Mute', 0 if curr == 1 else 1)

    def abrir_app(self, app_key):
        if not app_key: return False
        chave = str(app_key).lower().strip()
        if self.trazer_janela_para_frente(chave): return True
        path = self.app_paths.get(chave)
        if not path:
            match = self.match_inteligente(chave, list(self.indexed_apps.keys()))
            if match: path = self.indexed_apps[match]
        if not path: path = self.deep_search_disk(app_key)
        if path:
            self.executar_comando_direto(path)
            self.app_paths[chave] = path
            return True
        self.executar_comando_direto(app_key)
        return False

    def executar_comando_direto(self, alvo):
        try:
            if "://" in alvo or alvo.lower().startswith("http"):
                webbrowser.open(alvo)
            elif os.path.exists(alvo):
                os.startfile(alvo)
            else:
                subprocess.Popen(alvo, shell=True)
        except Exception as e:
            logger.error(f"Erro executar {alvo}: {e}")

    def trazer_janela_para_frente(self, termo: str) -> bool:
        if not gw or not win32gui: return False
        try:
            for j in gw.getAllWindows():
                if termo in j.title.lower():
                    if j.isMinimized: j.restore()
                    win32gui.ShowWindow(j._hWnd, win32con.SW_RESTORE)
                    win32gui.SetForegroundWindow(j._hWnd)
                    return True
            return False
        except: return False

    def bloquear_pc(self): os.system("rundll32.exe user32.dll,LockWorkStation")
    def dormir_pc(self): os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
    def desligar_pc(self): os.system("shutdown /s /t 60")
    def reiniciar_pc(self): os.system("shutdown /r /t 60")

    def executar_macro(self, macro_key):
        keys = self.macros.get(macro_key)
        if not keys or not pyautogui:
            logger.error(f"❌ Macro '{macro_key}' indisponível. PyAutoGUI: {pyautogui is not None}")
            return
        try:
            logger.info(f"⌨️ [Hardware] Executando: {keys}")
            if macro_key in ["alt_tab", "win_tab"]:
                main_key = "alt" if "alt" in macro_key else "win"
                pyautogui.keyDown(main_key)
                pyautogui.press('tab')
                pyautogui.keyUp(main_key)
            else:
                pyautogui.hotkey(*keys)
        except Exception as e:
            logger.error(f"❌ Erro macro: {e}")

    def set_system_volume(self, percent: int):
        if not AudioUtilities: return False
        try:
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))
            volume.SetMasterVolumeLevelScalar(percent / 100.0, None)
            return True
        except: return False

    def encerrar_processo(self, alvo):
        for proc in psutil.process_iter(['name', 'pid']):
            if str(alvo).lower() in proc.info['name'].lower():
                proc.kill()
                return True
        return False

    def obter_estado_completo(self):
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent
        disco = 0
        try: disco = psutil.disk_usage('C:').percent
        except: pass
        running_procs = []
        try:
            for proc in sorted(psutil.process_iter(['name', 'cpu_percent']), key=lambda p: p.info['cpu_percent'], reverse=True)[:5]:
                if proc.info['cpu_percent'] > 0.1:
                    running_procs.append({"n": proc.info['name'], "c": f"{proc.info['cpu_percent']:.1f}"})
        except: pass
        v3, v4, m_mute = 50, 50, 0
        if self.vm:
            try:
                v3 = max(0, min(100, int((self.vm.get('Strip[3].Gain') + 60) / self.fator_vol)))
                v4 = max(0, min(100, int((self.vm.get('Strip[4].Gain') + 60) / self.fator_vol)))
                m_mute = int(self.vm.get('Strip[0].Mute'))
            except: pass
        return {
            "audio_state": {
                "3": { "volume": v3, "a1": int(self.vm.get('Strip[3].A1')) if self.vm else 0, "a2": int(self.vm.get('Strip[3].A2')) if self.vm else 0, "a3": int(self.vm.get('Strip[3].A3')) if self.vm else 0 },
                "4": { "volume": v4, "a1": int(self.vm.get('Strip[4].A1')) if self.vm else 0, "a2": int(self.vm.get('Strip[4].A2')) if self.vm else 0, "a3": int(self.vm.get('Strip[4].A3')) if self.vm else 0 },
            },
            "cpu": cpu, "ram": ram, "disco": disco, "online": True, "mic_mute": m_mute,
            "sistema": {"cpu": cpu, "ram": ram, "disco": disco},
            "apps_disponiveis": list(self.indexed_apps.keys())[:30],
            "processes": running_procs
        }

pc_control_service = PcControlService()
