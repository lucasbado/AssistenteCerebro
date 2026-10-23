"""Pontos de entrada da revisão manual e da revisão oferecida por rotinas aprovadas."""
from core.evento import EventoCanonico
from core.kernel import kernel
from core.tipos import CategoriaEvento, OrigemEvento, TipoAcao
from servicos.mensagens import caixa_mensagens


async def registrar_uso(dispositivo):
    await kernel.publicar(EventoCanonico(categoria=CategoriaEvento.SISTEMA_COMANDO_INTERNO,
        origem=OrigemEvento.USUARIO, pacote='sistema.assistencia',
        payload={'tipo': 'ASSISTENCIA_USADA', 'habilidade': 'mensagens', 'acao': 'revisar', 'dispositivo': dispositivo}))


async def oferecer_revisao(evento, nome, dispositivo):
    from api.websocket import central_alertas
    cliente = central_alertas.pc_master if dispositivo == 'PC' else central_alertas.mobile_client
    if cliente is None: return False
    itens = await caixa_mensagens.listar()
    if not itens: return False
    resumo = 'uma mensagem separada' if len(itens) == 1 else f'{len(itens)} mensagens separadas'
    await kernel.publicar(evento.clonar(categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
        acao=TipoAcao.INTENCAO_INTERACAO, origem=OrigemEvento.IA, pacote='sistema.assistencia',
        payload={'tipo_ws': 'NOTIFICACAO', 'titulo': 'Quer revisar suas mensagens?',
            'texto': f'Você tem {resumo} para revisão. Quer dar uma olhada?',
            'acao_tipo': 'MENSAGENS_REVISAR', 'acao_parametro': 'pendentes', 'acao_texto': 'Revisar mensagens',
            'chave_deduplicacao': 'revisar-mensagens:' + dispositivo},
        metadados={'tipo_destino': 'NOTIFICACAO', 'destino_notificacao': dispositivo, 'rotina_aprovada': nome}))
    return True
