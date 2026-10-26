"""Ordens explícitas para o Android. Não interpreta notificações nem inventa parâmetros."""
import re

from servicos.controle_casa import normalizar
from servicos.roteamento_pedidos import destino_explicito

COMANDOS_LEGADOS = frozenset({"set_timer", "timer", "set_alarm", "alarme", "configurar_despertar", "despertar", "configurar_alarme",
    "toggle_flashlight", "lanterna", "set_volume", "volume", "set_brightness", "brilho", "set_dnd", "modo_nao_perturbe", "foco",
    "toggle_wifi", "wifi", "toggle_bluetooth", "bluetooth", "global_back", "voltar", "global_home", "home", "global_recents", "recentes", "click_text", "clicar"})


def _acao(nome, **parametros):
    return {"acao": nome, "parametros": parametros}


def interpretar_controle(texto, origem="MOBILE"):
    original = str(texto).strip()
    t = normalizar(original).strip(" .!?")
    t = re.sub(r"^(?:ei )?ollie[, ]+", "", t)
    t = re.sub(r"^(?:por favor[, ]+)?(?:(?:voce )?(?:pode|poderia|consegue) |quero que voce )?", "", t)
    # O corpo de mensagem é literal e não pode ser normalizado ou separado em ordens.
    msg = re.fullmatch(r"(?:ollie[, ]+)?(?:pode |por favor )?(?:mande|manda|envie|envia|enviar) (?:uma )?mensagem (?:para|pra|pro) (.+?) (?:no|pelo) (whatsapp|instagram) (?:dizendo|falando|com o texto)\s*[: ,]?\s*(.+)", original, re.I)
    if msg:
        if len(msg[1]) > 100 or len(msg[3]) > 2000:
            return {"esclarecimento": "Preciso de um destinatário curto e de uma mensagem com até 2.000 caracteres."}
        return {"acoes": [_acao("message.prepare", app=msg[2].lower(), destinatario=msg[1].strip(), texto=msg[3].strip())]}
    try:
        destino = destino_explicito(t)
    except ValueError:
        return {"esclarecimento": "Você mencionou os dois aparelhos. Esse controle é para o celular?"}
    if destino == "PC":
        return None
    if re.match(r"(?:mande|manda|envie|envia|enviar) (?:uma )?mensagem\b", t):
        return {"esclarecimento": "Diga, por exemplo: mande mensagem para Ana no WhatsApp dizendo chego às oito. Vou mostrar o texto antes de enviar."}
    if re.search(r"\b(?:nao|nunca|se|quando|ontem|como fazer|como funciona)\b", t.replace("nao perturbe", "dnd")):
        return None
    t = re.sub(r" (?:no|pelo|pro|para o) (?:meu )?(?:celular|telefone|android)\b", "", t)
    t = re.sub(r"(?: pra mim| para mim| por favor)$", "", t).strip()
    # Só aceita um plano inteiro reconhecido. Nunca executa um prefixo e ignora o resto.
    partes = re.split(r"\s+e\s+(?:depois\s+)?(?=(?:ligue|liga|desligue|desliga|ative|ativa|desative|ajuste|coloque|aumente|abaixe|diminua|abra)\b)|;\s*", t)
    if len(partes) > 1:
        if len(partes) > 6:
            return {"esclarecimento": "Vamos dividir em até seis controles por pedido."}
        planos = [interpretar_controle(p + " no celular", origem) for p in partes]
        if all(p and p.get("acoes") for p in planos):
            return {"acoes": [a for p in planos for a in p["acoes"]]}
        return {"esclarecimento": "Não consegui entender todas as etapas. Diga cada controle do celular separadamente."}
    m = re.fullmatch(r"(ligue|liga|ative|ativa|acenda|acende|desligue|desliga|desative|desativa|apague|apaga) (?:a |o )?(lanterna|flash|gps|localizacao|wi-?fi|bluetooth|nao perturbe)", t)
    if m:
        estado = m[1] in {"ligue", "liga", "ative", "ativa", "acenda", "acende"}
        alvo = m[2]
        if alvo in {"lanterna", "flash"}:
            return {"acoes": [_acao("flashlight.set", estado=estado)]}
        if alvo == "nao perturbe":
            return {"acoes": [_acao("dnd.set", estado=estado)]}
        painel = {"gps": "location", "localizacao": "location", "wifi": "wifi", "wi-fi": "wifi", "bluetooth": "bluetooth"}[alvo]
        return {"acoes": [_acao("settings.open", painel=painel, estado_desejado=estado)]}
    # Som e navegação pertencem ao aparelho de origem, salvo destino explícito.
    if origem == "PC" and destino != "MOBILE" and re.search(r"\b(?:volume|brilho|modo|silencioso|vibrar|volte|volta|tela inicial|notificacoes)\b", t):
        return None
    m = re.fullmatch(r"(?:ajuste|coloque|bote|defina|mude) (?:o )?(volume|brilho)(?: (?:de |do )?(midia|musica|alarme|toque|notificacoes))? (?:em|para|pra) (\d{1,3})(?:\s*%| por cento)?", t)
    if m:
        valor = int(m[3])
        if not 0 <= valor <= 100:
            return {"esclarecimento": "Escolha um valor entre 0 e 100%."}
        canal = {None: "media", "midia": "media", "musica": "media", "alarme": "alarm", "toque": "ring", "notificacoes": "notification"}[m[2]]
        return {"acoes": [_acao("brightness.set", valor=valor) if m[1] == "brilho" else _acao("volume.set", canal=canal, valor=valor)]}
    m = re.fullmatch(r"(?:coloque|bote|ative|ativa|mude para) (?:o )?(?:celular (?:no|em) )?(?:modo )?(silencioso|vibrar|vibracao|normal|som)", t)
    if m:
        return {"acoes": [_acao("sound.mode", modo={"silencioso": "silent", "vibrar": "vibrate", "vibracao": "vibrate", "normal": "normal", "som": "normal"}[m[1]])]}
    nav = {"volte": "back", "volta": "back", "volte uma tela": "back", "va para a tela inicial": "home", "abra a tela inicial": "home", "abra os aplicativos recentes": "recents", "abra as notificacoes": "notifications"}
    if t in nav:
        return {"acoes": [_acao("navigation", destino=nav[t])]}
    if t in {"abra os controles do celular", "abra controles do celular", "mostre os controles do celular"}:
        return {"acoes": [_acao("controls.open")]}
    m = re.fullmatch(r"(?:inicie|inicia|crie|cria|coloque|coloca|marque|marca|defina) (?:um )?(?:timer|temporizador)(?: (?:de|para))? (.+)", t)
    if m:
        duracao = m[1]
        partes = list(re.finditer(r"(\d+)\s*(horas?|h|minutos?|min|segundos?|s)\b", duracao))
        resto = re.sub(r"(\d+)\s*(horas?|h|minutos?|min|segundos?|s)\b", "", duracao).strip(" e,")
        if not partes or resto:
            return {"esclarecimento": "Qual a duração? Diga, por exemplo: timer de 5 minutos."}
        segundos = sum(int(p[1]) * (3600 if p[2].startswith("h") else 60 if p[2].startswith("m") else 1) for p in partes)
        if not 1 <= segundos <= 86400:
            return {"esclarecimento": "O timer precisa durar entre um segundo e 24 horas."}
        return {"acoes": [_acao("timer.create", segundos=segundos)]}
    m = re.fullmatch(r"(?:crie|cria|coloque|coloca|marque|marca|defina|ative|ativa) (?:um )?(?:alarme|despertador) (?:para |pra |as |pras )?(?:as )?(\d{1,2})(?:(?::|h| e )(\d{1,2}))?(?: horas?)?", t)
    if m:
        hora, minuto = int(m[1]), int(m[2] or 0)
        if hora > 23 or minuto > 59:
            return {"esclarecimento": "Qual o horário, entre 00:00 e 23:59?"}
        return {"acoes": [_acao("alarm.create", hora=hora, minuto=minuto)]}
    return None


