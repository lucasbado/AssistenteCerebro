"""Cenários locais: sequência fixa, sem código nem caminhos vindos do webhook."""
import json
import subprocess
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = Path(__file__).resolve().parents[1]


class PassoCenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    comando: Literal["python", "snapshot", "abrir_app", "abrir_url", "volume_sistema",
                     "media_play_pause", "media_next", "media_prev", "mutar_mic",
                     "ligar_luz", "desligar_luz"]
    parametro: str = ""
    script: str | None = None
    argumentos: list[str] = Field(default_factory=list, max_length=30)
    timeout_segundos: int = Field(default=30, ge=1, le=300)

    @model_validator(mode="after")
    def validar_python(self):
        if self.comando == "python":
            if not self.script or self.parametro:
                raise ValueError("Passo Python exige script e não recebe parametro")
        elif self.script or self.argumentos:
            raise ValueError("Somente passos Python recebem script/argumentos")
        return self


class Cenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ativo: bool = True
    passos: list[PassoCenario] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def limitar_duracao(self):
        if sum(p.timeout_segundos for p in self.passos) > 300:
            raise ValueError("Orçamento de tempo do cenário excede 300 segundos")
        return self


class ServicoCenarios:
    def __init__(self, root=ROOT):
        self.root = Path(root).resolve()

    def preparar(self, nome):
        import re
        if not re.fullmatch(r"[a-z0-9_-]{1,80}", nome):
            raise ValueError("Nome de cenário inválido")
        dados = json.loads((self.root / "config/cenarios.json").read_text(encoding="utf-8"))
        if nome not in dados:
            raise ValueError("Cenário não cadastrado neste PC")
        cenario = Cenario.model_validate(dados[nome])
        if not cenario.ativo:
            raise ValueError("Cenário desativado")
        pasta = (self.root / "scripts/cenarios").resolve()
        for passo in cenario.passos:
            if passo.comando == "python":
                script = (pasta / passo.script).resolve()
                if not script.is_relative_to(pasta) or script.suffix.lower() != ".py" or not script.is_file():
                    raise ValueError("Script deve existir dentro de scripts/cenarios")
                passo.script = str(script)
        return cenario

    def executar(self, nome, executar_comando=None):
        cenario = self.preparar(nome)  # Valida todos os scripts antes do primeiro efeito.
        if executar_comando is None:
            from scripts.pc_command import executar as executar_comando
        concluidos = 0
        for passo in cenario.passos:
            if passo.comando == "python":
                try:
                    # Arquivo e argumentos são cadastrados no PC, nunca recebidos pela rede.
                    subprocess.run([sys.executable, passo.script, *passo.argumentos],
                                   cwd=self.root, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   timeout=passo.timeout_segundos, check=True, shell=False)
                except (subprocess.SubprocessError, OSError) as e:
                    raise RuntimeError(f"Cenário interrompido no passo {concluidos + 1} ({type(e).__name__})") from e
            else:
                resultado = executar_comando(passo.comando, passo.parametro)
                if resultado is False:
                    raise RuntimeError(f"Cenário interrompido no passo {concluidos + 1}")
            concluidos += 1
        return {"status": "ok", "cenario": nome, "passos_concluidos": concluidos}
