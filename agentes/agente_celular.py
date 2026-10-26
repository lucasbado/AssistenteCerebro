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
        from servicos.dialogo_controles import dialogo_controles
        chave = dispositivo_origem(evento)
        texto_original = str(evento.payload.get('texto', ''))
        if dialogo_controles.cancelar(chave, texto_original):
            await responder_pedido(evento, 'Beleza, cancelei esse pedido.')
            return
        texto = dialogo_controles.resolver(chave, texto_original)
        pedido = texto
        plano = interpretar_controle(texto, chave, evento.timestamp)
        if not plano or plano.get('interpretar_semanticamente'):
            try:
                from servicos.interpretacao_celular import interpretar_intencao
                plano = await interpretar_intencao(evento, texto)
            except ValueError as erro:
                await responder_pedido(evento, str(erro), True)
                return
            except Exception:
                await responder_pedido(evento, 'A interpretação ficou sem resposta agora. Tente de novo em instantes; não executei esse pedido.')
                return
        if plano.get("esclarecimento"):
            dialogo_controles.guardar(chave, plano)
            dialogo_controles.guardar_semantico(chave, texto, plano)
            await responder_pedido(evento, plano["esclarecimento"], plano.get('pergunta', False))
            return
        dialogo_controles.guardar(chave, plano)
        dialogo_controles.guardar_semantico(chave, texto, plano)
        from api.websocket import central_alertas
        respostas = []
        for etapa in plano["acoes"]:
            if etapa['acao'] == 'app.task':
                from servicos.interpretacao_celular import executar_tarefa_app
                resultado = await executar_tarefa_app(evento, etapa['parametros']['pacote'], pedido)
            else:
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
        if plano.get('nota'):
            respostas.append(plano['nota'])
        await responder_pedido(evento, " ".join(respostas))
