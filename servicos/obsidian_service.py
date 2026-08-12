import os
import logging
import toml
from typing import List, Dict

logger = logging.getLogger("ObsidianService")

class ObsidianService:
    def __init__(self):
        try:
            config = toml.load("D:/Programacao/AssistenteCell/config.toml")
            self.vault_path = config.get("obsidian", {}).get("vault_path", "D:/Programacao/AssistenteCell/Ollie")
            self.agente_dir = os.path.join(self.vault_path, "Agente")
            
            if not os.path.exists(self.agente_dir):
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

    def listar_conhecimento_essencial(self) -> str:
        """Retorna um consolidado de notas na raiz e na pasta Agente/."""
        if not self.vault_path: return "Conhecimento Obsidian indisponível."
        
        consolidado = []
        try:
            # 1. Lê notas principais da raiz
            notas_raiz = ["Rotinas.md", "Gostos.md", "Identidade.md", "Projetos.md"]
            for nota in notas_raiz:
                c = self.ler_nota(nota)
                if c.strip():
                    consolidado.append(f"### NOTA RAIZ: {nota}\n{c.strip()}")
                    logger.info(f"📓 [Obsidian] Carregada nota da raiz: {nota}")

            # 2. Lê fatos extras da pasta Agente/
            if os.path.exists(self.agente_dir):
                arquivos = [f for f in os.listdir(self.agente_dir) if f.endswith(".md")]
                for filename in arquivos:
                    if filename in notas_raiz: continue
                    conteudo = self.ler_nota(filename)
                    if conteudo.strip():
                        consolidado.append(f"### FATO APRENDIDO: {filename}\n{conteudo.strip()}")
                        logger.info(f"📓 [Obsidian] Carregado fato: {filename}")
        except Exception as e:
            logger.error(f"Erro ao listar conhecimento do Obsidian: {e}")
        
        return "\n\n".join(consolidado) if consolidado else "Ollie ainda está aprendendo sobre você."

obsidian_service = ObsidianService()
