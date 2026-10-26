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
        if interpretar_controle(texto, dispositivo_origem(evento)):
            await kernel.publicar(evento.clonar(categoria=CategoriaEvento.CELULAR_ACAO_SOLICITADA))
            return
        try:
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
        await responder_pedido(evento, AVISO_LIMITADO +
            ' Para controlar um aparelho, diga, por exemplo: ligue a lanterna; apague a luz; ou abra YouTube no PC.')
