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
        Busca os dados de perfil de uso de apps, música e rotinas aprendidas.
        """
        try:
            top_apps_bruto = await memoria_perfil.obter_top_entidades(categoria="APP_USO", limite=10)
            top_artistas_bruto = await memoria_perfil.obter_top_entidades(categoria="ARTISTA_PREFERENCIA", limite=5)
            
            # 🧠 NOVO: Coleta rotinas aprendidas (Manhã, Tarde, Noite, Madrugada)
            rotinas_aprendidas = []
            for periodo in ["MANHA", "TARDE", "NOITE", "MADRUGADA"]:
                itens = await memoria_perfil.obter_top_entidades(categoria=f"PC_ROUTINE_{periodo}", limite=3)
                for it in itens:
                    rotinas_aprendidas.append({
                        "periodo": periodo,
                        "programa": it.valor,
                        "score": it.score
                    })

            return {
                "apps": [AppInfo(pacote=item.valor, score=item.score) for item in top_apps_bruto],
                "artistas": [ArtistaInfo(nome=item.valor, score=item.score) for item in top_artistas_bruto],
                "rotinas_pc": rotinas_aprendidas
            }
        except Exception as e:
            logger.error(f"Erro ao agregar dados do perfil: {e}")
            return {"apps": [], "artistas": [], "rotinas_pc": []}

agregador_perfil = AgregadorPerfil()