"""
agentes/agente_raciocinio.py
"""
from __future__ import annotations
import json
import logging
import re
import asyncio
from datetime import datetime
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
        # 🌟 LÓGICA DE APRENDIZADO POR REJEIÇÃO
        if evento.categoria == CategoriaEvento.SISTEMA_COMANDO_INTERNO and evento.payload.get("tipo") == "SUGESTAO_REJEITADA":
            id_orig = evento.payload.get("id_original")
            logger.info(f"🧠 [Aprendizado] Registrando rejeição da sugestão {id_orig}")
            obsidian_service.registrar_fato("Aprendizado", f"O usuário rejeitou a sugestão {id_orig} em {datetime.now().strftime('%d/%m/%Y %H:%M')}. Evitar proatividade similar neste contexto.")
            return

        if evento.acao != TipoAcao.INTENCAO_RACIOCINIO:
            return
            
        logger.info(f"🧠 [Raciocínio] 🚩 CHECKPOINT 1: Iniciando processamento do evento {evento.id[:8]}")

        # 1. Recupera Contexto do Obsidian (Long-term)
        try:
            conhecimento_atual = obsidian_service.listar_conhecimento_essencial()
            logger.info(f"🧠 [Raciocínio] 🚩 CHECKPOINT 3: Obsidian carregado.")
        except Exception as e:
            logger.warning(f"⚠️ Erro ao ler Obsidian: {e}")
            conhecimento_atual = ""
            
        # 🌟 FEEDBACK IMEDIATO (Silencioso para comandos rápidos)
        # Se for comando de luz, não manda sinal de thinking para não poluir o chat
        texto_msg = str(evento.payload.get("texto", "")).lower()
        if evento.categoria == CategoriaEvento.SISTEMA_COMANDO_USUARIO and not any(x in texto_msg for x in ["luz", "lampada", "apaga", "liga"]):
            try:
                await kernel.publicar(evento.clonar(
                    categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
                    acao=TipoAcao.INTENCAO_INTERACAO,
                    origem=OrigemEvento.IA,
                    payload={"tipo_ws": "THINKING", "titulo": "Ollie", "texto": "..."}
                ))
            except: pass

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
            
            # 🕵️ MEMÓRIA SEMÂNTICA DE CURTO PRAZO: Verifica se há um ID de correlação
            cid = evento.metadados.get("correlacao_id")
            if cid:
                logger.info(f"🎯 [Raciocínio] Contexto de Resposta detectado (CID: {cid})")
                historico.append(f"CONTEXTO: O usuário está respondendo especificamente à notificação {cid}.")
        except:
            historico = []

        # 4. Consulta o Córtex (LLM) com TIMEOUT de 40s
        logger.info(f"🧠 [Raciocínio] 🚩 CHECKPOINT 6: Chamando LLM ({self.llm.modelo_atual})...")
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
            logger.info(f"🧠 [Raciocínio] 🚩 CHECKPOINT 7: LLM ({self.llm.modelo_atual}) respondeu em {elapsed:.2f}s")
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

        # 🚀 CORREÇÃO: Força execução se a IA sugeriu algo mas o usuário já deu uma ordem
        exec_direta_raw = resultado.get("execucao_direta")
        tipo_interacao = resultado.get("tipo_interacao")
        
        texto_u = str(evento.payload.get("texto", "")).lower()
        if (not exec_direta_raw or exec_direta_raw == []) and ("luz" in texto_u or "filme" in texto_u or "apaga" in texto_u or "liga" in texto_u) and ("sim" in texto_u or "pode" in texto_u or "quero" in texto_u or "bora" in texto_u):
             # Tenta recuperar o que estava sendo discutido no histórico
             logger.info("🎯 [Raciocínio] Tentando recuperar ação de confirmação implícita...")
             # Busca nas últimas 5 mensagens do histórico
             for msg in reversed((historico or [])[-5:]):
                 msg_l = msg.lower()
                 if "ollie:" in msg_l and ("você quer" in msg_l or "gostaria" in msg_l or "deseja" in msg_l):
                     if "luz do quarto" in msg_l or "iluminação do quarto" in msg_l: 
                         acao_cmd = "desligar" if "apagar" in msg_l or "desligar" in msg_l or "diminuir" in msg_l else "ligar"
                         exec_direta_raw = {"alvo": "MOBILE", "comando": "ENVIAR_COMANDO", "parametro": f"luz_quarto {acao_cmd}"}
                         logger.info(f"✅ [Raciocínio] Ação recuperada: {acao_cmd} luz_quarto")
                         break
                     elif "luz da malu" in msg_l:
                         acao_cmd = "desligar" if "apagar" in msg_l or "desligar" in msg_l else "ligar"
                         exec_direta_raw = {"alvo": "MOBILE", "comando": "ENVIAR_COMANDO", "parametro": f"luz_malu {acao_cmd}"}
                         logger.info(f"✅ [Raciocínio] Ação recuperada: {acao_cmd} luz_malu")
                         break

        logger.info(f"🤔 [Raciocínio] LLM Decidiu: Interação={tipo_interacao} | Exec={exec_direta_raw is not None}")
        
        # 🌟 DEBUG: Log do que a IA disse
        msg_ia = resultado.get("mensagem_dinamica")
        if not msg_ia:
            logger.warning(f"⚠️ [Raciocínio] A IA não gerou uma mensagem dinâmica para {evento.categoria.value}")
        else:
            logger.info(f"💬 [IA] Respondeu: '{msg_ia[:50]}...'")

        # 4. LÓGICA DE EXECUÇÃO DIRETA (Prioridade Máxima)
        exec_direta_raw = resultado.get("execucao_direta")
        tipo_interacao = resultado.get("tipo_interacao")

        # 🧠 MODO SUGERIR: Não executa nada agora, apenas prepara o botão
        if tipo_interacao == "SUGERIR" and exec_direta_raw:
            logger.info("💡 [Raciocínio] Modo SUGERIR ativado. Postergando execução.")
            # Movemos os comandos para 'acao_sugerida' em vez de executar
            exec_direta_lista = [] 
        else:
            if not exec_direta_raw:
                exec_direta_lista = []
            elif isinstance(exec_direta_raw, list):
                exec_direta_lista = exec_direta_raw
            else:
                exec_direta_lista = [exec_direta_raw]

        for exec_direta in exec_direta_lista:
            if not isinstance(exec_direta, dict):
                continue
                
            if evento.categoria in [CategoriaEvento.NOTIFICACAO, CategoriaEvento.APP_FOREGROUND, CategoriaEvento.MEDIA]:
                logger.info(f"🛡️ [Raciocínio] Execução direta BLOQUEADA para evento ambiente ({evento.categoria}).")
                continue
            
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
                continue # Próximo comando na lista

            # 🌟 CASO 2: Comandos de PC
            elif alvo == "PC":
                payload_pc = {"comando": comando, "parametro": param} 
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
                
                # 🛡️ ROTEAMENTO DE HARDWARE: Força a categoria e limpa metadados de chat
                await kernel.publicar(EventoCanonico(
                    categoria=CategoriaEvento.SISTEMA_COMANDO_PC,
                    acao=TipoAcao.NORMAL,
                    origem=OrigemEvento.IA,
                    payload=payload_pc,
                    pacote="pc.master",
                    metadados={"tipo_destino": "PC"} 
                ))

            # 🌟 CASO 3: Comandos Mobile
            elif alvo == "MOBILE":
                # Alinhamento de nomes com o Android SystemCommandHandler
                acao_ajustada = comando.upper()
                if acao_ajustada == "SET_ALARM": acao_ajustada = "CONFIGURAR_DESPERTAR"
                
                payload_mob = {"tipo_ws": "COMANDO_SISTEMA", "acao": acao_ajustada, "parametro": param}
                if "abrir_app" in comando: payload_mob["pacote"] = param
                
                # Envia via WebSocket para o Celular
                from api.websocket import central_alertas
                await central_alertas._broadcast(payload_mob)
                logger.info(f"📱 [Raciocínio] Comando Mobile enviado: {acao_ajustada}({param})")

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
        
        # 🛡️ ROBUSTEZ: Tenta extrair a mensagem de várias chaves comuns em modelos menores
        mensagem = (
            resultado.get("mensagem_dinamica") or 
            resultado.get("mensagem") or 
            resultado.get("texto") or
            resultado.get("chat_response")
        )
        
        # 🌟 SEM FALLBACK: Se for comando do usuário, a IA é obrigada a ter mensagem_dinamica.
        if tipo_interacao in ["NOTIFICAR", "SUGERIR"]:
            # 🛡️ RECUPERAÇÃO: Se a IA esqueceu o texto mas planejou uma ação, usa confirmação padrão
            if not mensagem:
                if exec_direta_lista:
                    if tipo_interacao == "SUGERIR":
                        mensagem = "Notei algo aqui, quer uma ajuda com isso?"
                    else:
                        mensagem = "Massa, fazendo isso agora mesmo!"
                elif evento.categoria == CategoriaEvento.SISTEMA_COMANDO_USUARIO:
                    # 🚨 ÚLTIMO RECURSO: Nunca deixar o usuário no vácuo
                    mensagem = "Entendi! O que mais posso fazer?"
                
                if mensagem:
                    logger.info(f"🩹 [Raciocínio] Texto recuperado via fallback: {mensagem}")

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
                    "titulo": "Assistente" if tipo_interacao == "NOTIFICAR" else "Ollie Proativa",
                    "contexto": resultado.get("contexto_extra", {}),
                }
                
                # Se for SUGERIR, anexa o primeiro comando da lista como ação do botão
                if tipo_interacao == "SUGERIR" and exec_direta_raw:
                    sugestao = exec_direta_raw[0] if isinstance(exec_direta_raw, list) else exec_direta_raw
                    payload_notif["acao_tipo"] = "ENVIAR_COMANDO"
                    payload_notif["acao_parametro"] = json.dumps(sugestao)
                    payload_notif["acao_texto"] = "Bora!"
                    logger.info(f"💡 [Raciocínio] Botão de sugestão criado: {payload_notif['acao_parametro']}")
                
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
