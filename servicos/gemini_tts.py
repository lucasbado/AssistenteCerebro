"""Síntese Gemini com resposta PCM e diagnóstico sem credenciais."""
import base64
import binascii
from enum import Enum
from io import BytesIO
import os
import re
from time import monotonic
import wave

import httpx

from servicos.velocidade_fala import acelerar_pcm16

LISTA_VOZES_GEMINI = [
    # Vozes Femininas Gemini
    {"id": "Kore", "nome": "Kore", "genero": "feminino", "descricao": "Voz Gemini Natural (Feminina - Suave)", "fallback_edge": "pt-BR-ThalitaMultilingualNeural"},
    {"id": "Aoede", "nome": "Aoede", "genero": "feminino", "descricao": "Voz Gemini Natural (Feminina - Expressiva)", "fallback_edge": "pt-BR-FranciscaNeural"},
    {"id": "Leda", "nome": "Leda", "genero": "feminino", "descricao": "Voz Gemini Natural (Feminina - Elegante)", "fallback_edge": "pt-BR-ThalitaMultilingualNeural"},
    {"id": "Despina", "nome": "Despina", "genero": "feminino", "descricao": "Voz Gemini Natural (Feminina - Melódica)", "fallback_edge": "pt-BR-FranciscaNeural"},
    {"id": "Algieba", "nome": "Algieba", "genero": "feminino", "descricao": "Voz Gemini Natural (Feminina - Acolhedora)", "fallback_edge": "pt-BR-ThalitaMultilingualNeural"},
    {"id": "Callirrhoe", "nome": "Callirrhoe", "genero": "feminino", "descricao": "Voz Gemini Natural (Feminina - Amigável)", "fallback_edge": "pt-BR-FranciscaNeural"},
    {"id": "Sulafat", "nome": "Sulafat", "genero": "feminino", "descricao": "Voz Gemini Natural (Feminina - Calma)", "fallback_edge": "pt-BR-ThalitaMultilingualNeural"},
    
    # Vozes Masculinas Gemini
    {"id": "Puck", "nome": "Puck", "genero": "masculino", "descricao": "Voz Gemini Natural (Masculina - Enérgica)", "fallback_edge": "pt-BR-AntonioNeural"},
    {"id": "Charon", "nome": "Charon", "genero": "masculino", "descricao": "Voz Gemini Natural (Masculina - Profunda)", "fallback_edge": "pt-BR-AntonioNeural"},
    {"id": "Fenrir", "nome": "Fenrir", "genero": "masculino", "descricao": "Voz Gemini Natural (Masculina - Forte)", "fallback_edge": "pt-BR-AntonioNeural"},
]

# Lista Estruturada de Vozes Edge TTS (Microsoft Edge TTS)
LISTA_VOZES_EDGE = [
    {"id": "pt-BR-ThalitaMultilingualNeural", "nome": "Thalita", "genero": "feminino", "descricao": "Voz Neural Edge (Feminina - Multilíngue)", "fallback_gemini": "Kore"},
    {"id": "pt-BR-FranciscaNeural", "nome": "Francisca", "genero": "feminino", "descricao": "Voz Neural Edge (Feminina)", "fallback_gemini": "Aoede"},
    {"id": "pt-BR-AntonioNeural", "nome": "Antônio", "genero": "masculino", "descricao": "Voz Neural Edge (Masculina)", "fallback_gemini": "Puck"},
]

# Mapeamentos bidirecionais de fallback
MAPEAMENTO_GEMINI_PARA_EDGE = {v["id"]: v["fallback_edge"] for v in LISTA_VOZES_GEMINI}
MAPEAMENTO_EDGE_PARA_GEMINI = {v["id"]: v["fallback_gemini"] for v in LISTA_VOZES_EDGE}
MAPEAMENTO_EDGE_PARA_GEMINI["pt-BR-ThalitaNeural"] = "Kore"

VOZES_GEMINI_PADRAO = {v["id"] for v in LISTA_VOZES_GEMINI}
DEFAULT_GEMINI_VOICE = os.getenv("GEMINI_VOICE", "Kore")
DEFAULT_EDGE_VOICE = "pt-BR-ThalitaMultilingualNeural"


_ALIASES = {"Callisto": "Callirrhoe", "Rhea": "Sulafat"}
_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent"
_ESTILO = (
    "Fale em português do Brasil como em uma conversa. Use pausas naturais e entonação "
    "coerente com a pontuação. Leia somente o texto depois de FALA, sem acrescentar palavras."
)


class CodigoGemini(str, Enum):
    NAO_CONFIGURADO = "not_configured"
    CREDENCIAL = "authentication_failed"
    LIMITE = "rate_limited"
    MODELO = "model_unavailable"
    REQUISICAO = "request_rejected"
    REDE = "service_unavailable"
    AUDIO = "invalid_audio"
    INTERNO = "synthesis_failed"


