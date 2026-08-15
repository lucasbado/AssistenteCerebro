from fastapi import APIRouter, status, Body
from typing import Any
from servicos.consciencia import consciencia

router = APIRouter()

@router.post("/snapshot", status_code=status.HTTP_202_ACCEPTED)
async def receber_snapshot(data: dict[str, Any] = Body(...)):
    """
    Recebe um resumo do estado atual do ambiente vindo do app Android.
    """
    consciencia.atualizar(data)
    return {"status": "ok", "mensagem": "Consciência atualizada."}
