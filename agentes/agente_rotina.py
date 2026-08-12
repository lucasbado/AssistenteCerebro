"""
agentes/agente_rotina.py

Agente de Inteligência de Longo Prazo.
Analisa o perfil e o histórico de eventos para descobrir padrões complexos e rotinas.
"""
import logging
from datetime import datetime

from core.evento import EventoCanonico
from core.tipos import CategoriaEvento, TipoAcao, OrigemEvento, PrioridadeEvento
from core.kernel import kernel
from servicos.memoria_perfil import memoria_perfil

logger = logging.getLogger("AgenteRotina")

class AgenteRotina:
    """
    Este agente não reage a eventos imediatos, mas sim a gatilhos de 'reflexão'
    ou mudanças de contexto sistêmico (como chegar em casa).
    """
    async def processar(self, evento: EventoCanonico):
        if evento.categoria != CategoriaEvento.SISTEMA_COMANDO_INTERNO:
            return

        tipo_comando = evento.payload.get("tipo")
        
        if tipo_comando == "MUDANCA_LOCAL":
            await self._reagir_chegada_local(evento.payload.get("local"), evento)
        elif tipo_comando == "REFLEXAO_ROTINA":
            await self._analisar_padroes_gerais()

    async def _reagir_chegada_local(self, local: str, evento_origem: EventoCanonico):
        logger.info(f"🎭 AgenteRotina: Planejando ações para o local {local}")
        
        if local == "CASA":
            # Sugestão de descompressão
            await kernel.publicar(
                evento_origem.clonar(
                    id=None,
                    categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
                    acao=TipoAcao.INTENCAO_INTERACAO,
                    origem=OrigemEvento.IA,
                    payload={
                        "titulo": "Bem-vindo de volta!",
                        "texto": "Notei que você chegou em casa. Que tal uma música relaxante para descansar?",
                        "acao_tipo": "OPEN_APP",
                        "acao_parametro": "com.spotify.music",
                        "acao_texto": "Abrir Spotify"
                    }
                )
            )
        elif local == "TRABALHO":
            # Sugestão de foco
            await kernel.publicar(
                evento_origem.clonar(
                    id=None,
                    categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
                    acao=TipoAcao.INTENCAO_INTERACAO,
                    origem=OrigemEvento.IA,
                    payload={
                        "titulo": "Hora de Produzir",
                        "texto": "Você chegou no trabalho. Deseja que eu silencie as notificações não urgentes por 1 hora?",
                        "acao_tipo": "SISTEMA_COMANDO",
                        "acao_parametro": "ATIVAR_FOCO",
                        "acao_texto": "Ativar Foco"
                    }
                )
            )

    async def _analisar_padPatterns_gerais(self):
        """
        Lógica para ler a MemoriaPerfil e descobrir correlações para sugerir automações.
        """
        logger.info("🧠 AgenteRotina: Iniciando reflexão sobre padrões para sugerir automações...")
        
        # 1. Busca associações PC-Mobile aprendidas na memória semântica
        from servicos.catalogo_semantico import catalogo
        apps = await catalogo.memoria.obter_perfil_completo(confianca_minima=0.5)
        
        for app in apps:
            entidade = await catalogo.obter_app(app.valor)
            if entidade and entidade.atributos.get("associacoes", {}).get("pc_default"):
                programa = entidade.atributos["associacoes"]["pc_default"]["programa"]
                
                # Gera uma sugestão de regra se houver uma associação forte
                await kernel.publicar(EventoCanonico(
                    categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
                    acao=TipoAcao.INTENCAO_INTERACAO,
                    origem=OrigemEvento.IA,
                    pacote=app.valor,
                    payload={
                        "titulo": "Sugestão de Automação",
                        "texto": f"Sempre que você abre o app no celular, você usa o {programa} no PC. Quer que eu abra ele pra você?",
                        "sugestao_regra": {
                            "skill_id": "automacao",
                            "trigger_package": app.valor,
                            "action_type": "PC_COMMAND",
                            "action_parameter": programa,
                            "justificativa": "Notei que você costuma usar ambos juntos."
                        }
                    }
                ))
