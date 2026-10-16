"""
core/pipeline_atencao.py

Pipeline de Atenção Cognitiva.

Responsável por processar eventos brutos e decidir se merecem
a atenção do sistema. Ele enriquece o evento com um score de atenção
e metadados para guiar os agentes subsequentes.

Fluxo:
1. Normalização e extração de características.
2. Avaliação por um conjunto de regras (blacklist, duplicatas, spam).
3. Cálculo de um "Score de Atenção".
4. Geração de um `ResultadoAtencao` com o score e os motivos.

Eventos com score abaixo de um limiar são descartados.
"""

from __future__ import annotations

import time
import hashlib
import json
import logging
from pydantic import BaseModel, Field

from core.evento import EventoCanonico
from core.tipos import (
    CategoriaEvento,
    PrioridadeEvento,
)

logger = logging.getLogger(__name__)

class ResultadoAtencao(BaseModel):
    score: int = 0
    motivos: list[str] = Field(default_factory=list)
    pode_interagir: bool = True

class PipelineAtencao:

    def __init__(self):

        # assinatura -> timestamp
        self._historico = {}

        # pacote -> timestamp
        self._ultimo_evento_app = {}

        # pacotes ignorados
        self._blacklist = {

            "android",

            "com.android.systemui",

            "com.android.launcher",

            "com.android.providers.downloads",

            "com.google.android.permissioncontroller",

            "system",

            "sistema"

        }

        # apps que geram spam
        self._apps_midia = {

            "com.spotify.music",

            "com.google.android.youtube",

            "com.google.android.apps.youtube.music",

            "com.netflix.mediaclient"

        }

        # Títulos usados pelo próprio assistente. Notificações com esses títulos
        # são ignoradas para evitar loops de feedback.
        self._titulos_assistente = {
            "assistente",
            "ollie",
            "sugestão musical",
            "bem-estar",
            "assistente de hábitos",
            "sua rotina musical",
            "assistente musical",
            "o que aprendi sobre você",
            "teste de alerta ollie", # Título do botão de teste no app
            "agente ollie ativo", # Título da notificação persistente do serviço
        }

        # janelas

        self.janela_deduplicacao = 2 # Ajustado para 2s para capturar mensagens rápidas em sequência

        self.janela_midia = 15

    # ==========================================================
    # API
    # ==========================================================

    def avaliar(self, evento: EventoCanonico) -> ResultadoAtencao | None:
        """
        Avalia um evento e retorna um ResultadoAtencao se ele for digno de
        processamento, ou None se for descartado.
        """
        resultado = ResultadoAtencao()

        if self._blacklist_evento(evento):
            logger.debug(f"🚮 Evento {evento.id[:8]} descartado por blacklist.")
            return None

        # Adicionado para evitar loops de feedback
        if self._evento_autogerado(evento):
            logger.debug(f"🤫 Evento {evento.id[:8]} descartado por ser autogerado (loop).")
            return None

        if self._evento_duplicado(evento):
            logger.debug(f"🔁 Evento {evento.id[:8]} descartado por duplicidade.")
            return None

        if self._spam_de_midia(evento):
            resultado.pode_interagir = False
            resultado.motivos.append("SPAM_DE_MIDIA")

        self._atualizar_memoria(evento)
        self._calcular_score(evento, resultado)

        if resultado.score < 10: # Limiar mínimo de atenção
            logger.debug(f"📉 Evento {evento.id[:8]} descartado por score baixo ({resultado.score}).")
            return None

        return resultado

    # ==========================================================
    # BLACKLIST
    # ==========================================================

    def _blacklist_evento(
        self,
        evento: EventoCanonico,
    ) -> bool:

        pacote = evento.pacote.lower()

        return pacote in self._blacklist

    def _evento_autogerado(self, evento: EventoCanonico) -> bool:
        """
        Verifica se o evento é uma notificação gerada pelo próprio sistema.
        Isso é crucial para evitar loops de feedback onde o assistente lê
        suas próprias notificações.
        """
        if evento.categoria != CategoriaEvento.NOTIFICACAO:
            return False

        # Se o título da notificação corresponder a um dos títulos que o próprio
        # assistente usa, o evento é ignorado.
        titulo = evento.payload.get("titulo", "").lower()
        return titulo in self._titulos_assistente


    # ==========================================================
    # DEDUPLICAÇÃO
    # ==========================================================

    def _evento_duplicado(
        self,
        evento: EventoCanonico,
    ) -> bool:

        agora = time.time()

        assinatura = self._gerar_assinatura(evento)

        if assinatura not in self._historico:
            return False

        ultimo = self._historico[assinatura]

        return (agora - ultimo) < self.janela_deduplicacao

    # ==========================================================
    # SPAM DE MÍDIA
    # ==========================================================

    def _spam_de_midia(
        self,
        evento: EventoCanonico,
    ) -> bool:

        pacote = evento.pacote.lower()

        if pacote not in self._apps_midia:
            return False

        agora = time.time()

        ultimo = self._ultimo_evento_app.get(pacote)

        if ultimo is None:
            return False

        return (agora - ultimo) < self.janela_midia

    # ==========================================================
    # MEMÓRIA CURTA
    # ==========================================================

    def _atualizar_memoria(
        self,
        evento: EventoCanonico,
    ):

        agora = time.time()

        assinatura = self._gerar_assinatura(evento)

        self._historico[assinatura] = agora

        self._ultimo_evento_app[evento.pacote.lower()] = agora

    # ==========================================================
    # SCORING
    # ==========================================================

    def _calcular_score(self, evento: EventoCanonico, resultado: ResultadoAtencao):
        """Calcula o score de atenção inicial para um evento."""
        match evento.categoria:
            case CategoriaEvento.NOTIFICACAO:
                resultado.score += 50
                resultado.motivos.append("TIPO_NOTIFICACAO")
            case CategoriaEvento.MEDIA:
                resultado.score += 20
                resultado.motivos.append("TIPO_MEDIA")
            case CategoriaEvento.APP_FOREGROUND:
                resultado.score += 30
                resultado.motivos.append("TIPO_APP_FOREGROUND")
            case _:
                resultado.score += 10
                resultado.motivos.append("TIPO_GENERICO")

    # ==========================================================
    # HASH
    # ==========================================================

    def _gerar_assinatura(
        self,
        evento: EventoCanonico,
    ) -> str:
        """
        Gera uma assinatura única e estável para um evento, focando no conteúdo
        relevante para evitar duplicatas causadas por metadados voláteis.
        """
        categoria = evento.categoria
        pacote = evento.pacote
        payload = evento.payload

        # Cria uma assinatura baseada no conteúdo significativo, ignorando campos voláteis.
        if categoria == CategoriaEvento.NOTIFICACAO:
            # Para notificações, o conteúdo principal é quem enviou e o que disse.
            titulo = payload.get("titulo", "")
            texto_notif = payload.get("texto", "")
            texto_assinatura = f"{categoria.value}|{pacote}|{titulo}|{texto_notif}"
        elif categoria == CategoriaEvento.MEDIA:
            # Para mídia, é sobre o artista e a música.
            artista = payload.get("artista", "")
            musica = payload.get("musica", "")
            texto_assinatura = f"{categoria.value}|{pacote}|{artista}|{musica}"
        else:
            # Para outros eventos, usamos um hash do payload ordenado, que é mais robusto.
            payload_str = json.dumps(payload, sort_keys=True)
            texto_assinatura = f"{categoria.value}|{pacote}|{payload_str}"

        return hashlib.sha1(
            texto_assinatura.encode()
        ).hexdigest()


pipeline_atencao = PipelineAtencao()