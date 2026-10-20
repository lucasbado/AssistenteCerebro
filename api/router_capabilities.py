from fastapi import APIRouter, HTTPException, Query
import logging
import json
import os
from pydantic import BaseModel, Field
from servicos.routine_paths import ACTIVE_PATH, DISCOVERED_PATH as DISCOVERY_FILE, REJECTED_PATH, salvar_json
from servicos.routine_discovery_service import routine_discovery_service
from servicos.routine_generator_service import routine_generator_service

router = APIRouter()
logger = logging.getLogger("CapabilitiesAPI")

ROUTINES_PATH = ACTIVE_PATH
DISCOVERED_PATH = DISCOVERY_FILE

if not os.path.exists(os.path.dirname(ROUTINES_PATH)):
    os.makedirs(os.path.dirname(ROUTINES_PATH), exist_ok=True)

class RoutineAction(BaseModel):
    alvo: str
    comando: str
    parametro: str = ""
    acao_tipo: str | None = None
    acao_parametro: str | None = None
    acao_texto: str | None = None

class RoutineTrigger(BaseModel):
    tipo: str
    pacote: str = None
    processo: str = None
    inicio: str = None
    fim: str = None
    evento: str = None

class RoutineCreate(BaseModel):
    nome: str = Field(min_length=1)
    gatilho: RoutineTrigger
    acoes: list[RoutineAction] = Field(min_length=1)
    ativa: bool = True
    cooldown_segundos: int = Field(default=3600, ge=60)
    uma_vez_por_dia: bool = False

@router.get("/discover")
async def discover_routines(min_conf: float = Query(0.8, ge=0, le=1, description="Confiança mínima para sugestões.")):
    """
    Varre o banco de dados em busca de padrões para novas rotinas (apenas sugestões).
    """
    try:
        return await routine_discovery_service.discover_suggestions(min_confidence=min_conf)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro na descoberta: {e}")

@router.post("/discover/run")
async def trigger_generation():
    """
    Força a materialização de rotinas no arquivo de descoberta.
    """
    try:
        geradas = await routine_generator_service.run_batch_generation()
        return {"status": "success", "message": "Análise de rotinas concluída.", "geradas": geradas}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro na geração: {e}")

@router.get("/discovered")
async def list_discovered():
    """Lista rotinas que a Ollie criou e estão aguardando verificação."""
    if not os.path.exists(DISCOVERED_PATH): return []
    try:
        with open(DISCOVERED_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except: return []

class RoutineNameRequest(BaseModel):
    nome: str

@router.post("/approve")
@router.post("/approve/{nome:path}")
async def approve_routine(nome: str = None, req: RoutineNameRequest = None):
    """Aprova uma rotina descoberta, movendo-a para o arquivo principal."""
    target_name = nome or (req.nome if req else None)
    if not target_name:
        raise HTTPException(status_code=400, detail="Nome da rotina não fornecido.")

    if not os.path.exists(DISCOVERED_PATH):
        raise HTTPException(status_code=404, detail="Fila de descoberta vazia.")
    
    try:
        with open(DISCOVERED_PATH, "r", encoding="utf-8") as f:
            discovered = json.load(f)
        
        # Encontra a rotina alvo (case-insensitive e strip)
        target = next((r for r in discovered if r.get("nome", "").strip().lower() == target_name.strip().lower()), None)
        if not target:
            raise HTTPException(status_code=404, detail=f"Rotina '{target_name}' não encontrada na fila.")
        
        real_name = target["nome"]

        # Carrega rotinas ativas
        active = []
        if os.path.exists(ROUTINES_PATH):
            with open(ROUTINES_PATH, "r", encoding="utf-8") as f:
                active = json.load(f)
        
        # Mantém justificativa e evidência para explicar a automação depois.
        target["ativa"] = True
        
        # Evita duplicata nas ativas
        if not any(r.get("nome", "").strip().lower() == real_name.strip().lower() for r in active):
            active.append(target)
        
        # Remove da fila de descoberta
        new_discovered = [r for r in discovered if r.get("nome", "").strip().lower() != real_name.strip().lower()]
        
        # Salva ambos os arquivos
        salvar_json(ROUTINES_PATH, active)
        salvar_json(DISCOVERED_PATH, new_discovered)
            
        return {"status": "success", "message": f"Rotina '{real_name}' ativada!"}
    except Exception as e:
        if isinstance(e, HTTPException): raise e
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/discovered")
@router.delete("/discovered/{nome:path}")
async def reject_routine(nome: str = None, req: RoutineNameRequest = None):
    """Descarta uma rotina sugerida pela Ollie."""
    target_name = nome or (req.nome if req else None)
    if not target_name:
        raise HTTPException(status_code=400, detail="Nome da rotina não fornecido.")

    if not os.path.exists(DISCOVERED_PATH):
        raise HTTPException(status_code=404, detail="Fila de descoberta vazia.")
    
    try:
        with open(DISCOVERED_PATH, "r", encoding="utf-8") as f:
            discovered = json.load(f)
            
        new_discovered = [r for r in discovered if r.get("nome", "").strip().lower() != target_name.strip().lower()]
        rejeitadas = [r for r in discovered if r.get("nome", "").strip().lower() == target_name.strip().lower()]
        if not rejeitadas:
            raise HTTPException(status_code=404, detail="Rotina não encontrada na fila.")
        historico = []
        if os.path.exists(REJECTED_PATH):
            with open(REJECTED_PATH, encoding="utf-8") as f:
                historico = json.load(f)
        salvar_json(REJECTED_PATH, historico + rejeitadas)
        
        salvar_json(DISCOVERED_PATH, new_discovered)
            
        return {"status": "success", "message": f"Rotina '{target_name}' descartada."}
    except Exception as e:
        if isinstance(e, HTTPException): raise e
        raise HTTPException(status_code=500, detail=str(e))

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
        salvar_json(ROUTINES_PATH, routines)
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
            
        salvar_json(ROUTINES_PATH, new_routines)
        return {"status": "success", "message": f"Rotina '{nome}' removida."}
    except Exception as e:
        if isinstance(e, HTTPException): raise e
        raise HTTPException(status_code=500, detail=f"Erro ao remover rotina: {e}")
