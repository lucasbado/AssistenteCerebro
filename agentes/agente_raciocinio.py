"""
agentes/agente_raciocinio.py
"""
from __future__ import annotations
import json
import logging
import re
import asyncio
from core.evento import EventoCanonico
from core.tipos import PrioridadeEvento, OrigemEvento, TipoAcao, CategoriaEvento
from core.kernel import kernel
from servicos.llm import ServicoLLM
from servicos.memoria_episodica import MemoriaEpisodica
from servicos.memoria_semantica import MemoriaSemantica
from servicos.obsidian_service import obsidian_service
from modelos.catalogo import EntidadeSemantica

logger = logging.getLogger(__name__)

class AgenteRaciocinio:
    def __init__(self):
        self.llm = ServicoLLM()
        self.memoria_episodica = MemoriaEpisodica()
        self.memoria_semantica = MemoriaSemantica()
        from servicos.memoria_trabalho import memoria_trabalho
        self.memoria_trabalho = memoria_trabalho

    async def processar(self, evento: EventoCanonico):
        if evento.acao != TipoAcao.INTENCAO_RACIOCINIO:
            return
            
        logger.info(f"🧠 [Raciocínio] 🚩 CHECKPOINT 1: Iniciando processamento do evento {evento.id[:8]}")

        # 🌟 FEEDBACK IMEDIATO: Sinaliza que a Ollie começou a pensar
        if evento.categoria == CategoriaEvento.SISTEMA_COMANDO_USUARIO:
            try:
                await kernel.publicar(evento.clonar(
                    categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
                    acao=TipoAcao.INTENCAO_INTERACAO,
                    origem=OrigemEvento.IA,
                    payload={"tipo_ws": "THINKING", "titulo": "Ollie", "texto": "..."}
                ))
                logger.info(f"🧠 [Raciocínio] 🚩 CHECKPOINT 2: Sinal de THINKING enviado.")
            except Exception as e:
                logger.error(f"❌ Erro ao enviar sinal de thinking: {e}")

        # 1. Recupera Contexto do Obsidian (Long-term)
        try:
            conhecimento_atual = obsidian_service.listar_conhecimento_essencial()
            logger.info(f"🧠 [Raciocínio] 🚩 CHECKPOINT 3: Obsidian carregado.")
        except Exception as e:
            logger.warning(f"⚠️ Erro ao ler Obsidian: {e}")
            conhecimento_atual = ""

        # 2. Salva a mensagem do usuário com TIMEOUT
        chave_conversa = "br.com.assistentecell.chat" if evento.categoria == CategoriaEvento.SISTEMA_COMANDO_USUARIO else evento.pacote
        if evento.categoria == CategoriaEvento.SISTEMA_COMANDO_USUARIO:
            texto_usuario = evento.payload.get("texto", "")
            if texto_usuario:
                try:
                    await asyncio.wait_for(
                        self.memoria_trabalho.atualizar_conversa(chave_conversa, [f"Usuário: {texto_usuario}"]),
                        timeout=5.0
                    )
                    logger.info(f"🧠 [Raciocínio] 🚩 CHECKPOINT 4: Conversa salva no DB.")
                except Exception as e:
                    logger.error(f"❌ [Raciocínio] Falha ao salvar conversa no DB: {e}")

        # 3. Recupera contexto histórico
        try:
            historico = await asyncio.wait_for(self.memoria_trabalho.obter_contexto(chave_conversa), timeout=3.0)
            logger.info(f"🧠 [Raciocínio] 🚩 CHECKPOINT 5: Histórico recuperado.")
        except:
            historico = []

        # 4. Consulta o Córtex (LLM) com TIMEOUT de 40s
        logger.info(f"🧠 [Raciocínio] 🚩 CHECKPOINT 6: Chamando LLM...")
        try:
            start_time = asyncio.get_event_loop().time()
            resultado = await asyncio.wait_for(
                self.llm.classificar_evento(
                    categoria=evento.categoria.value,
                    pacote=evento.pacote,
                    payload=evento.payload,
                    historico=historico
                ),
                timeout=40.0
            )
            elapsed = asyncio.get_event_loop().time() - start_time
            logger.info(f"🧠 [Raciocínio] 🚩 CHECKPOINT 7: LLM respondeu em {elapsed:.2f}s")
        except asyncio.TimeoutError:
            logger.error("❌ [Raciocínio] TIMEOUT da LLM (40s).")
            resultado = {
                "tipo_interacao": "NOTIFICAR",
                "mensagem_dinamica": "Vixi, meu cérebro deu uma engasgada aqui na nuvem. Pode repetir, parceiro?",
                "execucao_direta": None
            }
        except Exception as e:
            logger.error(f"❌ [Raciocínio] Erro CRÍTICO na chamada LLM: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            resultado = {
                "tipo_interacao": "NOTIFICAR",
                "mensagem_dinamica": "Vish, deu pane no meu sistema aqui! Tenta de novo em um segundinho?",
                "execucao_direta": None
            }

        # 🌟 LOG DE DECISÃO: Ver exatamente o que a IA pensou
        logger.info(f"📊 [OLLIE_BRAIN] Raw Decision: {json.dumps(resultado, ensure_ascii=False)}")

        logger.info(f"🤔 [Raciocínio] LLM Decidiu: Interação={resultado.get('tipo_interacao')} | Exec={resultado.get('execucao_direta') is not None}")
        
        # 🌟 DEBUG: Log do que a IA disse
        msg_ia = resultado.get("mensagem_dinamica")
        if not msg_ia:
            logger.warning(f"⚠️ [Raciocínio] A IA não gerou uma mensagem dinâmica para {evento.categoria.value}")
        else:
            logger.info(f"💬 [IA] Respondeu: '{msg_ia[:50]}...'")

        # 4. LÓGICA DE EXECUÇÃO DIRETA (Prioridade Máxima)
        exec_direta = resultado.get("execucao_direta")
        if exec_direta and isinstance(exec_direta, dict):
            if evento.categoria in [CategoriaEvento.NOTIFICACAO, CategoriaEvento.APP_FOREGROUND, CategoriaEvento.MEDIA]:
                logger.info(f"🛡️ [Raciocínio] Execução direta BLOQUEADA para evento ambiente ({evento.categoria}).")
                exec_direta = None
            
        if exec_direta and isinstance(exec_direta, dict):
            alvo = str(exec_direta.get("alvo", "")).upper().strip()
            comando = str(exec_direta.get("comando", "")).lower().strip() # Forçamos lowercase
            param = str(exec_direta.get("parametro", "")).strip()

            logger.info(f"⚡ [Raciocínio] Decisão de Execução Direta: {alvo} -> {comando}({param})")

            # 🌟 CASO 1: Pesquisa Web
            if "pesquisa_web" in comando:
                logger.info(f"🌐 [Raciocínio] Escalando para AgentePesquisa: {param}")
                
                # 🛡️ Feedback imediato via Chat para manter a constância
                if evento.categoria == CategoriaEvento.SISTEMA_COMANDO_USUARIO:
                    await kernel.publicar(evento.clonar(
                        categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
                        acao=TipoAcao.INTENCAO_INTERACAO,
                        origem=OrigemEvento.IA,
                        payload={"texto": f"Para {param}, vou buscar isso para você.", "tipo_ws": "CHAT_RESPONSE"}
                    ))

                await kernel.publicar(evento.clonar(
                    categoria=CategoriaEvento.INTENCAO_PESQUISA,
                    acao=TipoAcao.INTENCAO_PESQUISA,
                    origem=OrigemEvento.IA,
                    payload={"query": param}
                ))
                return

            # 🌟 CASO 2: Comandos de PC
            elif alvo == "PC":
                payload_pc = {"comando": comando, "parametro": param} # 🌟 Sempre inclui o parametro
                if "abrir_app" in comando: payload_pc["app"] = param
                elif "executar_macro" in comando: payload_pc["macro"] = param
                elif "abrir_url" in comando: payload_pc["url"] = param
                elif "pesquisa_google" in comando: payload_pc["query"] = param
                elif "buscar_documentos" in comando: payload_pc["termo"] = param
                elif "spotify_play" in comando: payload_pc["query"] = param
                
                # 🌟 FALLBACK: Se o comando for "fullscreen", mapeia para "janela_fullscreen"
                if comando == "fullscreen": payload_pc["comando"] = "janela_fullscreen"
                if comando == "maximizar": payload_pc["comando"] = "janela_maximizar"
                if comando == "minimizar": payload_pc["comando"] = "janela_minimizar"
                
                await kernel.publicar(evento.clonar(
                    categoria=CategoriaEvento.SISTEMA_COMANDO_PC,
                    acao=TipoAcao.NORMAL,
                    origem=OrigemEvento.IA,
                    payload=payload_pc
                ))

            # 🌟 CASO 3: Comandos Mobile
            elif alvo == "MOBILE":
                payload_mob = {"comando": comando + "_mobile"} if not comando.endswith("_mobile") else {"comando": comando}
                if "abrir_app" in comando: payload_mob["pacote"] = param
                elif "abrir_url" in comando: payload_mob["url"] = param
                
                await kernel.publicar(evento.clonar(
                    categoria=CategoriaEvento.SISTEMA_COMANDO_PC,
                    acao=TipoAcao.NORMAL,
                    origem=OrigemEvento.IA,
                    payload=payload_mob
                ))

            # 🌟 CASO 4: Gerenciamento de Macros
            if comando == "criar_macro":
                from servicos.macro_service import macro_service
                # Extrai os passos reais decididos pela IA
                passos = exec_direta.get("passos", [])
                if not passos:
                    logger.warning(f"⚠️ [Raciocínio] IA tentou criar macro '{param}' sem passos!")
                
                macro_service.criar_macro(param, passos)
                logger.info(f"💾 [Raciocínio] Macro '{param}' salva com {len(passos)} passos.")

        # 5. LÓGICA DE INTERAÇÃO (Notificações e Sugestões)
        tipo_interacao = resultado.get("tipo_interacao")
        
        # 🌟 SEM FALLBACK: Se for comando do usuário, a IA é obrigada a ter mensagem_dinamica.
        # Caso não tenha (erro de IA), o sistema apenas loga, mas não envia mentiras.
        if tipo_interacao == "NOTIFICAR":
            mensagem = resultado.get("mensagem_dinamica")
            if mensagem:
                # 🛡️ CENSURA DE NOME: Remove apresentações em conversas contínuas
                if historico and len(historico) > 0:
                    # Regex para pegar variações como "Sou a Ollie", "Eu sou a Ollie", "É a Ollie"
                    padrao = r"(?i)\b(eu\s+)?sou\s+a\s+ollie\b[,!.]*|\b(olha,\s+)?é\s+a\s+ollie\b[,!.]*|\bollie\s+aqui\b[,!.]*"
                    mensagem = re.sub(padrao, "", mensagem).strip()
                    # Limpa pontuação sobressalente no início e garante capitalização
                    mensagem = re.sub(r"^[^\w\s]+", "", mensagem).strip().capitalize()

                payload_notif = {
                    "texto": mensagem,
                    "titulo": "Assistente",
                    "contexto": resultado.get("contexto_extra", {}),
                }
                
                # Suporte a Sugestão de Regra Automática
                sugestao = resultado.get("sugestao_regra")
                if sugestao:
                    payload_notif["sugestao_regra"] = sugestao

                # Se o evento original era um comando do usuário, marcamos como resposta de chat
                if evento.categoria == CategoriaEvento.SISTEMA_COMANDO_USUARIO:
                    payload_notif["tipo_ws"] = "CHAT_RESPONSE"
                    # Salva a resposta da Ollie na memória de trabalho
                    await self.memoria_trabalho.atualizar_conversa(chave_conversa, [f"Ollie: {mensagem}"])

                # Adiciona ação sugerida (botão) se a IA definiu
                acao_sug = resultado.get("acao_sugerida")
                if acao_sug:
                    payload_notif["acao_tipo"] = acao_sug.get("tipo")
                    payload_notif["acao_parametro"] = acao_sug.get("parametro")
                    payload_notif["acao_texto"] = acao_sug.get("texto_botao")

                await kernel.publicar(evento.clonar(
                    categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
                    acao=TipoAcao.INTENCAO_INTERACAO,
                    origem=OrigemEvento.IA,
                    payload=payload_notif,
                    metadados={"tipo_destino": "CHAT"} # 🌟 Força sinalização de chat nos metadados
                ))
                logger.info(f"🧠 [Raciocínio] Intenção de interação gerada com sugestão.")

            # 🌟 RE-ATIVAR THINKING: Se disparou uma pesquisa, garante que o indicador volte a pulsar
            # mesmo após a mensagem inicial de "Vou buscar...".
            if exec_direta and exec_direta.get("comando") == "pesquisa_web":
                 await kernel.publicar(evento.clonar(
                    categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
                    acao=TipoAcao.INTENCAO_INTERACAO,
                    origem=OrigemEvento.IA,
                    payload={"tipo_ws": "THINKING", "titulo": "Ollie", "texto": "..."}
                ))

        # 6. LÓGICA DE MEMÓRIA PERMANENTE (Obsidian - Filtro de Rigor)
        mem_obsidian = resultado.get("memoria_obsidian")
        if mem_obsidian and isinstance(mem_obsidian, dict):
            titulo = str(mem_obsidian.get("titulo", "")).strip()
            fato = str(mem_obsidian.get("fato", "")).strip()
            
            # Bloqueio de lixo: não salva notificações nem conversas como "conhecimento permanente"
            lixo_keywords = ["notificação", "whatsapp", "instagram", "conversa", "mensagem", "abriu"]
            is_lixo = any(k in titulo.lower() or k in fato.lower() for k in lixo_keywords)
            
            if titulo and fato and not is_lixo:
                logger.info(f"📓 [Raciocínio] Registrando fato novo no Obsidian: {titulo}")
                obsidian_service.registrar_fato(titulo, fato)
            else:
                logger.debug(f"🤫 [Raciocínio] Fato Obsidian ignorado por ser trivial ou ruído: {titulo}")

    async def sintetizar_com_pesquisa(self, evento_resultado: EventoCanonico):
        """Recebe o conteúdo bruto da web e gera a resposta final + aprendizado."""
        query = evento_resultado.payload.get("query")
        conteudo_bruto = evento_resultado.payload.get("conteudo")
        sucesso = evento_resultado.payload.get("sucesso", False)
        
        logger.info(f"🧠 [Raciocínio] Recebido resultado da pesquisa (Sucesso: {sucesso}). Iniciando síntese...")

        if not sucesso or not conteudo_bruto:
            logger.warning(f"[Raciocínio] Pesquisa falhou ou retornou vazia para '{query}'.")
            await kernel.publicar(evento_resultado.clonar(
                categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
                acao=TipoAcao.INTENCAO_INTERACAO,
                origem=OrigemEvento.IA,
                payload={"texto": f"Desculpe, não encontrei informações úteis sobre '{query}'.", "tipo_ws": "CHAT_RESPONSE"}
            ))
            return

        # 1. Recupera histórico do chat para manter a constância na síntese
        historico = await self.memoria_trabalho.obter_contexto("br.com.assistentecell.chat")

        # 2. Sintetiza a resposta e extrai fatos
        try:
            # 🛡️ Garantimos que o indicador de pensamento continue ativo no app
            await kernel.publicar(evento_resultado.clonar(
                categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
                acao=TipoAcao.INTENCAO_INTERACAO,
                origem=OrigemEvento.IA,
                payload={"tipo_ws": "THINKING", "titulo": "Ollie", "texto": "..."}
            ))

            resultado = await self.llm.sintetizar_resposta_pesquisa(query, conteudo_bruto, historico=historico)
            
            # Se a LLM não retornou o formato esperado, trata como erro amigável
            if not isinstance(resultado, dict) or "resposta_amigavel" not in resultado:
                raise ValueError("Resposta da LLM inválida para síntese.")

        except Exception as e:
            logger.error(f"❌ [Raciocínio] Falha na síntese da LLM: {e}")
            await kernel.publicar(evento_resultado.clonar(
                categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
                acao=TipoAcao.INTENCAO_INTERACAO,
                origem=OrigemEvento.IA,
                payload={"texto": "Desculpe, tive um problema ao ler as informações encontradas.", "tipo_ws": "CHAT_RESPONSE"}
            ))
            return
        
        # 3. Responde ao usuário no Chat
        resposta_texto = resultado.get("resposta_amigavel")
        
        # Salva a resposta da pesquisa na memória de trabalho
        await self.memoria_trabalho.atualizar_conversa("br.com.assistentecell.chat", [f"Ollie: {resposta_texto}"])

        await kernel.publicar(evento_resultado.clonar(
            categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
            acao=TipoAcao.INTENCAO_INTERACAO,
            origem=OrigemEvento.IA,
            payload={
                "texto": resposta_texto,
                "titulo": "Ollie (Web)",
                "tipo_ws": "CHAT_RESPONSE"
            }
        ))
        
        logger.info(f"✅ [Raciocínio] Resposta de pesquisa enviada ao chat.")

        # 3. APRENDIZADO: Salva Fato Semântico se identificado
        fato = resultado.get("fato_para_aprender")
        if fato and isinstance(fato, dict):
            chave = fato.get("chave")
            logger.info(f"🧠 [Aprendizado] Novo fato semântico sobre '{chave}' detectado.")
            
            entidade = EntidadeSemantica(
                tipo="CONHECIMENTO_GERAL",
                chave=chave,
                atributos={
                    "categoria": fato.get("categoria"),
                    "conteudo": fato.get("conteudo"),
                    "importancia": fato.get("importancia", 1),
                    "fonte": "WEB_RESEARCH",
                    "data_aprendizado": evento_resultado.timestamp.isoformat()
                }
            )
            await self.memoria_semantica.salvar(entidade)

        # 4. MEMÓRIA OBSIDIAN
        mem_obs = resultado.get("memoria_obsidian")
        if mem_obs and isinstance(mem_obs, dict):
            obsidian_service.registrar_fato(mem_obs.get("titulo", "Conhecimento_Web"), mem_obs.get("fato", ""))
