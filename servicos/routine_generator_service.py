import logging
import json
import os
from typing import List, Dict, Any
from servicos.routine_discovery_service import routine_discovery_service
from servicos.llm import ServicoLLM

logger = logging.getLogger("RoutineGenerator")

class RoutineGeneratorService:
    def __init__(self):
        self.discovered_path = "D:/Programacao/AssistenteCell/config/discovered_routines.json"
        self.active_path = "D:/Programacao/AssistenteCell/config/routines.json"
        self.llm = ServicoLLM()

    async def run_batch_generation(self):
        """
        Executa uma varredura completa nos padrões e gera rotinas no arquivo de descoberta.
        """
        logger.info("⚡ Iniciando geração de rotinas em lote...")
        
        # 1. Obtém sugestões brutas do motor de descoberta
        sugestoes = await routine_discovery_service.discover_suggestions(min_confidence=0.75)
        if not sugestoes:
            logger.info("Nenhuma nova sugestão encontrada para gerar rotinas.")
            return

        # 2. Carrega nomes de rotinas já existentes (ativas ou pendentes)
        existentes = self._get_all_existing_names()

        novas_rotinas = []
        for sug in sugestoes:
            if sug["tipo"] != "sugestao_regra": continue
            
            conteudo = sug["conteudo"]
            # Verifica se já geramos algo similar
            if conteudo.get("nome") in existentes: continue

            # 3. Transforma a sugestão em uma Rotina Completa
            rotina = await self._materialize_routine(conteudo)
            if rotina:
                novas_rotinas.append(rotina)
                existentes.add(rotina["nome"])

        if novas_rotinas:
            self._save_discovered_routines(novas_rotinas)
            logger.info(f"✅ Geradas {len(novas_rotinas)} novas rotinas para verificação.")
        else:
            logger.info("Nenhuma rotina nova gerada após filtragem.")

    async def _materialize_routine(self, sugestao: dict) -> dict | None:
        """
        Usa inteligência para converter uma sugestão simples em um objeto de rotina rico.
        """
        try:
            # Se for uma sugestão temporal de PC
            if sugestao["skill_id"] == "automacao_temporal_pc":
                programa = sugestao["action_parameter"].split(":")[-1]
                periodo = sugestao["nome"].split(" ")[1].replace(":", "") # Extrai MANHA, TARDE etc
                
                return {
                    "nome": f"Acesso Rápido: {programa} ({periodo})",
                    "justificativa": sugestao["justificativa"],
                    "gatilho": {
                        "tipo": "TIME_RANGE",
                        "inicio": self._get_time_for_period(periodo, "inicio"),
                        "fim": self._get_time_for_period(periodo, "fim"),
                        "evento": "PC_LOGIN"
                    },
                    "acoes": [
                        {"alvo": "PC", "comando": "abrir_app", "parametro": programa}
                    ],
                    "ativa": False # Sempre inicia inativa para verificação
                }

            # Se for uma sinergia Cross-Device
            if sugestao["skill_id"] == "automacao_cross":
                pacote = sugestao["trigger_package"]
                programa = sugestao["action_parameter"].split(":")[-1]
                
                return {
                    "nome": sugestao["nome"],
                    "justificativa": sugestao["justificativa"],
                    "gatilho": {
                        "tipo": "APP_OPENED",
                        "pacote": pacote
                    },
                    "acoes": [
                        {"alvo": "PC", "comando": "abrir_app", "parametro": programa}
                    ],
                    "ativa": False
                }

            # Para outros casos, usa a LLM para criar algo mais "criativo"
            return await self._llm_enhance_routine(sugestao)

        except Exception as e:
            logger.error(f"Erro ao materializar rotina: {e}")
            return None

    async def _llm_enhance_routine(self, sugestao: dict) -> dict | None:
        """Pede para a LLM dar um nome criativo e talvez adicionar ações complementares."""
        prompt = f"""Converta este padrão de comportamento em uma Rotina de Automação criativa.
Padrão: {sugestao['justificativa']}
Gatilho sugerido: {sugestao['trigger_package']}
Ação sugerida: {sugestao['action_parameter']}

Retorne um JSON no formato:
{{
  "nome": "Nome Criativo e Curto",
  "justificativa": "Explicação do porquê esta rotina existe",
  "gatilho": {{ "tipo": "APP_OPENED", "pacote": "..." }},
  "acoes": [ {{ "alvo": "PC|MOBILE", "comando": "...", "parametro": "..." }} ],
  "ativa": false
}}"""
        try:
            # Usando o método gerar_json simplificado (supondo que exista no ServicoLLM ou similar)
            res = await self.llm._gerar_json(prompt, "Você é um arquiteto de automações residenciais.")
            return res
        except:
            return None

    def _get_time_for_period(self, periodo: str, tipo: str) -> str:
        mapa = {
            "MANHA": {"inicio": "06:00", "fim": "11:59"},
            "TARDE": {"inicio": "12:00", "fim": "17:59"},
            "NOITE": {"inicio": "18:00", "fim": "23:59"},
            "MADRUGADA": {"inicio": "00:00", "fim": "05:59"}
        }
        return mapa.get(periodo, {"inicio": "08:00", "fim": "10:00"})[tipo]

    def _get_all_existing_names(self) -> set:
        names = set()
        for path in [self.active_path, self.discovered_path]:
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        for r in data: names.add(r.get("nome"))
                except: pass
        return names

    def _save_discovered_routines(self, novas: List[dict]):
        current = []
        if os.path.exists(self.discovered_path):
            try:
                with open(self.discovered_path, "r", encoding="utf-8") as f:
                    current = json.load(f)
            except: pass
        
        current.extend(novas)
        with open(self.discovered_path, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=4)

routine_generator_service = RoutineGeneratorService()
