"""Tarefas do usuário e sugestões de mensagens, coordenadas por eventos imutáveis."""
import asyncio
import logging
from datetime import datetime, timezone
from core.kernel import kernel
from core.tipos import CategoriaEvento, OrigemEvento, TipoAcao
from servicos.tarefas import tarefas
from servicos.linguagem_tarefas import interpretar_tarefa, pendencia_mensagem, palavras_alvo
from servicos.datas_agenda import extrair_data, completar_rascunho
from servicos.controle_casa import normalizar
from servicos.roteamento_pedidos import contexto_pedido, dispositivo_origem
from servicos.tempo import horario_local
from servicos.calendario import avisar_celular
from servicos.mensagens import chave_tarefa_mensagem

logger = logging.getLogger(__name__)


class AgenteTarefas:
    def __init__(self): self._tick_lock = asyncio.Lock()

    async def responder(self, evento, texto, itens=(), pergunta=False):
        await kernel.publicar(evento.clonar(categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
            origem=OrigemEvento.IA, acao=TipoAcao.INTENCAO_INTERACAO,
            payload={'tipo_ws': 'CHAT_RESPONSE', 'titulo': 'Ollie', 'texto': texto, 'aguarda_resposta': pergunta,
                'acoes_tarefas': [{'id': i['id'], 'texto': i['titulo'], 'quando': i['quando']} for i in itens[:15]]},
            metadados={**contexto_pedido(evento), 'tipo_destino': 'CHAT'}))

    async def processar(self, evento):
        if evento.categoria == CategoriaEvento.SISTEMA_COMANDO_INTERNO and evento.payload.get('tipo') == 'TICK_TAREFAS':
            await self.avisar_pendentes()
            return
        externo = evento.categoria == CategoriaEvento.NOTIFICACAO
        if not externo and evento.categoria != CategoriaEvento.TAREFA_SOLICITADA: return
        texto = str(evento.payload.get('texto', '')).strip()
        if not texto or (externo and evento.pacote.startswith(('com.example.assistentecell', 'sistema.'))): return
        chave = dispositivo_origem(evento)
        pedido = None
        try:
            if externo:
                if not pendencia_mensagem(texto): return
                data = extrair_data(texto, evento.timestamp)
                if data is None: return
                from servicos.linguagem_tarefas import limpar_alvo
                titulo = limpar_alvo(texto)
                remetente = str(evento.payload.get('titulo', ''))[:150]
                item = await tarefas.salvar(titulo, data['inicio'], data['dia_inteiro'], origem=evento.pacote,
                    contexto=f'{remetente}: {texto}'[:500], confirmar=False,
                    chave_evento=chave_tarefa_mensagem(evento.pacote, remetente, texto, evento.timestamp, evento.payload.get('conversa_ref')))
                if item['estado'] != 'sugestao': return
                await kernel.publicar(evento.clonar(categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
                    acao=TipoAcao.INTENCAO_INTERACAO, origem=OrigemEvento.IA, pacote='sistema.tarefas',
                    payload={'tipo_ws': 'NOTIFICACAO', 'titulo': 'Uma pendência pra revisar',
                        'texto': f'Essa mensagem parece trazer uma tarefa para {item["quando"]}. Quer guardar?',
                        'acao_tipo': 'TAREFA_REVISAR', 'acao_parametro': item['id'], 'acao_texto': 'Revisar tarefa',
                        'chave_deduplicacao': 'tarefa-sugestao:' + item['id']},
                    metadados={**evento.metadados, 'tipo_destino': 'NOTIFICACAO'}))
                return

            contexto = await tarefas.contexto(chave) or {}
            if normalizar(texto).strip(' .!?') in {'cancelar', 'cancela', 'esquece', 'deixa pra la', 'nao', 'nao obrigado'} and contexto.get('pedido'):
                await tarefas.guardar_contexto(chave, None)
                await self.responder(evento, 'Beleza, deixei esse pedido de lado.')
                return
            novo = interpretar_tarefa(texto)
            pedido = novo or contexto.get('pedido')
            if pedido is None: return
            if not novo:
                pedido = dict(pedido)
                if contexto.get('precisa') == 'data': pedido['texto'] = completar_rascunho(pedido['texto'], texto)
                else: pedido['alvo'] = texto

            if pedido['acao'] == 'listar':
                estado = 'concluida' if 'concluid' in normalizar(texto) else 'pendente'
                itens = await tarefas.listar(estado)
                data = extrair_data(texto, evento.timestamp)
                if data:
                    dia = horario_local(data['inicio']).date()
                    itens = [i for i in itens if i['prazo'] and horario_local(datetime.fromisoformat(i['prazo'])).date() == dia]
                resposta = 'Nenhuma tarefa nessa lista por enquanto.' if not itens else 'Aqui estão suas tarefas:\n' + '\n'.join(
                    f'• {i["titulo"]} — {i["quando"]}' + (' (prazo vencido)' if i['atrasada'] else '') for i in itens[:15])
                await tarefas.guardar_contexto(chave, {'referencia': itens[0]['id']} if len(itens) == 1 else None)
                await self.responder(evento, resposta, itens)
                return

            if pedido['acao'] == 'criar':
                if not pedido['alvo']:
                    await tarefas.guardar_contexto(chave, {'pedido': pedido, 'precisa': 'titulo'})
                    await self.responder(evento, 'O que você quer colocar na lista de tarefas?', pergunta=True)
                    return
                data = extrair_data(pedido['texto'], evento.timestamp, proxima_ocorrencia=True)
                item = await tarefas.salvar(pedido['alvo'], data['inicio'] if data else None, data['dia_inteiro'] if data else False,
                    chave_evento='pedido:' + evento.correlacao_id)
                await tarefas.guardar_contexto(chave, {'referencia': item['id']})
                await avisar_celular()
                await self.responder(evento, f'Anotei: {item["titulo"]}. ' + (f'Prazo: {item["quando"]}.' if data else 'Ficou sem prazo por enquanto.'), [item])
                return

            itens = await tarefas.listar('abertas')
            alvo = normalizar(pedido.get('alvo', '')).strip(' .!?')
            identificador = contexto.get('tarefa_id') if not novo else None
            if alvo in {'isso', 'essa', 'esta', 'essa tarefa', 'esta tarefa'}: identificador = contexto.get('referencia')
            if not novo and contexto.get('candidatos'):
                ordinais = {'primeira': 0, 'a primeira': 0, '1': 0, 'segunda': 1, 'a segunda': 1, '2': 1, 'terceira': 2, 'a terceira': 2, '3': 2}
                indice = ordinais.get(normalizar(texto).strip(' .!?'))
                if indice is not None and indice < len(contexto['candidatos']): identificador = contexto['candidatos'][indice]
            palavras = palavras_alvo(alvo)
            candidatos = [i for i in itens if i['id'] == identificador] if identificador else [i for i in itens if palavras and palavras <= palavras_alvo(i['titulo'])]
            if len(candidatos) != 1:
                await tarefas.guardar_contexto(chave, {'pedido': pedido, 'precisa': 'alvo', 'candidatos': [i['id'] for i in candidatos[:15]]})
                await self.responder(evento, 'Qual tarefa você quer? Diga o nome completo ou toque na tarefa abaixo.' if candidatos else
                    'Não encontrei uma tarefa aberta com esse nome. Como ela aparece na sua lista?', candidatos, pergunta=True)
                return
            item = candidatos[0]
            data = extrair_data(pedido['texto'], evento.timestamp, proxima_ocorrencia=True) if pedido['acao'] == 'adiar' else None
            if pedido['acao'] == 'adiar' and data is None:
                await tarefas.guardar_contexto(chave, {'pedido': pedido, 'precisa': 'data', 'tarefa_id': item['id']})
                await self.responder(evento, f'Pra quando você quer adiar “{item["titulo"]}”?', [item], pergunta=True)
                return
            item = await tarefas.alterar(item['id'], pedido['acao'], data['inicio'] if data else None,
                data['dia_inteiro'] if data else False, versao=item['versao'])
            await avisar_celular()
            await tarefas.guardar_contexto(chave, {'referencia': item['id']})
            respostas = {'concluir': f'Feito, marquei “{item["titulo"]}” como concluída.',
                'aceitar': f'Guardei “{item["titulo"]}” nas suas tarefas.',
                'descartar': f'Tirei “{item["titulo"]}” das suas pendências.',
                'adiar': f'Adiei “{item["titulo"]}” para {item["quando"]}.'}
            await self.responder(evento, respostas[pedido['acao']], [item])
        except (ValueError, LookupError) as erro:
            if not externo:
                await tarefas.guardar_contexto(chave, {'pedido': pedido, 'precisa': 'data'} if pedido else None)
                await self.responder(evento, str(erro), pergunta=True)
        except Exception:
            logger.exception('Falha nas tarefas')
            if not externo: await self.responder(evento, 'Não consegui atualizar suas tarefas agora. Tenta de novo daqui a pouco.')

    async def avisar_pendentes(self):
        from api.websocket import central_alertas
        async with self._tick_lock:
            for item in await tarefas.pendentes_aviso():
                atual = await tarefas.obter(item['id'])
                if atual['estado'] != 'pendente' or atual['versao'] != item['versao']: continue
                enviado = await central_alertas.enviar_lembrete_agenda({'tipo_ws': 'NOTIFICACAO',
                    'id': 'tarefa:' + item['id'], 'correlacao_id': item['id'], 'titulo': 'Uma tarefa chegou ao prazo',
                    'texto': f'{item["titulo"]} — {item["quando"]}', 'urgencia': 'ALTA',
                    'acao_tipo': 'TAREFA_REVISAR', 'acao_parametro': item['id'], 'acao_texto': 'Ver tarefa', 'origem_sistema': 'OLLIE'})
                if enviado: await tarefas.marcar_aviso(item['id'], item['versao'])
