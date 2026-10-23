import logging
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, AwareDatetime
from servicos.agenda import agenda
from servicos.calendario import avisar_celular

router = APIRouter(tags=['Agenda'])


class NovoItem(BaseModel):
    tipo: Literal['compromisso', 'lembrete', 'alarme'] = 'compromisso'
    titulo: str = Field(min_length=1, max_length=255)
    inicio: AwareDatetime
    dia_inteiro: bool = False
    antecedencia_minutos: int = Field(default=0, ge=0, le=10080)


class EstadoItem(BaseModel):
    estado: Literal['agendado', 'cancelado', 'concluido']
    antecedencia_minutos: int | None = Field(default=None, ge=0, le=10080)


async def operacao(coroutine):
    try: return await coroutine
    except LookupError as erro: raise HTTPException(404, detail=str(erro)) from erro
    except ValueError as erro: raise HTTPException(422, detail=str(erro)) from erro
    except Exception as erro:
        logging.getLogger(__name__).exception('Agenda indisponível')
        raise HTTPException(503, detail='A agenda está indisponível agora. Tente novamente.') from erro


@router.get('')
async def listar(): return await operacao(agenda.listar())


@router.get('/{identificador}')
async def obter(identificador: str): return await operacao(agenda.obter(identificador))


@router.post('')
async def criar(item: NovoItem):
    resultado = await operacao(agenda.salvar(**item.model_dump(), confirmar=True))
    await avisar_celular()
    return resultado


@router.patch('/{identificador}')
async def alterar(identificador: str, estado: EstadoItem):
    resultado = await operacao(agenda.alterar_estado(identificador, estado.estado, estado.antecedencia_minutos))
    await avisar_celular()
    return resultado
