import logging
from typing import List

from .agregador_perfil import agregador_perfil, AppInfo, ArtistaInfo
from .perfil_dto import PerfilCognitivoDTO, HabitoAppDTO, PreferenciaMusicalDTO
from servicos.llm import ServicoLLM
from servicos.catalogo_semantico import catalogo
from servicos.obsidian_service import obsidian_service

logger = logging.getLogger(__name__)

class ServicoPerfil:
    """
    Orquestra a criação do Perfil Cognitivo, transformando dados
    agregados em uma narrativa e DTOs de alto nível.
    """
    def __init__(self, llm_service: ServicoLLM):
        self.llm = llm_service

    async def _formatar_dados_para_llm(self, dados_agregados: dict) -> str:
        """Converte os dados brutos em uma string de fatos para a LLM."""
        fatos = []
        total_app_score = sum(app.score for app in dados_agregados.get("apps", []))
        if total_app_score > 0:
            fatos.append("Fatos sobre uso de aplicativos:")
            for app in dados_agregados["apps"]:
                percentual = (app.score / total_app_score) * 100
                fatos.append(f"- Usa o app '{app.pacote}' com {percentual:.1f}% de frequência relativa.")

        total_artista_score = sum(artista.score for artista in dados_agregados.get("artistas", []))
        if total_artista_score > 0:
            fatos.append("\nFatos sobre preferências musicais:")
            for artista in dados_agregados["artistas"]:
                percentual = (artista.score / total_artista_score) * 100
                fatos.append(f"- Ouve o artista '{artista.nome}' com {percentual:.1f}% de frequência relativa.")

        return "\n".join(fatos) if fatos else "Nenhum dado de perfil disponível para análise."

    async def gerar_perfil_cognitivo(self) -> PerfilCognitivoDTO:
        """Ponto de entrada principal para gerar o perfil completo."""
        dados_agregados = await agregador_perfil.obter_dados_perfil_consolidado()
        conhecimento_obsidian = obsidian_service.listar_conhecimento_essencial()

        texto_para_llm = await self._formatar_dados_para_llm(dados_agregados)
        # Mescla com Obsidian para contexto na análise do perfil
        texto_para_llm += f"\n\nContexto de Longo Prazo (Obsidian):\n{conhecimento_obsidian}"

        try:
            resumo_dict = await self.llm.resumir_perfil_usuario(texto_para_llm)
        except Exception as e:
            logger.error(f"Falha ao chamar LLM para resumo de perfil: {e}")
            resumo_dict = {"resumo": "Não foi possível gerar um resumo comportamental no momento."}

        habitos_apps = await self._montar_habitos_app_dto(dados_agregados.get("apps", []))
        preferencias_musicais = await self._montar_preferencias_musicais_dto(dados_agregados.get("artistas", []))

        # O campo 'resumo' agora pode ser um texto fixo ou o primeiro card de insight
        resumo_texto = resumo_dict.get("resumo", "")
        if not resumo_texto and resumo_dict.get("cards"):
            resumo_texto = resumo_dict["cards"][0].get("conteudo", {}).get("text", "")

        return PerfilCognitivoDTO(
            resumo_comportamental=resumo_texto or "N/A",
            cards_dinamicos=resumo_dict.get("cards", []),
            habitos_aplicativos=habitos_apps,
            preferencias_musicais=preferencias_musicais,
        )

    async def _montar_habitos_app_dto(self, apps_info: List[AppInfo]) -> List[HabitoAppDTO]:
        dtos = []
        total_score = sum(app.score for app in apps_info)
        if not total_score: return []

        for app in apps_info:
            entidade = await catalogo.obter_app(app.pacote)
            attrs = entidade.atributos if entidade else {}
            dtos.append(HabitoAppDTO(
                nome_app=attrs.get("nome", app.pacote),
                pacote=app.pacote,
                categoria=attrs.get("categoria", "Desconhecida"),
                percentual_uso=(app.score / total_score) * 100
            ))
        return dtos

    async def _montar_preferencias_musicais_dto(self, artistas_info: List[ArtistaInfo]) -> List[PreferenciaMusicalDTO]:
        dtos = []
        total_score = sum(artista.score for artista in artistas_info)
        if not total_score: return []

        for artista in artistas_info:
            entidade = await catalogo.obter_artista(artista.nome)
            attrs = entidade.atributos if entidade else {}
            dtos.append(PreferenciaMusicalDTO(
                artista=artista.nome,
                genero=attrs.get("genero", "Desconhecido"),
                percentual_escuta=(artista.score / total_score) * 100
            ))
        return dtos

servico_perfil = ServicoPerfil(llm_service=ServicoLLM())