def validar_acao(acao, parametros):
    """Contrato fechado, também aplicado antes de enviar para um dispositivo."""
    p = parametros
    if not isinstance(p, dict):
        raise ValueError("Parâmetros inválidos")
    def inteiro(chave, minimo, maximo):
        return type(p.get(chave)) is int and minimo <= p[chave] <= maximo
    def booleano(chave):
        return type(p.get(chave)) is bool
    regras = {
        "flashlight.set": ({"estado"}, lambda: booleano("estado")),
        "dnd.set": ({"estado"}, lambda: booleano("estado")),
        "volume.set": ({"canal", "valor"}, lambda: p.get("canal") in {"media", "ring", "alarm", "notification"} and inteiro("valor", 0, 100)),
        "brightness.set": ({"valor"}, lambda: inteiro("valor", 0, 100)),
        "sound.mode": ({"modo"}, lambda: p.get("modo") in {"normal", "vibrate", "silent"}),
        "timer.create": ({"segundos"}, lambda: inteiro("segundos", 1, 86400)),
        "alarm.create": ({"hora", "minuto"}, lambda: inteiro("hora", 0, 23) and inteiro("minuto", 0, 59)),
        "settings.open": ({"painel", "estado_desejado"}, lambda: p.get("painel") in {"location", "wifi", "bluetooth"} and booleano("estado_desejado")),
        "navigation": ({"destino"}, lambda: p.get("destino") in {"back", "home", "recents", "notifications"}),
        "controls.open": (set(), lambda: True),
        "message.prepare": ({"app", "destinatario", "texto"}, lambda: p.get("app") in {"whatsapp", "instagram"} and all(isinstance(p.get(k), str) and 0 < len(p[k].strip()) <= n for k, n in (("destinatario", 100), ("texto", 2000)))),
    }
    regra = regras.get(acao)
    if not regra or set(p) != regra[0] or not regra[1]():
        raise ValueError("Ação ou parâmetros de controle inválidos")
