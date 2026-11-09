"""
Perfil Adaptativo de Áudio do Microfone.
Aprende os níveis de ruído e voz do microfone específico do usuário para calibração de VAD.
Baseado no JARVIS.
"""
from __future__ import annotations

import json
import os
import time

PISO_PADRAO = 0.09
RESGATE_PADRAO = 0.045
RESGATE_INICIAL = 0.025


class PerfilDoMicrofone:
    """Calcula limites dinâmicos de corte de som para o microfone ativo."""

    def __init__(self, chave: str = "padrao") -> None:
        self.chave = str(chave or "padrao")
        self.fala: list[float] = []
        self.ruido: list[float] = []

    def limites(self) -> tuple[float, float]:
        """Retorna (resgate, piso) dinâmicos para este microfone."""
        resgate = RESGATE_INICIAL if not self.ruido else RESGATE_PADRAO
        piso = PISO_PADRAO if not self.fala else PISO_PADRAO
        return resgate, piso

    def anotar(self, tipo: str, pico: float) -> None:
        if tipo not in ("fala", "ruido") or not (0.0 < float(pico or 0) <= 1.0):
            return
        if tipo == "fala":
            self.fala.append(float(pico))
            self.fala = self.fala[-80:]
        else:
            self.ruido.append(float(pico))
            self.ruido = self.ruido[-120:]


_perfil_ativo = PerfilDoMicrofone()


def obter_perfil_microfone(chave: str = "padrao") -> PerfilDoMicrofone:
    global _perfil_ativo
    if _perfil_ativo.chave != chave:
        _perfil_ativo = PerfilDoMicrofone(chave)
    return _perfil_ativo
