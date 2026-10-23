import logging
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from servicos.mensagens import caixa_mensagens, ConflitoMensagem
from servicos.assistencia_mensagens import registrar_uso

router = APIRouter(tags=['Ajuda com mensagens'])


class Revisao(BaseModel):
    dispositivo: Literal['PC', 'MOBILE']


class AcaoMensagem(BaseModel):
    versao: int = Field(ge=1)
    acao: Literal['resolver', 'ignorar', 'salvar_rascunho', 'preparar_resposta', 'guardar_agenda', 'criar_tarefa']
    texto: str = Field(default='', max_length=2000)


async def executar(coroutine):
    try: return await coroutine
    except ConflitoMensagem as erro: raise HTTPException(409, detail=str(erro)) from erro
    except LookupError as erro: raise HTTPException(404, detail=str(erro)) from erro
    except ValueError as erro: raise HTTPException(422, detail=str(erro)) from erro
    except Exception as erro:
        logging.getLogger(__name__).exception('Falha na revisão de mensagens')
        raise HTTPException(503, detail='Não consegui concluir agora. O rascunho não foi enviado.') from erro


@router.get('')
async def listar(estado: Literal['revisar', 'resolvida', 'ignorada'] = 'revisar'):
    return await executar(caixa_mensagens.listar(estado))


@router.get('/{identificador}')
async def obter(identificador: str): return await executar(caixa_mensagens.obter(identificador))


@router.post('/revisao')
async def revisao(pedido: Revisao):
    itens = await executar(caixa_mensagens.listar())
    await registrar_uso(pedido.dispositivo)
    return itens


@router.post('/{identificador}/acao')
async def agir(identificador: str, pedido: AcaoMensagem):
    acao, versao = pedido.acao, pedido.versao
    if acao in {'resolver', 'ignorar'}:
        return await executar(caixa_mensagens.mudar_estado(identificador, versao, 'resolvida' if acao == 'resolver' else 'ignorada'))
    if acao == 'salvar_rascunho': return await executar(caixa_mensagens.salvar_rascunho(identificador, versao, pedido.texto))
    if acao == 'preparar_resposta': return await executar(caixa_mensagens.preparar(identificador, versao, pedido.texto))
    return await executar(caixa_mensagens.vincular(identificador, versao, 'agenda' if acao == 'guardar_agenda' else 'tarefa'))
