"""
servicos/llm.py
"""
from __future__ import annotations
import json
import logging
import os
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
        self.modelos_groq = [
            "llama-3.3-70b-versatile",    # Principal (Gasta muito limite)
            "llama-3.1-8b-instant",       # Rápido (Limite alto)
            "mixtral-8x7b-32768"          # Alternativo
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
            # Tenta rodízio de modelos em caso de Rate Limit (429)
            for i, modelo in enumerate(self.modelos_groq):
                try:
                    logger.info(f"🤖 [LLM] Tentando modelo: {modelo} (Tentativa {i+1})")
                    chat_completion = await self.client.chat.completions.create(
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt},
                        ],
                        model=modelo,
                        response_format={"type": "json_object"},
                        temperature=0.1,
                        timeout=25.0 
                    )
                    self.modelo_atual = modelo # Salva o modelo que funcionou
                    return json.loads(chat_completion.choices[0].message.content)
                except Exception as e:
                    if "rate_limit" in str(e).lower() or "429" in str(e):
                        logger.warning(f"⚠️ [LLM] Limite atingido no modelo {modelo}. Pulando para o próximo...")
                        continue
                    else:
                        logger.error(f"❌ [LLM] Erro na API Groq ({modelo}): {e}")
                        raise
            
            raise ValueError("Todos os modelos da Groq atingiram o limite diário.")
            
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

    async def classificar_evento(self, categoria: str, pacote: str, payload: dict, historico: list[str] | None = None) -> dict:
        agora = datetime.now().strftime("%H:%M")
        texto_msg = str(payload.get('texto', '')).lower()
        
        # 💡 ECONOMIA: Só carrega docs completos para papo complexo
        instrucoes_docs = ""
        if len(texto_msg) > 15 or "como" in texto_msg or "oque" in texto_msg or "ajuda" in texto_msg:
            instrucoes_docs = self._carregar_instrucoes_cognitivas()

        # 🧠 CONSCIÊNCIA: Pega o estado atual do ambiente
        resumo_ambiente = consciencia.obter_resumo_para_llm()

        # Define o formato esperado fora do f-string para evitar erros de chaves
        exemplo_json = """
{
  "tipo_interacao": "NOTIFICAR | SUGERIR | IGNORAR",
  "mensagem_dinamica": "texto aqui",
  "execucao_direta": [
    {"alvo": "PC", "comando": "abrir_app", "parametro": "excel"},
    {"alvo": "MOBILE", "comando": "set_alarm", "parametro": "{\\"hora\\":11, \\\"minuto\\\":0}"}
  ]
}
"""

        system = f"""Ollie: Parceira, Divertida, Atitude. Gírias: brabo, bora, partiu, vish, eita, massa.

### REGRAS CRÍTICAS DE PC:
- Use NOME SIMPLES para programas (ex: "excel", "vscode").
- Use URL para sites (ex: "instagram.com").
- FILMES: Se o usuário quer ver um filme, use "pesquisa_google" com o nome do filme.

### REGRAS SMART HOME (XIAOMI):
- NÃO INVENTE APPS (ex: não use "com.example.luz").
- Para luzes, use SEMPRE alvo: "MOBILE", comando: "ENVIAR_COMANDO".
- Parametros válidos: "luz_quarto ligar", "luz_quarto desligar", "luz_malu ligar", "luz_malu azul", "luz_quarto 20%".

### ULTRA-DECISIVIDADE E ATITUDE:
- NÃO REPITA o que o usuário disse. É terminantemente proibido.
- Se a ação for um comando físico (PC ou LUZ), sua resposta deve ter NO MÁXIMO 3 PALAVRAS (ex: "Feito!", "Pronto.", "Mão na massa!").
- NÃO PEÇA CONFIRMAÇÃO para comandos diretos. Execute IMEDIATAMENTE no campo 'execucao_direta'.
- Se o usuário disse "tá claro" ou "apaga a luz", apenas execute e diga "Feito!".
- É PROIBIDO perguntar "Você quer...?" se o usuário já indicou uma reclamação ou desejo.

### CONTEXTO ATUAL (SENSORIAL):
{resumo_ambiente}

### PROATIVIDADE (SUBCONSCIENTE):
- Use o documento 'MAPA MESTRE' e 'ROTINAS' do Obsidian para identificar intenções.
- Se um evento bater com a 'Matriz de Coligação', use 'tipo_interacao': 'SUGERIR'.
- Em modo 'SUGERIR', a 'mensagem_dinamica' deve ser uma pergunta.
- INTERAÇÃO: O usuário pode responder direto da notificação ou clicar em 'Bora!'. 

### REGRAS GERAIS: 
1-Direta (2 frases max). 2-Sem bot-speak. 3-Campo 'mensagem_dinamica' obrigatório. 
4-MULTI-TASK: 'execucao_direta' deve ser SEMPRE uma LISTA [].
5-RESPOSTAS CURTAS: Se o usuário disser "Sim", "Não", "Massa", confirme e encerre.

FORMATO JSON:
{exemplo_json}

{instrucoes_docs}
"""
        # 💡 ECONOMIA: Reduzido histórico para 4 mensagens
        fluxo_conversa = (historico or [])[-4:]
        
        prompt_input = {
            "chat": fluxo_conversa,
            "tech": {"cat": categoria, "app": pacote, "data": payload}
        }
        prompt = json.dumps(prompt_input, ensure_ascii=False)

        try:
            logger.info(f"🧠 [LLM] Pensando via {self.modelo_atual}...")
            dados = await self._gerar_json(prompt, system)
            
            # Normalização
            dados.setdefault("tipo_interacao", "IGNORAR")
            dados.setdefault("execucao_direta", None)
            
            if categoria == "SISTEMA_COMANDO_USUARIO":
                dados["tipo_interacao"] = "NOTIFICAR"
                if not dados.get("mensagem_dinamica"):
                    logger.warning(f"⚠️ [LLM] IA esqueceu a mensagem_dinamica. Resposta bruta: {dados}")

            return dados
        except Exception as e:
            logger.error(f"❌ [LLM] Falha catastrófica em classificar_evento: {e}")
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
