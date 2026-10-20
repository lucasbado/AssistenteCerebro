"""Gestão das rotinas; API, descoberta e executor compartilham o catálogo."""
import logging
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from servicos.catalogo_rotinas import catalogo_rotinas
from servicos.contrato_rotinas import apresentar_rotina
from servicos.routine_discovery_service import routine_discovery_service
from servicos.routine_generator_service import routine_generator_service

router = APIRouter()
logger = logging.getLogger("CapabilitiesAPI")


class RoutineAction(BaseModel):
    alvo: str
    comando: str
    parametro: str = ""
    acao_tipo: str | None = None
    acao_parametro: str | None = None
    acao_texto: str | None = None


class RoutineTrigger(BaseModel):
    tipo: str
    pacote: str | None = None
    processo: str | None = None
    inicio: str | None = None
    fim: str | None = None
    evento: str | None = None


class RoutineCreate(BaseModel):
    nome: str = Field(min_length=1, max_length=255)
    gatilho: RoutineTrigger
    acoes: list[RoutineAction] = Field(min_length=1)
    ativa: bool = False
    cooldown_segundos: int = Field(default=3600, ge=60)
    uma_vez_por_dia: bool = False


class RoutineNameRequest(BaseModel):
    nome: str = Field(min_length=1)


class RoutineStateRequest(RoutineNameRequest):
    ativa: bool


async def _operacao(operacao):
    try:
        return await operacao
    except LookupError as e:
        raise HTTPException(404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(422, detail=str(e)) from e
    except Exception as e:
        logger.exception("Falha ao acessar catálogo de rotinas")
        raise HTTPException(503, detail="Não foi possível acessar suas rotinas. Tente atualizar a lista.") from e


@router.get("/discover")
async def discover_routines(min_conf: float = Query(0.8, ge=0, le=1)):
    return await _operacao(routine_discovery_service.discover_suggestions(min_confidence=min_conf))


@router.post("/discover/run")
async def trigger_generation():
    geradas = await _operacao(routine_generator_service.run_batch_generation())
    return {"status": "success", "message": "Análise concluída.", "geradas": geradas}


@router.get("/discovered")
async def list_discovered():
    return [apresentar_rotina(r, "descobertas") for r in await _operacao(catalogo_rotinas.listar("descobertas"))]


def _nome(nome, req):
    resultado = nome or (req.nome if req else None)
    if not resultado or not resultado.strip():
        raise HTTPException(400, detail="Informe o nome da rotina.")
    return resultado


@router.post("/approve")
@router.post("/approve/{nome:path}")
async def approve_routine(nome: str = None, req: RoutineNameRequest = None):
    return await _operacao(catalogo_rotinas.aprovar(_nome(nome, req)))


@router.delete("/discovered")
@router.delete("/discovered/{nome:path}")
async def reject_routine(nome: str = None, req: RoutineNameRequest = None):
    return await _operacao(catalogo_rotinas.rejeitar(_nome(nome, req)))


@router.get("/routines")
async def list_routines():
    return [apresentar_rotina(r, "ativas") for r in await _operacao(catalogo_rotinas.listar("ativas"))]


@router.post("/routines")
async def add_routine(routine: RoutineCreate):
    return await _operacao(catalogo_rotinas.adicionar(routine.model_dump(exclude_none=True)))


@router.patch("/routines")
async def update_routine_state(req: RoutineStateRequest):
    return await _operacao(catalogo_rotinas.definir_ativa(req.nome, req.ativa))


@router.delete("/routines")
@router.delete("/routines/{nome:path}")
async def delete_routine(nome: str = None, req: RoutineNameRequest = None):
    return await _operacao(catalogo_rotinas.rejeitar(_nome(nome, req), "ativas"))
