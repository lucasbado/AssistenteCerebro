"""Execução pontual, com confirmação do socket selecionado e sem retentativa."""
import asyncio
import uuid

from servicos.controle_celular import validar_acao


class PonteCelular:
    def __init__(self):
        self.pendentes = {}

    async def executar(self, ws, enviar, acao, parametros, timeout=12):
        validar_acao(acao, parametros)
        if ws is None or ws.client_state.value != 1:
            return {"status": "offline"}
        if len(self.pendentes) >= 16:
            return {"status": "ocupado"}
        identificador = str(uuid.uuid4())
        futuro = asyncio.get_running_loop().create_future()
        self.pendentes[identificador] = (ws, acao, futuro)
        try:
            msg = {"tipo_ws": "CELULAR_EXECUTAR", "id_comando": identificador,
                   "acao": acao, "parametros": parametros, "pedido_usuario": True}
            if not await enviar(ws, msg):
                return {"status": "sem_confirmacao"}
            return await asyncio.wait_for(futuro, timeout)
        except asyncio.TimeoutError:
            return {"status": "sem_confirmacao"}
        finally:
            self.pendentes.pop(identificador, None)

    def confirmar(self, ws, msg):
        pedido = self.pendentes.get(str(msg.get("id_comando", "")))
        if not pedido or pedido[0] is not ws or pedido[2].done() or msg.get("acao") != pedido[1]:
            return False
        status = msg.get("status")
        texto = msg.get("texto")
        if status not in {"concluido", "encaminhado", "revisao", "permissao", "erro", "indisponivel"} or not isinstance(texto, str) or not 0 < len(texto) <= 600:
            return False
        pedido[2].set_result({"status": status, "texto": texto})
        return True

    def desconectar(self, ws):
        for cliente, _, futuro in tuple(self.pendentes.values()):
            if cliente is ws and not futuro.done():
                futuro.set_result({"status": "sem_confirmacao"})
