from __future__ import annotations
import asyncio
import logging
from collections import defaultdict
from typing import DefaultDict

from core.evento import EventoCanonico
from core.tipos import TipoAcao, CategoriaEvento
from core.kernel import kernel
from servicos.memoria_trabalho import memoria_trabalho

logger = logging.getLogger(__name__)

# Tempo em segundos para agrupar mensagens da mesma conversa antes de enviar para a IA
# Aumentado para 45 segundos na Nuvem para maximizar a economia de tokens
DEBOUNCE_SECONDS = 45

class AgenteMemoriaTrabalho:
    """
    Agente responsável por gerenciar a Memória de Trabalho. Sua principal função
    é agrupar notificações de texto sequenciais do mesmo aplicativo (ex: várias
    mensagens de WhatsApp de diferentes pessoas/grupos) para fornecer um contexto
    mais rico
    para a camada de raciocínio (LLM), evitando o "flood" de notificações e
    melhorando a compreensão.
    """
    def __init__(self):
        # O buffer agora armazena uma lista de tuplas (remetente, texto)
        self.buffers: dict[str, list[tuple[str, str]]] = defaultdict(list)
        self.timers: dict[str, asyncio.Task] = {}

    async def processar(self, evento: EventoCanonico):
        # Este agente agora é o responsável por agrupar notificações de texto
        if evento.categoria != CategoriaEvento.NOTIFICACAO:
            return

        texto = evento.payload.get("texto")
        remetente = evento.payload.get("titulo")

        if not texto or not remetente:
            return

        # A CHAVE DE AGRUPAMENTO AGORA É APENAS O PACOTE DO APP.
        # Isso garante que todas as notificações do WhatsApp, por exemplo,
        # sejam agrupadas em um único "debounce", independentemente do remetente.
        chave_conversa = evento.pacote
        logger.debug(f"🧠 [MemoriaTrabalho] Recebida mensagem de '{remetente}' do app '{chave_conversa}'. Adicionando ao buffer.")

        # Cancela o timer anterior se houver um, pois uma nova mensagem chegou
        if chave_conversa in self.timers:
            self.timers[chave_conversa].cancel()

        # Adiciona a nova tupla (remetente, mensagem) ao buffer da conversa
        self.buffers[chave_conversa].append((remetente, texto))

        # Cria um novo timer para despachar a conversa agrupada
        self.timers[chave_conversa] = asyncio.create_task(
            self._despachar_agrupado(chave_conversa, evento)
        )

    async def _despachar_agrupado(self, chave_conversa: str, evento_original: EventoCanonico):
        try:
            await asyncio.sleep(DEBOUNCE_SECONDS)

            # VERIFICAÇÃO DE SEGURANÇA (ANTI-RACE CONDITION):
            # Garante que esta tarefa ainda é a "dona" do timer. Se um novo evento chegou,
            # um novo timer foi criado, e esta tarefa se torna obsoleta.
            if self.timers.get(chave_conversa) is not asyncio.current_task():
                return # Silenciosamente encerra, pois uma tarefa mais nova assumiu.

            # O buffer agora contém tuplas (remetente, texto)
            mensagens_agrupadas = self.buffers.pop(chave_conversa, [])
            self.timers.pop(chave_conversa, None)
            if not mensagens_agrupadas: return

            # Remove duplicatas exatas de tuplas (remetente, texto) preservando a ordem
            mensagens_unicas = list(dict.fromkeys(mensagens_agrupadas))

            logger.info(f"🧠 [MemoriaTrabalho] Debounce finalizado para '{chave_conversa}'. Pré-processando {len(mensagens_unicas)} mensagens.")

            # --- INÍCIO DA LÓGICA DE PRÉ-SUMARIZAÇÃO SEM LLM ---

            # 1. Agrupa as mensagens por remetente para entender o contexto de cada conversa.
            mensagens_por_remetente: DefaultDict[str, list[str]] = defaultdict(list)
            for remetente, texto in mensagens_unicas:
                mensagens_por_remetente[remetente].append(texto)

            # 2. Gera um resumo em texto para cada remetente.
            partes_resumo = []
            nome_app = chave_conversa.split('.')[-1].capitalize() if '.' in chave_conversa else "Sistema"
            if "whatsapp" in chave_conversa.lower(): nome_app = "WhatsApp"
            if "instagram" in chave_conversa.lower(): nome_app = "Instagram"

            for remetente, textos in mensagens_por_remetente.items():
                # Heurísticas para categorizar cada notificação
                textos_puros = []
                num_figurinhas = 0
                num_chamadas_perdidas = 0

                for t in textos:
                    texto_lower = t.lower()
                    if "enviou uma figurinha" in texto_lower:
                        num_figurinhas += 1
                    elif "chamada perdida" in texto_lower or "chamada de voz perdida" in texto_lower:
                        num_chamadas_perdidas += 1
                    else:
                        textos_puros.append(t)

                # Lista para guardar as partes do resumo deste remetente
                resumos_parciais = []

                # Parte 1: Mensagens de texto (Incluindo trecho para clareza)
                if textos_puros:
                    trecho = f" ('{textos_puros[0][:40]}...')" if len(textos_puros) == 1 else ""
                    s_plural = "s" if len(textos_puros) > 1 else ""
                    resumos_parciais.append(f"{len(textos_puros)} mensagem{s_plural} de {remetente} no {nome_app}{trecho}")

                # Parte 2: Figurinhas
                if num_figurinhas > 0:
                    s = 's' if num_figurinhas > 1 else ''
                    resumos_parciais.append(f"{num_figurinhas} figurinha{s}")

                # Parte 3: Chamadas perdidas
                if num_chamadas_perdidas > 0:
                    s = 's' if num_chamadas_perdidas > 1 else ''
                    resumos_parciais.append(f"{num_chamadas_perdidas} chamada{s} perdida{s} de {remetente}")

                if not resumos_parciais:
                    continue

                # Junta as partes do resumo para este remetente (ex: "2 mensagens e 1 figurinha")
                if len(resumos_parciais) == 1:
                    partes_resumo.append(resumos_parciais[0])
                else:
                    partes_resumo.append(f"{', '.join(resumos_parciais[:-1])} e {resumos_parciais[-1]}")

            # 3. Constrói a frase final do resumo, juntando as partes de forma gramaticalmente correta.
            if not partes_resumo:
                return # Nenhuma mensagem útil para notificar.

            # Separa sentenças completas (ex: "Maria enviou 1 figurinha") de fragmentos (ex: "2 mensagens de Grupo X")
            sentencas_completas = [p for p in partes_resumo if any(p.startswith(remetente) for remetente in mensagens_por_remetente.keys())]
            fragmentos = [p for p in partes_resumo if p not in sentencas_completas]
            resumo_final_partes = []
            if fragmentos:
                prefixo = "Você tem" if len(fragmentos) <= 2 else "Você tem novas mensagens:"
                if len(fragmentos) == 1:
                    resumo_fragmentos = f"{prefixo} {fragmentos[0]}."
                elif len(fragmentos) == 2:
                    resumo_fragmentos = f"{prefixo} {fragmentos[0]} e {fragmentos[1]}."
                else: # 3 ou mais
                    primeiras = ", ".join(fragmentos[:-1])
                    ultima = fragmentos[-1]
                    resumo_fragmentos = f"{prefixo} {primeiras}, e {ultima}."
                resumo_final_partes.append(resumo_fragmentos)
            if sentencas_completas:
                resumo_final_partes.extend([s + '.' if not s.endswith('.') else s for s in sentencas_completas])
            resumo_final_str = " ".join(resumo_final_partes)
            logger.info(f"🧠 [MemoriaTrabalho] Pré-resumo gerado: {resumo_final_str}")

            # --- FIM DA LÓGICA DE PRÉ-SUMARIZAÇÃO ---

            # --- INÍCIO DA INTEGRAÇÃO COM MEMÓRIA PERSISTENTE ---

            # 1. Recupera o contexto histórico da conversa, se houver.
            contexto_historico = await memoria_trabalho.obter_contexto(chave_conversa) or []

            # 2. Formata as novas mensagens para serem salvas.
            mensagens_novas_formatadas = [f"{r}: {t}" for r, t in mensagens_unicas]

            # 3. Atualiza a memória de trabalho persistente com as novas mensagens (fire-and-forget).
            # O serviço de memória é responsável por manter o histórico conciso.
            asyncio.create_task(memoria_trabalho.atualizar_conversa(chave_conversa, mensagens_novas_formatadas))

            # --- FIM DA INTEGRAÇÃO ---

            # O payload agora inclui o pré-resumo, o contexto histórico e os dados brutos.
            payload_agrupado = {
                "remetente": f"{len(mensagens_unicas)} novas mensagens",
                "mensagens": [f"{r}: {t}" for r, t in mensagens_unicas],
                "conversa_completa": "\n".join([f"{r}: {t}" for r, t in mensagens_unicas]),
                "pre_resumo": resumo_final_str,
                "contexto_historico": contexto_historico # Adiciona o histórico para a LLM
            }
            await kernel.publicar(evento_original.clonar(acao=TipoAcao.INTENCAO_RACIOCINIO, payload=payload_agrupado))
        except asyncio.CancelledError:
            logger.debug(f"🧠 [MemoriaTrabalho] Debounce para '{chave_conversa}' resetado.")
        except Exception as e:
            logger.error(f"🧠 [MemoriaTrabalho] Erro no despacho agrupado: {e}")
            self.buffers.pop(chave_conversa, None)
            self.timers.pop(chave_conversa, None)