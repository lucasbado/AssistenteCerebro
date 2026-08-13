import logging
import edge_tts
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
import io

logger = logging.getLogger("VoiceAPI")
router = APIRouter()

# Vozes recomendadas: pt-BR-FranciscaNeural (F), pt-BR-AntonioNeural (M)
DEFAULT_VOICE = "pt-BR-FranciscaNeural"

@router.get("/speak")
async def speak(text: str, voice: str = DEFAULT_VOICE):
    """
    Gera áudio MP3 a partir de texto usando Microsoft Edge TTS.
    Retorna um stream de áudio direto para o Android.
    """
    if not text:
        raise HTTPException(status_code=400, detail="Texto não fornecido.")
    
    try:
        logger.info(f"🎙️ Gerando voz para: '{text[:30]}...'")
        communicate = edge_tts.Communicate(text, voice)
        
        # Buffer para armazenar o áudio em memória
        audio_stream = io.BytesIO()
        
        async for chunk in communicate.stream():
            if chunk["data"]:
                audio_stream.write(chunk["data"])
        
        audio_stream.seek(0)
        
        return StreamingResponse(
            audio_stream, 
            media_type="audio/mpeg",
            headers={"Content-Disposition": "attachment; filename=voice.mp3"}
        )
    except Exception as e:
        logger.error(f"❌ Erro ao gerar voz: {e}")
        raise HTTPException(status_code=500, detail=str(e))
