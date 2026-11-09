import asyncio
import logging
import os
import toml
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

CONFIG_TOML_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.toml")
DEFAULT_VOICE = DEFAULT_GEMINI_VOICE
HEADERS = {"Content-Disposition": "attachment; filename=voice.mp3", "Cache-Control": "no-store"}


def carregar_config_voz_pc() -> dict:
    """Carrega as configurações de voz do PC a partir do config.toml."""
    try:
        if os.path.exists(CONFIG_TOML_PATH):
            dados = toml.load(CONFIG_TOML_PATH)
            voz_cfg = dados.get("voz", {})
            return {
                "provider": voz_cfg.get("provider", "auto"),
                "voice": voz_cfg.get("voice", DEFAULT_VOICE),
                "edge_voice": voz_cfg.get("edge_voice", DEFAULT_EDGE_VOICE),
                "rate": float(voz_cfg.get("rate", 1.0)),
                "pitch": float(voz_cfg.get("pitch", 1.0))
            }
    except Exception as e:
        logger.warning("[VoiceAPI] Não foi possível ler config.toml: %s", e)

    return {
        "provider": "auto",
        "voice": DEFAULT_VOICE,
        "edge_voice": DEFAULT_EDGE_VOICE,
        "rate": 1.0,
        "pitch": 1.0
    }


def salvar_config_voz_pc(novos_dados: dict):
    """Salva a seção [voz] no config.toml."""
    try:
        dados = {}
        if os.path.exists(CONFIG_TOML_PATH):
            dados = toml.load(CONFIG_TOML_PATH)
        dados["voz"] = {
            "provider": novos_dados.get("provider", "auto"),
            "voice": novos_dados.get("voice", DEFAULT_VOICE),
            "edge_voice": novos_dados.get("edge_voice", DEFAULT_EDGE_VOICE),
            "rate": float(novos_dados.get("rate", 1.0)),
            "pitch": float(novos_dados.get("pitch", 1.0))
        }
        with open(CONFIG_TOML_PATH, "w", encoding="utf-8") as f:
            toml.dump(dados, f)
    except Exception as e:
        logger.error("[VoiceAPI] Erro ao salvar config.toml: %s", e)
        raise HTTPException(status_code=500, detail="Erro ao salvar a configuração de voz no arquivo config.toml.") from e


class PedidoDeVoz(BaseModel):
    text: str
    voice: str = None
    provider: str = None  # 'auto', 'gemini' ou 'edge'
    rate: float = None
    pitch: float = None
    stream: bool = False


class ConfiguracaoVozPC(BaseModel):
    provider: str = "auto"
    voice: str = DEFAULT_VOICE
    edge_voice: str = DEFAULT_EDGE_VOICE
    rate: float = 1.0
    pitch: float = 1.0


async def blocos_de_audio(communicate):
    async with aclosing(communicate.stream()) as origem:
        while True:
            async with asyncio.timeout(8):
                bloco = await anext(origem, None)
            if bloco is None:
                return
            if isinstance(bloco, dict) and bloco.get("type") in (None, "audio") and bloco.get("data"):
                yield bloco["data"]


async def sintetizar_edge(pedido: PedidoDeVoz, texto: str, config_pc: dict):
    """Sintetiza voz utilizando o provedor Edge TTS."""
    voz_solicitada = pedido.voice or config_pc["voice"]
    voice = obter_voz_edge_fallback(voz_solicitada)
    rate_val = pedido.rate if pedido.rate is not None else config_pc["rate"]
    pitch_val = pedido.pitch if pedido.pitch is not None else config_pc["pitch"]

    blocos = None
    transferido = False
    try:
        rate = f"{round((rate_val - 1.0) * 100):+d}%"
        pitch = f"{round((pitch_val - 1.0) * 100):+d}Hz"
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

    config_pc = carregar_config_voz_pc()
    provider_ativo = pedido.provider or config_pc["provider"]
    voice_ativa = pedido.voice or config_pc["voice"]

    # Tentativa com Gemini se provider for 'auto' ou 'gemini'
    if provider_ativo in ("auto", "gemini") and gemini_tts_service.disponivel():
        try:
            logger.info("🎙️ [VoiceAPI] Sintetizando áudio via Gemini TTS (%s)...", voice_ativa)
            audio_bytes = await gemini_tts_service.sintetizar(texto, voice=voice_ativa)
            return Response(audio_bytes, media_type="audio/mpeg", headers=HEADERS)
        except Exception as erro:
            logger.warning("⚠️ [VoiceAPI] Falha no Gemini TTS (%s). Ativando fallback para Edge TTS.", type(erro).__name__)
            if provider_ativo == "gemini":
                # Se o usuário exigiu estritamente o Gemini e este falhou
                raise HTTPException(status_code=500, detail=f"Falha ao sintetizar voz via Gemini: {erro}") from erro

    # Fallback / Provedor padrão: Edge TTS
    logger.info("🎙️ [VoiceAPI] Sintetizando áudio via Edge TTS...")
    return await sintetizar_edge(pedido, texto, config_pc)


@router.get("/voices")
async def listar_vozes():
    """Retorna o catálogo completo de vozes do Gemini e do Edge TTS, com mapeamento de fallback."""
    config_pc = carregar_config_voz_pc()
    provedor_ativo = "gemini" if gemini_tts_service.disponivel() else "edge"
    return {
        "active_provider": provedor_ativo,
        "gemini_available": gemini_tts_service.disponivel(),
        "pc_config": config_pc,
        "default_voice": config_pc["voice"],
        "default_edge_voice": config_pc["edge_voice"],
        "gemini_voices": LISTA_VOZES_GEMINI,
        "edge_voices": LISTA_VOZES_EDGE
    }


@router.get("/config")
async def obter_configuracao_voz():
    """Retorna a configuração atual de voz do PC."""
    config = carregar_config_voz_pc()
    return {
        "status": "sucesso",
        "gemini_available": gemini_tts_service.disponivel(),
        "config": config
    }


@router.post("/config")
async def atualizar_configuracao_voz(nova_config: ConfiguracaoVozPC):
    """Atualiza a configuração de voz do PC e salva no config.toml."""
    salvar_config_voz_pc(nova_config.model_dump())
    return {
        "status": "sucesso",
        "mensagem": "Configuração de voz do PC atualizada com sucesso.",
        "config": nova_config.model_dump()
    }


@router.get("/speak")
async def speak(
    text: str,
    voice: str = None,
    provider: str = None,
    rate: float = None,
    pitch: float = None
):
    return await sintetizar(PedidoDeVoz(text=text, voice=voice, provider=provider, rate=rate, pitch=pitch))


@router.post("/speak")
async def speak_post(pedido: PedidoDeVoz):
    return await sintetizar(pedido)
