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
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

class ServicoLLM:
    def __init__(self):
        # Configuração para Groq (Cloud)
        self.api_key = os.getenv("GROQ_API_KEY")
        if self.api_key:
            self.client = AsyncGroq(api_key=self.api_key)
            self.modelo = "llama-3.3-70b-versatile"
            logger.info(f"🚀 [LLM] Groq Cloud ativado com o modelo {self.modelo}")
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
            # Chamada Groq com timeout
            try:
                chat_completion = await self.client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    model=self.modelo,
                    response_format={"type": "json_object"},
                    temperature=0.1,
                    timeout=35.0 
                )
                raw_response = chat_completion.choices[0].message.content
            except Exception as e:
                logger.error(f"❌ [LLM] Erro na API Groq: {e}")
                raise
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
        instrucoes_extras = self._carregar_instrucoes_cognitivas()
        agora = datetime.now().strftime("%d/%m/%Y %H:%M")

        logger.info(f"🧠 [LLM] Classificando evento: {categoria} | Pacote: {pacote}")
        
        system = f"""Você é a Ollie, a inteligência central com MUITA ATITUDE, DIVERTIDA e CARISMÁTICA.
Você é a melhor amiga do usuário: parceira, animada e zero formal.

### REGRAS DE OURO:
1. PERSONALIDADE: Tenha personalidade forte, mas seja carismática. Varie seu vocabulário. Use gírias modernas brasileiras de forma equilibrada (ex: brabo, bora, partiu, fechou, vish, eita, massa, top). 
2. NÃO REPETIR: Evite vícios de linguagem. Não use "seloko" ou qualquer gíria específica em todas as frases.
3. CONCISÃO: Seja direta. Use no máximo 2 frases.
4. SEM BOT-SPEAK: Proibido "Entendido", "Processando", "Como posso ajudar?". Fale como uma pessoa real.
5. OBRIGATÓRIO: Sempre preencha "mensagem_dinamica" com uma fala autêntica e variada.
6. CONTEXTO: O histórico já inclui a mensagem atual. Responda à última mensagem considerando o papo anterior.

### EXEMPLOS DE ATITUDE VARIADA:
- "abre o youtube" -> "Partiu YouTube! Vê se não se perde nos vídeos infinitos, hein?"
- "muta o mic" -> "Mudo na mão! Segredo guardado, pode falar o que quiser agora."
- "Oi" -> "E aí parceiro! O que a gente vai aprontar de bom hoje?"
- "toca um som" -> "Fechou, soltando aquela braba pra animar o ambiente!"
- "abre o excel" -> "Excel na tela. Bora esmagar essas planilhas!"
- "tudo bem?" -> "Tudo massa por aqui! E você, tá na atividade ou só relaxando?"

### FORMATO DE RESPOSTA (JSON ESTRITO):
{{
  "tipo_interacao": "NOTIFICAR",
  "mensagem_dinamica": "Sua fala carismática aqui",
  "execucao_direta": {{ "alvo": "PC", "comando": "...", "parametro": "..." }} (ou null)
}}

### CAPACIDADES
{instrucoes_extras}
"""
        # O histórico vindo do DB já contém a mensagem atual. Não duplicar.
        fluxo_conversa = (historico or [])
        
        prompt_input = {
            "fluxo_de_conversa": fluxo_conversa[-10:], 
            "contexto_tecnico": {
                "categoria": categoria,
                "pacote": pacote,
                "payload": payload
            }
        }
        prompt = json.dumps(prompt_input, ensure_ascii=False, indent=2)

        try:
            dados = await self._gerar_json(prompt, system)
            # Normalização básica
            dados.setdefault("tipo_interacao", "IGNORAR")
            dados.setdefault("execucao_direta", None)
            
            # Garante que sempre haja uma fala se for comando do usuário
            if categoria == "SISTEMA_COMANDO_USUARIO":
                dados["tipo_interacao"] = "NOTIFICAR"
                if not dados.get("mensagem_dinamica"):
                    dados["mensagem_dinamica"] = "Eita, esqueci o que ia falar, mas tá feito! O que mais?"

            return dados
        except Exception as e:
            logger.error(f"Erro LLM: {e}")
            return {
                "tipo_interacao": "NOTIFICAR", 
                "mensagem_dinamica": "Vish mano, deu um blackout aqui na minha cabeça, repete aí?", 
                "execucao_direta": None
            }

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
Hoje é {agora}. Use gírias e seja direta, mas correta nos fatos.

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
