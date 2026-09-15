from fastapi import APIRouter, HTTPException, Query
import logging
import json
import os
from pydantic import BaseModel
from servicos.routine_discovery_service import routine_discovery_service

router = APIRouter()
logger = logging.getLogger("CapabilitiesAPI")

ROUTINES_PATH = "D:/Programacao/AssistenteCell/config/routines.json"

class RoutineAction(BaseModel):
    alvo: str
    comando: str
    parametro: str = ""

class RoutineTrigger(BaseModel):
    tipo: str
    pacote: str = None
    processo: str = None
    inicio: str = None
    fim: str = None
    evento: str = None

class RoutineCreate(BaseModel):
    nome: str
    gatilho: RoutineTrigger
    acoes: list[RoutineAction]
    ativa: bool = True

@router.get("/discover")
async def discover_routines(min_conf: float = Query(0.8, description="Confiança mínima para sugestões.")):
    """
    Varre o banco de dados em busca de padrões para novas rotinas.
    """
    try:
        return await routine_discovery_service.discover_suggestions(min_confidence=min_conf)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro na descoberta: {e}")

@router.get("/routines")
async def list_routines():
    if not os.path.exists(ROUTINES_PATH):
        return []
    try:
        with open(ROUTINES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao ler rotinas: {e}")

@router.post("/routines")
async def add_routine(routine: RoutineCreate):
    routines = []
    if os.path.exists(ROUTINES_PATH):
        try:
            with open(ROUTINES_PATH, "r", encoding="utf-8") as f:
                routines = json.load(f)
        except: pass
    
    # Evita duplicatas pelo nome
    if any(r["nome"] == routine.nome for r in routines):
        raise HTTPException(status_code=400, detail="Já existe uma rotina com este nome.")
    
    routines.append(routine.model_dump())
    
    try:
        with open(ROUTINES_PATH, "w", encoding="utf-8") as f:
            json.dump(routines, f, indent=4)
        return {"status": "success", "message": f"Rotina '{routine.nome}' adicionada."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao salvar rotina: {e}")

@router.delete("/routines/{nome}")
async def delete_routine(nome: str):
    if not os.path.exists(ROUTINES_PATH):
        raise HTTPException(status_code=404, detail="Arquivo de rotinas não encontrado.")
    
    try:
        with open(ROUTINES_PATH, "r", encoding="utf-8") as f:
            routines = json.load(f)
        
        new_routines = [r for r in routines if r["nome"] != nome]
        
        if len(new_routines) == len(routines):
            raise HTTPException(status_code=404, detail="Rotina não encontrada.")
            
        with open(ROUTINES_PATH, "w", encoding="utf-8") as f:
            json.dump(new_routines, f, indent=4)
        return {"status": "success", "message": f"Rotina '{nome}' removida."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao remover rotina: {e}")
