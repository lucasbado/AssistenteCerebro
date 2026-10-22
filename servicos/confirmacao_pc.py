"""Confirmações transitórias; envio não equivale a execução."""
import time
import asyncio
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

    def atualizar(self, identificador, status, resultado=None):
        registro = self._comandos.get(identificador)
        if registro is not None and status in {"concluido", "erro", "pc_offline"}:
            registro["status"] = status
            if isinstance(resultado, dict) and isinstance(resultado.get('primeiro_plano'), bool):
                registro['resultado'] = {'primeiro_plano': resultado['primeiro_plano']}

    async def aguardar(self, identificador, timeout=12):
        limite = self.relogio() + timeout
        while True:
            registro = self.consultar(identificador)
            if registro is None or registro['status'] != 'enviado':
                return registro or {'status': 'sem_confirmacao'}
            if self.relogio() >= limite:
                return {**registro, 'status': 'sem_confirmacao'}
            await asyncio.sleep(.05)

    def consultar(self, identificador):
        registro = self._comandos.get(identificador)
        if registro is None:
            return None
        segundos = max(0, round(self.relogio() - registro["inicio"], 1))
        status = registro["status"]
        if status == "enviado" and segundos > 360:
            status = "sem_confirmacao"
        return {"id": identificador, "comando": registro["comando"],
                "status": status, "segundos_desde_envio": segundos,
                **({'resultado': registro['resultado']} if 'resultado' in registro else {})}
