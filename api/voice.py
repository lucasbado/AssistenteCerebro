import logging
import edge_tts
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
import io

logger = logging.getLogger("VoiceAPI")
router = APIRouter()

# Vozes recomendadas: pt-BR-FranciscaNeural (F), pt-BR-AntonioNeural (M), pt-BR-ThalitaNeural (F - Suave)
DEFAULT_VOICE = "pt-BR-ThalitaNeural"

@router.get("/speak")
async def speak(text: str, voice: str = DEFAULT_VOICE, rate: float = 1.0, pitch: float = 1.0):
    """
    Gera áudio MP3 a partir de texto usando Microsoft Edge TTS.
    Retorna um stream de áudio direto para o Android.
    """
    if not text:
        raise HTTPException(status_code=400, detail="Texto não fornecido.")
    
    try:
        # Converte parâmetros numéricos para o formato do Edge TTS (ex: 1.2 -> "+20%")
        rate_str = f"{int((rate - 1.0) * 100):+d}%"
        pitch_str = f"{int((pitch - 1.0) * 100):+d}Hz" # O Edge aceita Hz ou % para pitch
        
        logger.info(f"🎙️ Gerando voz ({voice}): '{text[:30]}...' | Rate: {rate_str} | Pitch: {pitch_str}")
        
        communicate = edge_tts.Communicate(text, voice, rate=rate_str)
        
        audio_stream = io.BytesIO()
        async for chunk in communicate.stream():
            # 🌟 CORREÇÃO ROBUSTA: Verifica se o chunk é um dicionário e tem dados de áudio
            if isinstance(chunk, dict):
                if chunk.get("type") == "audio" and "data" in chunk:
                    audio_stream.write(chunk["data"])
                elif "data" in chunk and not chunk.get("type"):
                    # Fallback para versões onde o tipo não vem explícito
                    audio_stream.write(chunk["data"])
        
        audio_stream.seek(0)
        
        if audio_stream.getbuffer().nbytes == 0:
            raise ValueError("Stream de áudio gerado está vazio.")

        return StreamingResponse(
            audio_stream, 
            media_type="audio/mpeg",
            headers={"Content-Disposition": "attachment; filename=voice.mp3"}
        )
    except Exception as e:
        logger.error(f"❌ Erro ao gerar voz: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))
