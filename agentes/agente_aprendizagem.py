"""
agentes/agente_aprendizagem.py

Agente responsável por processar o feedback do usuário e ajustar as
memórias de longo prazo do sistema, permitindo que a assistente aprenda
com suas próprias ações.
"""
import logging

from core.evento import EventoCanonico
from core.tipos import TipoAcao, CategoriaEvento
from servicos.memoria_episodica import MemoriaEpisodica
from servicos.memoria_perfil import memoria_perfil
from servicos.obsidian_service import obsidian_service

logger = logging.getLogger(__name__)

class AgenteAprendizagem:
    def __init__(self):
        self.memoria_episodica = MemoriaEpisodica()

    async def processar(self, evento: EventoCanonico):
        feedback = evento.payload
        correlacao_id = feedback.get("correlacao_id")
        tipo_feedback = feedback.get("tipo_feedback")

        if not correlacao_id or not tipo_feedback:
            logger.warning("[Aprendizagem] Feedback recebido sem ID de correlação ou tipo.")
            return

        # 1. Recupera o evento original que gerou a notificação
        evento_original = await self.memoria_episodica.obter_evento_original_por_correlacao(correlacao_id)
        if not evento_original:
            logger.error(f"[Aprendizagem] Não foi possível encontrar o evento original para o ID de correlação {correlacao_id}")
            return

        # 2. Extrai a entidade relevante do evento original
        entidade_relevante = self._extrair_entidade_do_evento(evento_original)
        if not entidade_relevante:
            logger.debug(f"[Aprendizagem] Não foi possível extrair uma entidade para aprender do evento {evento_original.get('id')}")
            return
        
        categoria_perfil, valor_perfil = entidade_relevante

        # 3. Aplica o aprendizado na Memória de Perfil
        if tipo_feedback.upper() == "DISMISS":
            logger.info(f"🧠 [Aprendizagem] Feedback negativo (DISMISS) para '{valor_perfil}'. Diminuindo relevância.")
            await memoria_perfil.registrar_feedback_negativo(categoria_perfil, valor_perfil)
        elif tipo_feedback.upper() == "ACTION_CLICKED":
            logger.info(f"🧠 [Aprendizagem] Feedback positivo (ACTION_CLICKED) para '{valor_perfil}'. Aumentando relevância.")
            await memoria_perfil.registrar_feedback_positivo(categoria_perfil, valor_perfil)
            
            # 🌟 NOVO: Persistência de hábito confirmado no Obsidian
            obsidian_service.registrar_fato(
                "Aprendizado_Automatico", 
                f"Usuário confirmou interesse/hábito em: {valor_perfil} ({categoria_perfil})"
            )

    def _extrair_entidade_do_evento(self, evento_dict: dict) -> tuple[str, str] | None:
        """Heurística para encontrar a 'coisa' sobre a qual o usuário está dando feedback."""
        categoria = evento_dict.get("categoria")
        payload = evento_dict.get("payload", {})
        pacote = evento_dict.get("pacote")

        if categoria == CategoriaEvento.NOTIFICACAO.value and payload.get("titulo"):
            return ("CONTATO_INTERACAO", payload.get("titulo"))
        elif categoria == CategoriaEvento.APP_FOREGROUND.value and pacote:
            return ("APP_USO", pacote)
        elif categoria == CategoriaEvento.MEDIA.value and payload.get("artista"):
            return ("ARTISTA_PREFERENCIA", payload.get("artista"))
        
        return None