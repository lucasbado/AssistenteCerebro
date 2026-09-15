import os
import logging
import toml
from typing import List, Dict

logger = logging.getLogger("ObsidianService")

class ObsidianService:
    def __init__(self):
        try:
            # Tenta carregar do caminho absoluto (Local) ou relativo (Cloud/Local)
            config_path = "D:/Programacao/AssistenteCell/config.toml"
            if not os.path.exists(config_path):
                config_path = "config.toml"

            config = {}
            if os.path.exists(config_path):
                config = toml.load(config_path)
            
            # Prioriza variável de ambiente, depois config.toml, depois fallback
            self.vault_path = os.getenv("OBSIDIAN_VAULT_PATH") or \
                              config.get("obsidian", {}).get("vault_path", "D:/Programacao/AssistenteCell/Ollie")
            
            # Na nuvem, se o caminho absoluto falhar, tenta relativo
            if not os.path.exists(self.vault_path):
                self.vault_path = "Ollie"

            self.agente_dir = os.path.join(self.vault_path, "Agente")
            
            if self.vault_path and not os.path.exists(self.agente_dir):
                os.makedirs(self.agente_dir)
                logger.info(f"Diretório de aprendizado criado: {self.agente_dir}")
        except Exception as e:
            logger.error(f"Erro ao inicializar ObsidianService: {e}")
            self.vault_path = None

    def ler_nota(self, nome_arquivo: str) -> str:
        """Lê o conteúdo de uma nota específica (pode estar na raiz ou em Agente/)."""
        if not self.vault_path: return ""
        
        paths_to_try = [
            os.path.join(self.vault_path, nome_arquivo),
            os.path.join(self.agente_dir, nome_arquivo)
        ]
        
        for path in paths_to_try:
            if not path.endswith(".md"): path += ".md"
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        return f.read()
                except Exception as e:
                    logger.error(f"Erro ao ler nota {path}: {e}")
        return ""

    def registrar_fato(self, titulo: str, conteudo: str):
        """Salva ou anexa um fato novo na pasta Agente/."""
        if not self.vault_path: return
        
        # 🛡️ CORREÇÃO: Remove extensão duplicada e limpa o nome
        safe_title = titulo.replace(".md", "").strip().replace(" ", "_")
        filename = f"{safe_title}.md"
        path = os.path.join(self.agente_dir, filename)
        
        try:
            # 🛡️ VERIFICAÇÃO: Evita anexar exatamente o mesmo conteúdo repetidamente
            conteudo_existente = self.ler_nota(filename)
            if conteudo.strip() in conteudo_existente:
                logger.debug(f"Fato já existente na nota {filename}. Pulando.")
                return

            mode = "a" if os.path.exists(path) else "w"
            with open(path, mode, encoding="utf-8") as f:
                if mode == "a": f.write("\n\n---\n")
                f.write(conteudo)
            logger.info(f"Fato registrado em {path}")
        except Exception as e:
            logger.error(f"Erro ao registrar fato no Obsidian: {e}")

    def buscar_nota_relevante(self, texto_usuario: str) -> str:
        """Busca no vault por notas que contenham palavras-chave do texto do usuário."""
        if not self.vault_path: return ""
        
        # Extrai palavras-chave simples
        palavras = [p for p in texto_usuario.lower().split() if len(p) > 3]
        if not palavras: return ""

        notas_relevantes = []
        try:
            # Varre apenas os títulos das notas para ser rápido
            for root, _, files in os.walk(self.vault_path):
                for file in files:
                    if file.endswith(".md"):
                        nome_nota = file.lower()
                        if any(p in nome_nota for p in palavras):
                            conteudo = self.ler_nota(file)
                            if conteudo:
                                notas_relevantes.append(f"### NOTA RELACIONADA ({file}):\n{conteudo.strip()[:500]}")
                                if len(notas_relevantes) >= 2: break
                if len(notas_relevantes) >= 2: break
        except Exception as e:
            logger.error(f"Erro na busca seletiva Obsidian: {e}")
            
        return "\n\n".join(notas_relevantes)

    def listar_conhecimento_essencial(self, query_usuario: str = "") -> str:
        """Retorna um consolidado das notas mais cruciais (Injeção Seletiva)."""
        if not self.vault_path: return "Conhecimento Obsidian indisponível."
        
        consolidado = []
        try:
            # 1. Busca Seletiva baseada na dúvida do usuário
            if query_usuario:
                seletiva = self.buscar_nota_relevante(query_usuario)
                if seletiva: consolidado.append(seletiva)

            # 2. Notas básicas como fallback
            notas_raiz = ["Identidade.md", "Mapa_Mestre.md"]
            for nota in notas_raiz:
                if nota == "Mapa_Mestre.md" and len(consolidado) > 0: continue
                
                c = self.ler_nota(nota)
                if c.strip():
                    consolidado.append(f"### {nota.upper()}: {c.strip()[:250]}")

            # 3. Fato mais recente
            if os.path.exists(self.agente_dir):
                arquivos = [f for f in os.listdir(self.agente_dir) if f.endswith(".md")]
                arquivos.sort(key=lambda x: os.path.getmtime(os.path.join(self.agente_dir, x)), reverse=True)
                if arquivos:
                    conteudo = self.ler_nota(arquivos[0])
                    if conteudo.strip():
                        consolidado.append(f"### ÚLTIMO APRENDIZADO: {conteudo.strip()[:300]}")
        except Exception as e:
            logger.error(f"Erro ao listar conhecimento do Obsidian: {e}")
        
        return "\n\n".join(consolidado) if consolidado else "Ollie ainda está aprendendo."

obsidian_service = ObsidianService()
