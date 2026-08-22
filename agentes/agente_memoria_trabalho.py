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
        # O buffer agora armazena uma lista de tuplas (remetente, texto, tipo_conteudo)
        self.buffers: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
        self.timers: dict[str, asyncio.Task] = {}

    async def processar(self, evento: EventoCanonico):
        # Este agente agora é o responsável por agrupar notificações de texto
        if evento.categoria != CategoriaEvento.NOTIFICACAO:
            return

        texto = evento.payload.get("texto")
        remetente = evento.payload.get("titulo")
        tipo_cont = evento.payload.get("tipo_conteudo", "MSG")

        if not texto or not remetente:
            return

        # A CHAVE DE AGRUPAMENTO AGORA É APENAS O PACOTE DO APP.
        chave_conversa = evento.pacote
        logger.debug(f"🧠 [MemoriaTrabalho] Recebida mensagem ({tipo_cont}) de '{remetente}' no '{chave_conversa}'.")

        # Cancela o timer anterior se houver um, pois uma nova mensagem chegou
        if chave_conversa in self.timers:
            self.timers[chave_conversa].cancel()

        # Adiciona a nova tupla ao buffer da conversa
        self.buffers[chave_conversa].append((remetente, texto, tipo_cont))

        # Cria um novo timer para despachar a conversa agrupada
        self.timers[chave_conversa] = asyncio.create_task(
            self._despachar_agrupado(chave_conversa, evento)
        )

    async def _despachar_agrupado(self, chave_conversa: str, evento_original: EventoCanonico):
        try:
            await asyncio.sleep(DEBOUNCE_SECONDS)

            # VERIFICAÇÃO DE SEGURANÇA (ANTI-RACE CONDITION):
            if self.timers.get(chave_conversa) is not asyncio.current_task():
                return 

            # O buffer agora contém tuplas (remetente, texto, tipo_cont)
            mensagens_agrupadas = self.buffers.pop(chave_conversa, [])
            self.timers.pop(chave_conversa, None)
            if not mensagens_agrupadas: return

            # Remove duplicatas exatas preservando a ordem
            mensagens_unicas = list(dict.fromkeys(mensagens_agrupadas))

            logger.info(f"🧠 [MemoriaTrabalho] Debounce finalizado para '{chave_conversa}'. Pré-processando {len(mensagens_unicas)} notificações.")

            # 1. Agrupa as mensagens por remetente e tipo
            dados_por_remetente = defaultdict(lambda: {"mensagens": [], "posts": 0})
            for remetente, texto, tipo in mensagens_unicas:
                if tipo == "POST":
                    dados_por_remetente[remetente]["posts"] += 1
                else:
                    dados_por_remetente[remetente]["mensagens"].append(texto)

            # 2. Gera um resumo em texto inteligente
            partes_resumo = []
            nome_app = chave_conversa.split('.')[-1].capitalize() if '.' in chave_conversa else "Sistema"
            if "whatsapp" in chave_conversa.lower(): nome_app = "WhatsApp"
            if "instagram" in chave_conversa.lower(): nome_app = "Instagram"
            if "tiktok" in chave_conversa.lower() or "musically" in chave_conversa.lower(): nome_app = "TikTok"

            for remetente, dados in dados_por_remetente.items():
                textos = dados["mensagens"]
                posts = dados["posts"]
                
                info_remetente = []
                if textos:
                    s = "s" if len(textos) > 1 else ""
                    trecho = f" (falando sobre '{textos[0][:30]}...')" if len(textos) == 1 else ""
                    info_remetente.append(f"{len(textos)} mensagem{s}{trecho}")
                
                if posts:
                    s = "s" if posts > 1 else ""
                    termo = "vídeo" if "tiktok" in nome_app.lower() else "post"
                    info_remetente.append(f"{posts} novo{s} {termo}{s}")
                
                if info_remetente:
                    res_rem = " e ".join(info_remetente)
                    partes_resumo.append(f"{remetente} no {nome_app} tem {res_rem}")

            if not partes_resumo:
                return

            resumo_final_str = ". ".join(partes_resumo) + "."
            logger.info(f"🧠 [MemoriaTrabalho] Pré-resumo gerado: {resumo_final_str}")

            # 3. Recupera o contexto histórico da conversa
            contexto_historico = await memoria_trabalho.obter_contexto(chave_conversa) or []

            # 4. Atualiza a memória de trabalho persistente com as novas mensagens (fire-and-forget)
            mensagens_novas_formatadas = [f"{r}: {t} ({tp})" for r, t, tp in mensagens_unicas]
            asyncio.create_task(memoria_trabalho.atualizar_conversa(chave_conversa, mensagens_novas_formatadas))

            # O payload agora inclui o pré-resumo detalhado e as mensagens completas
            payload_agrupado = {
                "remetente": f"{len(mensagens_unicas)} notificações",
                "mensagens": mensagens_novas_formatadas,
                "conversa_completa": "\n".join([f"{r}: {t}" for r, t, tp in mensagens_unicas]),
                "pre_resumo": resumo_final_str,
                "contexto_historico": contexto_historico
            }
            await kernel.publicar(evento_original.clonar(acao=TipoAcao.INTENCAO_RACIOCINIO, payload=payload_agrupado))
        except asyncio.CancelledError:
            logger.debug(f"🧠 [MemoriaTrabalho] Debounce para '{chave_conversa}' resetado.")
        except Exception as e:
            logger.error(f"🧠 [MemoriaTrabalho] Erro no despacho agrupado: {e}")
            self.buffers.pop(chave_conversa, None)
            self.timers.pop(chave_conversa, None)