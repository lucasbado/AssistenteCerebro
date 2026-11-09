"""Confirmações transitórias; envio não equivale a execução."""
import time
import asyncio
from collections import OrderedDict
from servicos.foco_janelas import validar_observacao_janelas
from servicos.interface_pc import (
    COMANDO_ACIONAR_CONTROLE, COMANDO_INTERFACE, COMANDOS_INTERFACE_EXPLICITOS, COMANDOS_OBSERVACAO_PC,
    validar_resultado_acionamento, validar_resultado_interface,
)


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
            from servicos.arquivos_pc import COMANDOS_ARQUIVOS, validar_resultado_arquivo
            comando = registro['comando']
            if comando in COMANDOS_ARQUIVOS | COMANDOS_INTERFACE_EXPLICITOS | {'system_status'}:
                if registro['status'] != 'enviado':
                    return
                registro['status'] = status
                if status == 'concluido':
                    from servicos.comandos_pc import validar_status_pc
                    if comando == COMANDO_ACIONAR_CONTROLE:
                        valido = validar_resultado_acionamento(resultado)
                    elif comando == COMANDO_INTERFACE:
                        valido = validar_resultado_interface(resultado)
                    elif comando in COMANDOS_OBSERVACAO_PC:
                        valido = validar_observacao_janelas(comando, resultado)
                    elif comando == 'system_status':
                        valido = validar_status_pc(resultado)
                    else:
                        valido = validar_resultado_arquivo(comando, resultado)
                    if valido:
                        registro['resultado'] = resultado
                    else:
                        registro['status'] = 'erro'
                return
            registro["status"] = status
            if isinstance(resultado, dict) and isinstance(resultado.get('primeiro_plano'), bool):
                registro['resultado'] = {'primeiro_plano': resultado['primeiro_plano']}
            if registro['comando'] == 'audio_controle' and isinstance(resultado, dict):
                # Resultado fechado, limitado e sem transportar dados arbitrários do desktop.
                from servicos.resultado_audio import resultado_audio_valido
                if resultado_audio_valido(resultado):
                    registro['resultado'] = {'audio': resultado['audio']}

    async def aguardar(self, identificador, timeout=12):
        limite = self.relogio() + timeout
        while True:
            registro = self.consultar(identificador, incluir_observacao=True)
            if registro is None or registro['status'] != 'enviado':
                return registro or {'status': 'sem_confirmacao'}
            if self.relogio() >= limite:
                return {**registro, 'status': 'sem_confirmacao'}
            await asyncio.sleep(.05)

    def consultar(self, identificador, *, incluir_observacao=False):
        registro = self._comandos.get(identificador)
        if registro is None:
            return None
        segundos = max(0, round(self.relogio() - registro["inicio"], 1))
        status = registro["status"]
        if status == "enviado" and segundos > 360:
            status = "sem_confirmacao"
        visivel = incluir_observacao or registro['comando'] not in COMANDOS_INTERFACE_EXPLICITOS
        return {"id": identificador, "comando": registro["comando"],
                "status": status, "segundos_desde_envio": segundos,
                **({'resultado': registro['resultado']} if visivel and 'resultado' in registro else {})}
