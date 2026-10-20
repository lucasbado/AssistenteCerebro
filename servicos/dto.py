from pydantic import BaseModel, ConfigDict, Field
from typing import List
from datetime import datetime

class TimelineItemDTO(BaseModel):
    """Representa um único evento na linha do tempo inteligente."""
    id: str
    timestamp: datetime
    categoria: str
    origem: str
    resumo: str = Field(..., description="Uma narrativa curta do que aconteceu.")
    icone: str = Field(..., description="Um identificador de ícone para a UI (ex: 'notificacao', 'musica').")

class TimelineDTO(BaseModel):
    """DTO principal para a tela de timeline."""
    eventos: List[TimelineItemDTO] = Field(..., serialization_alias="events")
    
    model_config = ConfigDict(populate_by_name=True)
