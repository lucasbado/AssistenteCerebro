import re
from core.kernel import kernel
from core.tipos import CategoriaEvento, TipoAcao, OrigemEvento
from servicos.mensagens import caixa_mensagens
from servicos.controle_casa import normalizar
from servicos.roteamento_pedidos import contexto_pedido, dispositivo_origem
from servicos.assistencia_mensagens import registrar_uso


class AgenteMensagens:
    async def processar(self, evento):
        if evento.categoria == CategoriaEvento.NOTIFICACAO:
            await caixa_mensagens.registrar(evento.pacote, evento.payload, evento.timestamp)
            return
        if evento.categoria == CategoriaEvento.SISTEMA_COMANDO_INTERNO:
            await caixa_mensagens.limpar_antigas()
            return
        texto = str(evento.payload.get('texto', ''))
        itens = await caixa_mensagens.listar()
        await registrar_uso(dispositivo_origem(evento))
        match = re.search(r'prepar(?:e|a|ar) (?:uma )?resposta para (.+?)(?: (?:dizendo|falando) (.+))?$', texto.strip(' .!?'), re.I)
        if match:
            alvo, orientacao = normalizar(match[1]), match[2] or ''
            candidatos = [i for i in itens if normalizar(i['remetente']) == alvo]
            if len(candidatos) == 1:
                i = candidatos[0]
                try:
                    item = await caixa_mensagens.preparar(i['id'], i['versao'], orientacao)
                    resposta = f'Rascunho para {item["remetente"]}:\n“{item["rascunho"]}”\nConfira antes de copiar para a conversa.'
                    itens = [item]
                except Exception:
                    resposta = 'Não consegui preparar agora. Você pode abrir a mensagem e escrever seu rascunho.'
            else:
                itens = candidatos or itens
                resposta = 'Escolha a mensagem na caixa de revisão para eu preparar a resposta certa.'
        else:
            resposta = 'Nenhuma mensagem separada para revisão por enquanto.' if not itens else 'Separei estas mensagens para você revisar:\n' + '\n'.join(
                f'• {i["remetente"]} — {", ".join(i["sinais"])} ({i["quando"]})' for i in itens[:10]) + '\nA notificação não permite confirmar se você já respondeu no aplicativo.'
        await kernel.publicar(evento.clonar(categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
            acao=TipoAcao.INTENCAO_INTERACAO, origem=OrigemEvento.IA,
            payload={'tipo_ws': 'CHAT_RESPONSE', 'texto': resposta, 'titulo': 'Ollie', 'aguarda_resposta': False,
                'acoes_mensagens': [{'id': i['id'], 'texto': i['remetente']} for i in itens[:10]]},
            metadados={**contexto_pedido(evento), 'tipo_destino': 'CHAT'}))
