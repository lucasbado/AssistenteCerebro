"""Coordena controles explícitos e responde somente depois do executor Android."""
from collections import OrderedDict
from core.tipos import CategoriaEvento, OrigemEvento
from servicos.controle_celular import interpretar_controle, validar_acao
from servicos.roteamento_pedidos import dispositivo_origem, responder_pedido


class AgenteCelular:
    def __init__(self):
        self._processando = set()
        self._concluidos = OrderedDict()

    async def processar(self, evento):
        if evento.categoria != CategoriaEvento.CELULAR_ACAO_SOLICITADA or evento.origem not in {OrigemEvento.USUARIO, OrigemEvento.ANDROID, OrigemEvento.PC}:
            return
        chave = evento.correlacao_id
        if chave in self._processando or chave in self._concluidos:
            return
        self._processando.add(chave)
        try:
            await self._processar_pedido(evento)
        finally:
            self._processando.discard(chave)
            self._concluidos[chave] = True
            while len(self._concluidos) > 200:
                self._concluidos.popitem(last=False)

    async def _processar_pedido(self, evento):
        # Reinterpreta a ordem original; nunca aceita ações injetadas em um payload derivado.
        plano = interpretar_controle(evento.payload.get("texto", ""), dispositivo_origem(evento))
        if not plano:
            return
        if plano.get("esclarecimento"):
            await responder_pedido(evento, plano["esclarecimento"])
            return
        from api.websocket import central_alertas
        respostas = []
        for etapa in plano["acoes"]:
            validar_acao(etapa["acao"], etapa["parametros"])
            resultado = await central_alertas.executar_celular(etapa["acao"], etapa["parametros"])
            status = resultado.get("status")
            texto = resultado.get("texto") or {
                "offline": "O celular está desconectado da Ollie.",
                "atualizar": "O celular está conectado, mas precisa do APK com os novos controles.",
                "ocupado": "O celular já está atendendo vários pedidos. Tente em instantes.",
                "sem_confirmacao": "Não recebi confirmação do celular. O pedido pode ter sido executado; não vou repetir automaticamente.",
            }.get(status, "Não consegui confirmar esse controle no celular.")
            respostas.append(texto)
            if status != "concluido":
                if len(plano["acoes"]) > len(respostas):
                    respostas.append("Parei as próximas etapas para você resolver essa primeiro.")
                break
        await responder_pedido(evento, " ".join(respostas))
