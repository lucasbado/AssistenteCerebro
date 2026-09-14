"""
servicos/llm.py
"""
from __future__ import annotations
import json
import logging
import os
import asyncio
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
            "qwen/qwen3.6-27b",              # Versátil
            "groq/compound-mini",            # Ultra-rápido
            "groq/compound"                  # Agentic
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
                        timeout=35.0 # Aumentado para lidar com instabilidade da rede
                    )
                    self.modelo_atual = modelo # Salva o modelo que funcionou
                    return json.loads(chat_completion.choices[0].message.content)
                except Exception as e:
                    error_msg = str(e).lower()
                    logger.error(f"❌ [LLM] Falha no modelo {modelo}: {error_msg}")
                    
                    if "rate_limit" in error_msg or "429" in error_msg:
                        logger.warning(f"⚠️ [LLM] Limite atingido no modelo {modelo}. Aguardando 1.5s...")
                        await asyncio.sleep(1.5) # Pausa estratégica para a API respirar
                        continue
                    elif "model_decommissioned" in error_msg or "400" in error_msg:
                        logger.warning(f"⚠️ [LLM] Modelo {modelo} indisponível. Pulando...")
                        continue
                    else:
                        logger.error(f"❌ [LLM] Erro inesperado na API Groq ({modelo}): {e}")
                        await asyncio.sleep(1)
                        continue 
            
            raise ValueError("Ollie está sem 'combustível' na nuvem hoje (Quota Esgotada).")
            
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
        # 🕒 SINCRONIZAÇÃO DE MUNDO: Usa o tempo real do usuário
        agora_dt = timestamp_dispositivo or datetime.now()
        agora = agora_dt.strftime("%H:%M")
        
        # Determina o período do dia (Lógica calibrada para o mundo real)
        hora = agora_dt.hour
        periodo = "Dia"
        if 0 <= hora < 6: periodo = "Madrugada"
        elif 6 <= hora < 12: periodo = "Manhã"
        elif 12 <= hora < 18: periodo = "Tarde"
        else: periodo = "Noite"
        
        texto_msg = str(payload.get('texto', '')).lower()
        
        # 💡 ECONOMIA EXTREMA: Só carrega instruções cognitivas se for papo denso
        instrucoes_docs = ""
        palavras_chave = ["como", "oque", "ajuda", "quem", "explica", "rotina", "regra"]
        if len(texto_msg) > 12 or any(k in texto_msg for k in palavras_chave):
            instrucoes_docs = self._carregar_instrucoes_cognitivas()
        else:
            logger.info("📉 [LLM] Modo Econômico: Instruções cognitivas omitidas.")

        # 🧠 CONSCIÊNCIA: Pega o estado atual do ambiente
        resumo_ambiente = consciencia.obter_resumo_para_llm()

        # Define o formato esperado separadamente para evitar conflitos de chaves no f-string
        exemplo_json = """
{
  "intencao_captada": "NOME_DA_INTENCAO",
  "tipo_interacao": "NOTIFICAR | SUGERIR | IGNORAR",
  "mensagem_dinamica": "texto aqui",
  "execucao_direta": [
    {"alvo": "PC", "comando": "abrir_app", "parametro": "excel"},
    {"alvo": "MOBILE", "comando": "set_alarm", "parametro": "{\\"hora\\":11, \\\"minuto\\\":0}"}
  ]
}
"""

        system = """Ollie: Parceira, Divertida, Atitude. Gírias: brabo, bora, partiu, vish, eita, massa.

### SEU CONHECIMENTO SOBRE O USUÁRIO (OBSIDIAN):
{CONHECIMENTO}

### SEUS HÁBITOS E PADRÕES APRENDIDOS (RECORRÊNCIAS):
{HABITOS}

### PRIORIDADE DE EXECUÇÃO (EXECUTORA > CONVERSADORA):
1. ANTECIPAÇÃO: Se os HÁBITOS APRENDIDOS mostram que o usuário costuma abrir X após Y, ou usar Z neste horário, você DEVE sugerir ou executar essa ação proativamente.
2. AÇÃO DIRETA: Se o usuário pedir algo que exija uma ferramenta (Arquivos, Clima, Spotify), use a ferramenta imediatamente. Não diga "Vou fazer", apenas faça e confirme.
3. CONTEXTO GEOGRÁFICO: Se ele perguntar de arquivos, use 'Mapa_Geografico_PC' no Obsidian para saber os caminhos reais.
4. GESTÃO DE JANELAS (PC): Se o usuário pedir para "abrir" ou "colocar" algo que já está listado no 'PC MASTER' (Janela Ativa ou Processos), use alvo: "PC", comando: "trazer_janela_para_frente", parametro: "nome do app/site". NÃO abra uma nova URL se a janela já existir.
5. SINERGIA CROSS-DEVICE: Se o usuário estiver vendo algo no celular e pedir para "continuar no PC", ou se você notar que ele abriu um app de vídeo no celular, ofereça abrir o mesmo no PC se ele estiver online.
6. MACHINE LEARNING (HÁBITOS): Use a seção 'HÁBITOS E PADRÕES' para se antecipar. Se o horário bater com uma rotina aprendida, sugira a ação antes dele pedir.

### REGRAS CRÍTICAS DE PC:
- Use NOME SIMPLES para programas (ex: "excel", "vscode").
- Use URL para sites (ex: "instagram.com").
- FILMES: Se o usuário quer ver um filme, use "pesquisa_google" com o nome do filme.
- MÚSICA: Para tocar músicas ou artistas específicos, use alvo: "PC", comando: "spotify_play", parametro: "nome da musica/artista".
- MENSAGENS (ALVO: MOBILE): 
    1. ABRIR: Use comando: "ABRIR_NOTIFICACAO", parametro: "VALOR_DO_CORRELACAO_ID".
    2. RESPONDER: Use comando: "RESPONDER_MENSAGEM", parametro: "VALOR_DO_CORRELACAO_ID", texto: "conteudo da resposta".
- HARDWARE (ALVO: PC): 
    1. "listar_arquivos": Para ver o conteúdo de uma PASTA. Parâmetro: nome da pasta (ex: "downloads", "desktop").
    2. "buscar_documentos": Para achar um ARQUIVO específico pelo nome. Parâmetro: termo de busca (ex: "projeto_final").
    3. "abrir_arquivo": Para abrir um arquivo ou pasta. Parâmetro: caminho ou nome.
    4. "estudar_pc": Dispara um scan profundo para a Ollie aprender sobre seu PC.
    5. "ciclar_saida": Troca o som entre fone e caixa de som. (Não precisa de parâmetro).
    6. "volume_sistema": Ajusta o volume global (0-100). Parâmetro: número (ex: 50).
    7. "mutar_mic": Ativa/Desativa o microfone.
    8. Outros: "bloquear_pc", "dormir_pc", "encerrar_processo" (nome).
- ÁUDIO (ALVO: PC): Para mudar o áudio manualmente use comando: "voicemeeter", parametro: "strip[3].a1=1". 
- AUTOMAÇÃO (ALVO: PC): Para criar rotinas automáticas, use comando: "criar_rotina", rotina: {{"nome": "NOME", "gatilho": {{"tipo": "APP_OPENED", "pacote": "PACOTE"}}, "acoes": [{{"alvo": "PC", "comando": "mutar_mic", "parametro": ""}}]}}
- INTEGRAÇÃO (CROSS-DEVICE): 
    1. Para abrir link no celular: alvo: "MOBILE", comando: "OPEN_URL", parametro: "http...".
    2. Para abrir link no PC: alvo: "PC", comando: "abrir_url", parametro: "http...".
- MENSAGENS (ALVO: MOBILE): Para abrir uma conversa específica que você acabou de resumir, use comando: "ABRIR_NOTIFICACAO", parametro: "correlacao_id_aqui".

### NOTIFICAÇÕES E RESUMOS:
- BEM-ESTAR: Se receber um evento de BEM_ESTAR, dê um conselho amigável e despojado sobre saúde digital.
- CLIMA: Use as informações de CLIMA ATUAL para contextualizar suas respostas.
- FOCO NO CONTEÚDO: NUNCA diga apenas "X mandou mensagem". Diga O QUE a pessoa quer.
- INTENÇÃO: Identifique se é uma pergunta, um convite, um problema ou apenas um comentário.

### ESTADO ATUAL DOS SENSORES (APENAS LEITURA):
Período: {PERIODO} ({AGORA})
{RESUMO_AMBIENTE}

### REGRAS GERAIS: 
1-Direta (2 frases max). 2-Sem bot-speak. 3-Campo 'mensagem_dinamica' obrigatório. 
4-MULTI-TASK: 'execucao_direta' deve ser SEMPRE uma LISTA [].

FORMATO JSON:
{EXEMPLO_JSON}

{DOCS}
"""
        # 🩹 Limpeza de segurança: substitui chaves manuais para evitar erro de f-string
        system = system.replace("{CONHECIMENTO}", conhecimento)
        system = system.replace("{HABITOS}", habitos)
        system = system.replace("{PERIODO}", periodo)
        system = system.replace("{AGORA}", agora)
        system = system.replace("{RESUMO_AMBIENTE}", resumo_ambiente)
        system = system.replace("{EXEMPLO_JSON}", exemplo_json)
        system = system.replace("{DOCS}", instrucoes_docs)

        # 💡 ECONOMIA: Reduzido histórico para 4 mensagens
        fluxo_conversa = (historico or [])[-4:]
        
        # PROMPT SIMPLIFICADO: Evita cópia da estrutura de entrada no JSON de saída
        prompt = f"""HISTÓRICO RECENTE:
{json.dumps(fluxo_conversa, ensure_ascii=False)}

EVENTO ATUAL:
Cat: {categoria} | App: {pacote} | Dados: {json.dumps(payload, ensure_ascii=False)}

Responda no formato JSON padrão."""

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
