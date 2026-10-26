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
        self.pendentes[identificador] = (ws, acao, futuro, parametros)
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
        resultado = {'status': status, 'texto': texto}
        if pedido[1] == 'ui.snapshot' and status == 'concluido':
            dados = msg.get('resultado')
            if not self._captura_valida(dados, pedido[3].get('pacote')):
                return False
            resultado['resultado'] = dados
        pedido[2].set_result(resultado)
        return True

    @staticmethod
    def _captura_valida(dados, esperado):
        import re, json
        if not isinstance(dados, dict) or len(json.dumps(dados, ensure_ascii=False)) > 20000:
            return False
        pacote, captura, nodes = dados.get('pacote'), dados.get('captura'), dados.get('nodes')
        if not isinstance(pacote, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+', pacote) or (esperado and pacote != esperado):
            return False
        if not isinstance(captura, str) or not re.fullmatch(r'[a-f0-9-]{36}', captura) or not isinstance(nodes, list) or len(nodes) > 80:
            return False
        ids = set()
        for node in nodes:
            if not isinstance(node, dict) or type(node.get('id')) is not int or not 0 <= node['id'] < 80 or node['id'] in ids:
                return False
            ids.add(node['id'])
            if any(not isinstance(node.get(k), str) or len(node[k]) > 160 for k in ('texto', 'descricao', 'tipo')):
                return False
            if any(type(node.get(k)) is not bool for k in ('clicavel', 'editavel', 'rolavel')):
                return False
        return True

    def desconectar(self, ws):
        for cliente, _, futuro, _ in tuple(self.pendentes.values()):
            if cliente is ws and not futuro.done():
                futuro.set_result({"status": "sem_confirmacao"})
