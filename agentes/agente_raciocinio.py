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
            chave_conversa = "br.com.assistentecell.chat" if evento.categoria == CategoriaEvento.SISTEMA_COMANDO_USUARIO else evento.pacote
            if evento.categoria == CategoriaEvento.SISTEMA_COMANDO_USUARIO and texto_u:
                await self.memoria_trabalho.atualizar_conversa(chave_conversa, [f"Usuário: {texto_u}"])

            historico = await self.memoria_trabalho.obter_contexto(chave_conversa) or []

            # 4. Invocação da LLM
            resultado = await self.llm.classificar_evento(
                categoria=evento.categoria.value,
                pacote=evento.pacote,
                payload=evento.payload,
                historico=historico,
                timestamp_dispositivo=evento.timestamp,
                conhecimento=conhecimento_atual,
                habitos=habitos_str
            )

            # 🚀 EXTRAÇÃO ROBUSTA (SCAVENGER)
            exec_direta_raw = self._buscar_campo(resultado, "execucao_direta")
            msg_ia = self._buscar_campo(resultado, "mensagem_dinamica")
            tipo_interacao = resultado.get("tipo_interacao", "NOTIFICAR")

            # 📝 LOG COGNITIVO
            self._registrar_log_cognitivo(texto_u, habitos_contexto, resultado)

            # 5. DISPACHO DE RESPOSTA (Ollie Falando)
            if msg_ia and tipo_interacao in ["NOTIFICAR", "SUGERIR"]:
                msg_limpa = re.sub(r"(?i)\b(eu\s+)?sou\s+a\s+ollie\b[,!.]*|\bollie\s+aqui\b[,!.]*", "", msg_ia).strip().capitalize()
                
                # Determina se é Chat ou Notificação de Sistema
                tipo_ws = "CHAT_RESPONSE" if evento.categoria == CategoriaEvento.SISTEMA_COMANDO_USUARIO else "NOTIFICACAO"
                
                payload_notif = {
                    "texto": msg_limpa, 
                    "titulo": "Ollie", 
                    "tipo_ws": tipo_ws,
                    "contexto": resultado.get("contexto_extra", {})
                }
                
                if tipo_ws == "CHAT_RESPONSE":
                    await self.memoria_trabalho.atualizar_conversa(chave_conversa, [f"Ollie: {msg_limpa}"])
                
                await kernel.publicar(evento.clonar(
                    categoria=CategoriaEvento.INTENCAO_NOTIFICACAO, 
                    acao=TipoAcao.INTENCAO_INTERACAO, 
                    origem=OrigemEvento.IA, 
                    payload=payload_notif, 
                    metadados={"tipo_destino": "CHAT" if tipo_ws == "CHAT_RESPONSE" else "NOTIFICACAO"}
                ))

            # 6. EXECUÇÃO DE COMANDOS (Ollie Agindo)
            exec_direta_lista = []
            if tipo_interacao != "SUGERIR":
                if isinstance(exec_direta_raw, list): exec_direta_lista = exec_direta_raw
                elif exec_direta_raw: exec_direta_lista = [exec_direta_raw]

            for exec_direta in exec_direta_lista:
                if not isinstance(exec_direta, dict): continue
                
                alvo = str(exec_direta.get("alvo", "PC")).upper().strip()
                comando = str(exec_direta.get("comando") or exec_direta.get("action") or "").lower().strip()
                param = str(exec_direta.get("parametro") or exec_direta.get("param") or exec_direta.get("value") or "").strip()

                if not comando: continue
                logger.info(f"⚡ [Raciocínio] Executando: {alvo} -> {comando}({param})")

                if alvo == "PC":
                    # Encaminha comando para o executor do PC
                    await kernel.publicar(EventoCanonico(
                        categoria=CategoriaEvento.SISTEMA_COMANDO_PC, 
                        acao=TipoAcao.NORMAL, 
                        origem=OrigemEvento.IA,
                        pacote="pc.master",
                        payload={"comando": comando, "parametro": param}
                    ))
                elif alvo == "MOBILE":
                    from api.websocket import central_alertas
                    await central_alertas._broadcast({
                        "tipo_ws": "COMANDO_SISTEMA", 
                        "acao": comando.upper(), 
                        "parametro": param
                    })

            # 7. MEMÓRIA PERMANENTE (Obsidian)
            mem_obs = resultado.get("memoria_obsidian")
            if mem_obs and isinstance(mem_obs, dict):
                titulo, fato = mem_obs.get("titulo"), mem_obs.get("fato")
                if titulo and fato: obsidian_service.registrar_fato(titulo, fato)

        except Exception as e:
            logger.error(f"💥 Erro no Raciocínio: {e}")
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
