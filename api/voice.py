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
    CodigoGemini,
    FalhaGemini,
    gemini_tts_service,
    LISTA_VOZES_GEMINI,
    LISTA_VOZES_EDGE,
    obter_voz_edge_fallback,
    obter_voz_gemini,
    DEFAULT_EDGE_VOICE,
    voz_do_gemini,
)

logger = logging.getLogger("VoiceAPI")
router = APIRouter()

CONFIG_TOML_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.toml")
DEFAULT_VOICE = DEFAULT_EDGE_VOICE
HEADERS_BASE = {"Content-Disposition": "attachment; filename=voice.mp3", "Cache-Control": "no-store"}

_CONFIG_VOZ_MEMORIA = {}


def carregar_config_voz_pc() -> dict:
    """Carrega as configurações de voz do PC a partir de memória ou config.toml."""
    if _CONFIG_VOZ_MEMORIA:
        return dict(_CONFIG_VOZ_MEMORIA)

    try:
        if os.path.exists(CONFIG_TOML_PATH):
            dados = toml.load(CONFIG_TOML_PATH)
            voz_cfg = dados.get("voz", {})
            cfg = {
                "provider": voz_cfg.get("provider", "auto"),
                "voice": voz_cfg.get("voice", DEFAULT_VOICE),
                "edge_voice": voz_cfg.get("edge_voice", DEFAULT_EDGE_VOICE),
                "rate": float(voz_cfg.get("rate", 1.0)),
                "pitch": float(voz_cfg.get("pitch", 1.0))
            }
            _CONFIG_VOZ_MEMORIA.update(cfg)
            return cfg
    except Exception as e:
        logger.warning("[VoiceAPI] Não foi possível ler config.toml: %s", e)

    cfg_padrao = {
        "provider": "auto",
        "voice": DEFAULT_VOICE,
        "edge_voice": DEFAULT_EDGE_VOICE,
        "rate": 1.0,
        "pitch": 1.0
    }
    _CONFIG_VOZ_MEMORIA.update(cfg_padrao)
    return cfg_padrao


def salvar_config_voz_pc(novos_dados: dict):
    """Salva a seção [voz] na memória e tenta persistir no config.toml."""
    cfg = {
        "provider": novos_dados.get("provider", "auto"),
        "voice": novos_dados.get("voice", DEFAULT_VOICE),
        "edge_voice": novos_dados.get("edge_voice", DEFAULT_EDGE_VOICE),
        "rate": float(novos_dados.get("rate", 1.0)),
        "pitch": float(novos_dados.get("pitch", 1.0))
    }
    _CONFIG_VOZ_MEMORIA.update(cfg)

    try:
        dados = {}
        if os.path.exists(CONFIG_TOML_PATH):
            dados = toml.load(CONFIG_TOML_PATH)
        dados["voz"] = cfg
        with open(CONFIG_TOML_PATH, "w", encoding="utf-8") as f:
            toml.dump(dados, f)
        logger.info("[VoiceAPI] Configurações de voz salvas no config.toml.")
    except Exception as e:
        logger.warning("[VoiceAPI] Aviso ao salvar no config.toml (mantido em memória): %s", e)


class PedidoDeVoz(BaseModel):
    text: str
    voice: str | None = None
    provider: str | None = None  # 'auto', 'gemini' ou 'edge'
    rate: float | None = None
    pitch: float | None = None
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


