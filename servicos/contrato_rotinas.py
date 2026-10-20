"""Normaliza contratos antigos e explica rotinas antes da aprovação/execução."""
from copy import deepcopy
from datetime import time
import json
import re

PC_COMMANDS = {
    "abrir_app", "abrir_url", "pesquisa_google", "voicemeeter", "mutar_mic",
    "trocar_saida", "bloquear_pc", "hibernar_pc", "desligar_pc", "reiniciar_pc",
    "spotify_play", "spotify_next", "spotify_prev", "spotify_play_pause",
    "media_play_pause", "media_next", "media_prev", "executar_cenario",
    "janela_fullscreen", "janela_maximizar", "janela_minimizar", "modo_imersao",
}
MOBILE_COMMANDS = {"OPEN_APP", "ABRIR_APP_MOBILE", "ABRIR_URL_MOBILE", "FOCO", "WAKE_OLLIE"}


def chave_nome(nome):
    return str(nome).strip().casefold()


def normalizar_rotina(rotina):
    r = deepcopy(rotina)
    r["nome"] = str(r.get("nome", "")).strip()
    r.setdefault("ativa", False)
    r.setdefault("cooldown_segundos", 3600)
    for acao in r.get("acoes", []):
        alvo = str(acao.get("alvo", "")).upper()
        comando = str(acao.get("comando", ""))
        parametro = str(acao.get("parametro") or "")
        acao.update(alvo=alvo, parametro=parametro)
        if alvo == "PC":
            comando = comando.lower()
            if comando in {"launch_app", "open_app", "abrir_programa"}:
                comando = "abrir_app"
            elif comando.endswith(".exe") and not parametro:
                acao["parametro"], comando = comando, "abrir_app"
        elif alvo == "MOBILE":
            comando = comando.upper()
            if comando in {"LAUNCH_APP", "ABRIR_APP"}:
                comando = "OPEN_APP"
            if comando == "SISTEMA_COMANDO" and parametro.upper() == "ATIVAR_FOCO":
                comando, acao["parametro"] = "FOCO", "ativar"
        elif alvo == "IA":
            comando = comando.upper()
        acao["comando"] = comando
    return r


def problemas_rotina(rotina):
    r = normalizar_rotina(rotina)
    problemas = []
    if not r["nome"]:
        problemas.append("A rotina precisa de um nome.")
    g = r.get("gatilho") or {}
    tipo = g.get("tipo")
    if tipo == "APP_OPENED":
        if not g.get("pacote"):
            problemas.append("Escolha o aplicativo que dispara a rotina.")
    elif tipo == "PC_ACTIVITY":
        if not g.get("processo"):
            problemas.append("Informe o processo do PC que dispara a rotina.")
    elif tipo == "TIME_RANGE":
        try:
            for campo in ("inicio", "fim"):
                valor = g.get(campo, "")
                if not re.fullmatch(r"\d{2}:\d{2}", valor):
                    raise ValueError()
                time.fromisoformat(valor)
        except (ValueError, TypeError):
            problemas.append("Informe um intervalo de horário válido.")
        if g.get("evento", "TICK_ROTINA") not in {"TICK_ROTINA", "PC_ACTIVITY"}:
            problemas.append("Esse gatilho depende de um evento que o sistema não produz.")
    else:
        problemas.append("Esse tipo de gatilho não é suportado pelo motor de rotinas.")
    try:
        if float(r["cooldown_segundos"]) < 60:
            raise ValueError()
    except (ValueError, TypeError):
        problemas.append("O intervalo entre execuções deve ser de pelo menos 60 segundos.")
    if not r.get("acoes"):
        problemas.append("Adicione pelo menos uma ação à rotina.")
    for acao in r.get("acoes", []):
        alvo, comando, parametro = acao.get("alvo"), acao.get("comando"), acao.get("parametro")
        if alvo == "PC":
            if comando not in PC_COMMANDS:
                problemas.append(f"O comando de PC '{comando}' não é suportado em rotinas.")
            if comando in {"abrir_app", "abrir_url", "pesquisa_google", "spotify_play", "voicemeeter", "executar_cenario"} and not parametro:
                problemas.append(f"O comando '{comando}' precisa de um destino.")
        elif alvo == "MOBILE":
            if comando not in MOBILE_COMMANDS:
                problemas.append(f"O comando de celular '{comando}' não é suportado em rotinas.")
            if comando in {"OPEN_APP", "ABRIR_APP_MOBILE", "ABRIR_URL_MOBILE"} and not parametro:
                problemas.append("Escolha o aplicativo ou endereço da ação no celular.")
        elif alvo == "IA":
            if comando != "NOTIFICAR" or not parametro:
                problemas.append("A ação de notificação precisa de uma mensagem.")
            if acao.get("acao_tipo") and not acao.get("acao_parametro"):
                problemas.append("O botão da notificação precisa de um destino.")
        elif alvo == "CASA":
            from servicos.controle_casa import ACOES, controle_casa
            try:
                if comando.lower() not in ACOES:
                    raise ValueError()
                controle_casa.resolver(parametro)
            except (ValueError, LookupError):
                problemas.append("A ação da casa precisa de uma operação e de uma luz cadastrada.")
        else:
            problemas.append(f"O destino '{alvo}' não é suportado.")
    return list(dict.fromkeys(problemas))


def validar_rotina(rotina):
    problemas = problemas_rotina(rotina)
    if problemas:
        raise ValueError(" ".join(problemas))
    return normalizar_rotina(rotina)


def assinatura_rotina(rotina):
    r = normalizar_rotina(rotina)
    gatilho = {k: v for k, v in (r.get("gatilho") or {}).items() if v is not None}
    if gatilho.get("tipo") == "TIME_RANGE":
        gatilho.setdefault("evento", "TICK_ROTINA")
    if gatilho.get("processo"):
        gatilho["processo"] = gatilho["processo"].lower()
    acoes = []
    for acao in r.get("acoes", []):
        alvo, comando, parametro = acao.get("alvo"), acao.get("comando"), acao.get("parametro")
        # O mesmo próximo app continua sendo o mesmo padrão, mesmo se mudar
        # o nome da sugestão, o texto do aviso ou o rótulo do botão.
        if alvo == "IA" and acao.get("acao_tipo", "").upper() in {"OPEN_APP", "ABRIR_APP_MOBILE"}:
            alvo, comando, parametro = "MOBILE", "OPEN_APP", acao.get("acao_parametro")
        if alvo == "MOBILE" and comando == "ABRIR_APP_MOBILE":
            comando = "OPEN_APP"
        if alvo == "PC" and comando == "abrir_app":
            parametro = str(parametro).lower()
        acoes.append({"alvo": alvo, "comando": comando, "parametro": parametro})
    return json.dumps([gatilho, acoes], sort_keys=True, ensure_ascii=False)


def apresentar_rotina(rotina, estado):
    r = normalizar_rotina(rotina)
    r["problemas"] = problemas_rotina(r)
    r["estado"] = "sugerida" if estado == "descobertas" else ("ativa" if r["ativa"] else "pausada")
    r["pode_ativar"] = not r["problemas"]
    r["evidencia_verificada"] = bool(r.get("evidencia", {}).get("amostras"))
    return r
