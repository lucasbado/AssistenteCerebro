"""Origem, destino e resposta são decisões do sistema, independentes da LLM."""
import re
from servicos.controle_casa import normalizar

APPS = {
    "youtube": (("abrir_url", "https://www.youtube.com/"), ("OPEN_APP", "com.google.android.youtube")),
    "spotify": (("abrir_app", "spotify"), ("OPEN_APP", "com.spotify.music")),
    "whatsapp": (("abrir_app", "whatsapp"), ("OPEN_APP", "com.whatsapp")),
    "telegram": (("abrir_app", "telegram"), ("OPEN_APP", "org.telegram.messenger")),
    "instagram": (("abrir_url", "https://www.instagram.com/"), ("OPEN_APP", "com.instagram.android")),
    "tiktok": (("abrir_url", "https://www.tiktok.com/"), ("OPEN_APP", "com.zhiliaoapp.musically")),
    "chrome": (("abrir_app", "chrome"), ("OPEN_APP", "com.android.chrome")),
}
ALIASES = {"you tube": "youtube", "youtube.com": "youtube", "www.youtube.com": "youtube", "tik tok": "tiktok"}
for nome, (_, mobile) in APPS.items():
    ALIASES[mobile[1]] = nome


def metadados_entrada(dispositivo, canal="texto"):
    return {"pedido_usuario": True, "dispositivo_origem": dispositivo,
            "canal_origem": "voz" if canal == "voz" else "texto"}


def dispositivo_origem(evento):
    origem = evento.metadados.get("dispositivo_origem")
    if origem in {"PC", "MOBILE"}:
        return origem
    return "PC" if evento.pacote.startswith("pc.") or evento.origem == "PC" else "MOBILE"


def contexto_pedido(evento):
    return {**evento.metadados, **metadados_entrada(dispositivo_origem(evento), evento.metadados.get("canal_origem"))}


def destino_explicito(texto):
    t = normalizar(texto)
    pc = re.search(r"\b(?:no|pelo|pro|para o) (?:meu |seu |este |esse )?(?:pc|computador|desktop|notebook)\b", t)
    mobile = re.search(r"\b(?:no|pelo|pro|para o) (?:meu |seu |este |esse )?(?:celular|telefone|smartphone|android)\b", t)
    if pc and mobile:
        raise ValueError("Você mencionou PC e celular. Em qual deles devo abrir?")
    return "PC" if pc else "MOBILE" if mobile else None


def resolver_abertura(evento, comando, parametro):
    destino = destino_explicito(evento.payload.get("texto", "")) or dispositivo_origem(evento)
    command = str(comando).lower()
    from servicos.intervention_governor import APP_ALIASES
    if command in APP_ALIASES:
        parametro, command = command, "abrir_app"
    if command in {"open_url", "abrir_url", "abrir_url_mobile"}:
        return destino, "abrir_url" if destino == "PC" else "OPEN_URL", parametro
    if command in {"pesquisa_google", "web_search", "pesquisar"}:
        return destino, "pesquisa_google" if destino == "PC" else "WEB_SEARCH", parametro
    if command in {"abrir_notificacao", "abrir_mensagem", "read_message"}:
        if destino != "MOBILE":
            raise ValueError("Essa mensagem só pode ser aberta no celular. Diga ‘no celular’ para abrir lá.")
        return destino, command.upper(), parametro
    nome = str(parametro).strip().lower()
    nome = ALIASES.get(nome, nome)
    if nome in APPS:
        cmd, param = APPS[nome][0 if destino == "PC" else 1]
        return destino, cmd, param
    if destino == "MOBILE" and (nome.endswith(".exe") or nome in APP_ALIASES - {"spotify", "chrome"}):
        raise ValueError("Esse aplicativo é de PC. Diga ‘no PC’ para abrir lá.")
    return destino, "abrir_app" if destino == "PC" else "OPEN_APP", parametro


def interpretar_abertura(texto):
    from servicos.abertura_apps import pedido_explicito_de_abertura
    if not pedido_explicito_de_abertura(texto):
        return None
    t = normalizar(texto)
    nomes = "youtube|you tube|spotify|whatsapp|telegram|instagram|tiktok|tik tok|chrome"
    prefixo = r"(?:ollie[, ]+)?(?:por favor[, ]+)?(?:pode |poderia |quero que voce |quero )?"
    suffix = r"(?: (?:no|pelo|pro|para o) (?:meu |seu |este |esse )?(?:pc|computador|desktop|notebook|celular|telefone|smartphone|android))?(?: por favor)?[.!?]*"
    match = re.fullmatch(prefixo + r"(?:abre|abra|abrir|inicie|inicia|iniciar) (?:o |a )?(" + nomes + r")" + suffix, t)
    if match:
        return {"execucao_direta": [{"alvo": "ORIGEM", "comando": "abrir_app", "parametro": match[1]}],
                "mensagem_dinamica": "", "tipo_interacao": "NOTIFICAR"}
    return None


async def responder_pedido(evento, texto):
    from core.tipos import CategoriaEvento, TipoAcao, OrigemEvento
    from core.kernel import kernel
    await kernel.publicar(evento.clonar(categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
        acao=TipoAcao.INTENCAO_INTERACAO, origem=OrigemEvento.IA,
        payload={"texto": texto, "titulo": "Ollie", "tipo_ws": "CHAT_RESPONSE"},
        metadados={**contexto_pedido(evento), "tipo_destino": "CHAT"}))
