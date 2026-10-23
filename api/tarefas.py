from typing import Literal
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, AwareDatetime
from servicos.tarefas import tarefas, ConflitoTarefa
from servicos.calendario import avisar_celular
import logging

router = APIRouter(tags=['Tarefas'])


class NovaTarefa(BaseModel):
    titulo: str = Field(min_length=1, max_length=255)
    prazo: AwareDatetime | None = None
    dia_inteiro: bool = False


class AcaoTarefa(BaseModel):
    acao: Literal['aceitar', 'concluir', 'descartar', 'adiar']
    prazo: AwareDatetime | None = None
    dia_inteiro: bool = False
    versao: int | None = Field(default=None, ge=1)


async def executar(coroutine):
    try: return await coroutine
    except ConflitoTarefa as erro: raise HTTPException(409, detail=str(erro)) from erro
    except LookupError as erro: raise HTTPException(404, detail=str(erro)) from erro
    except ValueError as erro: raise HTTPException(422, detail=str(erro)) from erro
    except Exception as erro:
        logging.getLogger(__name__).exception('Tarefas indisponíveis')
        raise HTTPException(503, detail='Suas tarefas estão indisponíveis agora. Tente novamente.') from erro


@router.get('')
async def listar(estado: Literal['abertas', 'pendente', 'sugestao', 'concluida', 'descartada'] = Query(default='abertas')):
    return await executar(tarefas.listar(estado))


@router.get('/{identificador}')
async def obter(identificador: str): return await executar(tarefas.obter(identificador))


@router.post('')
async def criar(item: NovaTarefa):
    resultado = await executar(tarefas.salvar(**item.model_dump()))
    await avisar_celular()
    return resultado


@router.patch('/{identificador}')
async def alterar(identificador: str, acao: AcaoTarefa):
    resultado = await executar(tarefas.alterar(identificador, **acao.model_dump()))
    await avisar_celular()
    return resultado
