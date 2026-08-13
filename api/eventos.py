"""
api/eventos.py
"""
import logging
import json
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, status, Request, HTTPException
from pydantic import BaseModel, ValidationError, model_validator
from typing import Any

from core.evento import EventoCanonico
from core.tipos import CategoriaEvento, OrigemEvento
from core.motor_atencao import pipeline_atencao
from core.kernel import kernel

router = APIRouter()
logger = logging.getLogger(__name__)

# ==========================================
# CACHE DE DESDUPLICAÇÃO (ANTI-SPAM DO ANDROID)
# ==========================================
DEDUPLICATION_CACHE = OrderedDict()
CACHE_TTL_SECONDS = 10  # Ignora eventos idênticos em uma janela de 10 segundos

class RequestEvento(BaseModel):
    categoria: str
    pacote: str | None = None
    conteudo: dict[str, Any]

    @model_validator(mode="before")
    @classmethod
    def _unificar_payload(cls, data: Any) -> Any:
        """Garante compatibilidade com vários formatos de payload do cliente."""
        if isinstance(data, dict):
            # Compatibilidade com 'tipo' -> 'categoria'
            if "tipo" in data and "categoria" not in data:
                data["categoria"] = data.pop("tipo")
            
            # Compatibilidade com 'atributos' ou 'payload' -> 'conteudo'
            if "atributos" in data and "conteudo" not in data:
                data["conteudo"] = data.pop("atributos")
            elif "payload" in data and "conteudo" not in data:
                data["conteudo"] = data.pop("payload")

            # Garante um pacote padrão se não for fornecido (ex: para sensores de sistema)
            if "pacote" not in data:
                data["pacote"] = "br.com.ollie.sensor.sistema"
        return data

def _is_duplicate(evento: RequestEvento) -> bool:
    """Verifica se um evento muito parecido foi recebido recentemente."""
    now = datetime.now(timezone.utc)

    # 1. Cria uma chave estável para o evento (Ignora pequenas variações de conteúdo se necessário)
    # Aqui focamos apenas no texto se for comando do usuário
    texto_puro = evento.conteudo.get("texto", "")
    conteudo_str = json.dumps(evento.conteudo, sort_keys=True)
    
    if evento.categoria == "SISTEMA_COMANDO_USUARIO" and texto_puro:
        event_key = (evento.categoria, evento.pacote, texto_puro)
    else:
        event_key = (evento.categoria, evento.pacote, conteudo_str)

    # 2. Limpa o cache antigo (Janela de 5 segundos é suficiente para flood)
    keys_to_delete = [k for k, ts in DEDUPLICATION_CACHE.items() if now - ts > timedelta(seconds=5)]
    for key in keys_to_delete:
        del DEDUPLICATION_CACHE[key]

    # 3. Verifica se é duplicado
    if event_key in DEDUPLICATION_CACHE:
        logger.warning(f"🛡️ [Anti-Flood] Evento duplicado detectado: {event_key[:2]} - IGNORANDO.")
        return True

    # 4. Se não é duplicado, adiciona ao cache
    DEDUPLICATION_CACHE[event_key] = now
    return False

# ==========================================
# ENDPOINT PRINCIPAL DO SENSOR
# ==========================================
@router.post("/eventos", status_code=status.HTTP_202_ACCEPTED)
async def receber_evento(request: Request):
    try:
        body = await request.json()
        evento = RequestEvento.model_validate(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="JSON inválido.")
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=e.errors())

    # 0. Verificação Anti-Spam (Grito de rastreio)
    if _is_duplicate(evento):
        print(f"🛑 [GATEWAY] Evento {evento.categoria} do {evento.pacote} IGNORADO (DUPLICADO).")
        return {"status": "ignorado_como_duplicado"}

    # 1. Cria o evento oficial do Kernel
    evento_canonico = EventoCanonico(
        categoria=CategoriaEvento(evento.categoria.upper()),
        origem=OrigemEvento.ANDROID,
        pacote=evento.pacote or "br.com.ollie.sensor.sistema",
        payload=evento.conteudo
    )

    # 2. O Pipeline de Atenção avalia e enriquece o evento
    resultado_atencao = pipeline_atencao.avaliar(evento_canonico)
    if not resultado_atencao:
        print(f"🛑 [GATEWAY] Evento {evento.categoria} do {evento.pacote} BARRADO PELA ATENÇÃO.")
        return {"status": "ignorado_pelo_pipeline_de_atencao"}
    
    evento_canonico.metadados["atencao"] = resultado_atencao.model_dump()

    # RASTREADOR: O EVENTO PASSOU!
    print(f"✅ [GATEWAY] Evento {evento.categoria} APROVADO! Enviando para o Kernel...")

    # 3. Entrega ao Kernel Cognitivo (Event Bus)
    await kernel.publicar(evento_canonico)

    return {"status": "enfileirado", "id": evento_canonico.id}