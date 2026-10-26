"""Inferência pelo PC registrado, sem broadcast, portas públicas ou execução de código."""
import asyncio
import json
import uuid
from servicos.consumo_ia import consumo_ia


class PonteIAPC:
    def __init__(self): self.pendentes = {}

    def cliente(self):
        from api.websocket import central_alertas
        ws = central_alertas.pc_master
        return ws if ws is not None and ws.client_state.value == 1 and 'LOCAL_LLM' in central_alertas._capacidades.get(ws, set()) else None

    def disponivel(self): return self.cliente() is not None

    async def gerar(self, prompt, system, max_tokens=900, timeout=50, registrar_uso=True):
        from api.websocket import central_alertas
        ws = self.cliente()
        if ws is None: raise ValueError('O PC com IA local está desconectado.')
        if self.pendentes: raise ValueError('A IA do PC está atendendo outro pedido.')
        if len(prompt) + len(system) > 30000: raise ValueError('Contexto excede a capacidade da IA local.')
        identificador = str(uuid.uuid4())
        futuro = asyncio.get_running_loop().create_future()
        self.pendentes[identificador] = (ws, futuro)
        try:
            if not await central_alertas._enviar_direto(ws, dict(tipo_ws='IA_SOLICITACAO', id=identificador,
                    prompt=prompt, system=system, max_tokens=min(max_tokens, 500))):
                raise ValueError('Conexão com a IA do PC interrompida.')
            resultado = await asyncio.wait_for(futuro, timeout)
            if resultado is None: raise ValueError('A IA do PC não conseguiu responder.')
            if registrar_uso:
                try:
                    await consumo_ia.registrar_local(resultado['modelo'], resultado['entrada'], resultado['saida'])
                except Exception: pass  # Uma falha na métrica não perde a resposta já gerada.
            return resultado['texto']
        finally: self.pendentes.pop(identificador, None)

    def confirmar(self, ws, msg):
        pedido = self.pendentes.get(str(msg.get('id', '')))
        if pedido is None or pedido[0] is not ws or pedido[1].done(): return False
        texto = msg.get('texto')
        valido = msg.get('status') == 'concluido' and isinstance(texto, str) and 0 < len(texto) <= 24000
        try:
            valido = valido and isinstance(json.loads(texto), dict)
            entrada, saida = int(msg.get('entrada', 0)), int(msg.get('saida', 0))
            valido = valido and 0 <= entrada <= 100000 and 0 <= saida <= 10000
        except (ValueError, TypeError): valido = False
        pedido[1].set_result(dict(texto=texto, modelo=str(msg.get('modelo', 'local'))[:150], entrada=entrada, saida=saida) if valido else None)
        return True

    def desconectar(self, ws):
        for cliente, futuro in tuple(self.pendentes.values()):
            if cliente is ws and not futuro.done(): futuro.set_result(None)


ponte_ia_pc = PonteIAPC()
