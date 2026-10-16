import logging
import httpx
import os

logger = logging.getLogger("HomeAssistantService")

class HomeAssistantService:
    def __init__(self):
        # URL do Home Assistant informada pelo usuário (porta 8123 padrão)
        self.base_url = os.getenv("HA_URL", "http://192.168.15.179:8123")
        self.token = os.getenv("HA_TOKEN", "")

    async def chamar_servico(self, domain: str, service: str, entity_id: str, extra_data: dict = None) -> bool:
        if not self.token:
            logger.warning("⚠️ [HASS] Token de acesso do Home Assistant (HA_TOKEN) não configurado no .env")
            # Tenta executar sem token caso a API esteja sem autenticação na rede local
        
        url = f"{self.base_url}/api/services/{domain}/{service}"
        headers = {
            "Authorization": f"Bearer {self.token}" if self.token else "",
            "Content-Type": "application/json",
        }
        payload = {"entity_id": entity_id}
        if extra_data:
            payload.update(extra_data)

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload, headers=headers)
                if response.status_code in [200, 201]:
                    logger.info(f"🏠 [HASS] Serviço {domain}.{service} executado com sucesso em {entity_id}.")
                    return True
                else:
                    logger.error(f"❌ [HASS] Erro ao chamar serviço HASS: {response.status_code} - {response.text}")
                    return False
        except Exception as e:
            logger.error(f"💥 [HASS] Exceção ao comunicar com Home Assistant: {e}")
            return False

    async def ligar_luz(self, entity_id: str = "light.yeelink_color5_027d_light") -> bool:
        return await self.chamar_servico("light", "turn_on", entity_id)

    async def desligar_luz(self, entity_id: str = "light.yeelink_color5_027d_light") -> bool:
        return await self.chamar_servico("light", "turn_off", entity_id)

    async def toggle_luz(self, entity_id: str = "light.yeelink_color5_027d_light") -> bool:
        return await self.chamar_servico("light", "toggle", entity_id)

home_assistant_service = HomeAssistantService()
