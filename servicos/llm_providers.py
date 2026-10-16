# servicos/llm_providers.py
import logging
import os
import httpx
from typing import Protocol, runtime_checkable
from groq import AsyncGroq
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("LLMProviders")

@runtime_checkable
class LLMProvider(Protocol):
    async def gerar(self, prompt: str, system: str, max_tokens: int = 2500) -> str:
        ...
    def disponivel(self) -> bool:
        ...

class GroqProvider:
    def __init__(self):
        self.api_key = os.getenv("GROQ_API_KEY")
        self.client = AsyncGroq(api_key=self.api_key) if self.api_key else None
        # Cascata completa de todos os modelos disponíveis na conta do desenvolvedor Groq
        self.modelos = [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "openai/gpt-oss-120b",
            "openai/gpt-oss-20b",
            "qwen/qwen3.8-27b",
            "meta-models/muse-spark-open",
            "minimaxai/minimax-m2.7"
        ]
        self.circuit_open = False

    def disponivel(self) -> bool:
        return bool(self.client and not self.circuit_open)

    async def gerar(self, prompt: str, system: str, max_tokens: int = 2500) -> str:
        if not self.disponivel():
            raise ValueError("Groq indisponível ou em circuit breaker.")
        
        # Garante que a palavra "json" esteja presente no system prompt quando usando response_format={"type": "json_object"}
        system_mod = system
        if "json" not in system_mod.lower():
            system_mod += "\n\n(Return your response in valid JSON format)."

        ultima_excecao = None
        for modelo in self.modelos:
            try:
                logger.info(f"🤖 [Groq] Tentando gerar com o modelo: {modelo}")
                try:
                    chat_completion = await self.client.chat.completions.create(
                        messages=[
                            {"role": "system", "content": system_mod},
                            {"role": "user", "content": prompt},
                        ],
                        model=modelo,
                        response_format={"type": "json_object"},
                        temperature=0.1,
                        max_tokens=max_tokens,
                        timeout=25.0
                    )
                except Exception as e_json:
                    logger.warning(f"⚠️ [Groq] {modelo} falhou com json_object ({e_json}). Tentando sem response_format estrito...")
                    chat_completion = await self.client.chat.completions.create(
                        messages=[
                            {"role": "system", "content": system_mod},
                            {"role": "user", "content": prompt},
                        ],
                        model=modelo,
                        temperature=0.1,
                        max_tokens=max_tokens,
                        timeout=25.0
                    )

                content = chat_completion.choices[0].message.content
                if content:
                    return content
            except Exception as e:
                logger.warning(f"⚠️ [Groq] Falha com o modelo {modelo}: {e}. Migrando para o próximo modelo da cadeia...")
                ultima_excecao = e
                continue
        
        raise ultima_excecao or ValueError("Todos os modelos da Groq falharam.")

class OllamaProvider:
    def __init__(self):
        self.url = "http://localhost:11434/api/generate"
        self.modelo = "qwen2.5:3b"
        self.http_client = httpx.AsyncClient(timeout=45.0)

    def disponivel(self) -> bool:
        return not os.getenv("RENDER")

    async def gerar(self, prompt: str, system: str, max_tokens: int = 1000) -> str:
        payload = {
            "model": self.modelo,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1, "num_predict": max_tokens, "keep_alive": -1} # Mantém residente
        }
        resp = await self.http_client.post(self.url, json=payload)
        data = resp.json()
        return data.get("response", "{}")