class FalhaGemini(Exception):
    def __init__(self, codigo: CodigoGemini):
        self.codigo = codigo
        super().__init__(codigo.value)


def voz_do_gemini(voz):
    return _ALIASES.get(voz, voz) in VOZES_GEMINI_PADRAO


def obter_voz_gemini(voz_solicitada):
    voz = _ALIASES.get(voz_solicitada, voz_solicitada)
    if voz_do_gemini(voz):
        return voz
    padrao = DEFAULT_GEMINI_VOICE if voz_do_gemini(DEFAULT_GEMINI_VOICE) else "Kore"
    return MAPEAMENTO_EDGE_PARA_GEMINI.get(voz, _ALIASES.get(padrao, padrao))


def obter_voz_edge_fallback(voz_solicitada):
    voz = _ALIASES.get(voz_solicitada, voz_solicitada)
    if not voz or voz == "pt-BR-ThalitaNeural":
        return DEFAULT_EDGE_VOICE
    return MAPEAMENTO_GEMINI_PARA_EDGE.get(voz, voz)


class GeminiTTSService:
    def __init__(self, api_key=None, transporte=None, relogio=monotonic):
        self._chave = api_key
        self._transporte = transporte
        self._relogio = relogio
        self._bloqueado_ate = 0
        self.ultimo_erro = None
        self.testado = False

    @property
    def api_key(self):
        chave = self._chave
        if chave is None:
            chave = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
        return chave.strip()

    def disponivel(self):
        return bool(self.api_key)

    def _falha(self, codigo, espera=0):
        self.ultimo_erro = codigo
        if espera:
            self._bloqueado_ate = self._relogio() + espera
        return FalhaGemini(codigo)

    async def sintetizar(self, texto, voice=None, rate=1.0):
        chave = self.api_key
        if not chave:
            raise FalhaGemini(CodigoGemini.NAO_CONFIGURADO)
        if self._bloqueado_ate > self._relogio() and self.ultimo_erro:
            raise FalhaGemini(self.ultimo_erro)
        payload = {
            "contents": [{"parts": [{"text": f"{_ESTILO}\n\nFALA:\n{texto}"}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": obter_voz_gemini(voice)}}},
            },
        }
        self.testado = True
        try:
            async with httpx.AsyncClient(timeout=12.0, transport=self._transporte) as cliente:
                resposta = await cliente.post(_URL, headers={"x-goog-api-key": chave}, json=payload)
        except (httpx.HTTPError, ValueError):
            raise self._falha(CodigoGemini.REDE, 30) from None

        status = resposta.status_code
        if status in (401, 403):
            raise self._falha(CodigoGemini.CREDENCIAL, 300)
        if status == 429:
            try:
                espera = max(1, min(86400, int(resposta.headers.get("retry-after", "60"))))
            except ValueError:
                espera = 60
            raise self._falha(CodigoGemini.LIMITE, espera)
        if status == 404:
            raise self._falha(CodigoGemini.MODELO, 300)
        if status >= 500:
            raise self._falha(CodigoGemini.REDE, 30)
        if not resposta.is_success:
            # A API também devolve credencial inválida como 400. Não copie a mensagem.
            try:
                detalhes = resposta.json().get("error", {}).get("details", [])
                if any(d.get("reason") in {"API_KEY_INVALID", "API_KEY_EXPIRED"} for d in detalhes):
                    raise self._falha(CodigoGemini.CREDENCIAL, 300)
            except (ValueError, TypeError, AttributeError):
                pass
            raise self._falha(CodigoGemini.REQUISICAO, 30)

        try:
            partes = resposta.json()["candidates"][0]["content"]["parts"]
            dados = next(p["inlineData"] for p in partes if "inlineData" in p)
            mime = dados["mimeType"].lower()
            if not mime.startswith("audio/l16"):
                raise ValueError
            trecho = re.search(r"(?:^|;)\s*rate=(\d+)(?:;|$)", mime)
            taxa = int(trecho[1]) if trecho else 24000
            pcm = base64.b64decode(dados["data"], validate=True)
            if not pcm or len(pcm) % 2 or not 8000 <= taxa <= 48000:
                raise ValueError
        except (KeyError, IndexError, AttributeError, StopIteration, TypeError, ValueError, binascii.Error):
            raise self._falha(CodigoGemini.AUDIO) from None

        if rate > 1.001:
            pcm = acelerar_pcm16(pcm, fator=rate, taxa=taxa)
        buffer = BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setparams((1, 2, taxa, 0, "NONE", "not compressed"))
            wav.writeframes(pcm)
        self.ultimo_erro = None
        self._bloqueado_ate = 0
        return buffer.getvalue()


gemini_tts_service = GeminiTTSService()
