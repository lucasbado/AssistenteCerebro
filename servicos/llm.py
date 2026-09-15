"""
servicos/llm.py
"""
from __future__ import annotations
import json
import logging
import os
import asyncio
import re
from datetime import datetime
import httpx
from groq import AsyncGroq
from modelos.catalogo import EntidadeSemantica
from servicos.obsidian_service import obsidian_service
from servicos.consciencia import consciencia
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

class ServicoLLM:
    def __init__(self):
        # Configuração para Groq (Cloud)
        self.api_key = os.getenv("GROQ_API_KEY")
        # 🚀 LISTA REAL DE MODELOS DISPONÍVEIS (Verificada via API)
        self.modelos_groq = [
            "openai/gpt-oss-120b",           # Top 1: Inteligência Superior
            "openai/gpt-oss-20b",            # Top 2: Equilíbrio Perfeito
            "openai/gpt-oss-safeguard-20b",  # Top 3: Estabilidade / Segurança
            "qwen/qwen3.8-27b",              # Top 4: Versatilidade (Alibaba)
            "groq/compound",                 # Top 5: Raciocínio com Ferramentas
            "groq/compound-mini",            # Top 6: Velocidade Máxima
            "allam-2-7b",                    # Top 7: O "Tanque" (Cota Alta / Fallback Final)
            "canopylabs/orpheus-v1-english"  # Preview Fallback
        ]
        self.modelo_atual = self.modelos_groq[0]

        if self.api_key:
            self.client = AsyncGroq(api_key=self.api_key)
            logger.info(f"🚀 [LLM] Groq Cloud ativado. Modelo padrão: {self.modelo_atual}")
        else:
            if os.getenv("RENDER"):
                self.client = None
                self.modelo = None
                logger.error("❌ [LLM] ERRO CRÍTICO: GROQ_API_KEY não encontrada no Render!")
            else:
                self.url = "http://localhost:11434/api/generate"
                self.modelo = "qwen2.5:7b"
                self.http_client = httpx.AsyncClient(timeout=30)
                logger.warning("⚠️ [LLM] GROQ_API_KEY não encontrada. Usando Ollama local.")

    async def _gerar_json(self, prompt: str, system: str) -> dict: 
        if self.api_key and self.client:
            # 🚀 RODÍZIO INTELIGENTE DE MODELOS EM CASO DE RATE LIMIT
            for i, modelo in enumerate(self.modelos_groq):
                try:
                    logger.info(f"🤖 [LLM] Tentando {modelo}...")
                    chat_completion = await self.client.chat.completions.create(
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt},
                        ],
                        model=modelo,
                        response_format={"type": "json_object"},
                        temperature=0.1,
                        timeout=40.0
                    )
                    self.modelo_atual = modelo
                    return json.loads(chat_completion.choices[0].message.content)
                except Exception as e:
                    err_str = str(e).lower()
                    if "429" in err_str or "rate_limit" in err_str:
                        # 🧠 BACKOFF INTELIGENTE: Tenta extrair o tempo de espera da API
                        wait_time = 2.0
                        match = re.search(r"try again in (\d+m)?([\d.]+)s", err_str)
                        if match:
                            try:
                                m, s = match.groups()
                                m_val = int(m[:-1]) if m else 0
                                s_val = float(s)
                                wait_time = (m_val * 60) + s_val
                                wait_time = min(wait_time + 0.5, 8.0) # Não trava o app, prefere trocar de modelo
                            except: pass
                        
                        logger.warning(f"⚠️ [LLM] Limite em {modelo}. Aguardando {wait_time}s antes de trocar...")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        logger.error(f"❌ [LLM] Falha no modelo {modelo}: {e}")
                        continue 
            
            raise ValueError("Ollie esgotou todas as cotas diárias em todos os modelos.")
            
        elif not os.getenv("RENDER"):
            payload = {"model": self.modelo, "prompt": prompt, "system": system, "stream": False, "format": "json"}
            resposta = await self.http_client.post(self.url, json=payload)
            return json.loads(resposta.json()["response"])
        else:
            raise ValueError("IA Indisponível.")

    async def classificar_evento(self, categoria: str, pacote: str, payload: dict, historico: list[str] | None = None, timestamp_dispositivo: datetime | None = None, conhecimento: str = "", habitos: str = "") -> dict:
        agora_dt = timestamp_dispositivo or datetime.now()
        agora = agora_dt.strftime("%H:%M")
        hora = agora_dt.hour
        periodo = "Madrugada" if 0<=hora<6 else "Manhã" if 6<=hora<12 else "Tarde" if 12<=hora<18 else "Noite"
        
        # 💡 ECONOMIA: Instruções apenas se necessário (texto longo ou palavras-chave)
        texto_msg = str(payload.get('texto', '')).lower()
        instrucoes_docs = ""
        if len(texto_msg) > 15 or any(k in texto_msg for k in ["ajuda", "como", "quem", "explica", "rotina"]):
            instrucoes_docs = self._carregar_instrucoes_cognitivas()

        resumo_ambiente = consciencia.obter_resumo_para_llm()

        system = f"""Ollie: Parceira, Ácida, Gírias (brabo, vish, bora).
FOCO: AÇÃO DIRETA. Max 2 frases.

### CONTEXTO:
- Período: {periodo} ({agora})
- Ambiente: {resumo_ambiente}
- Obsidian: {conhecimento}
- Hábitos: {habitos}
{instrucoes_docs}

### RESPOSTA (JSON):
{{
  "intencao_captada": "...",
  "tipo_interacao": "NOTIFICAR|SUGERIR|IGNORAR",
  "mensagem_dinamica": "...",
  "execucao_direta": [ {{"alvo":"PC|MOBILE", "comando":"...", "parametro":"..."}} ]
}}"""
        
        fluxo = (historico or [])[-3:] # Somente 3 mensagens
        prompt = f"HISTÓRICO: {json.dumps(fluxo, ensure_ascii=False)}\nEVENTO: {categoria} | {pacote} | {json.dumps(payload, ensure_ascii=False)}"

        try:
            return await self._gerar_json(prompt, system)
        except Exception as e:
            logger.error(f"❌ [LLM] Erro crítico: {e}")
            raise

    async def resumir_perfil_usuario(self, fatos: str) -> dict:
        system = "Ollie: Inteligência Estratégica. Resumo comportamental ácido + card 'sugestao_regra' se houver padrão."
        prompt = f"Fatos do Usuário:\n{fatos}"
        try: return await self._gerar_json(prompt, system)
        except: return {"resumo": "N/A", "cards": []}

    async def sintetizar_resposta_pesquisa(self, query: str, conteudo_web: str, historico: list[str] | None = None) -> dict:
        system = "Ollie: Amiga ácida. Resuma a web com gírias e precisão."
        prompt = json.dumps({"historico": (historico or [])[-3:], "query": query, "web": conteudo_web[:2000]}, ensure_ascii=False)
        try: return await self._gerar_json(prompt, system)
        except: return {"resposta_amigavel": "Erro na pesquisa.", "fato_para_aprender": None}

    def _carregar_instrucoes_cognitivas(self) -> str:
        instrucoes = []
        arquivos = ["capabilities.md", "filosofia.md"]
        try:
            mapa = obsidian_service.ler_nota("Mapa_Mestre.md")
            if mapa: instrucoes.append(f"### MAPA MESTRE:\n{mapa[:500]}")
        except: pass

        for pasta in ["D:/Programacao/AssistenteCell/docs", "docs"]:
            if os.path.exists(pasta):
                for arq in arquivos:
                    path = os.path.join(pasta, arq)
                    if os.path.exists(path):
                        with open(path, "r", encoding="utf-8") as f:
                            instrucoes.append(f"### {arq.upper()}:\n{f.read()[:500]}")
                break
        return "\n\n".join(instrucoes)
