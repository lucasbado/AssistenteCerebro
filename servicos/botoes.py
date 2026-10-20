"""Transforma um toque identificado em uma ação previamente cadastrada."""
import asyncio
import json
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.evento import EventoCanonico
from core.tipos import CategoriaEvento, OrigemEvento

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "botoes.json"


class ToqueBotao(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dispositivo: str = Field(min_length=1, max_length=80, pattern=r"^[\w.-]+$")
    botao: str = Field(min_length=1, max_length=80, pattern=r"^[\w.-]+$")
    gesto: Literal["toque", "duplo", "longo"] = "toque"
    evento_id: str = Field(min_length=1, max_length=128, pattern=r"^[\w.:-]+$")


class VinculoBotao(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dispositivo: str
    botao: str
    gesto: Literal["toque", "duplo", "longo"] = "toque"
    acao: Literal["cenario", "wake", "casa"]
    cenario: str | None = Field(default=None, pattern=r"^[a-z0-9_-]+$")
    alvo: str | None = None
    operacao: Literal["ligar", "desligar", "alternar", "consultar"] | None = None
    ativo: bool = True
    cooldown_segundos: float = Field(default=1, ge=0.3, le=3600)

    @model_validator(mode="after")
    def validar_acao(self):
        if (self.acao == "cenario") != bool(self.cenario):
            raise ValueError("Somente uma ação de cenário deve informar cenario")
        if self.acao == "casa":
            if not self.alvo or self.operacao is None:
                raise ValueError("Ação da casa exige alvo e operacao")
        elif self.alvo is not None or self.operacao is not None:
            raise ValueError("Somente uma ação da casa recebe alvo e operacao")
        return self


class ServicoBotoes:
    def __init__(self, path=CONFIG_PATH, relogio=time.monotonic):
        self.path = Path(path)
        self.relogio = relogio
        self._recebidos = {}
        self._ultimos = {}
        self._lock = asyncio.Lock()

    def vinculos(self):
        dados = json.loads(self.path.read_text(encoding="utf-8"))
        vinculos = [VinculoBotao.model_validate(v) for v in dados]
        chaves = [(v.dispositivo, v.botao, v.gesto) for v in vinculos]
        if len(chaves) != len(set(chaves)):
            raise ValueError("Há vínculos duplicados para o mesmo botão e gesto")
        return vinculos

    def prever(self, toque: ToqueBotao):
        vinculo = next((v for v in self.vinculos() if v.ativo and
                       (v.dispositivo, v.botao, v.gesto) ==
                       (toque.dispositivo, toque.botao, toque.gesto)), None)
        if vinculo is None:
            raise LookupError("Botão/gesto sem ação ativa cadastrada")
        if vinculo.acao == "casa":
            from servicos.controle_casa import controle_casa
            alvo = controle_casa.resolver(vinculo.alvo)
            return {"comando": "casa_acao", "parametro": json.dumps({"acao": vinculo.operacao, "alvo": alvo["id"]}),
                    "cooldown_segundos": vinculo.cooldown_segundos}
        return {"comando": "executar_cenario" if vinculo.acao == "cenario" else "wake_ollie",
                "parametro": vinculo.cenario or "", "cooldown_segundos": vinculo.cooldown_segundos}

    async def receber(self, toque: ToqueBotao, kernel):
        async with self._lock:
            agora = self.relogio()
            self._recebidos = {k: v for k, v in self._recebidos.items() if v[0] > agora - 600}
            chave_id = (toque.dispositivo, toque.evento_id)
            if chave_id in self._recebidos:
                return {"status": "duplicado", "id": self._recebidos[chave_id][1]}
            acao = self.prever(toque)
            chave = (toque.dispositivo, toque.botao, toque.gesto)
            if agora - self._ultimos.get(chave, float("-inf")) < acao["cooldown_segundos"]:
                return {"status": "ignorado_cooldown"}
            evento = EventoCanonico(
                categoria=CategoriaEvento.BOTAO_ACIONADO, origem=OrigemEvento.USUARIO,
                pacote="home.assistant.botao", payload={**toque.model_dump(), **acao})
            await kernel.publicar(evento)
            self._recebidos[chave_id] = (agora, evento.id)
            self._ultimos[chave] = agora
            # Memória limitada; deduplicação cobre os últimos 10 min desta instância.
            if len(self._recebidos) > 2000:
                self._recebidos.pop(next(iter(self._recebidos)))
            if len(self._ultimos) > 1000:
                self._ultimos = {chave: agora}
            return {"status": "aceito", "id": evento.id,
                    "comando": acao["comando"], "parametro": acao["parametro"]}


servico_botoes = ServicoBotoes()
