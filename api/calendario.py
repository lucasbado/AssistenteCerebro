from typing import Literal
from uuid import UUID
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from servicos.calendario import itens_calendario
import logging

router = APIRouter(tags=['Calendário do celular'])


class Conhecido(BaseModel):
    dominio: Literal['agenda', 'tarefa']
    id: UUID


class Sincronizacao(BaseModel):
    conhecidos: list[Conhecido] = Field(default_factory=list, max_length=1000)


@router.post('/sincronizar')
async def sincronizar(pedido: Sincronizacao):
    try: return await itens_calendario([i.model_dump() for i in pedido.conhecidos])
    except Exception as erro:
        logging.getLogger(__name__).exception('Falha na projeção de calendário')
        raise HTTPException(503, detail='Não consegui atualizar as cópias no calendário agora.') from erro
