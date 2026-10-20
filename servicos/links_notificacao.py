"""Destinos de sugestões vêm da notificação atual, nunca do histórico ou da LLM."""
import re
from urllib.parse import urlsplit

PLATAFORMAS = {
    "tiktok": "tiktok.com", "tik tok": "tiktok.com",
    "com.zhiliaoapp.musically": "tiktok.com", "com.ss.android.ugc.trill": "tiktok.com",
    "instagram": "instagram.com", "com.instagram.android": "instagram.com",
    "youtube": "youtube.com", "com.google.android.youtube": "youtube.com",
}
COMANDOS_URL = {"open_url", "abrir_url", "abrir_url_mobile"}


def links_atuais(payload):
    textos = [payload.get("texto"), payload.get("conversa_completa")]
    mensagens = payload.get("mensagens")
    if isinstance(mensagens, list):
        textos.extend(m for m in mensagens if isinstance(m, str))
    links = []
    for texto in textos:
        if not isinstance(texto, str):
            continue
        for match in re.finditer(r"https?://[^\s<>\"']+", texto, re.IGNORECASE):
            link = match.group().rstrip(".,;")
            for abertura, fechamento in (("(", ")"), ("[", "]"), ("{", "}")):
                while link.endswith(fechamento) and link.count(fechamento) > link.count(abertura):
                    link = link[:-1]
            try:
                if not urlsplit(link).hostname:
                    continue
            except ValueError:
                continue
            if link not in links:
                links.append(link)
    return links


def destino_de_link(payload, comando, parametro):
    """Retorna (é sugestão de link, URL verificável ou None).

    None pede voltar ao aplicativo de origem para escolher a mensagem.
    """
    dominio = PLATAFORMAS.get(str(parametro).strip().lower())
    url_command = str(comando).lower() in COMANDOS_URL
    if not dominio and not url_command:
        return False, None
    links = links_atuais(payload)
    if url_command:
        # Só aceitar o endereço proposto se ele constar integralmente na mensagem.
        return True, parametro if parametro in links else None
    correspondentes = []
    for link in links:
        host = urlsplit(link).hostname.lower()
        if host == dominio or host.endswith("." + dominio) or (dominio == "youtube.com" and host == "youtu.be"):
            correspondentes.append(link)
    return True, correspondentes[0] if len(correspondentes) == 1 else None
