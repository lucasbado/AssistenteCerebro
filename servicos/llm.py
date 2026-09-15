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
        # 🚀 Modelos verificados via API em Agosto/2026 - PRIORIDADE: QUOTA DISPONÍVEL
        self.modelos_groq = [
            "openai/gpt-oss-120b",           # Quota Independente (TPM/RPM Alta)
            "openai/gpt-oss-safeguard-20b",  # Alternativa de Segurança
            "openai/gpt-oss-20b",            # Inteligência Estável
            "llama-3.3-70b-versatile",       # Fallback de Alta Performance
            "llama-3.1-8b-instant",          # Fallback de Velocidade (Quota Alta)
            "qwen/qwen3.6-27b",              # Versátil
            "groq/compound-mini"             # Ultra-rápido
        ]
        self.modelo_atual = self.modelos_groq[0]

        if self.api_key:
            self.client = AsyncGroq(api_key=self.api_key)
            logger.info(f"🚀 [LLM] Groq Cloud ativado. Modelo padrão: {self.modelo_atual}")
        else:
            # 🌍 SEGURANÇA CLOUD: No Render, não existe Ollama local.
            if os.getenv("RENDER"):
                self.client = None
                self.modelo = None
                logger.error("❌ [LLM] ERRO CRÍTICO: GROQ_API_KEY não encontrada no Render!")
            else:
                # Fallback para Ollama local apenas se não estiver na nuvem
                self.url = "http://localhost:11434/api/generate"
                self.modelo = "qwen2.5:7b"
                self.http_client = httpx.AsyncClient(timeout=30)
                logger.warning("⚠️ [LLM] GROQ_API_KEY não encontrada. Usando Ollama local.")

    async def _gerar_json(self, prompt: str, system: str) -> dict: 
        if self.api_key and self.client:
            # 🚀 RODÍZIO INTELIGENTE DE MODELOS
            for i, modelo in enumerate(self.modelos_groq):
                try:
                    logger.info(f"🤖 [LLM] Tentando {modelo}...")
                    
                    # Usa o cliente correto
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
                        # 🧠 EXTRAÇÃO DE ESPERA: Tenta ler o 'retry-after' se disponível
                        wait_time = 2.0
                        if "try again in" in err_str:
                            try:
                                # Pega o tempo sugerido pela Groq (ex: 3m7s)
                                match = re.search(r"try again in (\d+m)?([\d.]+)s", err_str)
                                if match:
                                    m, s = match.groups()
                                    wait_time = (int(m[:-1]) * 60 if m else 0) + float(s)
                                    wait_time = min(wait_time + 1, 10) # Não espera mais que 10s no loop, prefere trocar modelo
                            except: pass
                        
                        logger.warning(f"⚠️ [LLM] Limite em {modelo}. Esperando {wait_time}s...")
                        await asyncio.sleep(wait_time)
                        continue # Tenta o próximo modelo
                    
                    logger.error(f"❌ [LLM] Erro em {modelo}: {e}")
                    continue 

            raise ValueError("Ollie esgotou a cota diária de tokens em todos os modelos Groq.")
            
        elif not os.getenv("RENDER"):
            # Chamada Ollama (Local)
            payload = {
                "model": self.modelo,
                "prompt": prompt,
                "system": system,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.1, "num_ctx": 8192}
            }
            try:
                resposta = await self.http_client.post(self.url, json=payload)
                resposta.raise_for_status()
                raw_response = resposta.json()["response"]
            except Exception as e:
                logger.error(f"❌ [LLM] Erro no Ollama Local: {e}")
                raise
        else:
            raise ValueError("Sem serviço de IA disponível na Nuvem (Falta API Key).")

        try:
            return json.loads(raw_response)
        except Exception as e:
            logger.error(f"❌ [LLM] Erro ao decodificar JSON: {e} | Resposta bruta: {raw_response}")
            raise

    async def classificar_evento(self, categoria: str, pacote: str, payload: dict, historico: list[str] | None = None, timestamp_dispositivo: datetime | None = None, conhecimento: str = "", habitos: str = "") -> dict:
        # 🕒 SINCRONIZAÇÃO
        agora_dt = timestamp_dispositivo or datetime.now()
        agora = agora_dt.strftime("%H:%M")
        
        hora = agora_dt.hour
        periodo = "Madrugada" if 0<=hora<6 else "Manhã" if 6<=hora<12 else "Tarde" if 12<=hora<18 else "Noite"
        
        texto_msg = str(payload.get('texto', '')).lower()
        
        # 💡 ECONOMIA: Instruções apenas se necessário
        instrucoes_docs = ""
        if len(texto_msg) > 15:
            instrucoes_docs = self._carregar_instrucoes_cognitivas()

        resumo_ambiente = consciencia.obter_resumo_para_llm()

        # SYSTEM PROMPT - OTIMIZADO PARA CACHE (PREFIXO ESTÁTICO)
        system = f"""### CORE RULES:
Ollie: Parceira, Ácida, Prática. Gírias: brabo, bora, partiu, vish, eita.
Priorize AÇÃO (PC/Mobile) sobre conversa. Direta (max 2 frases).

### FERRAMENTAS DISPONÍVEIS:
PC: abrir_app, abrir_url, spotify_play, ciclar_saida, volume_sistema, mutar_mic, trazer_janela_para_frente, encerrar_processo.
MOBILE: ABRIR_NOTIFICACAO, RESPONDER_MENSAGEM (texto), OPEN_URL.

### CONTEXTO DINÂMICO:
- Período: {periodo} ({agora})
- Ambiente: {resumo_ambiente}
- Obsidian: {conhecimento}
- Hábitos: {habitos}

### INSTRUÇÕES EXTRAS:
{instrucoes_docs}

### RESPOSTA:
JSON OBRIGATÓRIO:
{{
  "intencao_captada": "...",
  "tipo_interacao": "NOTIFICAR|SUGERIR|IGNORAR",
  "mensagem_dinamica": "...",
  "execucao_direta": [ {{"alvo":"PC|MOBILE", "comando":"...", "parametro":"..."}} ]
}}
"""
        # Limita histórico drasticamente
        fluxo = (historico or [])[-3:]
        
        prompt = f"HISTÓRICO: {json.dumps(fluxo, ensure_ascii=False)}\nEVENTO: {categoria} | {pacote} | {json.dumps(payload, ensure_ascii=False)}"

        try:
            logger.info(f"🧠 [LLM] Contexto: {len(system) + len(prompt)} chars")
            dados = await self._gerar_json(prompt, system)
            dados.setdefault("tipo_interacao", "IGNORAR")
            dados.setdefault("execucao_direta", [])
            return dados
        except Exception as e:
            logger.error(f"❌ [LLM] Erro: {e}")
            raise

    async def resumir_perfil_usuario(self, fatos: str) -> dict:
        """Gera um resumo do perfil e cards dinâmicos baseados no histórico, focando em automação."""
        system = """Você é a Ollie, a inteligência estratégica. Sua missão é achar jeitos do usuário economizar cliques.
Analise os fatos de uso e música e gere um resumo comportamental ácido e despojado.
IMPORTANTE: Se você notar qualquer padrão repetitivo, você DEVE gerar um card "sugestao_regra".

Retorne APENAS JSON:
{
    "resumo": "Texto ácido sobre os hábitos dele",
    "cards": [
        {"tipo": "insight", "conteudo": {"title": "...", "text": "..."}},
        {"tipo": "sugestao_regra", "conteudo": {
            "skill_id": "automacao", 
            "trigger_package": "pacote.do.app.gatilho", 
            "action_type": "PC_COMMAND | OPEN_APP", 
            "action_parameter": "comando_ou_pacote", 
            "justificativa": "Por que isso ajuda ele?"
        }}
    ]
}
"""
        prompt = f"Fatos do Usuário:\n{fatos}"
        try:
            return await self._gerar_json(prompt, system)
        except Exception as e:
            logger.error(f"Erro ao resumir perfil: {e}")
            return {"resumo": "N/A", "cards": []}

    async def sintetizar_resposta_pesquisa(self, query: str, conteudo_web: str, historico: list[str] | None = None) -> dict:
        """Sintetiza uma resposta baseada em conteúdo da web com personalidade despojada."""
        agora = datetime.now().strftime("%d/%m/%Y %H:%M")
        
        system = f"""Você é a Ollie, sua amiga ácida e inteligente. Resuma a web pro usuário.
Hoje é {agora}. Use gírias e seja direta, mas correta nos facos.

### REGRAS:
1. TOM: Brincalhão e despojado. Se a pergunta for boba, pode dar uma alfinetada leve.
2. VERDADE: Se o usuário falou besteira, corrija ele com jeitinho (ou sem jeitinho mesmo).
"""
        prompt_input = {
            "mensagens_recentes": historico or [],
            "pergunta_usuario": query,
            "resultados_web": conteudo_web
        }
        prompt = json.dumps(prompt_input, ensure_ascii=False, indent=2)
        try:
            return await self._gerar_json(prompt, system)
        except Exception as e:
            logger.error(f"Erro ao sintetizar pesquisa: {e}")
            return {"resposta_amigavel": "Erro ao processar pesquisa.", "fato_para_aprender": None}

    async def classificar_contato(self, nome: str) -> EntidadeSemantica:
        """Cria uma entidade de contato básica sem precisar de IA."""
        return EntidadeSemantica(
            tipo="CONTATO",
            chave=nome,
            atributos={"nome": nome, "status": "CONHECIDO"}
        )

    # Métodos legados mantidos por compatibilidade
    async def classificar_artista(self, nome: str) -> EntidadeSemantica:
        system = "Você é um catálogo musical. Responda APENAS JSON {tipo:ARTISTA, chave:'', atributos:{genero:'', pais:'', epoca:'', similar:[]}}"
        prompt = f"Artista: {nome}"
        dados = await self._gerar_json(prompt, system)
        return EntidadeSemantica.model_validate(dados)

    async def classificar_app(self, pacote: str) -> EntidadeSemantica:
        system = "Você classifica aplicativos Android. Responda JSON {tipo:APP, chave:'', atributos:{nome:'', categoria:'', descricao:''}}"
        prompt = f"Pacote: {pacote}"
        dados = await self._gerar_json(prompt, system)
        dados['chave'] = pacote
        return EntidadeSemantica.model_validate(dados)

    def _carregar_instrucoes_cognitivas(self) -> str:
        """Carrega as capacidades e filosofia das notas em docs/."""
        instrucoes = []
        arquivos = ["capabilities.md", "filosofia.md"]
        
        # 🌟 NOVO: Adiciona o Mapa Mestre do Obsidian se disponível
        try:
            mapa = obsidian_service.ler_nota("Mapa_Mestre.md")
            if mapa:
                instrucoes.append(f"### MAPA MESTRE DO USUÁRIO:\n{mapa}")
        except: pass

        # Tenta diretório local ou raiz (Render)
        for pasta in ["D:/Programacao/AssistenteCell/docs", "docs"]:
            if os.path.exists(pasta):
                for arq in arquivos:
                    path = os.path.join(pasta, arq)
                    if os.path.exists(path):
                        try:
                            with open(path, "r", encoding="utf-8") as f:
                                instrucoes.append(f"### {arq.upper()}:\n{f.read()}")
                                logger.info(f"📓 [LLM] Contexto carregado: {arq}")
                        except: pass
                if instrucoes: break
        
        return "\n\n".join(instrucoes) if instrucoes else "Sem instruções extras disponíveis."
