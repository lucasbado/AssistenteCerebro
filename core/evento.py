from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from core.imutavel import congelar

from core.tipos import (
    CategoriaEvento,
    PrioridadeEvento,
    TipoAcao,
    OrigemEvento,
    EstadoEvento,
)

class EventoCanonico(BaseModel):
    model_config = ConfigDict(frozen=True)

    @model_validator(mode="after")
    def congelar_conteudo(self):
        object.__setattr__(self, "payload", congelar(self.payload))
        object.__setattr__(self, "metadados", congelar(self.metadados))
        return self

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    correlacao_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    categoria: CategoriaEvento
    acao: TipoAcao = TipoAcao.NORMAL
    origem: OrigemEvento
    prioridade: PrioridadeEvento = PrioridadeEvento.NORMAL
    estado: EstadoEvento = EstadoEvento.NOVO # type: ignore
    pacote: str
    
    payload: dict[str, Any] = Field(default_factory=dict)
    metadados: dict[str, Any] = Field(default_factory=dict)
    evento_pai: str | None = None

    @field_validator("id", "correlacao_id", "evento_pai", mode="before")
    @classmethod
    def force_uuid_to_str(cls, v):
        if isinstance(v, uuid.UUID):
            return str(v)
        return v

    def clonar(self, **kwargs) -> "EventoCanonico":
        dados_derivados = self.model_dump()
        
        # O novo ID é gerado, o ID atual torna-se o 'evento_pai'
        dados_derivados["id"] = str(uuid.uuid4())
        dados_derivados["evento_pai"] = self.id
        
        # O correlacao_id é preservado do original
        dados_derivados["correlacao_id"] = self.correlacao_id
        
        dados_derivados["timestamp"] = datetime.now(timezone.utc)
        
        # Atualiza com as alterações solicitadas (ex: mudança de TipoAcao)
        dados_derivados.update(kwargs)
        
        return EventoCanonico(**dados_derivados)
