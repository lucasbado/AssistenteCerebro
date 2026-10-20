"""Resolve serviços web cadastrados e endereços explícitos, sem inventar domínios."""
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from servicos.controle_casa import normalizar

CONFIG = Path(__file__).resolve().parents[1] / "config/sites_pc.json"


def url_explicita(texto):
    valor = str(texto or "").strip()
    if re.search(r"\s", valor):
        return None
    if valor.lower().startswith(("http://", "https://")):
        try:
            parsed = urlsplit(valor)
            return valor if parsed.hostname and not parsed.username and not parsed.password else None
        except ValueError:
            return None
    if re.search(r"\.(exe|dll|bat|cmd|ps1|py|lnk|msi)(?:$|[/?#])", valor, re.I):
        return None
    if re.match(r"^(?:com|org|net|io|android)\.[a-z0-9_]+\.[a-z0-9_.]+$", valor, re.I):
        return None  # Android package IDs, rather than website addresses.
    if re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}(?::\d{1,5})?(?:[/?#][^\s]*)?", valor, re.I):
        return "https://" + valor
    return None


def resolver_site_pc(destino):
    nome = normalizar(destino)
    sites = json.loads(CONFIG.read_text(encoding="utf-8"))
    for site in sites:
        if nome in {normalizar(x) for x in [site["nome"], *site["apelidos"]]}:
            url = url_explicita(site["url"])
            if not url:
                raise ValueError("Endereço inválido no catálogo de sites do PC")
            return url
    return url_explicita(destino)
