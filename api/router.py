from fastapi import APIRouter, Request
import logging
from .dto import HomeDTO
from .servico import servico_home

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get(
    "",
    response_model=HomeDTO,
    summary="Agrega todas as informações para a tela inicial",
    tags=["Home"]
)
async def get_home(request: Request):
    """
    Endpoint principal para o cliente. Retorna um objeto consolidado com
    tudo o que é necessário para renderizar a tela inicial do app.
    """
    logger.info("Recebida requisição para GET /home")
    return await servico_home.gerar_home(request)