"""Descobre padrões a partir de observações datadas, sem usar scores inflados."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from banco.database import AsyncSessionLocal
from banco.models import EventoEpisodicoDB
from servicos.catalogo_rotinas import catalogo_rotinas
from servicos.tempo import horario_local, periodo_do_dia, utc
from servicos.atividade import processo_pc


class RoutineDiscoveryService:
    MIN_SAMPLES = 5
    MIN_DAYS = 3

    def __init__(self):
        self.catalogo = catalogo_rotinas

    async def _get_existing_routine_names(self):
        return {r["nome"].strip().casefold() for r in await self.catalogo.existentes()}

    async def discover_suggestions(self, min_confidence=0.8):
        if not 0 <= min_confidence <= 1:
            raise ValueError("A confiança deve estar entre 0 e 1.")
        agora = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as session:
            resultado = await session.execute(select(EventoEpisodicoDB).where(
                EventoEpisodicoDB.timestamp >= agora - timedelta(days=21),
                EventoEpisodicoDB.timestamp <= agora,
                EventoEpisodicoDB.tipo.in_(["APP_FOREGROUND", "PC_ACTIVITY"]),
                EventoEpisodicoDB.origem.in_(["ANDROID", "PC"]),
            ).order_by(EventoEpisodicoDB.timestamp))
            observacoes = resultado.scalars().all()
        existentes = await self._get_existing_routine_names()
        return [s for s in self.analisar(observacoes, min_confidence, agora)
                if s["conteudo"]["nome"].strip().casefold() not in existentes]

    def analisar(self, observacoes, min_confidence=0.8, agora=None):
        agora = agora or datetime.now(timezone.utc)
        sessoes = {"mobile": [], "pc": []}
        for evento in sorted(observacoes, key=lambda e: utc(e.timestamp)):
            ts = utc(evento.timestamp)
            if not agora - timedelta(days=21) <= ts <= agora:
                continue
            if evento.origem not in ("ANDROID", "PC") or evento.tipo not in ("APP_FOREGROUND", "PC_ACTIVITY"):
                continue
            dados = evento.payload or {}
            if dados.get("heartbeat"):
                continue
            dispositivo = "mobile" if evento.tipo == "APP_FOREGROUND" else "pc"
            alvo = str(dados.get("pacote") or "") if dispositivo == "mobile" else processo_pc(dados)
            if not alvo or "assistentecell" in alvo.lower() or alvo.startswith("sistema."):
                continue
            if dispositivo == "pc" and alvo in {"explorer.exe", "dwm.exe", "svchost.exe"}:
                continue
            lista = sessoes[dispositivo]
            # Mudanças de título/aba e heartbeats não são novas aberturas.
            if lista and lista[-1][1] == alvo and ts - lista[-1][0] < timedelta(minutes=30):
                continue
            lista.append((ts, alvo))

        sugestoes = []

        def adicionar(nome, skill, alvo, evidencia, pacote="sistema.periodo", periodo=None):
            sucessos, total, datas, ultimo = evidencia
            confianca = sucessos / total if total else 0
            if (sucessos < self.MIN_SAMPLES or len(datas) < self.MIN_DAYS
                    or confianca < min_confidence or agora - ultimo > timedelta(days=7)):
                return
            sugestoes.append({"tipo": "sugestao_regra", "conteudo": {
                "nome": nome, "skill_id": skill, "trigger_package": pacote,
                "action_type": "PC_COMMAND" if skill in {"automacao_cross", "automacao_temporal_pc"} else "OPEN_APP",
                "action_parameter": f"abrir_app:{alvo}" if skill in {"automacao_cross", "automacao_temporal_pc"} else alvo,
                "periodo": periodo,
                "evidencia": {"amostras": sucessos, "oportunidades": total,
                              "dias_distintos": len(datas), "confianca": round(confianca, 3),
                              "ultima_observacao": ultimo.isoformat(), "janela_dias": 21},
                "justificativa": f"Padrão observado em {sucessos} de {total} oportunidades, "
                                 f"em {len(datas)} dias distintos ({confianca:.0%}).",
            }})

        mobile, pc = sessoes["mobile"], sessoes["pc"]
        for tipo, destinos, skill in (("Fluxo", mobile, "automacao_fluxo"),
                                      ("Sinergia", pc, "automacao_cross")):
            totais = Counter()
            pares = defaultdict(list)
            ultima_oportunidade = {}
            indice = 0
            for ts, pacote in mobile:
                # Inclui também oportunidades SEM uma abertura subsequente.
                if agora - ts < timedelta(seconds=60):
                    continue
                if pacote in ultima_oportunidade and ts - ultima_oportunidade[pacote] < timedelta(minutes=10):
                    continue
                ultima_oportunidade[pacote] = ts
                totais[pacote] += 1
                while indice < len(destinos) and destinos[indice][0] <= ts:
                    indice += 1
                if indice < len(destinos):
                    quando, alvo = destinos[indice]
                    if quando - ts <= timedelta(seconds=60) and alvo != pacote:
                        pares[pacote, alvo].append(quando)
            for (pacote, alvo), datas in pares.items():
                adicionar(f"{tipo}: {pacote} ➔ {alvo}", skill, alvo,
                          (len(datas), totais[pacote], {horario_local(t).date() for t in datas}, max(datas)), pacote)

        for dispositivo, lista in sessoes.items():
            dias_periodo = defaultdict(set)
            usos = defaultdict(list)
            for ts, alvo in lista:
                periodo = periodo_do_dia(ts)
                dias_periodo[periodo].add(horario_local(ts).date())
                usos[periodo, alvo].append(ts)
            for (periodo, alvo), datas in usos.items():
                dias = {horario_local(ts).date() for ts in datas}
                # Confiança temporal mede presença em dias, não volume de eventos.
                evidencia = (len(dias), len(dias_periodo[periodo]), dias, max(datas))
                adicionar(f"Rotina {periodo}: {alvo}", f"automacao_temporal_{dispositivo}",
                          alvo, evidencia, periodo=periodo)
        return sorted(sugestoes, key=lambda s: (-s["conteudo"]["evidencia"]["confianca"], s["conteudo"]["nome"]))


routine_discovery_service = RoutineDiscoveryService()
