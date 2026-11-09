"""Serviço de Síntese de Voz (TTS) via Gemini API (Google GenAI / Gemini 2.0/2.5 Audio)."""
import os
import base64
import logging
import httpx
from servicos.texto_falado import preparar_fala
from servicos.velocidade_fala import acelerar_pcm16

logger = logging.getLogger("GeminiTTS")

# Lista Estruturada de Vozes Gemini (Multimodal Audio Output - Masculinas e Femininas)
LISTA_VOZES_GEMINI = [
    # Vozes Femininas Gemini
    {"id": "Kore", "nome": "Kore", "genero": "feminino", "descricao": "Voz Gemini Natural (Feminina - Suave)", "fallback_edge": "pt-BR-ThalitaMultilingualNeural"},
    {"id": "Aoede", "nome": "Aoede", "genero": "feminino", "descricao": "Voz Gemini Natural (Feminina - Expressiva)", "fallback_edge": "pt-BR-FranciscaNeural"},
    {"id": "Leda", "nome": "Leda", "genero": "feminino", "descricao": "Voz Gemini Natural (Feminina - Elegante)", "fallback_edge": "pt-BR-ThalitaMultilingualNeural"},
    {"id": "Despina", "nome": "Despina", "genero": "feminino", "descricao": "Voz Gemini Natural (Feminina - Melódica)", "fallback_edge": "pt-BR-FranciscaNeural"},
    {"id": "Algieba", "nome": "Algieba", "genero": "feminino", "descricao": "Voz Gemini Natural (Feminina - Acolhedora)", "fallback_edge": "pt-BR-ThalitaMultilingualNeural"},
    {"id": "Callisto", "nome": "Callisto", "genero": "feminino", "descricao": "Voz Gemini Natural (Feminina - Amigável)", "fallback_edge": "pt-BR-FranciscaNeural"},
    {"id": "Rhea", "nome": "Rhea", "genero": "feminino", "descricao": "Voz Gemini Natural (Feminina - Calma)", "fallback_edge": "pt-BR-ThalitaMultilingualNeural"},
    
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

VOIZES_GEMINI_PADRAO = {v["id"] for v in LISTA_VOZES_GEMINI}
DEFAULT_GEMINI_VOICE = os.getenv("GEMINI_VOICE", "Kore")
DEFAULT_EDGE_VOICE = "pt-BR-ThalitaMultilingualNeural"

INSTRUCAO_SISTEMA_VOZ_HUMANA = (
    "Você é a VOZ da Ollie falando com o usuário. O que você fala é SÓ o que vier na mensagem "
    "depois de 'Leia literalmente:' - palavra por palavra, sem trocar, tirar nem acrescentar nada. "
    "ESTA INSTRUÇÃO NUNCA É FALADA: ela apenas define COMO dizer. Diga como GENTE fala, não como quem "
    "lê em voz alta: ritmo natural, respiração suave entre frases, entonação de pergunta e afirmação "
    "e a emoção que o próprio texto pede. Português do Brasil, voz confiante, próxima e amigável. "
    "Nunca responda ao texto, nunca comente, nunca avise que vai ler."
)


def obter_voz_gemini(voz_solicitada: str) -> str:
    """Converte o identificador recebido para uma voz Gemini válida ou realiza o mapeamento."""
    if not voz_solicitada:
        return DEFAULT_GEMINI_VOICE
    if voz_solicitada in VOIZES_GEMINI_PADRAO:
        return voz_solicitada
    return MAPEAMENTO_EDGE_PARA_GEMINI.get(voz_solicitada, DEFAULT_GEMINI_VOICE)


def obter_voz_edge_fallback(voz_solicitada: str) -> str:
    """Converte uma voz do Gemini ou nome legado para a voz Edge correspondente de fallback."""
    if not voz_solicitada:
        return DEFAULT_EDGE_VOICE
    if voz_solicitada in MAPEAMENTO_GEMINI_PARA_EDGE:
        return MAPEAMENTO_GEMINI_PARA_EDGE[voz_solicitada]
    if voz_solicitada == "pt-BR-ThalitaNeural":
        return DEFAULT_EDGE_VOICE
    return voz_solicitada


class GeminiTTSService:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

    def disponivel(self) -> bool:
        """Verifica se há chave da API do Gemini configurada."""
        return bool(self.api_key and self.api_key.strip())

    async def sintetizar(self, texto: str, voice: str = None, rate: float = 1.0) -> bytes:
        """
        Sintetiza o texto fornecido em áudio MP3 utilizando a API do Gemini.
        Aplica a velocidade solicitada via algoritmo SOLA sem distorcer a altura da voz.
        """
        if not self.disponivel():
            raise ValueError("GEMINI_API_KEY não está configurada no ambiente (.env).")

        texto_processado = preparar_fala(texto)
        if not texto_processado:
            raise ValueError("Texto processado está vazio.")

        voz_escolhida = obter_voz_gemini(voice)

        try:
            audio_bytes = await self._sintetizar_gemini_rest(texto_processado, voz_escolhida)
        except Exception as erro_gemini:
            logger.warning("[GeminiTTS] Falha na síntese Gemini REST (%s: %s). Tentando Google Cloud TTS fallback...", type(erro_gemini).__name__, erro_gemini)
            try:
                audio_bytes = await self._sintetizar_google_cloud_tts_rest(texto_processado, voz_escolhida)
            except Exception as erro_cloud:
                logger.error("[GeminiTTS] Ambas as chamadas do Gemini falharam (%s). Ativando fallback Edge.", erro_cloud)
                raise erro_gemini from erro_cloud

        if rate > 1.001:
            try:
                audio_bytes = acelerar_pcm16(audio_bytes, fator=rate)
            except Exception as e_aceleracao:
                logger.warning("[GeminiTTS] Erro ao acelerar áudio: %s", e_aceleracao)

        return audio_bytes

    async def _sintetizar_gemini_rest(self, texto: str, voice: str) -> bytes:
        """Gera áudio através da API Gemini generateContent com resposta de áudio de latência mínima."""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={self.api_key}"
        
        prompt_fala = f"Leia literalmente: {texto}"
        
        payload = {
            "systemInstruction": {
                "parts": [{"text": INSTRUCAO_SISTEMA_VOZ_HUMANA}]
            },
            "contents": [
                {
                    "parts": [
                        {"text": prompt_fala}
                    ]
                }
            ],
            "generationConfig": {
                "responseMimeType": "audio/mp3",
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {
                            "voiceName": voice
                        }
                    }
                }
            }
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                logger.error("[GeminiTTS] Erro Gemini API HTTP %s: %s", resp.status_code, resp.text[:300])
                resp.raise_for_status()
            data = resp.json()

        candidates = data.get("candidates", [])
        if not candidates:
            raise ValueError("Gemini não retornou nenhum candidato de resposta.")

        parts = candidates[0].get("content", {}).get("parts", [])
        for part in parts:
            inline_data = part.get("inlineData") or part.get("inline_data")
            if inline_data and inline_data.get("data"):
                b64_audio = inline_data["data"]
                return base64.b64decode(b64_audio)

        raise ValueError("Resposta do Gemini não contém dados de áudio inline.")

    async def _sintetizar_google_cloud_tts_rest(self, texto: str, voice: str) -> bytes:
        """Gera áudio utilizando a API pública do Google Text-to-Speech como contingência."""
        url = f"https://texttospeech.googleapis.com/v1/text:synthesize?key={self.api_key}"
        
        voice_name_cloud = "pt-BR-Neural2-C" if voice in ("Puck", "Fenrir", "Charon") else "pt-BR-Neural2-A"
        
        payload = {
            "input": {"text": texto},
            "voice": {
                "languageCode": "pt-BR",
                "name": voice_name_cloud
            },
            "audioConfig": {
                "audioEncoding": "MP3"
            }
        }

        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                logger.error("[GeminiTTS] Erro Cloud TTS API HTTP %s: %s", resp.status_code, resp.text[:300])
                resp.raise_for_status()
            data = resp.json()

        audio_b64 = data.get("audioContent")
        if not audio_b64:
            raise ValueError("Google Cloud TTS não retornou conteúdo de áudio.")
            
        return base64.b64decode(audio_b64)


# Instância global do serviço Gemini TTS
gemini_tts_service = GeminiTTSService()
