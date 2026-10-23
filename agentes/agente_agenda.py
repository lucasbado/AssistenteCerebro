"""Datas recebidas são sugestões; só uma ordem ou confirmação do usuário agenda."""
import asyncio
import logging
from datetime import datetime, timezone
from core.evento import EventoCanonico
from core.kernel import kernel
from core.tipos import CategoriaEvento, OrigemEvento, TipoAcao
from servicos.agenda import agenda
from servicos.tarefas import tarefas
from servicos.calendario import avisar_celular
from servicos.datas_agenda import extrair_data, intencao_agenda, titulo_sem_data, completar_rascunho
from servicos.controle_casa import normalizar
from servicos.roteamento_pedidos import contexto_pedido, dispositivo_origem
import re

logger = logging.getLogger(__name__)
EVENTOS = re.compile(r'\b(?:reuniao|consulta|dentista|aniversario|prova|entrevista|voo|viagem|compromisso|entrega|prazo|importante|encontro)\b')


class AgenteAgenda:
    def __init__(self): self._tick_lock = asyncio.Lock()

    async def responder(self, evento, texto, item=None, pergunta=False, tarefas_itens=()):
        acoes = [] if item is None else [{'id': item['id'], 'texto': 'Revisar alarme' if item['tipo'] == 'alarme' else 'Ver na agenda',
            'quando': item['quando'], 'tipo': item['tipo']}]
        await kernel.publicar(evento.clonar(categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
            acao=TipoAcao.INTENCAO_INTERACAO, origem=OrigemEvento.IA,
            payload={'tipo_ws': 'CHAT_RESPONSE', 'titulo': 'Ollie', 'texto': texto,
                     'aguarda_resposta': pergunta, 'acoes_agenda': acoes,
                     'acoes_tarefas': [{'id': i['id'], 'texto': i['titulo'], 'quando': i['quando']} for i in tarefas_itens[:15]]},
            metadados={**contexto_pedido(evento), 'tipo_destino': 'CHAT'}))

    async def processar(self, evento):
        if evento.categoria == CategoriaEvento.SISTEMA_COMANDO_INTERNO and evento.payload.get('tipo') == 'TICK_AGENDA':
            await self.avisar_pendentes()
            return
        externo = evento.categoria == CategoriaEvento.NOTIFICACAO
        if not externo and evento.categoria != CategoriaEvento.AGENDA_SOLICITADA: return
        texto = str(evento.payload.get('texto', ''))
        if not texto or (externo and evento.pacote.startswith(('com.example.assistentecell', 'sistema.'))): return
        tipo = None if externo else intencao_agenda(texto)
        try:
            chave = dispositivo_origem(evento)
            if not externo:
                if normalizar(texto).strip(' .!?') in {'cancelar', 'cancela', 'deixa pra la', 'esquece', 'nao quero mais'}:
                    await agenda.limpar_rascunho(chave)
                    await self.responder(evento, 'Beleza, não marquei esse pedido.')
                    return
                rascunho = await agenda.rascunho(chave)
                if rascunho and not tipo:
                    texto = completar_rascunho(rascunho, texto)
                    tipo = intencao_agenda(texto)
                elif tipo:
                    await agenda.limpar_rascunho(chave)
            if tipo == 'listar':
                itens = [i for i in await agenda.listar() if i['estado'] != 'sugestao']
                pendencias = [i for i in await tarefas.listar('pendente') if i['prazo']]
                from servicos.tempo import horario_local
                filtro = extrair_data(texto, evento.timestamp)
                if filtro:
                    dia = horario_local(filtro['inicio']).date()
                    itens = [i for i in itens if horario_local(datetime.fromisoformat(i['inicio'])).date() == dia]
                    pendencias = [i for i in pendencias if horario_local(datetime.fromisoformat(i['prazo'])).date() == dia]
                resposta = 'Sua agenda tá livre por enquanto.' if not itens else 'Aqui está o que você guardou:\n' + '\n'.join(
                    f'• {i["titulo"]} — {i["quando"]}' + (' (despertador: revise no celular)' if i['tipo'] == 'alarme' else '') for i in itens[:15])
                if pendencias:
                    resposta = (resposta + '\n\n' if itens else '') + 'Tarefas com prazo:\n' + '\n'.join(
                        f'• {i["titulo"]} — {i["quando"]}' + (' (prazo vencido)' if i['atrasada'] else '') for i in pendencias[:15])
                await self.responder(evento, resposta, tarefas_itens=pendencias)
                return
            if externo and (not EVENTOS.search(normalizar(texto)) or re.search(r'\b(?:cancelad[oa]|remarcad[oa]|nao vai|nao sera)\b', normalizar(texto))): return
            if externo:
                from servicos.linguagem_tarefas import pendencia_mensagem
                if pendencia_mensagem(texto): return
            data = extrair_data(texto, evento.timestamp, proxima_ocorrencia=not externo)
            if data is None:
                if not externo:
                    await agenda.guardar_rascunho(chave, texto)
                    await self.responder(evento, 'Pra qual dia e horário você quer?', pergunta=True)
                return
            if tipo in {'alarme', 'lembrete'} and data['dia_inteiro']:
                await agenda.guardar_rascunho(chave, texto)
                await self.responder(evento, 'Que horas você quer que o despertador toque?' if tipo == 'alarme' else 'Que horas você quer receber o lembrete?', pergunta=True)
                return
            titulo = titulo_sem_data(texto) or ('Despertador da Ollie' if tipo == 'alarme' else '')
            if not titulo:
                if not externo:
                    await agenda.guardar_rascunho(chave, texto)
                    await self.responder(evento, 'O que você quer guardar nessa data?', pergunta=True)
                return
            item = await agenda.salvar(tipo or 'compromisso', titulo, data['inicio'], data['dia_inteiro'],
                origem=evento.pacote if externo else 'pedido', confirmar=tipo is not None,
                antecedencia_minutos=0)
            if not externo: await agenda.limpar_rascunho(chave)
            if not externo and tipo and tipo != 'alarme': await avisar_celular()
            if externo:
                if item['estado'] != 'sugestao': return
                await kernel.publicar(evento.clonar(categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
                    acao=TipoAcao.INTENCAO_INTERACAO, origem=OrigemEvento.IA, pacote='sistema.agenda',
                    payload={'tipo_ws': 'NOTIFICACAO', 'titulo': 'Uma data pra guardar',
                        'texto': f'Vi “{titulo}” para {item["quando"]}. Quer guardar na agenda?',
                        'acao_tipo': 'AGENDA_REVISAR', 'acao_parametro': item['id'], 'acao_texto': 'Revisar data',
                        'chave_deduplicacao': f'agenda:{item["id"]}'}, metadados={**evento.metadados, 'tipo_destino': 'NOTIFICACAO'}))
            elif tipo == 'alarme':
                await self.responder(evento, f'Preparei o despertador para {item["quando"]}. Toque em “Revisar alarme” no celular pra conferir no relógio. Ainda não tenho confirmação de que ele foi ativado.', item)
            elif tipo:
                await self.responder(evento, f'Guardei {titulo} para {item["quando"]} na sua agenda.' +
                    (' Ficou como dia inteiro, sem horário definido.' if item['dia_inteiro'] else ''), item)
            else:
                await self.responder(evento, f'Isso parece importante: {titulo}, em {item["quando"]}. Deixei como sugestão pra você revisar e salvar.', item)
        except (ValueError, LookupError) as erro:
            if not externo:
                await agenda.guardar_rascunho(chave, texto)
                await self.responder(evento, str(erro), pergunta=True)
        except Exception:
            logger.exception('Falha na agenda')
            if not externo: await self.responder(evento, 'Não consegui salvar na agenda agora. Não vou dizer que ficou marcado sem ter certeza.')

    async def avisar_pendentes(self):
        from api.websocket import central_alertas
        async with self._tick_lock:
            for item in await agenda.pendentes_aviso():
                enviado = await central_alertas.enviar_lembrete_agenda({
                    'tipo_ws': 'NOTIFICACAO', 'id': 'agenda:' + item['id'], 'correlacao_id': item['id'],
                    'titulo': 'Lembrete da Ollie', 'texto': f'{item["titulo"]} — {item["quando"]}', 'urgencia': 'ALTA',
                    'acao_tipo': 'AGENDA_REVISAR', 'acao_parametro': item['id'], 'acao_texto': 'Ver compromisso',
                    'origem_sistema': 'OLLIE'})
                if enviado: await agenda.marcar_aviso(item['id'])
