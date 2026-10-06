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
    async def gerar(self, prompt: str, system: str, max_tokens: int = 500) -> str:
        ...
    def disponivel(self) -> bool:
        ...

class GroqProvider:
    def __init__(self):
        self.api_key = os.getenv("GROQ_API_KEY")
        self.client = AsyncGroq(api_key=self.api_key) if self.api_key else None
        self.modelo = "llama-3.3-70b-versatile"
        self.circuit_open = False

    def disponivel(self) -> bool:
        return bool(self.client and not self.circuit_open)

    async def gerar(self, prompt: str, system: str, max_tokens: int = 500) -> str:
        if not self.disponivel():
            raise ValueError("Groq indisponível ou em circuit breaker.")
        
        chat_completion = await self.client.chat.completions.create(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            model=self.modelo,
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=max_tokens,
            timeout=30.0
        )
        return chat_completion.choices[0].message.content

class OllamaProvider:
    def __init__(self):
        self.url = "http://localhost:11434/api/generate"
        self.modelo = "qwen2.5:3b"
        self.http_client = httpx.AsyncClient(timeout=45.0)

    def disponivel(self) -> bool:
        return not os.getenv("RENDER")

    async def gerar(self, prompt: str, system: str, max_tokens: int = 500) -> str:
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
