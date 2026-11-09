import asyncio
import logging
from contextlib import aclosing

import edge_tts
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from servicos.texto_falado import preparar_fala

logger = logging.getLogger("VoiceAPI")
router = APIRouter()

DEFAULT_VOICE = "pt-BR-ThalitaMultilingualNeural"
HEADERS = {"Content-Disposition": "attachment; filename=voice.mp3", "Cache-Control": "no-store"}


class PedidoDeVoz(BaseModel):
    text: str
    voice: str = DEFAULT_VOICE
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


async def sintetizar(pedido: PedidoDeVoz):
    texto = preparar_fala(pedido.text)
    if not texto:
        raise HTTPException(status_code=400, detail="Texto não fornecido.")
    voice = DEFAULT_VOICE if pedido.voice == "pt-BR-ThalitaNeural" else pedido.voice
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
        logger.warning("Síntese de voz indisponível (%s).", type(erro).__name__)
        raise HTTPException(status_code=500, detail="Não consegui gerar o áudio.") from erro
    finally:
        if blocos is not None and not transferido:
            await blocos.aclose()


@router.get("/speak")
async def speak(text: str, voice: str = DEFAULT_VOICE, rate: float = 1.0, pitch: float = 1.0):
    return await sintetizar(PedidoDeVoz(text=text, voice=voice, rate=rate, pitch=pitch))


@router.post("/speak")
async def speak_post(pedido: PedidoDeVoz):
    return await sintetizar(pedido)
