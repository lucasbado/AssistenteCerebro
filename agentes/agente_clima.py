"""
agentes/agente_clima.py

Agente especializado em recolher contexto ambiental e meteorológico.
"""

import logging
import httpx
from datetime import datetime
from core.evento import EventoCanonico
from core.tipos import CategoriaEvento, TipoAcao, OrigemEvento
from agentes.agente_memoria_trabalho import AgenteMemoriaTrabalho
from servicos.consciencia import consciencia
from core.kernel import kernel

logger = logging.getLogger("AgenteClima")


class AgenteClima:
    # 🔥 CORREÇÃO DO TIPO (Type Hint) AQUI:
    def __init__(self, memoria_trabalho: AgenteMemoriaTrabalho):
        self.memoria_trabalho = memoria_trabalho
        # Coordenadas configuradas por defeito (São Paulo)
        self.lat = "-23.6500"
        self.lon = "-46.7000"

    async def processar(self, evento: EventoCanonico):
        """
        Reage a eventos de batimento cardíaco (Tick) do sistema ou pedidos explícitos de contexto.
        """
        logger.info("🌤️ AgenteClima: A consultar condições meteorológicas...")

        try:
            url = f"https://api.open-meteo.com/v1/forecast?latitude={self.lat}&longitude={self.lon}&current_weather=true"

            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=10.0)
                data = response.json()

                if "current_weather" in data:
                    clima_atual = data["current_weather"]

                    condicao_str, icon_code_str = self._traduzir_codigo_clima(
                        clima_atual["weathercode"]
                    )

                    # Formatar os dados para o formato que o telemóvel espera
                    contexto_clima = {
                        "temperatura": f"{clima_atual['temperature']}",
                        "condicao": condicao_str,
                        "icon_code": icon_code_str,
                        "atualizado_em": datetime.now().isoformat(),
                    }

                    # Guarda a informação na consciência global
                    consciencia.atualizar({"clima": contexto_clima})

                    # ⛈️ PROATIVIDADE: Alerta de Chuva Imediato
                    if icon_code_str == "rain" or "chuva" in condicao_str.lower():
                        await kernel.publicar(EventoCanonico(
                            categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
                            acao=TipoAcao.INTENCAO_INTERACAO,
                            origem=OrigemEvento.SISTEMA,
                            payload={
                                "titulo": "Alerta de Chuva",
                                "texto": f"Parece que vai chover em breve ({contexto_clima['temperatura']}°C). Não esqueça o guarda-chuva se for sair!",
                                "tipo_ws": "NOTIFICACAO"
                            }
                        ))

                    # Guarda a informação na memória de curto prazo do sistema
                    if hasattr(self.memoria_trabalho, "definir_contexto"):
                        self.memoria_trabalho.definir_contexto("clima", contexto_clima)
                    else:
                        # Fallback: injetar diretamente num dicionário de contexto caso exista
                        self.memoria_trabalho.contexto_atual = contexto_clima

                    logger.info(
                        f"✅ AgenteClima: Contexto atualizado - {contexto_clima['temperatura']} ({contexto_clima['condicao']})"
                    )

        except Exception as e:
            logger.error(f"❌ AgenteClima: Erro ao buscar dados meteorológicos: {e}")

    def _traduzir_codigo_clima(self, codigo: int) -> tuple[str, str]:
        """Traduz o código da WMO para uma condição legível e um código de ícone canônico."""
        mapa_condicao = {
            0: "Céu limpo", 1: "Principalmente limpo", 2: "Parcialmente nublado", 3: "Encoberto",
            45: "Nevoeiro", 48: "Nevoeiro com geada",
            51: "Chuvisco leve", 61: "Chuva leve", 63: "Chuva moderada", 65: "Chuva forte",
            80: "Aguaceiros", 95: "Trovoada",
        }
        condicao = mapa_condicao.get(codigo, "Variável")

        # Mapeamento do código WMO para ícone canônico que o frontend entende
        if codigo in [0, 1]:
            icon_code = "clear"
        elif codigo in [61, 63, 65, 80, 51]:
            icon_code = "rain"
        elif codigo in [95]:
            icon_code = "storm"
        else:  # Nublado, nevoeiro, etc.
            icon_code = "cloud"

        return condicao, icon_code
