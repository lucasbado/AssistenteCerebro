"""Normalização comum aos sensores de atividade via UDP e WebSocket."""


def processo_pc(payload):
    dados = payload.get("payload") or payload
    return str(dados.get("processo") or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
