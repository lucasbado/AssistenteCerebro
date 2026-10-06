# servicos/llm.py
from __future__ import annotations
import json
import logging
import asyncio
from datetime import datetime
from servicos.llm_providers import GroqProvider, OllamaProvider
from servicos.semantic_cache import semantic_cache_service
from servicos.context_builder import context_builder
from servicos.obsidian_service import obsidian_service
from servicos.consciencia import consciencia
from modelos.catalogo import EntidadeSemantica

logger = logging.getLogger("ServicoLLM")

class ServicoLLM:
    def __init__(self):
        self.groq = GroqProvider()
        self.ollama = OllamaProvider()
        self._consecutive_failures = 0
        self._circuit_open_until = 0

    def _pick_provider(self):
        agora = asyncio.get_event_loop().time()
        if self._consecutive_failures >= 3 and agora < self._circuit_open_until:
            logger.warning("⚡ [LLM] Circuit breaker aberto na Groq. Usando Ollama local.")
            if self.ollama.disponivel():
                return self.ollama
        
        if self.groq.disponivel():
            return self.groq
        elif self.ollama.disponivel():
            return self.ollama
        raise ValueError("Nenhum provedor LLM disponível.")

    async def classificar_evento(self, categoria: str, pacote: str, payload: dict, historico: list[str] | None = None, timestamp_dispositivo: datetime | None = None, knowledge: str = "", habits: str = "") -> dict:
        texto_msg = str(payload.get('texto', '')).lower()

        # 1. Verificar Cache Semântico
        cached_resp = await semantic_cache_service.buscar(texto_msg)
        if cached_resp:
            try:
                return json.loads(cached_resp)
            except: pass

        # 2. Construir Contexto Enxuto via ContextBuilder (≤ 2k tokens)
        contexto = await context_builder.construir_contexto(texto_msg, session_id=pacote)

        agora_dt = timestamp_dispositivo or datetime.now()
        agora = agora_dt.strftime("%H:%M")
        periodo = "Madrugada" if 0 <= agora_dt.hour < 6 else "Manhã" if 6 <= agora_dt.hour < 12 else "Tarde" if 12 <= agora_dt.hour < 18 else "Noite"
        resumo_ambiente = consciencia.obter_resumo_para_llm()

        system = f"""Ollie: Parceira estratégica, inteligente e humana.
TOM: Informal, direta, parceira de desenvolvimento.
CONTEXTO:
- Período: {periodo} ({agora})
- Ambiente: {resumo_ambiente}
- Resumo Global: {contexto['global_summary']}
- Resumo Sessão: {contexto['session_summary']}
- Fatos Relevantes: {contexto['fatos_relevantes']}

RESPOSTA (JSON):
{{
  "intencao_captada": "...",
  "tipo_interacao": "NOTIFICAR|SUGERIR|IGNORAR",
  "mensagem_dinamica": "...",
  "execucao_direta": [ {{"alvo":"PC|MOBILE", "comando":"...", "parametro":"..."}} ],
  "memoria_obsidian": {{ "titulo": "...", "fato": "..." }}
}}"""

        prompt = f"EVENTO: {categoria} | {pacote} | {json.dumps(payload, ensure_ascii=False)}"

        provider = self._pick_provider()
        try:
            resposta_str = await provider.gerar(prompt, system, max_tokens=400)
            
            # Sucesso: reseta falhas consecutivas
            self._consecutive_failures = 0

            # Salva no cache semântico
            await semantic_cache_service.inserir(texto_msg, resposta_str)

            return json.loads(resposta_str)
        except Exception as e:
            logger.error(f"❌ [LLM] Erro com provider: {e}")
            self._consecutive_failures += 1
            if self._consecutive_failures >= 3:
                self._circuit_open_until = asyncio.get_event_loop().time() + 60 # Cooldown de 60s
            
            # Tenta fallback para Ollama se falhou na Groq
            if provider != self.ollama and self.ollama.disponivel():
                logger.warning("🔄 [LLM] Acionando fallback para Ollama local...")
                resposta_str = await self.ollama.gerar(prompt, system, max_tokens=400)
                return json.loads(resposta_str)
            raise

    async def resumir_perfil_usuario(self, texto_perfil: str) -> dict:
        system = "Ollie: Analise os dados de perfil do usuário e retorne um JSON estrito com 'resumo' e 'cards'."
        prompt = f"DADOS DO PERFIL:\n{texto_perfil}"
        provider = self._pick_provider()
        try:
            resp = await provider.gerar(prompt, system, max_tokens=600)
            return json.loads(resp)
        except Exception as e:
            logger.error(f"Erro em resumir_perfil_usuario: {e}")
            return {"resumo": "Resumo indisponível.", "cards": []}

    async def classificar_contato(self, contato_nome: str) -> EntidadeSemantica:
        from modelos.catalogo import EntidadeSemantica
        system = "Classifique o contato e retorne um JSON com os atributos (ex: nome, tipo)."
        prompt = f"CONTATO: {contato_nome}"
        provider = self._pick_provider()
        try:
            resp = await provider.gerar(prompt, system, max_tokens=200)
            data = json.loads(resp)
            return EntidadeSemantica(tipo="CONTATO", chave=contato_nome, atributos=data)
        except:
            return EntidadeSemantica(tipo="CONTATO", chave=contato_nome, atributos={"nome": contato_nome})

    async def sintetizar_resposta_pesquisa(self, query: str, conteudo: str, historico: list) -> dict:
        system = "Sintetize a pesquisa web e retorne um JSON estrito com 'resposta_amigavel' e 'fato_para_aprender'."
        prompt = f"QUERY: {query}\nCONTEÚDO: {conteudo}"
        provider = self._pick_provider()
        try:
            resp = await provider.gerar(prompt, system, max_tokens=500)
            return json.loads(resp)
        except Exception as e:
            logger.error(f"Erro em sintetizar_resposta_pesquisa: {e}")
            return {"resposta_amigavel": f"Pesquisei sobre {query}, mas tive um erro ao sintetizar.", "fato_para_aprender": ""}

    async def _gerar_json(self, prompt: str, system: str) -> dict:
        provider = self._pick_provider()
        try:
            resp = await provider.gerar(prompt, system, max_tokens=800)
            return json.loads(resp)
        except Exception as e:
            logger.error(f"Erro em _gerar_json: {e}")
            return {}
