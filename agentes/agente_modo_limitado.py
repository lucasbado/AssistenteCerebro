"""Roteia somente ordens explícitas conhecidas enquanto a persistência está pausada."""
from core.kernel import kernel
from core.tipos import CategoriaEvento, OrigemEvento, TipoAcao
from servicos.disponibilidade import AVISO_LIMITADO
from servicos.controle_celular import interpretar_controle
from servicos.controle_casa import controle_casa
from servicos.plano_pedidos import interpretar_composto, preparar_plano
from servicos.roteamento_pedidos import (
    dispositivo_origem, interpretar_abertura, contexto_pedido, responder_pedido,
)


class AgenteModoLimitado:
    async def processar(self, evento):
        if evento.categoria != CategoriaEvento.SISTEMA_COMANDO_USUARIO or evento.origem not in {
            OrigemEvento.USUARIO, OrigemEvento.ANDROID, OrigemEvento.PC,
        }:
            return
        texto = str(evento.payload.get('texto', ''))
        from servicos.dialogo_controles import dialogo_controles
        if dialogo_controles.continua(dispositivo_origem(evento), texto) or interpretar_controle(dialogo_controles.resolver(dispositivo_origem(evento), texto), dispositivo_origem(evento), evento.timestamp):
            await kernel.publicar(evento.clonar(categoria=CategoriaEvento.CELULAR_ACAO_SOLICITADA))
            return
        try:
            from servicos.roteamento_pedidos import destino_explicito
            from servicos.interpretacao_celular import precisa_apps
            if precisa_apps(texto) and (destino_explicito(texto) == 'MOBILE' or (dispositivo_origem(evento) == 'MOBILE' and destino_explicito(texto) != 'PC')):
                await kernel.publicar(evento.clonar(categoria=CategoriaEvento.CELULAR_ACAO_SOLICITADA))
                return
            plano = interpretar_composto(texto) or interpretar_abertura(texto)
            if plano:
                etapas = preparar_plano(evento, plano['execucao_direta'])
                await kernel.publicar(evento.clonar(categoria=CategoriaEvento.PLANO_SOLICITADO,
                    acao=TipoAcao.NORMAL, payload={'etapas': etapas, 'texto_pedido': texto},
                    metadados=contexto_pedido(evento)))
                return
            casa = controle_casa.interpretar(texto)
            if casa:
                await kernel.publicar(evento.clonar(categoria=CategoriaEvento.CASA_ACAO_SOLICITADA, payload=casa))
                return
        except (ValueError, LookupError) as erro:
            await responder_pedido(evento, str(erro))
            return
        # A limitação da memória não impede interpretar um pedido novo de controle.
        from servicos.datas_agenda import intencao_agenda
        if intencao_agenda(texto) in {'listar', 'lembrete', 'compromisso'}:
            await responder_pedido(evento, AVISO_LIMITADO)
            return
        await kernel.publicar(evento.clonar(categoria=CategoriaEvento.CELULAR_ACAO_SOLICITADA))
