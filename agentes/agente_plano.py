"""Executa pedidos validados por etapas; envio ao celular não é confirmação física."""
import asyncio
from collections import OrderedDict
from core.tipos import CategoriaEvento
from servicos.roteamento_pedidos import responder_pedido
from servicos.respostas_acoes import resumir_resultados


class AgentePlano:
    def __init__(self):
        self._processando = set()
        self._concluidos = OrderedDict()

    async def processar(self, evento):
        if evento.categoria != CategoriaEvento.PLANO_SOLICITADO or not evento.metadados.get('pedido_usuario'):
            return
        chave = evento.correlacao_id
        if chave in self._processando or chave in self._concluidos:
            return
        self._processando.add(chave)
        resultados = []
        interrupcao = ''
        try:
            from api.websocket import central_alertas
            etapas = evento.payload.get('etapas', [])
            if not 1 <= len(etapas) <= 6:
                raise ValueError('O pedido não tem uma sequência válida de ações.')
            conexoes = central_alertas.estado_conexoes()
            for etapa in etapas:
                alvo = etapa['alvo']
                if alvo in {'PC', 'MOBILE'} and not conexoes['pc' if alvo == 'PC' else 'mobile']['conectado']:
                    raise ValueError(f'O {"PC" if alvo == "PC" else "celular"} está desconectado. Não iniciei a sequência.')
                if alvo == 'CASA' and not central_alertas.ponte_casa_disponivel():
                    raise ValueError('Preciso de uma ponte conectada à casa. Não iniciei a sequência.')
            async with asyncio.timeout(35):
                for indice, etapa in enumerate(etapas, 1):
                    alvo, comando, parametro = etapa['alvo'], etapa['comando'], etapa['parametro']
                    if alvo == 'PC':
                        resultado = await central_alertas.enviar_comando_pc({
                            'comando': comando, 'parametro': parametro, 'id_comando': etapa['id_comando'],
                            'correlacao_id': chave, 'origem': 'IA', 'abertura_modo': 'pedido', 'abertura_autorizada': True})
                        if resultado and resultado['status'] == 'enviado':
                            resultado = await central_alertas.confirmacoes.aguardar(etapa['id_comando'])
                        status = (resultado or {}).get('status')
                        if status != 'concluido':
                            resultados.append({'etapa': etapa, 'status': status if status in {'pc_offline', 'sem_confirmacao'} else 'erro'})
                            interrupcao = 'Parei por aqui e não fiz o restante.' if indice < len(etapas) else 'Parei por aqui.'
                            break
                        foco = resultado.get('resultado', {}).get('primeiro_plano')
                        resultados.append({'etapa': etapa, 'status': 'concluido', 'foco': foco})
                    elif alvo == 'MOBILE':
                        enviado = await central_alertas.enviar_comando_mobile({
                            'tipo_ws': 'COMANDO_SISTEMA', 'acao': comando, 'parametro': parametro,
                            'correlacao_id': chave, 'id_comando': etapa['id_comando'],
                            'abertura_modo': 'pedido', 'abertura_autorizada': True})
                        resultados.append({'etapa': etapa, 'status': 'enviado' if enviado else 'mobile_offline'})
                        if not enviado:
                            interrupcao = 'Parei por aqui.'
                            break
                    elif alvo == 'CASA':
                        resultado = await central_alertas.executar_casa(etapa['id_comando'], comando, parametro)
                        estado = resultado.get('resultado', {}).get('state')
                        if resultado.get('status') != 'concluido' or estado not in {'on', 'off'}:
                            resultados.append({'etapa': etapa, 'status': 'sem_confirmacao'})
                            interrupcao = 'Parei por aqui.'
                            break
                        resultados.append({'etapa': etapa, 'status': 'concluido', 'estado': estado})
                    else:
                        raise ValueError('Dispositivo da etapa não reconhecido.')
        except TimeoutError:
            interrupcao = 'Demorou mais do que eu esperava, então parei por aqui. A última ação enviada ainda pode terminar.'
        except (ValueError, LookupError) as erro:
            interrupcao = str(erro)
        except Exception:
            interrupcao = 'A conexão falhou e parei por aqui, sem iniciar outras ações.'
        finally:
            self._processando.discard(chave)
            self._concluidos[chave] = True
            while len(self._concluidos) > 100:
                self._concluidos.popitem(last=False)
        await responder_pedido(evento, resumir_resultados(resultados, evento.payload.get('texto_pedido', ''), interrupcao))
