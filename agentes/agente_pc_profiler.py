"""
agentes/agente_pc_profiler.py

Agente especializado em analisar a estrutura de arquivos e pastas do PC do usuário.
Identifica locais importantes (Projetos, Jogos, Documentos) e salva no Obsidian.
"""
import logging
import json
from core.evento import EventoCanonico
from core.tipos import CategoriaEvento, TipoAcao, OrigemEvento
from core.kernel import kernel
from servicos.obsidian_service import obsidian_service

logger = logging.getLogger("AgentePcProfiler")

class AgentePcProfiler:
    async def processar(self, evento: EventoCanonico):
        # Escuta o evento de estrutura do PC vindo do WebSocket
        if evento.payload.get("tipo_ws") != "PC_STRUCTURE":
            return

        logger.info("🧠 [PcProfiler] Analisando nova estrutura de diretórios recebida...")
        
        pastas = evento.payload.get("pastas", [])
        if not pastas:
            return

        # 1. Identifica padrões de pastas
        atalhos_encontrados = self._analisar_pastas(pastas)
        
        # 2. Salva no Obsidian como conhecimento geográfico
        if atalhos_encontrados:
            resumo = "\n".join([f"- {nome}: {path}" for nome, path in atalhos_encontrados.items()])
            obsidian_service.registrar_fato(
                "Mapa_Geografico_PC", 
                f"Estrutura de pastas detectada em {evento.timestamp.strftime('%d/%m/%Y')}:\n{resumo}"
            )
            
            # 3. Notifica o usuário que o estudo foi concluído
            await kernel.publicar(EventoCanonico(
                categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
                acao=TipoAcao.INTENCAO_INTERACAO,
                origem=OrigemEvento.IA,
                payload={
                    "titulo": "Estudo do PC Concluído",
                    "texto": f"Terminei de mapear seu computador! Agora já sei onde ficam suas pastas de {', '.join(list(atalhos_encontrados.keys())[:3])}.",
                    "tipo_ws": "NOTIFICACAO"
                }
            ))

    def _analisar_pastas(self, pastas: list) -> dict:
        """Identifica pastas importantes com base em nomes comuns."""
        mapeamento = {}
        
        # Keywords para identificar propósitos
        keywords = {
            "Projetos": ["dev", "projetos", "work", "workspace", "coding", "github", "repos"],
            "Jogos": ["games", "jogos", "steam", "epic", "riot", "blizzard"],
            "Mídia": ["filmes", "movies", "series", "videos", "cinema"],
            "Design": ["design", "art", "fotos", "pictures", "adobe", "canva"],
            "Estudos": ["estudo", "faculdade", "universidade", "cursos", "livros"]
        }

        for path in pastas:
            path_lower = path.lower()
            nome_pasta = path.split("\\")[-1].split("/")[-1]
            
            for categoria, lista_k in keywords.items():
                if any(k in path_lower for k in lista_k):
                    # Se achar uma pasta que bate com a keyword, guarda o caminho
                    if categoria not in mapeamento or len(path) < len(mapeamento[categoria]):
                        mapeamento[categoria] = path
        
        return mapeamento
