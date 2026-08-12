import os
import subprocess
import psutil
import spotipy
import toml
from spotipy.oauth2 import SpotifyOAuth
import logging
from typing import List

# Importação condicional para bibliotecas de hardware e serviços externos
# 🌍 SEGURANÇA CLOUD: Não importa bibliotecas de GUI/Hardware no Render
if not os.getenv("RENDER"):
    try:
        import pyautogui
    except ImportError:
        pyautogui = None

    try:
        import voicemeeterlib
    except ImportError:
        voicemeeterlib = None
else:
    pyautogui = None
    voicemeeterlib = None

try:
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth
except ImportError:
    spotipy = None
    SpotifyOAuth = None

logger = logging.getLogger("PCControl")

class PcControlService:
    def __init__(self):
        self.vm = None
        self.sp = None
        self.fator_vol = 0.72
        self.mobile_apps = [] 
        self._carregar_config()
        
        self.app_paths = {
            "vscode": "code",
            "spotify": "C:\\Users\\lucba\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu\\Programs\\Spotify.lnk",
            "lol": "C:\\Riot Games\\League of Legends\\LeagueClient.exe",
            "android_studio": "C:\\Program Files\\Android\\Android Studio\\bin\\studio64.exe",
            "pasta_jogos": "D:\\games",
            "discord": "C:\\Users\\lucba\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu\\Programs\\Discord Inc\\Discord.lnk"
        }
        self.macros = {
            "alt_tab": ["alt", "tab"],
            "win_d": ["win", "d"],
            "print_screen": ["printscreen"],
            "task_mgr": ["ctrl", "shift", "esc"],
            "alt_f4": ["alt", "f4"],
            "win_tab": ["win", "tab"],
        }

    def _carregar_config(self):
        try:
            # Tenta carregar do caminho absoluto (Local) ou relativo (Cloud/Local)
            path = "D:/Programacao/AssistenteCell/config.toml"
            if not os.path.exists(path):
                path = "config.toml" # Tenta na raiz do projeto
            
            if os.path.exists(path):
                config = toml.load(path)
                self.spot_id = config.get("spotify", {}).get("client_id")
                self.spot_secret = config.get("spotify", {}).get("client_secret")
                self.spot_uri = config.get("spotify", {}).get("redirect_uri", "http://127.0.0.1:8888/callback")
            else:
                logger.warning("Arquivo config.toml não encontrado.")
                self.spot_id = None
        except Exception as e:
            logger.error(f"Erro ao carregar config.toml: {e}")
            self.spot_id = None

    def inicializar(self):
        try:
            # Tenta Voicemeeter, mas não mata o serviço se falhar (ex: nuvem)
            if voicemeeterlib:
                try:
                    self.vm = voicemeeterlib.api('banana')
                    self.vm.login()
                    logger.info("[PCControl] Voicemeeter conectado.")
                except Exception as e:
                    logger.warning(f"[PCControl] Falha ao logar no Voicemeeter: {e}")
            else:
                logger.warning("[PCControl] Biblioteca voicemeeterlib não instalada.")

            self._init_spotify()
            
            # Pyautogui pode falhar em servidores sem tela
            if pyautogui:
                try:
                    pyautogui.PAUSE = 0
                    pyautogui.FAILSAFE = False
                except Exception as e:
                    logger.warning(f"[PCControl] Falha ao configurar PyAutoGUI: {e}")
            else:
                logger.warning("[PCControl] Biblioteca pyautogui não instalada.")
                
            return True
        except Exception as e:
            logger.error(f"[PCControl] Erro na inicialização: {e}")
            return False

    def _init_spotify(self):
        if not self.spot_id:
            logger.warning("[PCControl] Spotify ignorado (sem credenciais no config.toml).")
            return
        try:
            scope = "user-modify-playback-state,user-read-currently-playing,user-read-playback-state,user-library-modify,user-library-read"
            auth = SpotifyOAuth(client_id=self.spot_id, client_secret=self.spot_secret, redirect_uri=self.spot_uri, scope=scope, open_browser=True)
            self.sp = spotipy.Spotify(auth_manager=auth)
            logger.info("[PCControl] Spotify (Spotipy) conectado.")
        except Exception as e:
            logger.warning(f"[PCControl] Falha ao conectar Spotify: {e}")

    def encerrar(self):
        if self.vm:
            try: self.vm.logout()
            except: pass

    # --- AÇÕES DE HARDWARE ---
    def set_gain(self, canal, valor_porcentagem):
        if self.vm:
            db = -60.0 + (valor_porcentagem * self.fator_vol)
            self.vm.set(f"Strip[{canal}].Gain", db)

    def toggle_rota(self, canal, saida, estado):
        if self.vm:
            self.vm.set(f"Strip[{canal}].{saida.upper()}", 1 if estado else 0)

    def mutar_mic(self):
        if self.vm:
            curr = int(self.vm.get('Strip[0].Mute'))
            self.vm.set('Strip[0].Mute', 0 if curr == 1 else 1)

    # --- AÇÕES DE SISTEMA ---
    def abrir_app(self, app_key):
        path = self.app_paths.get(app_key)
        if not path:
            self.executar_comando_direto(app_key)
            return
        self.executar_comando_direto(path)

    def abrir_url(self, url):
        """Abre uma URL no navegador padrão."""
        if not url.startswith("http"):
            url = "https://" + url
        self.executar_comando_direto(url)

    def pesquisa_google(self, query):
        """Realiza uma busca no Google abrindo o navegador."""
        url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        self.executar_comando_direto(url)

    def buscar_arquivos(self, termo: str) -> List[str]:
        """Procura por arquivos em pastas de usuário."""
        user_path = os.path.expanduser("~")
        targets = ["Documents", "Downloads", "Desktop"]
        found = []
        for folder in targets:
            base = os.path.join(user_path, folder)
            if not os.path.exists(base): continue
            try:
                for root, _, files in os.walk(base):
                    for name in files:
                        if termo.lower() in name.lower():
                            found.append(os.path.join(root, name))
                            if len(found) >= 5: return found
            except Exception as e:
                logger.error(f"Erro ao vasculhar {base}: {e}")
        return found

    def executar_comando_direto(self, alvo):
        try:
            logger.info(f"[PCControl] Executando: {alvo}")
            if alvo.endswith(":") or "\\" in alvo or ":" in alvo:
                os.startfile(alvo)
            else:
                try:
                    os.startfile(alvo)
                except:
                    subprocess.Popen(alvo, shell=True)
        except Exception as e:
            logger.error(f"[PCControl] Falha ao executar {alvo}: {e}")

    def executar_macro(self, macro_key):
        keys = self.macros.get(macro_key)
        if keys: pyautogui.hotkey(*keys)

    def set_modo_imersao(self, ativo: bool):
        """Ativa ou desativa o modo imersão."""
        if not self.vm: return
        if ativo:
            logger.info("[PCControl] Ativando Modo Imersão...")
            self.vm.set('Strip[0].Mute', 1)
            pyautogui.hotkey('win', 'd')
            self.set_gain(4, 30)
        else:
            logger.info("[PCControl] Desativando Modo Imersão...")
            self.vm.set('Strip[0].Mute', 0)
            self.set_gain(4, 70)

    def janela_fullscreen(self, alvo: str = None):
        """Tenta colocar a janela atual ou um alvo específico em tela cheia."""
        if alvo and not self.focar_janela(alvo):
            logger.warning(f"[PCControl] Cancelando Fullscreen: Alvo '{alvo}' não encontrado.")
            return
        
        logger.info(f"[PCControl] Comutando Tela Cheia para: {alvo or 'Janela Ativa'}")
        pyautogui.press('f11')
        pyautogui.press('f')

    def janela_maximizar(self, alvo: str = None):
        """Maximiza a janela atual ou um alvo específico."""
        if alvo and not self.focar_janela(alvo):
            logger.warning(f"[PCControl] Cancelando Maximizar: Alvo '{alvo}' não encontrado.")
            return
            
        logger.info(f"[PCControl] Maximizando: {alvo or 'Janela Ativa'}")
        pyautogui.hotkey('win', 'up')

    def janela_minimizar(self, alvo: str = None):
        """Minimiza a janela atual ou um alvo específico."""
        if alvo and not self.focar_janela(alvo):
            logger.warning(f"[PCControl] Cancelando Minimizar: Alvo '{alvo}' não encontrado.")
            return
            
        logger.info(f"[PCControl] Minimizando: {alvo or 'Janela Ativa'}")
        pyautogui.hotkey('win', 'down')

    def focar_janela(self, titulo_parcial: str) -> bool:
        """Usa PowerShell de alto nível para forçar uma janela para o primeiro plano com inteligência de conteúdo."""
        # Limpeza agressiva do termo
        termo_limpo = titulo_parcial.lower()
        substituicoes = [".com.br", ".com", "https://", "http://", "www.", ".exe"]
        for s in substituicoes:
            termo_limpo = termo_limpo.replace(s, "")
        termo_limpo = termo_limpo.strip()

        logger.info(f"[PCControl] Buscando foco seletivo para: {termo_limpo}")
        import time
        
        # 1. TENTATIVA PRIORITÁRIA: Buscar o termo exato no TÍTULO das janelas
        ps_script_titulo = f"""
        $code = @'
            [DllImport("user32.dll")]
            public static extern bool SetForegroundWindow(IntPtr hWnd);
            [DllImport("user32.dll")]
            public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
            [DllImport("user32.dll")]
            public static extern bool IsIconic(IntPtr hWnd);
'@
        if (-not ([Ref].Assembly.GetType("Win32.Win32Focus"))) {{
            Add-Type -MemberDefinition $code -Name "Win32Focus" -Namespace "Win32"
        }}
        
        # Busca processos que tenham o termo no TÍTULO da janela e tenham handle
        $target = Get-Process | Where-Object {{ ($_.MainWindowTitle -match '{termo_limpo}') -and $_.MainWindowHandle -ne 0 }} | Select-Object -First 1
        if ($target) {{
            $handle = $target.MainWindowHandle
            if ([Win32.Win32Focus]::IsIconic($handle)) {{ [Win32.Win32Focus]::ShowWindow($handle, 9) }}
            [Win32.Win32Focus]::SetForegroundWindow($handle)
            return $true
        }}
        return $false
        """

        try:
            pyautogui.press('alt')
            result = subprocess.run(["powershell", "-Command", ps_script_titulo], capture_output=True, text=True)
            if "True" in result.stdout:
                logger.info(f"✅ [PCControl] Conteúdo '{termo_limpo}' encontrado e focado.")
                time.sleep(0.5)
                return True
        except Exception as e:
            logger.error(f"Erro no foco por título: {e}")

        # 2. TENTATIVA SECUNDÁRIA: Se não achou o conteúdo, busca pelo processo do app (apenas se for app conhecido)
        apps_diretos = ["spotify", "discord", "vscode", "code", "studio64", "vlc", "opera", "chrome", "msedge"]
        if termo_limpo in apps_diretos:
            # Aqui buscamos pelo nome do processo
            ps_script_proc = ps_script_titulo.replace(f"$_.MainWindowTitle -match '{termo_limpo}'", f"$_.ProcessName -match '{termo_limpo}'")
            try:
                result = subprocess.run(["powershell", "-Command", ps_script_proc], capture_output=True, text=True)
                if "True" in result.stdout:
                    logger.info(f"✅ [PCControl] App '{termo_limpo}' focado pelo processo.")
                    return True
            except: pass

        logger.warning(f"❌ [PCControl] Não encontrei nenhuma janela ativa com o título '{termo_limpo}'.")
        return False

    # --- DJ OLLIE (SPOTIPY) ---
    def tocar_spotify(self, query: str) -> bool:
        """Busca e toca uma música/artista no Spotify."""
        if not self.sp: return False
        try:
            resultados = self.sp.search(q=query, limit=1, type='track')
            if resultados['tracks']['items']:
                track_uri = resultados['tracks']['items'][0]['uri']
                
                # Tenta tocar. Se falhar, busca um dispositivo ativo.
                try:
                    self.sp.start_playback(uris=[track_uri])
                except Exception:
                    devices = self.sp.devices()
                    if devices and devices['devices']:
                        # Tenta o primeiro dispositivo disponível
                        device_id = devices['devices'][0]['id']
                        self.sp.start_playback(device_id=device_id, uris=[track_uri])
                    else:
                        logger.warning("Nenhum dispositivo Spotify ativo encontrado.")
                        return False

                logger.info(f"🎵 Tocando no Spotify: {query}")
                return True
            return False
        except Exception as e:
            logger.error(f"Erro Spotify: {e}")
            return False

    def spotify_next(self):
        if self.sp: self.sp.next_track()

    def spotify_prev(self):
        if self.sp: self.sp.previous_track()

    def spotify_pause(self):
        if not self.sp: return
        try:
            curr = self.sp.current_playback()
            if curr and curr['is_playing']: self.sp.pause_playback()
            else: self.sp.start_playback()
        except: pass

    def spotify_like(self):
        if not self.sp: return
        try:
            curr = self.sp.current_playback()
            if curr and curr['item']:
                t_id = curr['item']['id']
                if self.sp.current_user_saved_tracks_contains([t_id])[0]:
                    self.sp.current_user_saved_tracks_delete([t_id])
                else:
                    self.sp.current_user_saved_tracks_add([t_id])
        except: pass

    # --- RELÉ PARA MOBILE ---
    async def abrir_app_mobile(self, package_name):
        from api.websocket import central_alertas
        payload = {"tipo_ws": "COMANDO_SISTEMA", "acao": "ABRIR_APP", "pacote": package_name}
        await central_alertas._broadcast(payload)

    async def abrir_url_mobile(self, url):
        from api.websocket import central_alertas
        payload = {"tipo_ws": "COMANDO_SISTEMA", "acao": "ABRIR_URL", "url": url}
        await central_alertas._broadcast(payload)

    # --- COLETA DE DADOS ---
    def obter_estado_completo(self):
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent
        disco = psutil.disk_usage('/').percent
        track, artist, playing, liked = "Nenhuma Música", "", False, False
        if self.sp:
            try:
                curr = self.sp.current_playback()
                if curr and curr['item']:
                    track = curr['item']['name']
                    artist = curr['item']['artists'][0]['name']
                    playing = curr['is_playing']
                    liked = self.sp.current_user_saved_tracks_contains([curr['item']['id']])[0]
            except: pass
        v3, v4, m_mute = 50, 50, 0
        if self.vm:
            try:
                v3 = max(0, min(100, int((self.vm.get('Strip[3].Gain') + 60) / self.fator_vol)))
                v4 = max(0, min(100, int((self.vm.get('Strip[4].Gain') + 60) / self.fator_vol)))
                m_mute = int(self.vm.get('Strip[0].Mute'))
            except: pass
        return {
            "3": { "volume": v3, "a1": int(self.vm.get('Strip[3].A1')) if self.vm else 0, "a2": int(self.vm.get('Strip[3].A2')) if self.vm else 0, "a3": int(self.vm.get('Strip[3].A3')) if self.vm else 0 },
            "4": { "volume": v4, "a1": int(self.vm.get('Strip[4].A1')) if self.vm else 0, "a2": int(self.vm.get('Strip[4].A2')) if self.vm else 0, "a3": int(self.vm.get('Strip[4].A3')) if self.vm else 0 },
            "mic_mute": m_mute,
            "sistema": {"cpu": cpu, "ram": ram, "disco": disco},
            "spotify": {"track": track, "artist": artist, "playing": playing, "liked": liked},
            "mobile_apps_count": len(self.mobile_apps)
        }

pc_control_service = PcControlService()
