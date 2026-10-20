"""Política de abertura para todos os destinos; importância não é confiança de hábito."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import math
from urllib.parse import urlparse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from banco.database import AsyncSessionLocal
from banco.models import PoliticaIntervencaoDB


class InterventionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    auto_open_enabled: StrictBool = False
    min_priority_score: float = Field(default=0.85, ge=0, le=1, allow_inf_nan=False)
    whitelist: list[str] = Field(default_factory=lambda: ["whatsapp", "telegram", "vscode"], max_length=100)
    blacklist: list[str] = Field(default_factory=lambda: ["jogo", "netflix", "youtube"], max_length=100)


OPEN_COMMANDS = {"abrir_app", "abrir_programa", "open_app", "launch_app", "abrir_app_mobile",
                 "abrir_url", "open_url", "abrir_url_mobile", "pesquisa_google", "web_search", "pesquisar",
                 "abrir_notificacao", "abrir_mensagem", "read_message"}
APP_ALIASES = {"vscode", "android_studio", "spotify", "discord", "lol", "chrome", "steam", "clone_hero"}
PACKAGE_ALIASES = {"com.whatsapp": "whatsapp", "org.telegram.messenger": "telegram",
                   "com.spotify.music": "spotify", "com.instagram.android": "instagram", "code.exe": "vscode",
                   "com.google.android.youtube": "youtube", "com.netflix.mediaclient": "netflix"}


def e_abertura(comando):
    return str(comando).lower() in OPEN_COMMANDS | APP_ALIASES


def identidade(alvo):
    valor = str(alvo or "").strip().lower()
    if valor.startswith(("http://", "https://")):
        return urlparse(valor).hostname or valor
    return PACKAGE_ALIASES.get(valor, valor.removesuffix(".exe"))


class InterventionGovernor:
    def __init__(self, now=lambda: datetime.now(timezone.utc)):
        self.policy = InterventionPolicy().model_dump()
        self._lock = asyncio.Lock()
        self._now = now

    async def _transaction(self, action):
        async with self._lock:
            for attempt in range(2):
                try:
                    async with AsyncSessionLocal() as session, session.begin():
                        row = (await session.execute(select(PoliticaIntervencaoDB)
                            .where(PoliticaIntervencaoDB.id == 1).with_for_update())).scalar_one_or_none()
                        if row is None:
                            row = PoliticaIntervencaoDB(id=1, dados={"policy": InterventionPolicy().model_dump(), "openings": []})
                            session.add(row); await session.flush()
                        data = deepcopy(row.dados)
                        result = action(data)
                        row.dados = data
                        self.policy = deepcopy(data["policy"])
                        return result
                except IntegrityError:
                    if attempt:
                        raise

    async def obter_politica(self):
        return await self._transaction(lambda data: {**data["policy"], "controle_abertura_version": 1})

    async def atualizar_politica(self, dados):
        dados = {k: v for k, v in dados.items() if k != "controle_abertura_version"}
        def action(data):
            data["policy"] = InterventionPolicy.model_validate({**data["policy"], **dados}).model_dump()
            return {**data["policy"], "controle_abertura_version": 1}
        return await self._transaction(action)

    @staticmethod
    def motivo(policy, alvo, score):
        if not policy.get("auto_open_enabled"):
            return "abertura_automatica_desativada"
        try:
            score = float(score)
        except (ValueError, TypeError):
            return "importancia_ausente"
        if not math.isfinite(score) or not 0 < score <= 1 or score < policy["min_priority_score"]:
            return "importancia_insuficiente"
        target = identidade(alvo)
        if not target:
            return "aplicativo_ausente"
        if target in {identidade(x) for x in policy.get("blacklist", [])}:
            return "aplicativo_bloqueado"
        if target not in {identidade(x) for x in policy.get("whitelist", [])}:
            return "aplicativo_nao_permitido"
        return None

    async def avaliar_abertura(self, alvo, dispositivo, score=None, explicito=False):
        if explicito:
            return {"permitida": True, "modo": "pedido", "motivo": "pedido_explicito"}
        def action(data):
            reason = self.motivo(data["policy"], alvo, score)
            now = self._now()
            records = [r for r in data.get("openings", []) if now - datetime.fromisoformat(r["at"]) < timedelta(hours=1)]
            key = f"{dispositivo}:{identidade(alvo)}"
            if not reason and (any(r["target"] == key for r in records) or len(records) >= 3 or
                               (records and now - datetime.fromisoformat(records[-1]["at"]) < timedelta(minutes=10))):
                reason = "limite_de_aberturas"
            if not reason:
                records.append({"target": key, "at": now.isoformat()})
            data["openings"] = records
            return {"permitida": reason is None, "modo": "automatica", "motivo": reason or "autorizada",
                    "importance_score": score if reason is None else 0}
        return await self._transaction(action)


intervention_governor = InterventionGovernor()
