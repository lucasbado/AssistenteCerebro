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
from servicos.routine_discovery_service import routine_discovery_service

# Imports para a nova estrutura de cards
from .dto import (
    HomeDTO,
    ApiWeather,
    AnyCard
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

            perfil_cognitivo, timeline, status_sistema, sugestoes_descubertas = await asyncio.gather(
                safe_task(servico_perfil.gerar_perfil_cognitivo(), "perfil"),
                safe_task(servico_timeline.gerar_timeline(), "timeline"),
                safe_task(servico_status.gerar_status_sistema(), "status"),
                safe_task(routine_discovery_service.discover_suggestions(min_confidence=0.85), "discovery")
            )

            # 2. Monta a lista de cards dinamicamente (Usando dicionários para resiliência do Pydantic)
            cards: list[dict] = []

            # Adiciona sugestões descobertas automaticamente se houver
            if sugestoes_descubertas:
                for sug in sugestoes_descubertas:
                    try:
                        conteudo = sug["conteudo"]
                        if sug["tipo"] == "sugestao_regra":
                            cards.append({
                                "tipo": "sugestao_regra",
                                "conteudo": {
                                    "sugestao_regra": {
                                        "nome": str(conteudo.get("nome", "Nova Rotina")),
                                        "skill_id": str(conteudo["skill_id"]),
                                        "trigger_package": str(conteudo["trigger_package"]),
                                        "action_type": str(conteudo["action_type"]),
                                        "action_parameter": str(conteudo["action_parameter"]),
                                        "justificativa": str(conteudo.get("justificativa", ""))
                                    }
                                }
                            })
                        elif sug["tipo"] == "insight":
                             cards.append({
                                 "tipo": "insight",
                                 "conteudo": {
                                     "title": str(conteudo.get("title", "Destaque")),
                                     "text": str(conteudo.get("text", ""))
                                 }
                             })
                    except Exception as e:
                        logger.error(f"Erro ao converter sugestão descoberta: {e}")

            # Processa os cards dinâmicos gerados pela LLM (Insight, Dica, Piada, Sugestão de Regra)
            if perfil_cognitivo and hasattr(perfil_cognitivo, "cards_dinamicos") and perfil_cognitivo.cards_dinamicos:
                for card_data in perfil_cognitivo.cards_dinamicos:
                    try:
                        tipo = card_data.get("tipo")
                        raw_conteudo = card_data.get("conteudo")
                        if not raw_conteudo or not isinstance(raw_conteudo, dict): continue
                        
                        conteudo = raw_conteudo.get("conteudo", raw_conteudo) if isinstance(raw_conteudo.get("conteudo"), dict) else raw_conteudo

                        if tipo == "insight":
                            text = conteudo.get("text") or conteudo.get("texto")
                            if text:
                                cards.append({
                                    "tipo": "insight",
                                    "conteudo": {
                                        "title": str(conteudo.get("title") or conteudo.get("titulo") or "Insight"),
                                        "text": str(text)
                                    }
                                })
                        elif tipo == "dica":
                            text = conteudo.get("text") or conteudo.get("texto")
                            if text:
                                cards.append({
                                    "tipo": "dica",
                                    "conteudo": {
                                        "title": str(conteudo.get("title") or conteudo.get("titulo") or "Dica do Dia"),
                                        "text": str(text)
                                    }
                                })
                        elif tipo == "piada":
                            text = conteudo.get("text") or conteudo.get("texto")
                            if text:
                                cards.append({
                                    "tipo": "piada",
                                    "conteudo": {
                                        "title": str(conteudo.get("title") or conteudo.get("titulo") or "Humor"),
                                        "text": str(text)
                                    }
                                })
                        elif tipo == "sugestao_regra":
                            campos_obrigatorios = ["skill_id", "trigger_package", "action_type", "action_parameter"]
                            if all(k in conteudo for k in campos_obrigatorios):
                                cards.append({
                                    "tipo": "sugestao_regra",
                                    "conteudo": {
                                        "sugestao_regra": {
                                            "nome": str(conteudo.get("nome", "Nova Rotina")),
                                            "skill_id": str(conteudo["skill_id"]),
                                            "trigger_package": str(conteudo["trigger_package"]),
                                            "action_type": str(conteudo["action_type"]),
                                            "action_parameter": str(conteudo["action_parameter"]),
                                            "justificativa": str(conteudo.get("justificativa", ""))
                                        }
                                    }
                                })
                    except Exception as e:
                        logger.error(f"Erro ao processar card dinâmico {card_data.get('tipo')}: {e}")
            
            # Fallback para o resumo comportamental antigo
            if not cards and perfil_cognitivo and hasattr(perfil_cognitivo, "resumo_comportamental") and perfil_cognitivo.resumo_comportamental != "N/A":
                cards.append({
                    "tipo": "insight",
                    "conteudo": {
                        "title": "Resumo",
                        "text": str(perfil_cognitivo.resumo_comportamental)
                    }
                })

            # Card de Timeline
            if timeline and hasattr(timeline, "eventos") and timeline.eventos:
                try:
                    cards.append({
                        "tipo": "timeline",
                        "conteudo": { "eventos": timeline.eventos[:3] }
                    })
                except Exception as e:
                    logger.error(f"Erro ao adicionar card de timeline: {e}")

            # Card de Status do Sistema
            if status_sistema and hasattr(status_sistema, "llm") and status_sistema.llm:
                try:
                    cards.append({
                        "tipo": "status_llm",
                        "conteudo": status_sistema.llm
                    })
                except Exception as e:
                    logger.error(f"Erro ao adicionar card de status LLM: {e}")

            # Lógica de Boas-Vindas
            if not cards:
                cards.append({
                    "tipo": "boas_vindas",
                    "conteudo": { "titulo": "Bem-vindo ao Ollie!", "texto": "Comece a usar seu celular e em breve terei sugestões para você." }
                })

            # 3. Monta o DTO final da Home (O Pydantic validará a lista de dicts contra o AnyCard)
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
                cards=[{ "tipo": "boas_vindas", "conteudo": { "titulo": "Erro no Servidor", "texto": "Ocorreu um erro ao carregar os dados." } }]
            )

servico_home = ServicoHome()