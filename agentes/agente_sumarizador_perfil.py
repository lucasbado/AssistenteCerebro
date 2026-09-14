"""
agentes/agente_sumarizador_perfil.py

Agente responsável por analisar o perfil de usuário aprendido e gerar
um resumo em linguagem natural para o próprio usuário.
"""
import logging
from collections import defaultdict

from core.evento import EventoCanonico
from core.tipos import TipoAcao, OrigemEvento, CategoriaEvento
from core.kernel import kernel
from servicos.memoria_perfil import memoria_perfil
from servicos.llm import ServicoLLM

logger = logging.getLogger(__name__)

class AgenteSumarizadorPerfil:
    def __init__(self):
        self.llm = ServicoLLM()

    async def processar(self, evento: EventoCanonico):
        logger.info("🧠 [Sumarizador] Iniciando geração de resumo de perfil de usuário.")

        # 1. Coletar todos os dados do perfil com confiança mínima
        # Agora usamos o agregador para ter uma visão rica (incluindo rotinas de PC)
        from servicos.agregador_perfil import agregador_perfil
        dados_perfil = await agregador_perfil.obter_dados_perfil_consolidado()
        
        if not dados_perfil.get("apps") and not dados_perfil.get("artistas") and not dados_perfil.get("rotinas_pc"):
            await self._publicar_resultado("Ainda não aprendi o suficiente sobre você para criar um resumo. Use mais o seu celular!", evento)
            return

        # 2. Formatar os dados para a LLM (usando a mesma lógica do PerfilServico para consistência)
        from servicos.perfil_servico import servico_perfil
        dados_formatados = await servico_perfil._formatar_dados_para_llm(dados_perfil)

        # 3. Chamar a LLM para gerar o resumo e cards
        resultado_llm = await self.llm.resumir_perfil_usuario(dados_formatados)
        resumo = resultado_llm.get("resumo")
        cards = resultado_llm.get("cards", [])

        # 4. Publicar o resultado
        # Se houver cards, enviamos eles para que o frontend possa renderizar
        await self._publicar_resultado(resumo, evento, cards)
        logger.info(f"🧠 [Sumarizador] Resumo enviado com {len(cards)} cards de sugestão.")

    def _formatar_fatos_para_llm(self, fatos: list) -> str:
        # Método obsoleto, removido em favor da orquestração com PerfilServico
        return ""

    async def _publicar_resultado(self, resumo: str, evento_original: EventoCanonico, cards: list = None):
        """Envia o resumo e os cards para o usuário."""
        await kernel.publicar(
            evento_original.clonar(
                categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
                acao=TipoAcao.INTENCAO_INTERACAO,
                origem=OrigemEvento.IA,
                payload={
                    "titulo": "O que aprendi sobre você",
                    "texto": resumo,
                    "tipo_ws": "RESUMO_PERFIL",
                    "cards": cards or []
                }
            )
        )
