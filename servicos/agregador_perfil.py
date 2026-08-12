import logging
from pydantic import BaseModel
from typing import List

from servicos.memoria_perfil import memoria_perfil

logger = logging.getLogger(__name__)

class AppInfo(BaseModel):
    pacote: str
    score: int

class ArtistaInfo(BaseModel):
    nome: str
    score: int

class AgregadorPerfil:
    """
    Responsável por buscar e consolidar dados brutos de diferentes
    memórias para construir uma visão unificada do perfil do usuário.
    """

    async def obter_dados_perfil_consolidado(self) -> dict:
        """
        Busca os dados de perfil de uso de apps e música.
        Assume que memoria_perfil.obter_top_entidades retorna uma lista de objetos com 'valor' e 'score'.
        """
        try:
            top_apps_bruto = await memoria_perfil.obter_top_entidades(categoria="APP_USO", limite=5)
            # Corrigido: A categoria correta é ARTISTA_PREFERENCIA (conforme definido em memoria_perfil.py)
            top_artistas_bruto = await memoria_perfil.obter_top_entidades(categoria="ARTISTA_PREFERENCIA", limite=5)

            return {
                "apps": [AppInfo(pacote=item.valor, score=item.score) for item in top_apps_bruto],
                "artistas": [ArtistaInfo(nome=item.valor, score=item.score) for item in top_artistas_bruto],
            }
        except Exception as e:
            logger.error(f"Erro ao agregar dados do perfil: {e}")
            return {"apps": [], "artistas": []}

agregador_perfil = AgregadorPerfil()