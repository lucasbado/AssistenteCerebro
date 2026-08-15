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

# 🌍 SEGURANÇA CLOUD: Não importa bibliotecas de GUI/Hardware no Render
if not os.getenv("RENDER"):
    try:
        import pyautogui
    except ImportError:
        pyautogui = None
    except Exception:
        pyautogui = None

    try:
        import voicemeeterlib
    except ImportError:
        voicemeeterlib = None
    except Exception:
        voicemeeterlib = None
        
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth
    except ImportError:
        spotipy = None
        SpotifyOAuth = None
    except Exception:
        spotipy = None
        SpotifyOAuth = None
else:
    pyautogui = None
    voicemeeterlib = None
    spotipy = None
    SpotifyOAuth = None

logger = logging.getLogger("PCControl")

class PcControlService:
    def __init__(self):
        self.vm = None
        self.sp = None
        self.fator_vol = 0.72
        self.mobile_apps = [] 
        self.indexed_apps = {} # Cache de descoberta em 2º plano
        
        # Mapeamentos Base (Fixos)
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
                
                # Carrega mapeamentos dinâmicos
                apps_extras = config.get("apps_mapeados", {})
                for k, v in apps_extras.items():
                    self.app_paths[k.lower()] = v
                if apps_extras:
                    logger.info(f"[PCControl] {len(apps_extras)} apps extras carregados do config.toml")
            else:
                self.spot_id = None
        except Exception as e:
            logger.error(f"Erro ao carregar config.toml: {e}")

    def salvar_mapeamento(self, nome, path_alvo):
        try:
            config_path = "D:/Programacao/AssistenteCell/config.toml"
            if not os.path.exists(config_path): config_path = "config.toml"
            
            config = {}
            if os.path.exists(config_path):
                config = toml.load(config_path)
            
            if "apps_mapeados" not in config:
                config["apps_mapeados"] = {}
                
            config["apps_mapeados"][nome.lower()] = path_alvo
            
            with open(config_path, "w", encoding="utf-8") as f:
                toml.dump(config, f)
            logger.info(f"[PCControl] Mapeamento salvo no config.toml: {nome}")
        except Exception as e:
            logger.error(f"Erro ao salvar mapeamento: {e}")

    def mapear_todos_apps(self):
        """
        Varre o PC em busca de todos os atalhos e programas instalados.
        Roda em segundo plano para não travar a interface.
        """
        logger.info("[PCControl] 🔍 Iniciando mapeamento neural de aplicativos em 2º plano...")
        search_paths = [
            os.path.join(os.environ.get('APPDATA', ''), 'Microsoft', 'Windows', 'Start Menu', 'Programs'),
            os.path.join(os.environ.get('PROGRAMDATA', ''), 'Microsoft', 'Windows', 'Start Menu', 'Programs'),
            os.path.join(os.path.expanduser('~'), 'Desktop'),
            'C:\\Users\\Public\\Desktop'
        ]
        
        # Bibliotecas de jogos conhecidas
        game_libs = ["D:\\games", "D:\\SteamLibrary\\steamapps\\common", "C:\\Program Files (x86)\\Steam\\steamapps\\common", "G:\\Jogos"]
        for p in game_libs:
            if os.path.exists(p): search_paths.append(p)

        novos_apps = {}
        for base_path in search_paths:
            if not os.path.exists(base_path): continue
            try:
                # Limite de profundidade adaptativo
                max_depth = 2 if any(x in base_path.lower() for x in ['games', 'steamapps', 'common']) else 5
                
                for root, dirs, files in os.walk(base_path):
                    depth = root[len(base_path):].count(os.sep)
                    if depth > max_depth:
                        del dirs[:]
                        continue

                    for file in files:
                        ext = file.lower()
                        if ext.endswith(('.lnk', '.exe', '.url')):
                            name = file.rsplit('.', 1)[0].lower()
                            
                            # Filtro de ruído (evita launchers de sistema/crash reporters)
                            if any(x in name for x in ['uninstall', 'unins000', 'crashreporter', 'setup', 'helper', 'dxwebsetup']):
                                continue
                                
                            path = os.path.join(root, file)
                            
                            # Tratamento especial para Steam (.url)
                            if ext.endswith('.url'):
                                try:
                                    with open(path, 'r', errors='ignore') as f:
                                        content = f.read()
                                        if 'steam://rungameid/' in content:
                                            novos_apps[name] = path
                                except: pass
                            else:
                                # Prioriza atalhos reais (.lnk) sobre executáveis soltos
                                if name not in novos_apps or ext.endswith('.lnk'):
                                    novos_apps[name] = path
            except Exception as e:
                logger.error(f"Erro ao varrer {base_path}: {e}")
        
        self.indexed_apps.update(novos_apps)
        logger.info(f"✅ [PCControl] Mapeamento concluído: {len(self.indexed_apps)} programas prontos.")

    def match_inteligente(self, termo: str, candidatos: List[str]) -> str:
        """
        Scoring semântico para encontrar o melhor app com rigor de palavras-chave.
        """
        if not candidatos: return None
        
        termo = termo.lower().strip()
        palavras_termo = set(re.findall(r'\w+', termo))
        # Palavras primárias = não numéricas
        palavras_primarias = {p for p in palavras_termo if not p.isdigit() and len(p) > 1}
        
        melhor_match = None
        highest_score = -1
        
        logger.info(f"🧠 [PCControl] Raciocinando sobre match para '{termo}'...")
        
        for cand in candidatos:
            cand_lower = cand.lower()
            palavras_cand = set(re.findall(r'\w+', cand_lower))
            
            # 1. Base Score: Difflib Sequence Match (Typos)
            seq_match = difflib.SequenceMatcher(None, termo, cand_lower).ratio()
            
            # 2. Keyword Match
            overlap = len(palavras_termo.intersection(palavras_cand))
            keyword_score = overlap / len(palavras_termo) if palavras_termo else 0
            
            # 3. RIGOR: Se o termo tem palavras (não números) e nenhuma bate, score cai drasticamente
            overlap_primario = len(palavras_primarias.intersection(palavras_cand))
            if palavras_primarias:
                rigor_overlap = overlap_primario / len(palavras_primarias)
                if rigor_overlap < 0.6: # Exige que pelo menos 60% das palavras principais batam
                    keyword_score *= 0.1
                    logger.debug(f"   ❌ Rigor insuficiente: '{cand}' (Overlap primário: {rigor_overlap:.2f})")
            
            # 4. Sufixo Penalty: Evita match por número (ex: Borderlands 2 vs Spider-man 2)
            sufixo_penalty = 0
            if overlap_primario == 0 and overlap > 0:
                sufixo_penalty = 0.8 # Quase mata o match se só bater o número
            
            final_score = (keyword_score * 0.7) + (seq_match * 0.3) - sufixo_penalty
            
            if final_score > highest_score:
                highest_score = final_score
                melhor_match = cand
                
        if highest_score < 0.6:
            logger.info(f"⚠️ [PCControl] Nenhum candidato qualificado para '{termo}'. Melhor: '{melhor_match}' ({highest_score:.2f})")
            return None
            
        logger.info(f"✅ [PCControl] Match vitorioso: '{melhor_match}' (Score: {highest_score:.2f})")
        return melhor_match

    def deep_search_disk(self, nome: str) -> str:
        """
        Busca física em todos os drives por pastas que combinem com o nome.
        """
        logger.info(f"🕵️ [DeepSearch] Iniciando crawler em discos locais para: {nome}")
        drives = ['D:', 'C:', 'G:', 'E:', 'F:']
        termo = nome.lower().strip()
        
        for drive in drives:
            drive_path = drive + "\\"
            if not os.path.exists(drive_path): continue
            
            logger.info(f"🔎 [DeepSearch] Vasculhando Drive {drive}...")
            
            bibliotecas = ['games', 'Jogos', 'SteamLibrary\\steamapps\\common', 'Program Files (x86)', 'Program Files', 'Epic Games', 'Riot Games']
            for lib in bibliotecas:
                base_lib = os.path.join(drive_path, lib)
                if not os.path.exists(base_lib): continue
                
                try:
                    pastas = [d for d in os.listdir(base_lib) if os.path.isdir(os.path.join(base_lib, d))]
                    match_pasta = self.match_inteligente(termo, pastas)
                    
                    if match_pasta:
                        pasta_alvo = os.path.join(base_lib, match_pasta)
                        logger.info(f"📍 [DeepSearch] Pasta encontrada: {pasta_alvo}")
                        melhor_exe = self._encontrar_executavel_principal(pasta_alvo, termo)
                        if melhor_exe: return melhor_exe
                except: continue
        return None

    def _encontrar_executavel_principal(self, pasta: str, termo: str) -> str:
        """Analisa a pasta e escolhe o .exe mais relevante."""
        candidatos = []
        logger.info(f"📁 [Scoring] Analisando executáveis em: {pasta}")
        
        for root, dirs, files in os.walk(pasta):
            # Ignora subpastas irrelevantes
            if any(x in root.lower() for x in ['engine', 'redist', 'anticheat', 'tools', 'crash', 'logs', 'binaries']):
                continue
                
            for file in files:
                if file.lower().endswith('.exe'):
                    name = file.rsplit('.', 1)[0].lower()
                    if any(x in name for x in ['unins', 'crash', 'setup', 'helper', 'dxwebsetup', 'report', 'unity', 'launcher_']):
                        continue
                    candidatos.append(os.path.join(root, file))

        if not candidatos: return None
        
        # Scoring de Relevância
        best_path = None
        highest_score = -1
        nome_pasta_pai = os.path.basename(pasta).lower()
        
        for path in candidatos:
            name = os.path.basename(path).lower().rsplit('.', 1)[0]
            score = 0
            
            # Bônus se o nome do EXE for igual ao da PASTA (Muito comum em jogos)
            if name == nome_pasta_pai: score += 30
            elif name in nome_pasta_pai or nome_pasta_pai in name: score += 15
            
            # Bônus se bater com o termo de busca do usuário
            if termo in name: score += 10
            
            # Penaliza nomes genéricos
            if name in ['launcher', 'game', 'play', 'start', 'shipping', 'client']: score -= 5
            
            logger.debug(f"   ⚖️  EXE: {name} | Score: {score}")
            
            if score > highest_score:
                highest_score = score
                best_path = path
        
        if best_path:
            logger.info(f"🎯 [Scoring] Vencedor: {os.path.basename(best_path)} (Score: {highest_score})")
        return best_path

    def inicializar(self):
        try:
            if voicemeeterlib:
                try:
                    self.vm = voicemeeterlib.api('banana')
                    self.vm.login()
                    logger.info("[PCControl] Voicemeeter conectado.")
                except Exception as e:
                    logger.warning(f"[PCControl] Falha ao logar no Voicemeeter: {e}")

            self._init_spotify()
            
            if pyautogui:
                try:
                    pyautogui.PAUSE = 0
                    pyautogui.FAILSAFE = False
                except: pass
            
            # Inicia mapeamento neural em background
            if not os.getenv("RENDER"):
                threading.Thread(target=self.mapear_todos_apps, daemon=True).start()
                
            return True
        except Exception as e:
            logger.error(f"[PCControl] Erro na inicialização: {e}")
            return False

    def _init_spotify(self):
        if not spotipy or not self.spot_id: return
        try:
            scope = "user-modify-playback-state,user-read-currently-playing,user-read-playback-state,user-library-modify,user-library-read"
            auth = SpotifyOAuth(client_id=self.spot_id, client_secret=self.spot_secret, redirect_uri=self.spot_uri, scope=scope, open_browser=True)
            self.sp = spotipy.Spotify(auth_manager=auth)
            logger.info("[PCControl] Spotify conectado.")
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

    def ciclar_saida(self, canal=3):
        if not self.vm: return False
        try:
            a1 = int(self.vm.get(f'Strip[{canal}].A1'))
            a2 = int(self.vm.get(f'Strip[{canal}].A2'))
            if a1 == 1:
                self.toggle_rota(canal, "A1", False)
                self.toggle_rota(canal, "A2", True)
            else: 
                self.toggle_rota(canal, "A2", False)
                self.toggle_rota(canal, "A1", True)
            return True
        except: return False

    def toggle_rota(self, canal, saida, estado):
        if self.vm:
            self.vm.set(f"Strip[{canal}].{saida.upper()}", 1 if estado else 0)

    def mutar_mic(self):
        if self.vm:
            curr = int(self.vm.get('Strip[0].Mute'))
            self.vm.set('Strip[0].Mute', 0 if curr == 1 else 1)

    # --- AÇÕES DE SISTEMA ---
    def abrir_app(self, app_key):
        chave = app_key.lower().strip()
        logger.info(f"🚀 [Launch] Iniciando sequência para abrir: '{chave}'")
        
        # 1. Tenta o mapeamento conhecido
        path = self.app_paths.get(chave)
        if path:
            logger.info(f"✅ [Launch] App mapeado encontrado: {path}")
            self.executar_comando_direto(path)
            return

        # 2. Busca no índice neural (Fuzzy + Keyword)
        candidatos = list(self.indexed_apps.keys())
        match = self.match_inteligente(chave, candidatos)
        
        if match:
            path_encontrado = self.indexed_apps[match]
            logger.info(f"✅ [Launch] Match encontrado no índice: {match}")
            self.salvar_mapeamento(chave, path_encontrado)
            self.app_paths[chave] = path_encontrado
            self.executar_comando_direto(path_encontrado)
            return

        # 3. Deep Search
        path_deep = self.deep_search_disk(app_key)
        if path_deep:
            logger.info(f"✅ [Launch] Deep Crawler recuperou o alvo: {path_deep}")
            self.salvar_mapeamento(chave, path_deep)
            self.app_paths[chave] = path_deep
            self.executar_comando_direto(path_deep)
        else:
            logger.warning(f"❌ [Launch] App '{chave}' não localizado. Tentando execução direta.")
            self.executar_comando_direto(app_key)

    def executar_comando_direto(self, alvo):
        try:
            logger.info(f"[PCControl] Executando alvo: {alvo}")
            
            # Tratamento de URI (Steam/Web)
            if "://" in alvo:
                webbrowser.open(alvo)
                return

            # Tratamento de atalho Steam (.url)
            if alvo.lower().endswith(".url"):
                try:
                    with open(alvo, 'r', errors='ignore') as f:
                        for line in f:
                            if line.startswith('URL=') and 'steam://' in line:
                                webbrowser.open(line.split('=', 1)[1].strip())
                                return
                except: pass

            # Execução de Arquivo Local com Contexto
            if os.path.exists(alvo):
                wdir = os.path.dirname(alvo)
                try:
                    os.startfile(alvo)
                except:
                    # Fallback via Shell 'start' (Crucial para alguns jogos)
                    subprocess.Popen(f'start "" "{alvo}"', shell=True, cwd=wdir)
            else:
                # Fallback final como comando de terminal
                subprocess.Popen(alvo, shell=True)
                
        except Exception as e:
            logger.error(f"[PCControl] Erro na execução de {alvo}: {e}")

    def abrir_url(self, url):
        url_limpa = url.lower().strip()
        if "." not in url_limpa: url_limpa += ".com"
        if not url_limpa.startswith("http"): url_limpa = "https://" + url_limpa
        try:
            if not webbrowser.open(url_limpa):
                os.system(f'start "" "{url_limpa}"')
        except: self.executar_comando_direto(url_limpa)

    def pesquisa_google(self, query):
        url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        self.executar_comando_direto(url)

    def bloquear_pc(self):
        os.system("rundll32.exe user32.dll,LockWorkStation")

    def dormir_pc(self):
        os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")

    def executar_macro(self, macro_key):
        keys = self.macros.get(macro_key)
        if keys and pyautogui: pyautogui.hotkey(*keys)

    def set_modo_imersao(self, ativo: bool):
        if not self.vm: return
        if ativo:
            self.vm.set('Strip[0].Mute', 1)
            if pyautogui: pyautogui.hotkey('win', 'd')
            self.set_gain(4, 30)
        else:
            self.vm.set('Strip[0].Mute', 0)
            self.set_gain(4, 70)

    # --- COLETA DE DADOS ---
    def obter_estado_completo(self):
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent
        disco = 0
        try: disco = psutil.disk_usage('C:').percent
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
            "sistema": {"cpu": cpu, "ram": ram, "disco": disco}
        }

pc_control_service = PcControlService()