async def sintetizar_edge(pedido: PedidoDeVoz, texto: str, config_pc: dict, gemini_erro: CodigoGemini | None = None):
    """Sintetiza voz utilizando o provedor Edge TTS."""
    voz_solicitada = pedido.voice or config_pc["voice"]
    voice = obter_voz_edge_fallback(voz_solicitada)
    rate_val = pedido.rate if pedido.rate is not None else config_pc["rate"]
    pitch_val = pedido.pitch if pedido.pitch is not None else config_pc["pitch"]

    headers = dict(HEADERS_BASE)
    headers.update({
        "X-Voice-Provider": "edge",
        "X-Voice-Used": voice,
        "X-Voice-Fallback": "true" if gemini_erro else "false",
        "X-Gemini-Available": "true" if gemini_tts_service.disponivel() else "false"
    })
    if gemini_erro:
        headers["X-Gemini-Error"] = gemini_erro.value

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
            resposta = StreamingResponse(audio(), media_type="audio/mpeg", headers=headers)
            transferido = True
            return resposta
        dados = bytearray(primeiro)
        async for bloco in blocos:
            dados.extend(bloco)
        return Response(bytes(dados), media_type="audio/mpeg", headers=headers)
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
    rate_val = pedido.rate if pedido.rate is not None else config_pc["rate"]

    gemini_erro = None
    if provider_ativo == "gemini" or (provider_ativo == "auto" and voz_do_gemini(voice_ativa)):
        try:
            audio_bytes = await gemini_tts_service.sintetizar(texto, voice=voice_ativa, rate=rate_val)
            headers = dict(HEADERS_BASE)
            headers.update({
                "Content-Disposition": "attachment; filename=voice.wav",
                "X-Voice-Provider": "gemini",
                "X-Voice-Used": obter_voz_gemini(voice_ativa),
                "X-Voice-Fallback": "false",
                "X-Gemini-Available": "true"
            })
            return Response(audio_bytes, media_type="audio/wav", headers=headers)
        except FalhaGemini as erro:
            gemini_erro = erro.codigo
        except Exception as erro:
            gemini_erro = CodigoGemini.INTERNO
            logger.warning("Falha interna na voz Gemini (%s).", type(erro).__name__)
        if gemini_erro:
            logger.info("Voz Gemini indisponível (%s).", gemini_erro.value)
            if provider_ativo == "gemini":
                raise HTTPException(
                    status_code=503, detail="Voz Gemini indisponível no momento.",
                    headers={"X-Gemini-Error": gemini_erro.value},
                )

    return await sintetizar_edge(pedido, texto, config_pc, gemini_erro=gemini_erro)


@router.get("/diagnostic")
async def diagnostico_voz():
    """Relata a última tentativa real de síntese sem consumir uma chamada de teste."""
    gemini_ok = gemini_tts_service.disponivel()
    gemini_teste_status = "não configurado"
    ultimo_erro = gemini_tts_service.ultimo_erro
    if gemini_ok:
        gemini_teste_status = "ainda não testado nesta instância"
        if gemini_tts_service.testado:
            gemini_teste_status = "falha na chamada da API" if ultimo_erro else "sucesso"

    vozes_femininas_gemini = [v["nome"] for v in LISTA_VOZES_GEMINI if v["genero"] == "feminino"]
    vozes_masculinas_gemini = [v["nome"] for v in LISTA_VOZES_GEMINI if v["genero"] == "masculino"]

    return {
        "status": "ok",
        "gemini_available": gemini_ok,
        "gemini_test_status": gemini_teste_status,
        "gemini_test_error": ultimo_erro.value if ultimo_erro else None,
        "female_gemini_voices": vozes_femininas_gemini,
        "male_gemini_voices": vozes_masculinas_gemini,
        "active_pc_config": carregar_config_voz_pc()
    }


@router.get("/voices")
async def listar_vozes():
    """Retorna o catálogo completo de vozes do Gemini e do Edge TTS, com mapeamento de fallback."""
    config_pc = carregar_config_voz_pc()
    provedor_ativo = "gemini" if gemini_tts_service.disponivel() and (
        config_pc["provider"] == "gemini" or
        (config_pc["provider"] == "auto" and voz_do_gemini(config_pc["voice"]))
    ) else "edge"
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
    voice: str | None = None,
    provider: str | None = None,
    rate: float | None = None,
    pitch: float | None = None
):
    return await sintetizar(PedidoDeVoz(text=text, voice=voice, provider=provider, rate=rate, pitch=pitch))


@router.post("/speak")
async def speak_post(pedido: PedidoDeVoz):
    return await sintetizar(pedido)
