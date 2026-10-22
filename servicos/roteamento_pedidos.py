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


def resolver_abertura(evento, comando, parametro, texto_etapa=None):
    destino = destino_explicito(texto_etapa if texto_etapa is not None else evento.payload.get("texto", "")) or dispositivo_origem(evento)
    command = str(comando).lower()
    from servicos.intervention_governor import APP_ALIASES
    if command in APP_ALIASES:
        parametro, command = command, "abrir_app"
    nome = str(parametro).strip().lower()
    nome = ALIASES.get(nome, nome)
    if nome in APPS and command not in {"pesquisa_google", "web_search", "pesquisar", "abrir_notificacao", "abrir_mensagem", "read_message"}:
        cmd, param = APPS[nome][0 if destino == "PC" else 1]
        return destino, cmd, param
    from servicos.sites_pc import resolver_site_pc, url_explicita
    if command in {"abrir_app", "open_app", "abrir_programa", "abrir_app_mobile", "launch_app", "open_url", "abrir_url", "abrir_url_mobile"}:
        url = resolver_site_pc(parametro) if destino == "PC" else url_explicita(parametro)
        if url:
            return destino, "abrir_url" if destino == "PC" else "OPEN_URL", url
    if command in {"open_url", "abrir_url", "abrir_url_mobile"}:
        return destino, "abrir_url" if destino == "PC" else "OPEN_URL", parametro
    if command in {"pesquisa_google", "web_search", "pesquisar"}:
        return destino, "pesquisa_google" if destino == "PC" else "WEB_SEARCH", parametro
    if command in {"abrir_notificacao", "abrir_mensagem", "read_message"}:
        if destino != "MOBILE":
            raise ValueError("Essa mensagem só pode ser aberta no celular. Diga ‘no celular’ para abrir lá.")
        return destino, command.upper(), parametro
    if destino == "MOBILE" and (nome.endswith(".exe") or nome in APP_ALIASES - {"spotify", "chrome"}):
        raise ValueError("Esse aplicativo é de PC. Diga ‘no PC’ para abrir lá.")
    return destino, "abrir_app" if destino == "PC" else "OPEN_APP", parametro


def interpretar_abertura(texto, site_busca=None):
    from servicos.abertura_apps import pedido_explicito_de_abertura
    if not pedido_explicito_de_abertura(texto):
        return None
    prefixo = r"(?:ollie[, ]+)?(?:por favor[, ]+)?(?:voc[eê] )?(?:pode |poderia |consegue |quero que voc[eê] |quero )?"
    suffix = r"(?: (?:no|pelo|pro|para o) (?:meu |seu |este |esse )?(?:pc|computador|desktop|notebook|celular|telefone|smartphone|android))?(?: por favor)?[.!?]*"
    raw_text = str(texto).strip()
    search = re.fullmatch(prefixo + r"(?:pesquise|pesquisa|pesquisar|busque|busca|buscar|procure|procura|procurar)\s+(.+?)" + suffix, raw_text, re.I)
    if search:
        termo = search[1]
        # Uma conjunção seguida de outra ordem deve ser planejada por etapas.
        from servicos.linguagem_pedidos import separar_etapas
        if len(separar_etapas(termo)) > 1:
            return None
        from servicos.buscas_web import url_busca
        site = site_busca
        inicio = re.fullmatch(r"(?:no|na)\s+(Google|YouTube|GitHub|[\w.-]+\.[a-z]{2,})\s+(?:por\s+|sobre\s+)?(.+)", termo, re.I)
        fim = re.fullmatch(r"(.+?)\s+(?:no|na)\s+(Google|YouTube|GitHub|[\w.-]+\.[a-z]{2,})", termo, re.I)
        if inicio:
            site, termo = inicio[1], inicio[2]
        elif fim:
            termo, site = fim[1], fim[2]
        return {"execucao_direta": [{"alvo": "ORIGEM", "comando": "abrir_url", "parametro": url_busca(termo, site)}],
                "mensagem_dinamica": "", "tipo_interacao": "NOTIFICAR"}
    match = re.fullmatch(prefixo + r"(?:abre|abra|abrir|inicie|inicia|iniciar|acesse|acessa|acessar|entre|entrar|visite|visitar) (?:em |no |na |o |a )?(?:(?:site|app|aplicativo) (?:do |da )?)?(.+?)" + suffix, raw_text, re.I)
    if match:
        if len(match[1]) > 250 or re.search(r"\b(?:e|depois|tambem|quando|porque|se|mas|nao|nunca)\b", normalizar(match[1])):
            return None
        # Preserve URL path/query casing; normalization is for the verb and destination only.
        raw = re.search(r"https?://\S+", str(texto), re.I)
        parametro = raw.group().rstrip(".,") if raw else match[1]
        web = re.search(r'\b(?:acesse|acessa|acessar|entre|visite|visitar|site)\b', normalizar(raw_text))
        if web:
            from servicos.sites_pc import resolver_site_pc
            nome = ALIASES.get(normalizar(parametro), normalizar(parametro))
            if not resolver_site_pc(parametro) and nome not in APPS:
                return None  # Let reasoning ask/resolve a web address, rather than launch a guessed app.
        return {"execucao_direta": [{"alvo": "ORIGEM", "comando": "abrir_app", "parametro": parametro}],
                "mensagem_dinamica": "", "tipo_interacao": "NOTIFICAR"}
    return None


async def responder_pedido(evento, texto):
    from core.tipos import CategoriaEvento, TipoAcao, OrigemEvento
    from core.kernel import kernel
    await kernel.publicar(evento.clonar(categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
        acao=TipoAcao.INTENCAO_INTERACAO, origem=OrigemEvento.IA,
        payload={"texto": texto, "titulo": "Ollie", "tipo_ws": "CHAT_RESPONSE"},
        metadados={**contexto_pedido(evento), "tipo_destino": "CHAT"}))
