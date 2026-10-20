"""
agentes/agente_perfil.py

Agente responsável por observar eventos e registrar interações
na memória de perfil de longo prazo, construindo um modelo
estatístico do usuário.
"""
import logging
from datetime import timedelta
from servicos.tempo import utc

from core.evento import EventoCanonico
from core.tipos import CategoriaEvento
from servicos.memoria_perfil import memoria_perfil
from servicos.catalogo_semantico import catalogo

logger = logging.getLogger(__name__)

# A heurística estática KNOWN_APP_TITLES foi removida em favor de uma
# abordagem dinâmica que consulta o Catálogo Semântico para identificar apps.

class AgentePerfil:
    """
    Este agente é um dos primeiros no pipeline. Sua função é observar
    o fluxo de eventos brutos e atualizar a MemoriaPerfil com
    estatísticas de uso, formando a base do aprendizado de longo prazo
    sobre os hábitos do usuário.
    """
    def __init__(self):
        self._ultimo_foreground = None

    async def processar(self, evento: EventoCanonico):
        # Registra o uso de um app sempre que ele está em primeiro plano
        if evento.categoria == CategoriaEvento.APP_FOREGROUND:
            if evento.payload.get("heartbeat"):
                return
            if evento.pacote:
                ts = utc(evento.timestamp)
                anterior = self._ultimo_foreground
                if anterior and (ts <= anterior[1] or
                        (evento.pacote == anterior[0] and ts - anterior[1] < timedelta(minutes=30))):
                    return
                self._ultimo_foreground = (evento.pacote, ts)
                await memoria_perfil.registrar_uso_app(evento.pacote)
                # NOVO: Garante que o app seja conhecido pelo catálogo semântico.
                # A função obter_app é idempotente e irá classificar/salvar o app
                # apenas se ele for desconhecido, evitando trabalho repetido.
                logger.debug(f"Garantindo que o app '{evento.pacote}' está no catálogo.")
                await catalogo.obter_app(evento.pacote)

        # Registra a escuta de um artista
        elif evento.categoria == CategoriaEvento.MEDIA:
            artista = evento.payload.get("artista")
            if artista:
                await memoria_perfil.registrar_escuta_artista(artista, evento.timestamp)

        # Registra uma interação a partir de uma notificação
        elif evento.categoria == CategoriaEvento.NOTIFICACAO:
            remetente = evento.payload.get("titulo")
            # É necessário ter o pacote para identificar a origem da notificação
            if not remetente or not evento.pacote:
                return

            # MELHORIA: A heurística para diferenciar uma notificação de app (ex: "Instagram")
            # de uma notificação de contato (ex: "João da Silva") agora é dinâmica.
            app_entity = await catalogo.obter_app(evento.pacote)
            app_nome_canonico = None
            if app_entity and app_entity.atributos:
                app_nome_canonico = app_entity.atributos.get("nome")

            # Notificações do próprio aplicativo não são interações com contatos.
            if app_nome_canonico and remetente.lower() == app_nome_canonico.lower():
                # Uma notificação recebida não comprova abertura do aplicativo.
                return
            else:
                # Caso contrário (remetente diferente do nome do app ou app não catalogado),
                # assumimos que é uma interação com um "contato" (pessoa, grupo, etc.).
                await memoria_perfil.registrar_interacao_contato(remetente)
