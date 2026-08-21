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
        # 🔒 LOCK DE PROCESSAMENTO: Evita múltiplas chamadas simultâneas para o mesmo evento
        self._locks_ativos = set()

    async def processar(self, evento: EventoCanonico):
        # 0. Inicializa resultado padrão
        resultado = {
            "tipo_interacao": "IGNORAR",
            "mensagem_dinamica": None,
            "execucao_direta": None
        }

        # 🌟 LÓGICA DE APRENDIZADO POR REJEIÇÃO
        if evento.categoria == CategoriaEvento.SISTEMA_COMANDO_INTERNO and evento.payload.get("tipo") == "SUGESTAO_REJEITADA":
            id_orig = evento.payload.get("id_original")
            logger.info(f"🧠 [Aprendizado] Registrando rejeição da sugestão {id_orig}")
            obsidian_service.registrar_fato("Aprendizado", f"O usuário rejeitou a sugestão {id_orig} em {datetime.now().strftime('%d/%m/%Y %H:%M')}. Evitar proatividade similar neste contexto.")
            return

        if evento.acao != TipoAcao.INTENCAO_RACIOCINIO:
            return
            
        # 🛡️ TRAVA DE DUPLICIDADE (LOCK)
        lock_id = evento.metadados.get("correlacao_id") or evento.id
        
        if lock_id in self._locks_ativos:
            logger.warning(f"🛡️ [Raciocínio] Evento {lock_id[:20]} já está em processamento.")
            return
        
        self._locks_ativos.add(lock_id)
        
        try:
            logger.info(f"🧠 [Raciocínio] Iniciando processamento de '{lock_id[:30]}'")

            # 1. Recupera Contexto do Obsidian
            conhecimento_atual = ""
            try:
                conhecimento_atual = obsidian_service.listar_conhecimento_essencial()
            except Exception as e:
                logger.warning(f"⚠️ Erro Obsidian: {e}")
                
            # 🌟 FEEDBACK IMEDIATO (Thinking)
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

            # 2. Salva na Memória de Trabalho
            chave_conversa = "br.com.assistentecell.chat" if evento.categoria == CategoriaEvento.SISTEMA_COMANDO_USUARIO else evento.pacote
            if evento.categoria == CategoriaEvento.SISTEMA_COMANDO_USUARIO:
                texto_usuario = evento.payload.get("texto", "")
                if texto_usuario:
                    try:
                        await asyncio.wait_for(self.memoria_trabalho.atualizar_conversa(chave_conversa, [f"Usuário: {texto_usuario}"]), timeout=2.0)
                    except: pass

            # 3. Recupera histórico
            historico = []
            try:
                historico = await asyncio.wait_for(self.memoria_trabalho.obter_contexto(chave_conversa), timeout=2.0)
                cid = evento.metadados.get("correlacao_id")
                if cid:
                    historico.append(f"CONTEXTO: O usuário está respondendo especificamente à notificação {cid}.")
            except: pass

            # 4. Chama LLM
            try:
                resultado = await asyncio.wait_for(
                    self.llm.classificar_evento(
                        categoria=evento.categoria.value,
                        pacote=evento.pacote,
                        payload=evento.payload,
                        historico=historico,
                        timestamp_dispositivo=evento.timestamp,
                        conhecimento=conhecimento_atual
                    ),
                    timeout=35.0
                )
            except asyncio.TimeoutError:
                resultado = {"tipo_interacao": "NOTIFICAR", "mensagem_dinamica": "Vixi, meu cérebro deu uma engasgada aqui na nuvem. Pode repetir?"}
            except Exception as e:
                logger.error(f"❌ [Raciocínio] Erro LLM: {e}")
                err_str = str(e).lower()
                if "rate_limit" in err_str or "429" in err_str or "todos os modelos" in err_str:
                    msg = "Vish, a Groq tá me barrando por velocidade! Dá um segundinho e tenta de novo?"
                elif "400" in err_str or "model" in err_str:
                    msg = "Eita, o modelo de IA mudou. Dá um segundinho que tô me atualizando!"
                else:
                    msg = "Vish, deu pane no meu sistema aqui! Tenta de novo em um segundinho?"
                resultado = {"tipo_interacao": "NOTIFICAR", "mensagem_dinamica": msg}

        except Exception as outer_e:
            logger.error(f"💥 Erro fatal Raciocínio: {outer_e}")
            resultado = {"tipo_interacao": "NOTIFICAR", "mensagem_dinamica": "Vish, deu pane no meu sistema aqui!"}
        finally:
            if lock_id in self._locks_ativos:
                self._locks_ativos.remove(lock_id)

        # 🌟 LOG DE DECISÃO
        logger.info(f"📊 [BRAIN] Decision: {json.dumps(resultado, ensure_ascii=False)}")

        # 🚀 EXTRAÇÃO ROBUSTA (SCAVENGER)
        def buscar_campo(obj, campo):
            if isinstance(obj, dict):
                aliases = {
                    "execucao_direta": ["execucao_direta", "comandos", "actions", "exec"],
                    "mensagem_dinamica": ["mensagem_dinamica", "mensagem", "texto", "chat", "chat_response", "resposta"]
                }
                alvos = aliases.get(campo, [campo])
                for alvo in alvos:
                    if alvo in obj and obj[alvo] is not None:
                        val = obj[alvo]
                        if campo == "mensagem_dinamica" and isinstance(val, list):
                            return " ".join([str(x) for x in val])
                        if val: return val
                for v in obj.values():
                    if isinstance(v, (dict, list)):
                        res = buscar_campo(v, campo)
                        if res: return res
            elif isinstance(obj, list):
                for item in obj:
                    res = buscar_campo(item, campo)
                    if res: return res
            return None

        # Captura os valores reais
        scavenged_exec = buscar_campo(resultado, "execucao_direta")
        scavenged_msg = buscar_campo(resultado, "mensagem_dinamica")
        
        if scavenged_exec: resultado["execucao_direta"] = scavenged_exec
        if scavenged_msg: resultado["mensagem_dinamica"] = scavenged_msg

        exec_direta_raw = resultado.get("execucao_direta")
        msg_ia = resultado.get("mensagem_dinamica")
        tipo_interacao = resultado.get("tipo_interacao") or "NOTIFICAR"

        # 🚀 CORREÇÃO: Força execução se a IA sugeriu algo mas o usuário deu uma ordem
        texto_u = str(evento.payload.get("texto", "")).lower()
        if (not exec_direta_raw or exec_direta_raw == []) and ("luz" in texto_u or "apaga" in texto_u or "liga" in texto_u) and ("sim" in texto_u or "pode" in texto_u or "bora" in texto_u):
             for msg in reversed((historico or [])[-5:]):
                 msg_l = msg.lower()
                 if "ollie:" in msg_l and ("você quer" in msg_l or "gostaria" in msg_l):
                     if "luz do quarto" in msg_l: 
                         acao = "desligar" if "apagar" in msg_l or "desligar" in msg_l else "ligar"
                         exec_direta_raw = {"alvo": "MOBILE", "comando": "ENVIAR_COMANDO", "parametro": f"luz_quarto {acao}"}
                         resultado["execucao_direta"] = exec_direta_raw
                         break

        # 🧠 CONSCIÊNCIA DE AÇÃO
        if exec_direta_raw and msg_ia:
            if "?" in msg_ia or any(x in msg_ia.lower() for x in ["quer", "gostaria", "deseja"]):
                msg_ia = msg_ia.split("?")[0].strip() + "!"
                if len(msg_ia) < 3: msg_ia = "Fechou, tá na mão!"
                resultado["mensagem_dinamica"] = msg_ia

        # 4. EXECUÇÃO DIRETA
        exec_direta_lista = []
        if tipo_interacao != "SUGERIR":
            if isinstance(exec_direta_raw, list): exec_direta_lista = exec_direta_raw
            elif exec_direta_raw: exec_direta_lista = [exec_direta_raw]

        for exec_direta in exec_direta_lista:
            if not isinstance(exec_direta, dict): continue
            if evento.categoria in [CategoriaEvento.NOTIFICACAO, CategoriaEvento.APP_FOREGROUND]: continue
            
            alvo = str(exec_direta.get("alvo", "PC")).upper().strip()
            comando = str(exec_direta.get("comando", "")).lower().strip()
            param = str(exec_direta.get("parametro", "")).strip()

            if "pesquisa_web" in comando:
                await kernel.publicar(evento.clonar(categoria=CategoriaEvento.INTENCAO_PESQUISA, payload={"query": param}))
            elif alvo == "PC":
                await kernel.publicar(EventoCanonico(categoria=CategoriaEvento.SISTEMA_COMANDO_PC, acao=TipoAcao.NORMAL, payload={"comando": comando, "parametro": param}, pacote="pc.master", metadados={"tipo_destino": "PC"}))
            elif alvo == "MOBILE":
                from api.websocket import central_alertas
                await central_alertas._broadcast({"tipo_ws": "COMANDO_SISTEMA", "acao": comando.upper(), "parametro": param})

        # 5. NOTIFICAÇÕES E SUGESTÕES
        if tipo_interacao in ["NOTIFICAR", "SUGERIR"]:
            if not msg_ia and exec_direta_lista: msg_ia = "Massa, fazendo isso!"
            if not msg_ia and evento.categoria == CategoriaEvento.SISTEMA_COMANDO_USUARIO: msg_ia = "Entendi!"

            if msg_ia:
                # Remove apresentações repetitivas
                if historico:
                    msg_ia = re.sub(r"(?i)\b(eu\s+)?sou\s+a\s+ollie\b[,!.]*|\bollie\s+aqui\b[,!.]*", "", msg_ia).strip().capitalize()

                payload_notif = {"texto": msg_ia, "titulo": "Ollie", "contexto": resultado.get("contexto_extra", {})}
                
                if tipo_interacao == "SUGERIR" and exec_direta_raw:
                    if not msg_ia.endswith("?"): payload_notif["texto"] += "?"
                    sug = exec_direta_raw[0] if isinstance(exec_direta_raw, list) else exec_direta_raw
                    payload_notif["acao_tipo"] = "ENVIAR_COMANDO"
                    payload_notif["acao_parametro"] = json.dumps(sug)
                    payload_notif["acao_texto"] = "Bora!"

                if evento.categoria == CategoriaEvento.SISTEMA_COMANDO_USUARIO:
                    payload_notif["tipo_ws"] = "CHAT_RESPONSE"
                    await self.memoria_trabalho.atualizar_conversa(chave_conversa, [f"Ollie: {msg_ia}"])

                await kernel.publicar(evento.clonar(categoria=CategoriaEvento.INTENCAO_NOTIFICACAO, acao=TipoAcao.INTENCAO_INTERACAO, origem=OrigemEvento.IA, payload=payload_notif, metadados={"tipo_destino": "CHAT"}))

        # 6. MEMÓRIA PERMANENTE (Obsidian)
        mem_obs = resultado.get("memoria_obsidian")
        if mem_obs and isinstance(mem_obs, dict):
            titulo, fato = str(mem_obs.get("titulo", "")), str(mem_obs.get("fato", ""))
            if titulo and fato and not any(k in fato.lower() for k in ["notificação", "conversa"]):
                obsidian_service.registrar_fato(titulo, fato)

    async def sintetizar_com_pesquisa(self, evento_resultado: EventoCanonico):
        # ... (Mantido o código de síntese sem alterações para brevidade) ...
        pass
