import logging
import httpx
import os
import asyncio
import re

logger = logging.getLogger("HomeAssistantService")

class HomeAssistantService:
    def __init__(self):
        # Usa o endereço configurado, inclusive quando há proxy na porta 80/443.
        self.base_url = os.getenv("HA_URL", "").rstrip("/")
        self.token = os.getenv("HA_TOKEN", "")

    async def chamar_servico(self, domain: str, service: str, entity_id: str, extra_data: dict = None) -> bool:
        if not self.token or not self.base_url:
            logger.warning("[HASS] Configure HA_URL e HA_TOKEN no PC que acessa a rede local")
            return False
        
        url = f"{self.base_url}/api/services/{domain}/{service}"
        headers = {
            "Content-Type": "application/json",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

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
                    logger.error("[HASS] Serviço recusado (HTTP %s)", response.status_code)
                    return False
        except Exception as e:
            logger.error("[HASS] Falha de conexão: %s", type(e).__name__)
            return False

    async def verificar_conexao(self):
        if not self.base_url or not self.token:
            return {"conectado": False, "motivo": "configuracao_ausente"}
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resposta = await client.get(self.base_url + "/api/",
                                           headers={"Authorization": f"Bearer {self.token}"})
            return {"conectado": resposta.status_code == 200, "http_status": resposta.status_code}
        except httpx.HTTPError:
            return {"conectado": False, "motivo": "inacessivel"}

    async def feedback_audio(self, modo):
        if modo not in {'VOLUME', 'SINCRONIZACAO'}:
            raise ValueError('Modo de áudio inválido')
        try:
            return await asyncio.wait_for(self.chamar_servico('script', 'turn_on', 'script.ollie_feedback_visual',
                {'variables': {'modo_controle': modo}}), timeout=2)
        except TimeoutError:
            logger.warning('[HASS] Feedback de áudio sem confirmação; comando não será repetido')
            return False

    async def controlar_luz_confirmada(self, acao, entity_id):
        return await asyncio.wait_for(self._controlar_luz_confirmada(acao, entity_id), timeout=15)

    async def _controlar_luz_confirmada(self, acao, entity_id):
        if acao not in {"ligar", "desligar", "alternar", "consultar"} or not re.fullmatch(r"light\.[a-z0-9_]+", entity_id):
            raise ValueError("Ação ou luz inválida")
        if not self.base_url or not self.token:
            raise RuntimeError("Home Assistant não configurado nesta ponte")
        headers = {"Authorization": f"Bearer {self.token}"}
        async with httpx.AsyncClient(timeout=5) as client:
            url_estado = f"{self.base_url}/api/states/{entity_id}"
            antes = await client.get(url_estado, headers=headers)
            antes.raise_for_status()
            estado = antes.json().get("state")
            if estado not in {"on", "off"}:
                raise RuntimeError("A luz está indisponível no Home Assistant")
            esperado = {"ligar": "on", "desligar": "off"}.get(acao)
            if acao == "alternar":
                esperado = "off" if estado == "on" else "on"
            if acao != "consultar" and estado != esperado:
                # Alternância também vira um estado explícito, evitando um segundo toggle por retentativa.
                servico = "turn_on" if esperado == "on" else "turn_off"
                resposta = await client.post(f"{self.base_url}/api/services/light/{servico}",
                                            headers=headers, json={"entity_id": entity_id})
                resposta.raise_for_status()
                for tentativa in range(5):
                    atual = await client.get(url_estado, headers=headers)
                    atual.raise_for_status()
                    estado = atual.json().get("state")
                    if estado == esperado:
                        break
                    if tentativa < 4:
                        await asyncio.sleep(0.3)
                if estado != esperado:
                    raise RuntimeError("Home Assistant não confirmou o estado solicitado")
        return {"entity_id": entity_id, "state": estado}

    async def ligar_luz(self, entity_id: str = "light.yeelink_color5_027d_light") -> bool:
        return await self.chamar_servico("light", "turn_on", entity_id)

    async def desligar_luz(self, entity_id: str = "light.yeelink_color5_027d_light") -> bool:
        return await self.chamar_servico("light", "turn_off", entity_id)

    async def toggle_luz(self, entity_id: str = "light.yeelink_color5_027d_light") -> bool:
        return await self.chamar_servico("light", "toggle", entity_id)

home_assistant_service = HomeAssistantService()
