"""Condições atuais da região padrão, sem passar por um modelo de linguagem."""
import asyncio
import logging
import math
import re
import unicodedata
from datetime import datetime, timezone
from time import monotonic

import httpx

from servicos.consciencia import consciencia
from servicos.roteamento_pedidos import responder_pedido

logger = logging.getLogger(__name__)
CIDADE = "São Paulo"
_cache = None
_lock = asyncio.Lock()
_PERGUNTA = re.compile(
    r"(?:(?:ollie|oi ollie)\s*[,;:]?\s*)?"
    r"(?:(?:(?:como (?:esta|ta) (?:a |o )?|qual (?:e )?(?:a |o )?|"
    r"me (?:diga|fala) (?:a |o )?)?"
    r"(?:temperatura|tempo|clima)(?: (?:atual|agora))?)"
    r"|quantos graus (?:esta|faz|ta)(?: fazendo)?(?: agora)?)"
    r"(?: (?:aqui|em sao paulo))?[?.! ]*"
)


def pedido_clima_atual(texto):
    texto = unicodedata.normalize("NFKD", texto.casefold())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return bool(_PERGUNTA.fullmatch(" ".join(texto.split())))


def traduzir_codigo_clima(codigo):
    condicao = {
        0: "Céu limpo", 1: "Principalmente limpo", 2: "Parcialmente nublado", 3: "Encoberto",
        45: "Nevoeiro", 48: "Nevoeiro com geada", 51: "Chuvisco leve",
        61: "Chuva leve", 63: "Chuva moderada", 65: "Chuva forte",
        80: "Pancadas de chuva", 95: "Trovoada",
    }.get(codigo, "Variável")
    if codigo in (0, 1):
        return condicao, "clear"
    if codigo in (51, 61, 63, 65, 80):
        return condicao, "rain"
    return condicao, "storm" if codigo == 95 else "cloud"


async def consultar_clima_atual():
    global _cache
    async with _lock:
        if _cache and monotonic() - _cache[0] < 600:
            return _cache[1]
        async with httpx.AsyncClient(timeout=7.0) as client:
            resposta = await client.get("https://api.open-meteo.com/v1/forecast", params={
                "latitude": "-23.6500", "longitude": "-46.7000",
                "current": "temperature_2m,weather_code", "temperature_unit": "celsius",
            })
            resposta.raise_for_status()
        atual = resposta.json()["current"]
        temperatura = float(atual["temperature_2m"])
        if not math.isfinite(temperatura):
            raise ValueError("Temperatura inválida.")
        condicao, icone = traduzir_codigo_clima(atual["weather_code"])
        dados = {"temperatura": f"{temperatura:g}", "condicao": condicao, "icon_code": icone,
                 "atualizado_em": datetime.now(timezone.utc).isoformat()}
        consciencia.atualizar({"clima": dados})
        _cache = monotonic(), dados
        return dados


async def responder_clima_atual(evento):
    if not pedido_clima_atual(str(evento.payload.get("texto", ""))):
        return False
    try:
        clima = await consultar_clima_atual()
        temperatura = clima["temperatura"].replace(".", ",")
        mensagem = f"Em {CIDADE}, está fazendo {temperatura} °C agora. {clima['condicao']}."
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as erro:
        logger.warning("Consulta de clima indisponível (%s).", type(erro).__name__)
        mensagem = f"Não consegui consultar a temperatura atual em {CIDADE} agora."
    await responder_pedido(evento, mensagem)
    return True
