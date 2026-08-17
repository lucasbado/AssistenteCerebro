"""
agentes/agente_contexto_sistema.py

Agente especializado em processar eventos de contexto do sistema operacional,
como localização, conectividade e outros sensores.
"""
import logging

from core.evento import EventoCanonico
from core.tipos import CategoriaEvento, TipoAcao, OrigemEvento
from core.kernel import kernel
from servicos.memoria_perfil import memoria_perfil
from servicos.consciencia import consciencia

logger = logging.getLogger(__name__)

class AgenteContextoSistema:
    """
    Este agente observa os dados brutos dos sensores do sistema (enviados pelo Android)
    e os registra na memória de perfil e na consciência situacional.
    """
    def __init__(self):
        self._ultimo_local = None

    async def processar(self, evento: EventoCanonico):
        payload = evento.payload
        logger.info(f"🧠 [Contexto Sistema] Processando dados de sensores: {list(payload.keys())}")

        # 🚀 ATUALIZA CONSCIÊNCIA GLOBAL
        # Transforma o payload do Android em device_state
        consciencia.atualizar({
            "device_state": payload
        })

        # 1. Processar informações de Wi-Fi
        wifi_info = payload.get("wifi")
        local_inferido = None

        if isinstance(wifi_info, dict):
            ssid = wifi_info.get("ssid")
            # Ignora SSIDs padrões ou ocultos que não agregam valor
            if ssid and ssid not in ["<unknown ssid>", "HIDDEN_BY_OS"]:
                logger.info(f"💾 Registrando conexão com Wi-Fi: {ssid}")
                await memoria_perfil.registrar_conexao_wifi(ssid)
                
                # Inferência simples de local baseada no SSID (pode ser expandida com ML)
                if "casa" in ssid.lower() or "home" in ssid.lower():
                    local_inferido = "CASA"
                elif "office" in ssid.lower() or "work" in ssid.lower() or "empresa" in ssid.lower():
                    local_inferido = "TRABALHO"

        # 2. Processar informações de Localização
        location_info = payload.get("location")
        if isinstance(location_info, dict) and "lat" in location_info:
            lat = location_info.get('lat')
            lon = location_info.get('lon')
            logger.info(f"📍 Localização recebida: Lat={lat}, Lon={lon}")
            # Futuro: Clusterização de coordenadas para detectar locais frequentes

        # 3. Disparar mudança de contexto se o local mudou
        if local_inferido and local_inferido != self._ultimo_local:
            logger.info(f"🌎 Mudança de Local Detectada: {local_inferido}")
            self._ultimo_local = local_inferido
            
            await kernel.publicar(
                EventoCanonico(
                    categoria=CategoriaEvento.SISTEMA_COMANDO_INTERNO,
                    acao=TipoAcao.EVENTO_COMPLEXO,
                    origem=OrigemEvento.SISTEMA,
                    pacote="sistema.contexto",
                    payload={
                        "tipo": "MUDANCA_LOCAL",
                        "local": local_inferido
                    }
                )
            )
