import logging
import json
import os
from typing import List, Dict, Any
from servicos.memoria_perfil import memoria_perfil
from servicos.catalogo_semantico import catalogo
from sqlalchemy.future import select
from banco.database import AsyncSessionLocal
from banco.models import EntidadeSemanticaDB

logger = logging.getLogger("RoutineDiscovery")

class RoutineDiscoveryService:
    def __init__(self):
        self.routines_path = "D:/Programacao/AssistenteCell/config/routines.json"

    def _get_existing_routine_names(self) -> set:
        if not os.path.exists(self.routines_path): return set()
        try:
            with open(self.routines_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {r.get("nome") for r in data}
        except: return set()

    async def discover_suggestions(self, min_confidence: float = 0.8) -> List[Dict[str, Any]]:
        """
        Varre todas as memórias em busca de padrões para sugerir rotinas.
        """
        logger.info(f"🔍 Iniciando descoberta de rotinas (Confiança mín: {min_confidence})...")
        sugestoes = []
        existentes = self._get_existing_routine_names()

        # 1. Scanner de Sinergia (Cross-Device) via Memória Semântica
        sugestoes.extend(await self._scan_cross_device_associations(min_confidence, existentes))

        # 2. Scanner Temporal via Memória de Perfil (PC)
        sugestoes.extend(await self._scan_temporal_patterns(min_confidence, existentes))
        
        # 3. Scanner de Hábitos de Apps Fortes (Mobile)
        sugestoes.extend(await self._scan_strong_habits(min_confidence, existentes))

        logger.info(f"✅ Descoberta finalizada. {len(sugestoes)} novas sugestões encontradas.")
        return sugestoes

    async def _scan_cross_device_associations(self, min_conf: float, existentes: set) -> List[Dict[str, Any]]:
        sugestoes = []
        from sqlalchemy import cast, String
        async with AsyncSessionLocal() as session:
            # 🛡️ FIX: Cast para String para compatibilidade com Postgres/SQLite no LIKE
            stmt = select(EntidadeSemanticaDB).where(cast(EntidadeSemanticaDB.dados_json, String).like('%associacoes%'))
            result = await session.execute(stmt)
            entidades = result.scalars().all()

            for ent in entidades:
                dados = ent.dados_json
                assoc = dados.get("atributos", {}).get("associacoes", {})
                
                # Sinergia PC
                pc_default = assoc.get("pc_default")
                if pc_default:
                    programa = pc_default.get("programa")
                    pacote = ent.chave
                    nome_app = dados.get("atributos", {}).get("nome", pacote)
                    nome_rotina = f"Sinergia: {nome_app} ➔ {programa}"

                    if nome_rotina not in existentes:
                        sugestoes.append({
                            "tipo": "sugestao_regra",
                            "conteudo": {
                                "nome": nome_rotina,
                                "skill_id": "automacao_cross",
                                "trigger_package": pacote,
                                "action_type": "PC_COMMAND",
                                "action_parameter": f"abrir_app:{programa}",
                                "justificativa": f"Sempre que você usa {nome_app}, o {programa} costuma estar aberto no PC."
                            }
                        })
                
                # Fluxo Mobile (Próximo App)
                mobile_next = assoc.get("mobile_next")
                if mobile_next:
                    p2 = mobile_next.get("pacote")
                    p1 = ent.chave
                    nome1 = dados.get("atributos", {}).get("nome", p1)
                    nome_rotina = f"Fluxo: {nome1} ➔ {p2.split('.')[-1].capitalize()}"
                    
                    if nome_rotina not in existentes:
                        sugestoes.append({
                            "tipo": "sugestao_regra",
                            "conteudo": {
                                "nome": nome_rotina,
                                "skill_id": "automacao_fluxo",
                                "trigger_package": p1,
                                "action_type": "OPEN_APP",
                                "action_parameter": p2,
                                "justificativa": f"Notei que você quase sempre abre o {p2.split('.')[-1].capitalize()} logo após o {nome1}."
                            }
                        })

        return sugestoes

    async def _scan_temporal_patterns(self, min_conf: float, existentes: set) -> List[Dict[str, Any]]:
        sugestoes = []
        periodos = ["MANHA", "TARDE", "NOITE", "MADRUGADA"]
        for periodo in periodos:
            # Busca padrões de PC por horário
            itens_pc = await memoria_perfil.obter_top_entidades(categoria=f"PC_ROUTINE_{periodo}", limite=3)
            for it in itens_pc:
                if it.confianca >= min_conf:
                    programa = it.valor
                    nome_rotina = f"Rotina {periodo}: {programa}"
                    if nome_rotina not in existentes:
                        sugestoes.append({
                            "tipo": "sugestao_regra",
                            "conteudo": {
                                "nome": nome_rotina,
                                "skill_id": "automacao_temporal_pc",
                                "trigger_package": "sistema.periodo",
                                "action_type": "PC_COMMAND",
                                "action_parameter": f"abrir_app:{programa}",
                                "justificativa": f"Hábito detectado: Você usa {programa} frequentemente no período da {periodo} ({it.score} vezes)."
                            }
                        })

            # 🧠 NOVO: Busca padrões de Apps Mobile por horário
            itens_app = await memoria_perfil.obter_top_entidades(categoria=f"APP_USO_{periodo}", limite=3)
            for it in itens_app:
                if it.confianca >= min_conf:
                    pacote = it.valor
                    if "assistentecell" in pacote: continue
                    nome_app = pacote.split('.')[-1].capitalize()
                    nome_rotina = f"Hábito {periodo}: {nome_app}"
                    
                    if nome_rotina not in existentes:
                        sugestoes.append({
                            "tipo": "sugestao_regra",
                            "conteudo": {
                                "nome": nome_rotina,
                                "skill_id": "automacao_temporal_mobile",
                                "trigger_package": "sistema.periodo",
                                "action_type": "OPEN_APP",
                                "action_parameter": pacote,
                                "justificativa": f"Notei que você abre muito o {nome_app} no período da {periodo}."
                            }
                        })
        return sugestoes

    async def _scan_strong_habits(self, min_conf: float, existentes: set) -> List[Dict[str, Any]]:
        sugestoes = []
        # Apps com score altíssimo
        top_apps = await memoria_perfil.obter_top_entidades(categoria="APP_USO", limite=5)
        for it in top_apps:
            if it.score > 100: # Super hábito
                pacote = it.valor
                if "assistentecell" in pacote: continue
                nome_rotina = f"Favorito: {pacote.split('.')[-1].capitalize()}"
                
                if nome_rotina not in existentes:
                    # Sugere uma automação de boas-vindas ou atalho rápido
                    sugestoes.append({
                        "tipo": "insight",
                        "conteudo": {
                            "title": f"Destaque: {pacote.split('.')[-1].capitalize()}",
                            "text": f"Este é seu app mais usado ({it.score} vezes!). Quer que eu crie um atalho de voz personalizado para ele?"
                        }
                    })
        return sugestoes

routine_discovery_service = RoutineDiscoveryService()
