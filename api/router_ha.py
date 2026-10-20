from fastapi import APIRouter, HTTPException, Response, Query
import logging
import os
from servicos.home_assistant_service import home_assistant_service
from core.kernel import kernel
from core.evento import EventoCanonico
from core.tipos import CategoriaEvento, OrigemEvento
from servicos.botoes import ToqueBotao, servico_botoes

router = APIRouter(tags=["Home Assistant"])
logger = logging.getLogger("HomeAssistantAPI")

@router.post("/webhook")
async def ha_webhook(toque: ToqueBotao, response: Response):
    """202 confirma enfileiramento; a execução do PC possui confirmação separada."""
    try:
        resultado = await servico_botoes.receber(toque, kernel)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (ValueError, OSError) as e:
        logger.error("Configuração de botões inválida: %s", type(e).__name__)
        raise HTTPException(status_code=503, detail="Configuração de botões indisponível") from e
    response.status_code = 202 if resultado["status"] == "aceito" else 200
    return resultado


@router.post("/buttons/preview")
async def prever_botao(toque: ToqueBotao):
    """Simula o vínculo, sem publicar eventos nem consumir cooldown."""
    try:
        return {"simulacao": True, **servico_botoes.prever(toque)}
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (ValueError, OSError) as e:
        raise HTTPException(status_code=503, detail="Configuração de botões indisponível") from e

async def controlar_luz(comando, entity_id, response):
    # O IP privado do HA é acessível pelo desktop, não pelo Render.
    is_cloud = os.getenv("RENDER", "false").lower() in {"true", "1", "yes"} or os.name != "nt"
    if is_cloud:
        from api.websocket import central_alertas
        if not central_alertas.estado_conexoes()["pc"]["conectado"]:
            raise HTTPException(status_code=503, detail="PC desconectado: ponte local com o Home Assistant indisponível")
        evento = EventoCanonico(categoria=CategoriaEvento.SISTEMA_COMANDO_PC,
                                origem=OrigemEvento.USUARIO, pacote="home.assistant.luz",
                                payload={"comando": comando, "parametro": entity_id})
        await kernel.publicar(evento)
        response.status_code = 202
        return {"status": "aceito", "id": evento.id, "entity_id": entity_id}
    success = await getattr(home_assistant_service, comando)(entity_id)
    if not success:
        raise HTTPException(status_code=502, detail="Home Assistant não confirmou o comando")
    return {"status": "success", "entity_id": entity_id}


ENTITY = Query(default="light.yeelink_color5_027d_light", pattern=r"^light\.[a-z0-9_]+$")


@router.post("/light/toggle")
async def api_toggle_luz(response: Response, entity_id: str = ENTITY):
    return await controlar_luz("toggle_luz", entity_id, response)

@router.post("/light/on")
async def api_ligar_luz(response: Response, entity_id: str = ENTITY):
    return await controlar_luz("ligar_luz", entity_id, response)

@router.post("/light/off")
async def api_desligar_luz(response: Response, entity_id: str = ENTITY):
    return await controlar_luz("desligar_luz", entity_id, response)
