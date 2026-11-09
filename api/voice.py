import asyncio
import logging
from contextlib import aclosing

import edge_tts
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from servicos.texto_falado import preparar_fala
from servicos.gemini_tts import (
    gemini_tts_service,
    LISTA_VOZES_GEMINI,
    LISTA_VOZES_EDGE,
    obter_voz_edge_fallback,
    obter_voz_gemini,
    DEFAULT_GEMINI_VOICE,
    DEFAULT_EDGE_VOICE,
)

logger = logging.getLogger("VoiceAPI")
router = APIRouter()

DEFAULT_VOICE = DEFAULT_GEMINI_VOICE
HEADERS = {"Content-Disposition": "attachment; filename=voice.mp3", "Cache-Control": "no-store"}


class PedidoDeVoz(BaseModel):
    text: str
    voice: str = DEFAULT_VOICE
    provider: str = "auto"  # 'auto', 'gemini' ou 'edge'
    rate: float = 1.0
    pitch: float = 1.0
    stream: bool = False


async def blocos_de_audio(communicate):
    async with aclosing(communicate.stream()) as origem:
        while True:
            async with asyncio.timeout(8):
                bloco = await anext(origem, None)
            if bloco is None:
                return
            if isinstance(bloco, dict) and bloco.get("type") in (None, "audio") and bloco.get("data"):
                yield bloco["data"]


async def sintetizar_edge(pedido: PedidoDeVoz, texto: str):
    """Sintetiza voz utilizando o provedor Edge TTS."""
    voice = obter_voz_edge_fallback(pedido.voice)
    blocos = None
    transferido = False
    try:
        rate = f"{round((pedido.rate - 1.0) * 100):+d}%"
        pitch = f"{round((pedido.pitch - 1.0) * 100):+d}Hz"
        blocos = blocos_de_audio(edge_tts.Communicate(texto, voice, rate=rate, pitch=pitch))
        async with asyncio.timeout(10):
            primeiro = await anext(blocos)
        if pedido.stream:
            async def audio():
                async with aclosing(blocos):
                    yield primeiro
                    async for bloco in blocos:
                        yield bloco
            resposta = StreamingResponse(audio(), media_type="audio/mpeg", headers=HEADERS)
            transferido = True
            return resposta
        dados = bytearray(primeiro)
        async for bloco in blocos:
            dados.extend(bloco)
        return Response(bytes(dados), media_type="audio/mpeg", headers=HEADERS)
    except Exception as erro:
        logger.warning("Edge TTS indisponível (%s).", type(erro).__name__)
        raise HTTPException(status_code=500, detail="Não consegui gerar o áudio.") from erro
    finally:
        if blocos is not None and not transferido:
            await blocos.aclose()


async def sintetizar(pedido: PedidoDeVoz):
    texto = preparar_fala(pedido.text)
    if not texto:
        raise HTTPException(status_code=400, detail="Texto não fornecido.")

    # Tentativa com Gemini se provider for 'auto' ou 'gemini'
    if pedido.provider in ("auto", "gemini") and gemini_tts_service.disponivel():
        try:
            logger.info("🎙️ [VoiceAPI] Sintetizando áudio via Gemini TTS...")
            audio_bytes = await gemini_tts_service.sintetizar(texto, voice=pedido.voice)
            return Response(audio_bytes, media_type="audio/mpeg", headers=HEADERS)
        except Exception as erro:
            logger.warning("⚠️ [VoiceAPI] Falha no Gemini TTS (%s). Ativando fallback para Edge TTS.", type(erro).__name__)
            if pedido.provider == "gemini":
                # Se o usuário exigiu estritamente o Gemini e este falhou
                raise HTTPException(status_code=500, detail=f"Falha ao sintetizar voz via Gemini: {erro}") from erro

    # Fallback / Provedor padrão: Edge TTS
    logger.info("🎙️ [VoiceAPI] Sintetizando áudio via Edge TTS...")
    return await sintetizar_edge(pedido, texto)


@router.get("/voices")
async def listar_vozes():
    """Retorna o catálogo completo de vozes do Gemini e do Edge TTS, com mapeamento de fallback."""
    provedor_ativo = "gemini" if gemini_tts_service.disponivel() else "edge"
    return {
        "active_provider": provedor_ativo,
        "gemini_available": gemini_tts_service.disponivel(),
        "default_voice": DEFAULT_VOICE,
        "default_edge_voice": DEFAULT_EDGE_VOICE,
        "gemini_voices": LISTA_VOZES_GEMINI,
        "edge_voices": LISTA_VOZES_EDGE
    }


@router.get("/speak")
async def speak(
    text: str,
    voice: str = DEFAULT_VOICE,
    provider: str = "auto",
    rate: float = 1.0,
    pitch: float = 1.0
):
    return await sintetizar(PedidoDeVoz(text=text, voice=voice, provider=provider, rate=rate, pitch=pitch))


@router.post("/speak")
async def speak_post(pedido: PedidoDeVoz):
    return await sintetizar(pedido)
