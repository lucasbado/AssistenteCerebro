import asyncio
import logging
from datetime import datetime
from fastapi import Request

# Configuração de Log
logger = logging.getLogger(__name__)

# Importa os serviços existentes que serão orquestrados
from servicos.perfil_servico import servico_perfil
from servicos.servico import servico_timeline
from api.status import servico_status

# Imports para a nova estrutura de cards
from .dto import (
    HomeDTO,
    ApiWeather,
    AnyCard,
    ApiRecommendation,
    BoasVindasCard, BoasVindasContent,
    ResumoCognitivoCard, ResumoCognitivoContent,
    InsightCard, InsightContent,
    DicaCard, DicaContent,
    PiadaCard, PiadaContent,
    SugestaoRegraCard, SugestaoRegraContent,
    TimelineCard, TimelineContent,
    StatusLLMCard
)

class ServicoHome:
    """
    Orquestra múltiplos serviços para construir a resposta agregada
    para o endpoint /home, agora baseado em um sistema dinâmico de cards.
    """
    def _gerar_saudacao(self) -> str:
        """Gera uma saudação baseada no período do dia."""
        current_hour = datetime.now().hour
        if 5 <= current_hour < 12:
            return "Bom dia!"
        elif 12 <= current_hour < 18:
            return "Boa tarde!"
        else:
            return "Boa noite!"

    async def gerar_home(self, request: Request) -> HomeDTO:
        """
        Chama outros serviços em paralelo e transforma seus resultados em uma
        lista de 'cards' que compõem a tela inicial.
        """
        try:
            # 1. Executa as chamadas de serviço em paralelo para máxima eficiência
            # --- LÓGICA DO CLIMA ---
            try:
                memoria = request.app.state.agente_memoria_trabalho
                clima_interno = getattr(memoria, 'contexto_atual', None)
                weather_dto = None
                if clima_interno and clima_interno.get("temperatura"):
                    weather_dto = ApiWeather(
                        temperatura=str(clima_interno.get("temperatura")),
                        cidade=clima_interno.get("cidade", "São Paulo"),
                        condicao=clima_interno.get("condicao", "Desconhecido"),
                        icon_code=clima_interno.get("icon_code", "sun")
                    )
            except Exception as e:
                logger.error(f"Erro ao obter clima: {e}")
                weather_dto = None
            # --- FIM DA LÓGICA DO CLIMA ---

            async def safe_task(coro, task_name):
                try:
                    return await coro
                except Exception as e:
                    logger.error(f"Erro na task {task_name}: {e}", exc_info=True)
                    return None

            perfil_cognitivo, timeline, status_sistema = await asyncio.gather(
                safe_task(servico_perfil.gerar_perfil_cognitivo(), "perfil"),
                safe_task(servico_timeline.gerar_timeline(), "timeline"),
                safe_task(servico_status.gerar_status_sistema(), "status")
            )

            # 2. Monta a lista de cards dinamicamente
            cards: list[AnyCard] = []

            # Processa os cards dinâmicos gerados pela LLM (Insight, Dica, Piada, Sugestão de Regra)
            if perfil_cognitivo and hasattr(perfil_cognitivo, "cards_dinamicos") and perfil_cognitivo.cards_dinamicos:
                for card_data in perfil_cognitivo.cards_dinamicos:
                    try:
                        tipo = card_data.get("tipo")
                        raw_conteudo = card_data.get("conteudo")
                        if not raw_conteudo or not isinstance(raw_conteudo, dict): continue
                        
                        # Suporte a campos alternativos ou aninhamento excessivo vindo da LLM
                        conteudo = raw_conteudo.get("conteudo", raw_conteudo) if isinstance(raw_conteudo.get("conteudo"), dict) else raw_conteudo

                        if tipo == "insight":
                            text = conteudo.get("text") or conteudo.get("texto")
                            if text:
                                cards.append(InsightCard(conteudo=InsightContent(
                                    title=conteudo.get("title") or conteudo.get("titulo") or "Insight",
                                    text=text
                                )))
                        elif tipo == "dica":
                            text = conteudo.get("text") or conteudo.get("texto")
                            if text:
                                cards.append(DicaCard(conteudo=DicaContent(
                                    title=conteudo.get("title") or conteudo.get("titulo") or "Dica do Dia",
                                    text=text
                                )))
                        elif tipo == "piada":
                            text = conteudo.get("text") or conteudo.get("texto")
                            if text:
                                cards.append(PiadaCard(conteudo=PiadaContent(
                                    title=conteudo.get("title") or conteudo.get("titulo") or "Humor",
                                    text=text
                                )))
                        elif tipo == "sugestao_regra":
                            # Validação rigorosa para evitar ValidationError do Pydantic
                            campos_obrigatorios = ["skill_id", "trigger_package", "action_type", "action_parameter"]
                            if all(k in conteudo for k in campos_obrigatorios):
                                cards.append(SugestaoRegraCard(conteudo=SugestaoRegraContent(
                                    skill_id=str(conteudo["skill_id"]),
                                    trigger_package=str(conteudo["trigger_package"]),
                                    action_type=str(conteudo["action_type"]),
                                    action_parameter=str(conteudo["action_parameter"]),
                                    justificativa=conteudo.get("justificativa")
                                )))
                            else:
                                logger.warning(f"Card sugestao_regra malformado (hallucination) ignorado: {conteudo}")
                    except Exception as e:
                        logger.error(f"Erro ao processar card dinâmico {card_data.get('tipo')}: {e}")
            
            # Fallback para o resumo comportamental antigo se não houver cards novos
            if not cards and perfil_cognitivo and perfil_cognitivo.resumo_comportamental and perfil_cognitivo.resumo_comportamental != "N/A":
                cards.append(
                    InsightCard(
                        conteudo=InsightContent(
                            title="Resumo",
                            text=perfil_cognitivo.resumo_comportamental
                        )
                    )
                )

            # Card de Timeline
            if timeline and timeline.eventos:
                cards.append(TimelineCard(conteudo=TimelineContent(eventos=timeline.eventos[:3])))

            # 2.1. Lógica de "Boas-Vindas" para novos usuários
            if not cards:
                cards.append(
                    BoasVindasCard(
                        conteudo=BoasVindasContent(
                            titulo="Bem-vindo ao Ollie!",
                            texto="Comece a usar seu celular e em breve terei sugestões para você."
                        )
                    )
                )
            
            # 2.2. Card de Status do Sistema
            if status_sistema and status_sistema.llm:
                cards.append(StatusLLMCard(conteudo=status_sistema.llm))

            # 3. Monta o DTO final da Home
            return HomeDTO(
                saudacao=self._gerar_saudacao(),
                clima=weather_dto,
                cards=cards
            )
        except Exception as e:
            logger.error(f"ERRO CRÍTICO ao gerar Home: {e}", exc_info=True)
            return HomeDTO(
                saudacao="Olá (Modo de Segurança)",
                clima=None,
                cards=[BoasVindasCard(conteudo=BoasVindasContent(titulo="Erro no Servidor", texto="Ocorreu um erro ao carregar os dados. Verifique a conexão."))]
            )

servico_home = ServicoHome()