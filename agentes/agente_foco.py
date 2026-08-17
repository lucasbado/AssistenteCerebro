"""
agentes/agente_foco.py

Agente especializado em processar eventos de uso de aplicativos.
Ele combina o evento atual com a memória de perfil e semântica para
gerar insights sobre hábitos, bem-estar e sugestões contextuais.
"""

import logging
import asyncio
from datetime import datetime

from core.evento import EventoCanonico
from core.tipos import PrioridadeEvento, TipoAcao, CategoriaEvento, OrigemEvento
from core.kernel import kernel
from servicos.catalogo_semantico import catalogo
from servicos.memoria_perfil import memoria_perfil
from modelos.catalogo import EntidadeSemantica
from banco.models import PerfilUsuarioDB
from servicos.consciencia import consciencia

logger = logging.getLogger("AgenteFoco")


def _get_time_slot(timestamp: datetime) -> str:
    hour = timestamp.hour
    if 6 <= hour < 12:
        return "MANHA"
    if 12 <= hour < 18:
        return "TARDE"
    if 18 <= hour < 24:
        return "NOITE"
    return "MADRUGADA"


class AgenteFoco:
    def __init__(self):
        self._local_atual = None

    async def processar(self, evento: EventoCanonico):
        # Escuta mudanças de local enviadas pelo ContextoSistema
        if evento.categoria == CategoriaEvento.SISTEMA_COMANDO_INTERNO and evento.payload.get("tipo") == "MUDANCA_LOCAL":
            self._local_atual = evento.payload.get("local")
            return

        # MENSAGEM DE RASTREAMENTO IMEDIATA
        if evento.categoria != CategoriaEvento.APP_FOREGROUND:
            return

        print(
            f"🎯 [AGENTE FOCO] Acordei! Fui chamado pelo Kernel para analisar o app: {evento.pacote}"
        )

        pacote = evento.payload.get("pacote") or getattr(evento, "pacote", None)
        if not pacote:
            print("❌ [AGENTE FOCO] O pacote veio vazio. Abortando.")
            return

        logger.info(f"🧠 AgenteFoco: Iniciando análise para o app [{pacote}]")

        # 🚀 ATUALIZA CONSCIÊNCIA GLOBAL: App em foco
        consciencia.atualizar({
            "device_state": {"app_foreground": pacote}
        })

        # Obter dados de ambas as memórias para tomar a decisão
        entidade_app = await catalogo.obter_app(pacote)
        perfil_app = await memoria_perfil.obter_perfil_app(pacote)

        # Roda as lógicas de inferência em paralelo para maior eficiência
        await asyncio.gather(
            self._inferir_sugestao_contextual(evento, entidade_app),
            self._inferir_bem_estar(evento, entidade_app),
            self._inferir_app_favorito(evento, perfil_app),
            self._inferir_trabalho_vs_lazer(evento, entidade_app),
            self._verificar_associacao_pc(evento, entidade_app)
        )

    async def _inferir_trabalho_vs_lazer(self, evento: EventoCanonico, entidade: EntidadeSemantica | None):
        if not entidade or not self._local_atual:
            return

        categoria = entidade.atributos.get("categoria", "").lower()
        
        # Se estou no TRABALHO e abro algo de LAZER
        if self._local_atual == "TRABALHO" and any(c in categoria for c in ["social", "jogos", "entretenimento"]):
            logger.info("💡 AgenteFoco: Detectado app de lazer no trabalho.")
            # Disparar um insight suave (que aparecerá na Home)
            await kernel.publicar(
                evento.clonar(
                    id=None,
                    categoria=CategoriaEvento.INSIGHT_MEMORIA, # Para ser salvo e aparecer na Home depois
                    acao=TipoAcao.NORMAL,
                    payload={
                        "tipo": "insight",
                        "conteudo": {
                            "title": "Foco no Trabalho",
                            "text": "Notei que você costuma ser mais produtivo quando evita distrações agora. Quer ajuda para focar?"
                        }
                    }
                )
            )

    async def _inferir_sugestao_contextual(
        self, evento: EventoCanonico, entidade_app: EntidadeSemantica | None
    ):
        if not entidade_app or not entidade_app.atributos:
            logger.debug(
                "🤷‍♂️ AgenteFoco: App não catalogado. Sem sugestão contextual."
            )
            return

        categoria_app = entidade_app.atributos.get("categoria", "").lower()
        logger.info(
            f"📚 AgenteFoco: Categoria do app identificada como '{categoria_app}'"
        )

        if "navegação" in categoria_app or "mapas" in categoria_app:
            horario = _get_time_slot(evento.timestamp)
            artista_rotina = await memoria_perfil.obter_item_mais_frequente_por_periodo(
                "ARTISTA_PREFERENCIA", horario
            )

            # 🔥 A CORREÇÃO ESTÁ AQUI: Se o banco de dados estiver vazio, usamos um Fallback
            if not artista_rotina:
                logger.info(
                    f"⚠️ AgenteFoco: Memória vazia para artistas no período {horario}. Usando Fallback."
                )
                artista_rotina = "um Podcast ou AC/DC"

            logger.info(
                "💡 AgenteFoco: Gatilho de mapa ativado! Gerando notificação de música."
            )

            await kernel.publicar(
                evento.clonar(
                    categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
                    acao=TipoAcao.INTENCAO_INTERACAO,
                    origem=OrigemEvento.IA,
                    prioridade=PrioridadeEvento.NORMAL,
                    payload={
                        "titulo": "Sugestão Musical",
                        "texto": f"Vai sair? Que tal ouvir {artista_rotina} no caminho?",
                        # Contrato de Ação Dinâmica
                        "acao_tipo": "OPEN_APP",
                        "acao_parametro": "com.spotify.music",  # Ou o pacote do seu player favorito
                        "acao_texto": "Ouvir Música",
                    },
                )
            )

    async def _verificar_associacao_pc(self, evento: EventoCanonico, entidade_app: EntidadeSemantica | None):
        """
        Verifica se o aplicativo aberto tem uma ação de PC associada (aprendida
        pelo AgenteInferencia) e, em caso afirmativo, dispara o evento para executá-la.
        """
        if not entidade_app or not entidade_app.atributos:
            return

        associacao_pc = entidade_app.atributos.get("associacoes", {}).get("pc_default")
        if not associacao_pc:
            return

        programa = associacao_pc.get("programa")
        if programa:
            logger.info(f"💡 AgenteFoco: Associação de PC encontrada para '{evento.pacote}'. Acionando '{programa}'.")

            # Dispara um evento específico para o AgentePcExecutor
            await kernel.publicar(
                evento.clonar(
                    categoria=CategoriaEvento.SISTEMA_COMANDO_PC,
                    acao=TipoAcao.EXECUTAR_PROGRAMA,
                    origem=OrigemEvento.IA,
                    payload={
                        "programa": programa
                    }
                )
            )

    async def _inferir_bem_estar(
        self, evento: EventoCanonico, entidade_app: EntidadeSemantica | None
    ):
        if not entidade_app or not entidade_app.atributos:
            return

        stats = entidade_app.atributos.get("stats", {})
        if stats.get("tempo_foco_minutos", 0) > 20:
            logger.info("💡 AgenteFoco: Gatilho de Bem-estar ativado.")
            await kernel.publicar(
                evento.clonar(
                    categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
                    acao=TipoAcao.INTENCAO_INTERACAO,
                    origem=OrigemEvento.IA,
                    prioridade=PrioridadeEvento.ALTA,
                    payload={
                        "titulo": "Bem-estar",
                        "texto": f"Você está focado neste app há um bom tempo. Que tal uma pausa?",
                    },
                )
            )

    async def _inferir_app_favorito(
        self, evento: EventoCanonico, perfil_app: PerfilUsuarioDB | None
    ):
        # 🔥 Abaixei a confiança provisoriamente para 0.0 para testar com banco de dados vazio
        confianca_atual = perfil_app.confianca if perfil_app else 0.0

        if perfil_app and confianca_atual > 0.8:
            logger.info("💡 AgenteFoco: Gatilho de App Favorito ativado.")
            await kernel.publicar(
                evento.clonar(
                    categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
                    acao=TipoAcao.INTENCAO_INTERACAO,
                    origem=OrigemEvento.IA,
                    prioridade=PrioridadeEvento.BAIXA,
                    payload={
                        "titulo": "Assistente de Hábitos",
                        "texto": "Notei que este é um dos seus apps mais usados. Bom te ver por aqui!",
                    },
                )
            )
