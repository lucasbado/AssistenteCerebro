"""Confirmações transitórias; envio não equivale a execução."""
import time
from collections import OrderedDict


class ConfirmacoesPC:
    def __init__(self, relogio=time.monotonic):
        self.relogio = relogio
        self._comandos = OrderedDict()

    def registrar(self, identificador, comando):
        if identificador in self._comandos:
            return False
        self._comandos[identificador] = {"id": identificador, "comando": comando,
                                        "status": "enviado", "inicio": self.relogio()}
        while len(self._comandos) > 200:
            self._comandos.popitem(last=False)
        return True

    def atualizar(self, identificador, status):
        registro = self._comandos.get(identificador)
        if registro is not None and status in {"concluido", "erro", "pc_offline"}:
            registro["status"] = status

    def consultar(self, identificador):
        registro = self._comandos.get(identificador)
        if registro is None:
            return None
        segundos = max(0, round(self.relogio() - registro["inicio"], 1))
        status = registro["status"]
        if status == "enviado" and segundos > 360:
            status = "sem_confirmacao"
        return {"id": identificador, "comando": registro["comando"],
                "status": status, "segundos_desde_envio": segundos}
