"""
api/feedback.py

Endpoint para receber feedback do usuário sobre as interações do sistema.
"""
import logging
from fastapi import APIRouter, status
from pydantic import BaseModel, Field, field_validator
from typing import Literal

from core.kernel import kernel
from core.evento import EventoCanonico
from core.tipos import CategoriaEvento, OrigemEvento, TipoAcao

router = APIRouter(prefix="/feedback", tags=["Feedback"])
logger = logging.getLogger(__name__)

class FeedbackUsuario(BaseModel):
    correlacao_id: str = Field(min_length=1)
    tipo_feedback: Literal["DISMISS", "ACTION_CLICKED", "SUGGESTION_REJECTED"]
    notificacao_id: str | None = None

    @field_validator("tipo_feedback", mode="before")
    @classmethod
    def normalizar_tipo(cls, valor):
        return valor.upper() if isinstance(valor, str) else valor

@router.post("/", status_code=status.HTTP_202_ACCEPTED)
async def receber_feedback(feedback: FeedbackUsuario):
    """
    Recebe feedback do cliente (Android) sobre uma interação e o publica
    no Kernel para que o AgenteAprendizagem possa processá-lo.
    """
    logger.info(f"👍 Recebido feedback do usuário para {feedback.correlacao_id}: {feedback.tipo_feedback}")

    evento_feedback = EventoCanonico(
        categoria=CategoriaEvento.SISTEMA_COMANDO_USUARIO,
        acao=TipoAcao.FEEDBACK_USUARIO,
        origem=OrigemEvento.USUARIO,
        pacote="br.com.ollie.interface", # Pacote do cliente
        payload=feedback.model_dump()
    )
    await kernel.publicar(evento_feedback)
    return {"status": "feedback_recebido", "id": evento_feedback.id}
