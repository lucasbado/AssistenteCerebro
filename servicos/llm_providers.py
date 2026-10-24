# servicos/llm_providers.py
import logging
import os
import time
import re
import httpx
from typing import Protocol, runtime_checkable
from groq import AsyncGroq
from dotenv import load_dotenv
from servicos.consumo_ia import consumo_ia

load_dotenv()
logger = logging.getLogger("LLMProviders")

@runtime_checkable
class LLMProvider(Protocol):
    async def gerar(self, prompt: str, system: str, max_tokens: int = 2500) -> str:
        ...
    def disponivel(self) -> bool:
        ...

class GroqProvider:
    def __init__(self, client=None, relogio=time.monotonic, consumo=None):
        self.consumo = consumo if consumo is not None else consumo_ia
        self.api_key = os.getenv("GROQ_API_KEY")
        self.client = client if client is not None else (AsyncGroq(api_key=self.api_key, max_retries=0) if self.api_key else None)
        principal = os.getenv("GROQ_MODEL", "").strip() or "openai/gpt-oss-120b"
        fallbacks = os.getenv("GROQ_FALLBACK_MODELS", "openai/gpt-oss-20b").split(",")
        self.modelos = list(dict.fromkeys(m.strip() for m in [principal, *fallbacks] if m.strip()))
        self._relogio = relogio
        self._indisponiveis_ate = {}
        self._sem_json_object = set()
        self.modelo_atual = None
        self.circuit_open = False

    def disponivel(self) -> bool:
        return bool(self.client and not self.circuit_open)

    @staticmethod
    def _erro_api(erro):
        body = getattr(erro, "body", None)
        if not isinstance(body, dict):
            return {}
        return body.get("error", body) if isinstance(body.get("error", body), dict) else {}

    @classmethod
    def _formato_nao_suportado(cls, erro):
        if getattr(erro, "status_code", None) not in {400, 422}:
            return False
        dados = cls._erro_api(erro)
        mensagem = str(dados.get("message", "")).lower()
        return (dados.get("code") == "unsupported_response_format" or
                ("response_format" in mensagem and any(termo in mensagem for termo in
                    ("not supported", "unsupported", "does not support", "not available"))))

    async def gerar(self, prompt: str, system: str, max_tokens: int = 2500) -> str:
        if not self.disponivel():
            raise ValueError("Groq indisponível ou em circuit breaker.")
        
        # Garante que a palavra "json" esteja presente no system prompt quando usando response_format={"type": "json_object"}
        system_mod = system
        if "json" not in system_mod.lower():
            system_mod += "\n\n(Return your response in valid JSON format)."

        ultima_excecao = None
        for modelo in self.modelos:
            if self._indisponiveis_ate.get(modelo, 0) > self._relogio():
                continue
            reserva = None
            try:
                reserva = await self.consumo.reservar(modelo, prompt, system_mod, max_tokens)
                logger.info(f"🤖 [Groq] Tentando gerar com o modelo: {modelo}")
                parametros = {
                    "messages": [{"role": "system", "content": system_mod}, {"role": "user", "content": prompt}],
                    "model": modelo, "temperature": 0.1, "max_tokens": max_tokens, "timeout": 25.0,
                }
                if modelo not in self._sem_json_object:
                    parametros["response_format"] = {"type": "json_object"}
                try:
                    chat_completion = await self.client.chat.completions.create(**parametros)
                except Exception as e_json:
                    if not self._formato_nao_suportado(e_json) or "response_format" not in parametros:
                        raise
                    logger.warning("[Groq] %s não suporta json_object; mantendo instrução JSON no prompt.", modelo)
                    self._sem_json_object.add(modelo)
                    parametros.pop("response_format")
                    chat_completion = await self.client.chat.completions.create(**parametros)

                content = chat_completion.choices[0].message.content
                await self.consumo.concluir(reserva, getattr(chat_completion, 'usage', None))
                reserva = None
                if content:
                    self.modelo_atual = modelo
                    logger.info("[Groq] Resposta gerada com %s.", modelo)
                    return content
                raise ValueError("Resposta vazia da Groq.")
            except Exception as e:
                status = getattr(e, "status_code", None)
                codigo = self._erro_api(e).get("code")
                if reserva is not None:
                    await self.consumo.concluir(reserva, recusado=status is not None and 400 <= status < 500)
                if status == 429:
                    await self.consumo.bloquear(modelo, self._tempo_espera(e))
                if status == 401 or (status == 403 and codigo != "model_permission_blocked"):
                    raise
                if status == 404 or codigo in {"model_not_found", "model_decommissioned", "model_permission_blocked"}:
                    self._indisponiveis_ate[modelo] = self._relogio() + 3600
                    await self.consumo.bloquear(modelo, 3600)
                logger.warning("[Groq] Falha em %s (HTTP %s, código %s); tentando o próximo modelo.",
                               modelo, status or "indisponível", codigo or type(e).__name__)
                ultima_excecao = e
                continue
        
        raise ultima_excecao or ValueError("Todos os modelos da Groq falharam.")

    @classmethod
    def _tempo_espera(cls, erro):
        headers = getattr(getattr(erro, 'response', None), 'headers', {})
        try: return max(1, min(86400, float(headers.get('retry-after', ''))))
        except (ValueError, TypeError): pass
        mensagem = str(cls._erro_api(erro).get('message', ''))
        trecho = re.search(r'try again in\s+([\d.hms]+)', mensagem, re.I)
        if trecho:
            segundos = sum(float(n) * {'h': 3600, 'm': 60, 's': 1}[u] for n, u in re.findall(r'([\d.]+)([hms])', trecho[1]))
            if segundos: return min(86400, segundos + 1)
        return 60

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
            "keep_alive": "2m",
            "options": {"temperature": 0.1, "num_predict": max_tokens}
        }
        resp = await self.http_client.post(self.url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        if not data.get('response'): raise ValueError('Ollama não devolveu resposta.')
        return data['response']
