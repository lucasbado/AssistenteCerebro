"""
agentes/agente_raciocinio.py
Cérebro Cognitivo da Ollie - Refatorado para Sinergia e Orquestração
"""
from __future__ import annotations
import json
import logging
import re
import asyncio
import os
from datetime import datetime
from core.evento import EventoCanonico
from core.tipos import PrioridadeEvento, OrigemEvento, TipoAcao, CategoriaEvento
from core.kernel import kernel
from servicos.llm import ServicoLLM
from servicos.memoria_episodica import MemoriaEpisodica
from servicos.memoria_semantica import MemoriaSemantica
from servicos.obsidian_service import obsidian_service
from servicos.catalogo_semantico import catalogo
from servicos.memoria_perfil import memoria_perfil
from modelos.catalogo import EntidadeSemantica

logger = logging.getLogger("AgenteRaciocinio")

class AgenteRaciocinio:
    def __init__(self):
        self.llm = ServicoLLM()
        self.memoria_episodica = MemoriaEpisodica()
        self.memoria_semantica = MemoriaSemantica()
        from servicos.memoria_trabalho import memoria_trabalho
        self.memoria_trabalho = memoria_trabalho
        # 🔒 LOCK DE PROCESSAMENTO
        self._locks_ativos = set()

    async def processar(self, evento: EventoCanonico):
        if evento.acao != TipoAcao.INTENCAO_RACIOCINIO:
            return

        # 🌟 LÓGICA DE APRENDIZADO POR REJEIÇÃO
        if evento.categoria == CategoriaEvento.SISTEMA_COMANDO_INTERNO and evento.payload.get("tipo") == "SUGESTAO_REJEITADA":
            id_orig = evento.payload.get("id_original")
            logger.info(f"🧠 [Aprendizado] Registrando rejeição da sugestão {id_orig}")
            obsidian_service.registrar_fato("Aprendizado", f"O usuário rejeitou a sugestão {id_orig} em {datetime.now().strftime('%d/%m/%Y %H:%M')}. Evitar proatividade similar neste contexto.")
            return

        lock_id = evento.id
        if lock_id in self._locks_ativos: return
        self._locks_ativos.add(lock_id)
        
        try:
            texto_u = str(evento.payload.get("texto", "")).lower()
            logger.info(f"🧠 [Raciocínio] Processando evento de {evento.pacote}...")

            # 1. Recupera Contexto do Obsidian (Busca Seletiva)
            conhecimento_atual = ""
            saudacoes = ["oi", "olá", "ola", "bom dia", "boa tarde", "boa noite", "tudo bem", "opa"]
            if len(texto_u) > 6 and not any(texto_u == s for s in saudacoes):
                try: 
                    # 💡 INJEÇÃO SELETIVA: Passa o texto do usuário para filtrar notas
                    conhecimento_atual = obsidian_service.listar_conhecimento_essencial(texto_u)
                except: pass

            # 2. Busca de Padrões e Recorrências
            habitos_contexto = await self._harvest_current_habits(evento)
            habitos_str = "\n".join(habitos_contexto) if habitos_contexto else "Nenhum padrão detectado ainda."
                
            # 3. Gerenciamento de Memória de Trabalho
            chave_conversa = "br.com.assistentecell.chat" if evento.categoria == CategoriaEvento.SISTEMA_COMANDO_USUARIO else evento.metadados.get('chave_conversa', evento.pacote)
            if evento.categoria == CategoriaEvento.SISTEMA_COMANDO_USUARIO and texto_u:
                await self.memoria_trabalho.atualizar_conversa(chave_conversa, [f"Usuário: {texto_u}"])

            historico = await self.memoria_trabalho.obter_contexto(chave_conversa) or []

            # 4. Invocação da LLM (com Heurística Local Fast-Path)
            heuristic_res = (self._tentar_heuristica_local(str(evento.payload.get('texto', '')))
                             if evento.categoria == CategoriaEvento.SISTEMA_COMANDO_USUARIO else None)
            if heuristic_res:
                logger.info(f"⚡ [Heurística Local] Resolvido sem LLM: {heuristic_res}")
                resultado = heuristic_res
            else:
                resultado = await self.llm.classificar_evento(
                    categoria=evento.categoria.value,
                    pacote=evento.pacote,
                    payload=evento.payload,
                    historico=historico,
                    timestamp_dispositivo=evento.timestamp,
                    knowledge=conhecimento_atual,
                    habits=habitos_str
                )

            # 🚀 EXTRAÇÃO ROBUSTA (SCAVENGER)
            exec_direta_raw = self._buscar_campo(resultado, "execucao_direta")
            msg_ia = self._buscar_campo(resultado, "mensagem_dinamica")
            tipo_interacao = resultado.get("tipo_interacao", "NOTIFICAR")
            if (evento.categoria == CategoriaEvento.SISTEMA_COMANDO_USUARIO and tipo_interacao == 'NOTIFICAR'
                    and isinstance(exec_direta_raw, list) and len(exec_direta_raw) > 1):
                from servicos.plano_pedidos import preparar_plano
                from servicos.roteamento_pedidos import contexto_pedido, responder_pedido
                try:
                    etapas = preparar_plano(evento, exec_direta_raw)
                except (ValueError, LookupError) as erro:
                    await responder_pedido(evento, str(erro))
                    return
                await kernel.publicar(evento.clonar(categoria=CategoriaEvento.PLANO_SOLICITADO,
                    acao=TipoAcao.NORMAL, payload={'etapas': etapas, 'texto_pedido': str(evento.payload.get('texto', ''))}, metadados=contexto_pedido(evento)))
                return
            from servicos.controle_casa import ACOES
            acoes_extraidas = exec_direta_raw if isinstance(exec_direta_raw, list) else [exec_direta_raw]
            tem_casa = any(isinstance(item, dict) and
                           str(item.get("comando") or item.get("action") or "").lower().strip() in ACOES
                           for item in acoes_extraidas)
            if tem_casa and tipo_interacao != "SUGERIR":
                # O agente da casa responde após confirmação; a LLM não antecipa sucesso.
                msg_ia = None
            from servicos.intervention_governor import e_abertura
            from servicos.abertura_apps import pedido_explicito_de_abertura
            explicito = (evento.categoria == CategoriaEvento.SISTEMA_COMANDO_USUARIO and
                         pedido_explicito_de_abertura(texto_u))
            tem_abertura = any(isinstance(item, dict) and
                e_abertura(item.get("comando") or item.get("action")) for item in acoes_extraidas)
            if tem_abertura:
                # A sugestão abaixo contém o botão real; não anunciar execução que foi negada.
                msg_ia = None

            # 📝 LOG COGNITIVO
            self._registrar_log_cognitivo(texto_u, habitos_contexto, resultado)

            # 5. DISPACHO DE RESPOSTA (Ollie Falando)
            if msg_ia and tipo_interacao in ["NOTIFICAR", "SUGERIR"]:
                msg_limpa = re.sub(r"(?i)\b(eu\s+)?sou\s+a\s+ollie\b[,!.]*|\bollie\s+aqui\b[,!.]*", "", msg_ia).strip()
                
                # Determina se é Chat ou Notificação de Sistema
                tipo_ws = "CHAT_RESPONSE" if evento.categoria == CategoriaEvento.SISTEMA_COMANDO_USUARIO else "NOTIFICACAO"
                
                payload_notif = {
                    "texto": msg_limpa, 
                    "titulo": "Ollie", 
                    "tipo_ws": tipo_ws,
                    "contexto": resultado.get("contexto_extra", {})
                }
                if tipo_ws == "CHAT_RESPONSE":
                    # The conversational decision belongs to reasoning; clients only
                    # reopen capture after the spoken answer has actually finished.
                    payload_notif["aguarda_resposta"] = resultado.get("aguarda_resposta") is True
                
                if tipo_ws == "CHAT_RESPONSE":
                    await self.memoria_trabalho.atualizar_conversa(chave_conversa, [f"Ollie: {msg_limpa}"])
                
                await kernel.publicar(evento.clonar(
                    categoria=CategoriaEvento.INTENCAO_NOTIFICACAO, 
                    acao=TipoAcao.INTENCAO_INTERACAO, 
                    origem=OrigemEvento.IA, 
                    payload=payload_notif, 
                    metadados={**evento.metadados, "tipo_destino": "CHAT" if tipo_ws == "CHAT_RESPONSE" else "NOTIFICACAO"}
                ))

            # 6. EXECUÇÃO DE COMANDOS (Ollie Agindo)
            exec_direta_lista = []
            if tipo_interacao in {"NOTIFICAR", "SUGERIR"}:
                if isinstance(exec_direta_raw, list): exec_direta_lista = exec_direta_raw
                elif exec_direta_raw: exec_direta_lista = [exec_direta_raw]

            for exec_direta in exec_direta_lista:
                if not isinstance(exec_direta, dict): continue
                
                alvo = str(exec_direta.get("alvo", "PC")).upper().strip()
                comando = str(exec_direta.get("comando") or exec_direta.get("action") or "").lower().strip()
                param = str(exec_direta.get("parametro") or exec_direta.get("param") or exec_direta.get("value") or "").strip()

                if not comando: continue
                if tipo_interacao == "SUGERIR" and not e_abertura(comando):
                    continue
                if comando in ACOES:
                    if evento.categoria == CategoriaEvento.SISTEMA_COMANDO_USUARIO:
                        await kernel.publicar(evento.clonar(
                            categoria=CategoriaEvento.CASA_ACAO_SOLICITADA,
                            acao=TipoAcao.NORMAL,
                            payload={"acao": ACOES[comando], "alvo": param}))
                    continue
                
                from servicos.roteamento_pedidos import resolver_abertura, contexto_pedido, responder_pedido
                # O texto do usuário e a origem prevalecem sobre o destino escolhido pela LLM.
                if e_abertura(comando) and explicito and tipo_interacao != "SUGERIR":
                    try:
                        alvo, comando, param = resolver_abertura(evento, comando, param)
                    except ValueError as erro:
                        await responder_pedido(evento, str(erro))
                        break
                alvos = [a.strip() for a in alvo.split("|")]
                
                logger.info(f"⚡ [Raciocínio] Executando em {alvos}: {comando}({param})")

                from servicos.abertura_apps import sugerir_abertura
                for a in alvos:
                    # Background reasoning may suggest an app, but never appoints itself authority to open it.
                    if e_abertura(comando) and (not explicito or tipo_interacao == "SUGERIR"):
                        await sugerir_abertura(evento, a, comando, param, "inferencia_sem_pedido")
                        continue
                    if a == "PC":
                        await kernel.publicar(evento.clonar(
                            categoria=CategoriaEvento.SISTEMA_COMANDO_PC, acao=TipoAcao.NORMAL,
                            origem=OrigemEvento.IA,
                            payload={"comando": comando, "parametro": param},
                            metadados={**(contexto_pedido(evento) if explicito else evento.metadados), "pedido_explicito": explicito}))
                    elif a == "MOBILE":
                        from api.websocket import central_alertas
                        enviado = await central_alertas.enviar_comando_mobile({
                            "tipo_ws": "COMANDO_SISTEMA", "acao": comando.upper(), "parametro": param,
                            "correlacao_id": evento.correlacao_id, "id_comando": evento.id,
                            **({"abertura_modo": "pedido", "abertura_autorizada": True} if e_abertura(comando) else {})})
                        if e_abertura(comando) and explicito:
                            from servicos.respostas_acoes import resumir_resultados
                            await responder_pedido(evento, resumir_resultados([{'etapa': {'alvo': 'MOBILE', 'comando': comando, 'parametro': param},
                                'status': 'enviado' if enviado else 'mobile_offline'}]))

            # 7. MEMÓRIA PERMANENTE (Obsidian + Novo Banco FactDB)
            mem_obs = resultado.get("memoria_obsidian")
            if mem_obs and isinstance(mem_obs, dict):
                titulo = str(mem_obs.get("titulo", "Aprendizado")).strip()
                fato = str(mem_obs.get("fato", "")).strip()
                if titulo and fato:
                    logger.info(f"🧠 [Aprendizado] Registrando novo fato no Obsidian e FactDB [{titulo}]: {fato[:50]}...")
                    obsidian_service.registrar_fato(titulo, fato)
                    try:
                        from servicos.fact_service import fact_service
                        await fact_service.extrair_e_salvar_fatos(fato)
                    except Exception as fe:
                        logger.error(f"Erro ao salvar fato no FactDB: {fe}")

        except Exception as e:
            logger.error(f"💥 Erro no Raciocínio: {e}")
            err_str = str(e).lower()
            is_rate_limit = "429" in err_str or "rate limit" in err_str or "rate_limit" in err_str
            
            if evento.categoria == CategoriaEvento.SISTEMA_COMANDO_USUARIO:
                msg = "Estou atingindo o limite de requisições da IA (Rate Limit). Tente novamente em instantes!" if is_rate_limit else "Tive um pequeno soluço ao processar seu pedido. Pode repetir?"
                try:
                    await kernel.publicar(evento.clonar(
                        categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
                        acao=TipoAcao.INTENCAO_INTERACAO,
                        origem=OrigemEvento.IA,
                        payload={
                            "texto": msg,
                            "titulo": "Ollie",
                            "tipo_ws": "CHAT_RESPONSE"
                        },
                        metadados={**evento.metadados, "tipo_destino": "CHAT"}
                    ))
                except: pass
        finally:
            self._locks_ativos.remove(lock_id)

    async def sintetizar_com_pesquisa(self, evento_resultado: EventoCanonico):
        """Sintetiza os resultados de uma busca na web."""
        query = evento_resultado.payload.get("query")
        conteudo = evento_resultado.payload.get("conteudo")
        sucesso = evento_resultado.payload.get("sucesso")

        if not sucesso:
            await kernel.publicar(evento_resultado.clonar(
                categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
                acao=TipoAcao.INTENCAO_INTERACAO,
                origem=OrigemEvento.IA,
                payload={"texto": f"Desculpa, tive um problema ao pesquisar sobre '{query}'.", "tipo_ws": "CHAT_RESPONSE"}
            ))
            return

        historico = await self.memoria_trabalho.obter_contexto("br.com.assistentecell.chat") or []
        
        try:
            resultado = await self.llm.sintetizar_resposta_pesquisa(query, conteudo, historico)
            resposta = resultado.get("resposta_amigavel")
            fato = resultado.get("fato_para_aprender")

            if resposta:
                await kernel.publicar(evento_resultado.clonar(
                    categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
                    acao=TipoAcao.INTENCAO_INTERACAO,
                    origem=OrigemEvento.IA,
                    payload={"texto": resposta, "tipo_ws": "CHAT_RESPONSE"}
                ))
            
            if fato:
                obsidian_service.registrar_fato("Conhecimento_Web", f"Em {datetime.now().strftime('%d/%m/%Y')}, pesquisei sobre '{query}': {fato}")
        except Exception as e:
            logger.error(f"Erro ao sintetizar pesquisa: {e}")

    def _buscar_campo(self, obj, campo):
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
                    return val
            for v in obj.values():
                res = self._buscar_campo(v, campo)
                if res: return res
        elif isinstance(obj, list):
            for item in obj:
                res = self._buscar_campo(item, campo)
                if res: return res
        return None

    async def _harvest_current_habits(self, evento: EventoCanonico) -> list[str]:
        habitos = []
        try:
            # 1. Associações de App
            entidade = await catalogo.obter_app(evento.pacote)
            if entidade and entidade.atributos.get("associacoes"):
                assoc = entidade.atributos["associacoes"]
                if "pc_default" in assoc:
                    habitos.append(f"PADRÃO: Ao abrir '{evento.pacote}', você costuma usar '{assoc['pc_default']['programa']}' no PC.")
            
            # 2. Padrões de Horário
            from servicos.memoria_perfil import _get_time_slot
            periodo = _get_time_slot(datetime.now())
            top_app = await memoria_perfil.obter_item_mais_frequente_por_periodo("APP_USO", periodo)
            if top_app: habitos.append(f"ROTINA {periodo}: Seu app mais usado agora é '{top_app}'.")
        except: pass
        return habitos

    def _registrar_log_cognitivo(self, usuario_diz: str, habitos: list, resultado: dict):
        log_dir = "logs" if os.getenv("RENDER") else "D:/Programacao/AssistenteCell/logs"
        if not os.path.exists(log_dir): os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "cognitivo.log")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = (
            f"[{timestamp}] USUÁRIO: \"{usuario_diz}\"\n"
            f"[HÁBITOS]: {json.dumps(habitos, ensure_ascii=False)}\n"
            f"[INTENÇÃO]: {resultado.get('intencao_captada', 'N/A')}\n"
            f"[EXECUÇÃO]: {json.dumps(resultado.get('execucao_direta', []), ensure_ascii=False)}\n"
            f"[RESPOSTA]: \"{resultado.get('mensagem_dinamica', 'N/A')}\"\n"
            f"{'-'*50}\n"
        )
        try:
            with open(log_path, "a", encoding="utf-8") as f: f.write(entry)
        except: pass

    def _tentar_heuristica_local(self, texto: str) -> dict | None:
        if not texto: return None
        from servicos.conversa import pedido_de_explicacao
        if pedido_de_explicacao(texto):
            return None
        t = texto.lower().strip()
        from servicos.plano_pedidos import interpretar_composto
        composto = interpretar_composto(texto)
        if composto:
            return composto
        from servicos.roteamento_pedidos import interpretar_abertura
        abertura = interpretar_abertura(texto)
        if abertura:
            return abertura

        # 💡 COMANDOS DE ILUMINAÇÃO
        from servicos.controle_casa import controle_casa
        pedido = controle_casa.interpretar(texto)
        if pedido:
            comandos = {"ligar": "ligar_luz", "desligar": "desligar_luz",
                        "alternar": "toggle_luz", "consultar": "consultar_luz"}
            return {"execucao_direta": [{"alvo": "CASA", "comando": comandos[pedido["acao"]],
                                        "parametro": pedido["alvo"]}],
                    "mensagem_dinamica": "", "tipo_interacao": "NOTIFICAR"}

        if any(kw in t for kw in ["mutar mic", "muta mic", "desmutar mic", "desmuta mic", "mutar microfone"]):
            return {
                "execucao_direta": [{"alvo": "PC", "comando": "mutar_mic", "parametro": ""}],
                "mensagem_dinamica": "Alternando mudo do microfone.",
                "tipo_interacao": "NOTIFICAR"
            }

        return None
