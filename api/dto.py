from pydantic import BaseModel, Field
from typing import List, Union, Literal, Annotated, Optional

from servicos.dto import TimelineItemDTO
from api.status import LLMStatusDTO

# --- Modelo para o Clima ---
class ApiWeather(BaseModel):
    temperatura: Optional[str] = None
    cidade: Optional[str] = None
    condicao: Optional[str] = None
    icon_code: Optional[str] = None

# --- Definição dos CONTEÚDOS específicos de cada Card ---

class BoasVindasContent(BaseModel):
    """Conteúdo para o card de boas-vindas."""
    titulo: str
    texto: str

class ApiRecommendation(BaseModel):
    """Modelo para recomendações acionáveis na UI."""
    texto: str
    action_label: Optional[str] = "Configurar"
    action_route: Optional[str] = "capabilities"

class ResumoCognitivoContent(BaseModel):
    """Conteúdo para o card de resumo cognitivo (Legado)."""
    texto: str
    recommendation: Optional[ApiRecommendation] = None

class InsightContent(BaseModel):
    """Conteúdo para o card de insight."""
    title: Optional[str] = "Insight"
    text: str

class DicaContent(BaseModel):
    """Conteúdo para o card de dica."""
    title: Optional[str] = "Dica do Dia"
    text: str

class PiadaContent(BaseModel):
    """Conteúdo para o card de piada."""
    title: Optional[str] = "Humor"
    text: str

class SugestaoRegraContent(BaseModel):
    """Conteúdo para o card de sugestão de regra automática."""
    skill_id: str = "automacao"
    trigger_package: str = ""
    action_type: str = "OPEN_APP"
    action_parameter: str = ""
    justificativa: Optional[str] = None

class TimelineContent(BaseModel):
    """Conteúdo para o card de timeline."""
    eventos: List[TimelineItemDTO]

# --- Definição dos CARDS individuais (com 'tipo' literal) ---

class BoasVindasCard(BaseModel):
    tipo: Literal["boas_vindas"] = "boas_vindas"
    conteudo: BoasVindasContent

class ResumoCognitivoCard(BaseModel):
    tipo: Literal["resumo_cognitivo"] = "resumo_cognitivo"
    conteudo: ResumoCognitivoContent

class InsightCard(BaseModel):
    tipo: Literal["insight"] = "insight"
    conteudo: InsightContent

class DicaCard(BaseModel):
    tipo: Literal["dica"] = "dica"
    conteudo: DicaContent

class PiadaCard(BaseModel):
    tipo: Literal["piada"] = "piada"
    conteudo: PiadaContent

class TimelineCard(BaseModel):
    tipo: Literal["timeline"] = "timeline"
    conteudo: TimelineContent

class StatusLLMCard(BaseModel):
    tipo: Literal["status_llm"] = "status_llm"
    conteudo: LLMStatusDTO # Reutiliza o DTO de status diretamente

class SugestaoRegraCard(BaseModel):
    tipo: Literal["sugestao_regra"] = "sugestao_regra"
    conteudo: SugestaoRegraContent

# --- União Discriminada de todos os tipos de cards possíveis ---
# O Pydantic usará o campo 'tipo' para validar qual card está sendo usado.
AnyCard = Annotated[
    Union[
        BoasVindasCard, 
        ResumoCognitivoCard, 
        InsightCard, 
        DicaCard, 
        PiadaCard, 
        TimelineCard, 
        StatusLLMCard,
        SugestaoRegraCard
    ],
    Field(discriminator="tipo")
]

# --- DTO Principal e final da Home ---

class HomeDTO(BaseModel):
    """
    DTO principal para a tela inicial, baseado em uma lista dinâmica de cards.
    """
    saudacao: str = Field(..., description="Uma saudação personalizada baseada no horário e contexto.")
    clima: Optional[ApiWeather] = Field(None, description="Informações meteorológicas atuais.")
    cards: List[AnyCard]
