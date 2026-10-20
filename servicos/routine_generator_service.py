"""Materializa sugestões auditáveis; nenhuma sugestão nasce ativa."""
import asyncio

from servicos.routine_discovery_service import routine_discovery_service
from servicos.catalogo_rotinas import catalogo_rotinas


class RoutineGeneratorService:
    def __init__(self):
        self.catalogo = catalogo_rotinas
        self._lock = asyncio.Lock()

    async def run_batch_generation(self):
        async with self._lock:
            sugestoes = await routine_discovery_service.discover_suggestions(min_confidence=0.8)
            existentes = await self._get_all_existing_names()
            novas = []
            for sugestao in sugestoes:
                if sugestao.get("tipo") != "sugestao_regra":
                    continue
                conteudo = sugestao["conteudo"]
                nome = conteudo["nome"].strip().casefold()
                if nome in existentes:
                    continue
                rotina = await self._materialize_routine(conteudo)
                if rotina:
                    novas.append(rotina)
                    existentes.add(nome)
            return await self.catalogo.adicionar_sugestoes(novas) if novas else 0

    async def _materialize_routine(self, sugestao):
        skill = sugestao.get("skill_id")
        alvo = sugestao["action_parameter"].removeprefix("abrir_app:")
        rotina = {"nome": sugestao["nome"], "justificativa": sugestao["justificativa"],
                  "evidencia": sugestao.get("evidencia", {}), "ativa": False,
                  "cooldown_segundos": 3600}
        if skill in {"automacao_temporal_pc", "automacao_temporal_mobile"}:
            periodo = sugestao.get("periodo")
            if periodo not in {"MANHA", "TARDE", "NOITE", "MADRUGADA"}:
                return None
            rotina["gatilho"] = {"tipo": "TIME_RANGE",
                "inicio": self._get_time_for_period(periodo, "inicio"),
                "fim": self._get_time_for_period(periodo, "fim"),
                "evento": "PC_ACTIVITY" if skill.endswith("_pc") else "TICK_ROTINA"}
            rotina["uma_vez_por_dia"] = True
        elif skill in {"automacao_cross", "automacao_fluxo"}:
            rotina["gatilho"] = {"tipo": "APP_OPENED", "pacote": sugestao["trigger_package"]}
        else:
            return None

        if skill in {"automacao_cross", "automacao_temporal_pc"}:
            rotina["acoes"] = [{"alvo": "PC", "comando": "abrir_app", "parametro": alvo}]
        else:
            # Abrir B imediatamente ao entrar em A impede o usuário de usar A.
            # Oferecemos o próximo passo com uma ação explícita na notificação.
            nome_app = alvo.rsplit(".", 1)[-1].capitalize()
            if skill == "automacao_fluxo":
                origem = sugestao["trigger_package"].rsplit(".", 1)[-1].capitalize()
                texto = f"Depois de usar {origem}, você costuma abrir {nome_app}. Quer abrir agora?"
            else:
                periodo = {"MANHA": "pela manhã", "TARDE": "à tarde", "NOITE": "à noite", "MADRUGADA": "de madrugada"}[sugestao["periodo"]]
                texto = f"Você costuma usar {nome_app} {periodo}. Quer abrir agora?"
            rotina["acoes"] = [{"alvo": "IA", "comando": "NOTIFICAR",
                "parametro": texto,
                "acao_tipo": "OPEN_APP", "acao_parametro": alvo, "acao_texto": "Abrir app"}]
        return rotina

    def _get_time_for_period(self, periodo, tipo):
        mapa = {"MANHA": ("06:00", "11:59"), "TARDE": ("12:00", "17:59"),
                "NOITE": ("18:00", "23:59"), "MADRUGADA": ("00:00", "05:59")}
        return mapa[periodo][0 if tipo == "inicio" else 1]

    async def _get_all_existing_names(self):
        return {r["nome"].strip().casefold() for r in await self.catalogo.existentes()}


routine_generator_service = RoutineGeneratorService()
