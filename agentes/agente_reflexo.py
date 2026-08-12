"""
agentes/agente_reflexo.py

Camada 2: Reflexo de Notificações.

Este agente tem uma única responsabilidade: analisar eventos de NOTIFICACAO
e decidir se eles são simples o suficiente para serem descartados ou se são
complexos (contêm texto) e devem ser escalados para a camada de Raciocínio (LLM).
"""

import logging

from core.evento import EventoCanonico
from core.tipos import TipoAcao, CategoriaEvento
from core.kernel import kernel

logger = logging.getLogger(__name__)

class AgenteReflexo:
    async def processar(self, evento: EventoCanonico):
        # 🌟 NOVO: Comandos diretos do usuário são sempre complexos (merecem LLM)
        if evento.categoria == CategoriaEvento.SISTEMA_COMANDO_USUARIO:
            logger.info(f"💬 [Reflexo] Comando do usuário recebido. Elevando para complexo.")
            await kernel.publicar(evento.clonar(acao=TipoAcao.EVENTO_COMPLEXO))
            return

        # O filtro do Kernel já garante que este agente só recebe eventos de NOTIFICACAO.
        remetente = evento.payload.get("titulo")
        texto = evento.payload.get("texto")

        if not remetente:
            logger.debug(f"[Reflexo] Ignorando notificação sem remetente: {evento.id[:8]}")
            return

        # A filosofia do sistema é clara: se um evento é complexo, ele deve
        # ser analisado pelo "córtex" (LLM). Uma notificação com texto é, por
        # definição, complexa. Este agente, como um "reflexo", não deve tentar
        # interpretá-la. Essa responsabilidade foi delegada ao AgenteMemoriaTrabalho,
        # que agrupa as mensagens para dar contexto à IA antes de escalar.
        if texto:
            # Ação para notificações com texto agora é do AgenteMemoriaTrabalho.
            # Simplesmente retornamos para que o AgenteReflexo não faça nada,
            # pois o AgenteMemoriaTrabalho já está cuidando deste evento em paralelo.
            return 
        else:
            # Se não há texto, não há o que a LLM interpretar. O agente de reflexo
            # termina sua análise aqui. Não há ação a ser tomada.
            logger.debug(f"✅ [Reflexo] Notificação de '{remetente}' sem texto. Nenhuma ação necessária. Evento: {evento.id[:8]}")
