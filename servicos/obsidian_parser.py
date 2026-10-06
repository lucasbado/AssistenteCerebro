import os
import re
from pathlib import Path
from typing import Tuple, List, Set

class ObsidianParser:
    def __init__(self, vault_root: str):
        self.vault_root = Path(vault_root).resolve()

    def parse_file(self, file_path: str | Path) -> Tuple[str, List[str], str]:
        """
        Lê um arquivo .md, limpa a sintaxe do Obsidian e retorna:
        (texto_limpo, palavras_chave_tags, caminho_relativo)
        """
        path = Path(file_path).resolve()
        try:
            rel_path = str(path.relative_to(self.vault_root))
        except ValueError:
            rel_path = path.name

        with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
            raw_text = f.read()

        clean_text, tags = self.clean_markdown(raw_text)
        return clean_text, tags, rel_path

    def clean_markdown(self, text: str) -> Tuple[str, List[str]]:
        # 1. Remover Frontmatter YAML (---\n ... \n---)
        text = re.sub(r'^---\s*\n.*?\n---\s*\n', '', text, flags=re.DOTALL)

        # 2. Remover blocos de código (``` ... ```)
        text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)

        # 3. Remover blocos Dataview / Templater (<% ... %>)
        text = re.sub(r'<%.*?%>', '', text, flags=re.DOTALL)

        # 4. Remover Embeds do Obsidian (![[...]])
        text = re.sub(r'!\[\[(.*?)\]\]', '', text)

        # 5. Resolver Wikilinks ([[Nota|Texto]] -> Texto, [[Nota]] -> Nota)
        def _resolve_wikilink(match):
            content = match.group(1)
            if '|' in content:
                return content.split('|')[1]
            return content

        text = re.sub(r'\[\[(.*?)\]\]', _resolve_wikilink, text)

        # 6. Extrair Tags (#tag) para keywords e limpar do texto
        tags = re.findall(r'(?<!\S)#([a-zA-Z0-9_-]+)', text)
        text = re.sub(r'(?<!\S)#[a-zA-Z0-9_-]+', '', text)

        # 7. Limpar Callouts (> [!note] -> > note)
        text = re.sub(r'>\s*\[![a-zA-Z0-9_-]+\]', '>', text)

        # 8. Normalizar quebras de linha e espaços
        text = re.sub(r'\n\s*\n', '\n\n', text).strip()

        return text, list(set(tags))
