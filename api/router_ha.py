from fastapi import APIRouter, Request, HTTPException
import logging
from servicos.home_assistant_service import home_assistant_service
from core.evento import EventoCanonico
from core.tipos import CategoriaEvento, TipoAcao, OrigemEvento
from core.kernel import kernel

router = APIRouter(tags=["Home Assistant"])
logger = logging.getLogger("HomeAssistantAPI")

@router.post("/webhook")
async def ha_webhook(request: Request):
    """
    Recebe eventos e webhooks vindos do Home Assistant (ex: acionamento do botão físico no ESP).
    """
    try:
        data = await request.json()
        logger.info(f"🏠 [HASS Webhook] Evento recebido do Home Assistant: {data}")
        
        evento = EventoCanonico(
            categoria=CategoriaEvento.SISTEMA_COMANDO_IOT,
            acao=TipoAcao.NORMAL,
            origem=OrigemEvento.PC,
            payload=data,
            pacote="home.assistant"
        )
        await kernel.publicar(evento)
        return {"status": "ok", "message": "Evento IoT recebido e processado."}
    except Exception as e:
        logger.error(f"Erro no webhook do HASS: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/light/toggle")
async def api_toggle_luz(entity_id: str = "light.yeelink_color5_027d_light"):
    success = await home_assistant_service.toggle_luz(entity_id)
    return {"status": "success" if success else "error", "entity_id": entity_id}

@router.post("/light/on")
async def api_ligar_luz(entity_id: str = "light.yeelink_color5_027d_light"):
    success = await home_assistant_service.ligar_luz(entity_id)
    return {"status": "success" if success else "error", "entity_id": entity_id}

@router.post("/light/off")
async def api_desligar_luz(entity_id: str = "light.yeelink_color5_027d_light"):
    success = await home_assistant_service.desligar_luz(entity_id)
    return {"status": "success" if success else "error", "entity_id": entity_id}
