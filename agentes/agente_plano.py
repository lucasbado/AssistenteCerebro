"""Executa pedidos validados por etapas; envio ao celular não é confirmação física."""
import asyncio
from collections import OrderedDict
from core.tipos import CategoriaEvento
from servicos.roteamento_pedidos import responder_pedido


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
        relatos = []
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
                            motivo = 'o PC desconectou' if status == 'pc_offline' else 'não recebi confirmação do PC' if status == 'sem_confirmacao' else 'o PC informou uma falha'
                            relatos.append(f'{indice}. Parei nesta etapa: {motivo}.')
                            break
                        foco = resultado.get('resultado', {}).get('primeiro_plano')
                        relatos.append(f'{indice}. PC: ' + ('abertura concluída, com a janela em primeiro plano.' if foco is True
                            else 'abertura encaminhada; o Windows não confirmou o foco da janela.' if foco is False else 'comando concluído.'))
                    elif alvo == 'MOBILE':
                        enviado = await central_alertas.enviar_comando_mobile({
                            'tipo_ws': 'COMANDO_SISTEMA', 'acao': comando, 'parametro': parametro,
                            'correlacao_id': chave, 'id_comando': etapa['id_comando'],
                            'abertura_modo': 'pedido', 'abertura_autorizada': True})
                        relatos.append(f'{indice}. ' + ('Pedido enviado ao celular.' if enviado else 'O celular desconectou; interrompi a sequência.'))
                        if not enviado:
                            break
                    elif alvo == 'CASA':
                        resultado = await central_alertas.executar_casa(etapa['id_comando'], comando, parametro)
                        estado = resultado.get('resultado', {}).get('state')
                        if resultado.get('status') != 'concluido' or estado not in {'on', 'off'}:
                            relatos.append(f'{indice}. Não consegui confirmar a luz. Interrompi a sequência.')
                            break
                        relatos.append(f'{indice}. A luz está {"acesa" if estado == "on" else "apagada"}.')
                    else:
                        raise ValueError('Dispositivo da etapa não reconhecido.')
        except TimeoutError:
            relatos.append('A sequência demorou além do esperado. Não iniciei outras etapas; a última ação enviada pode ainda terminar.')
        except (ValueError, LookupError) as erro:
            relatos.append(str(erro))
        except Exception:
            relatos.append('A sequência foi interrompida por uma falha de conexão. Não iniciei outras etapas.')
        finally:
            self._processando.discard(chave)
            self._concluidos[chave] = True
            while len(self._concluidos) > 100:
                self._concluidos.popitem(last=False)
        await responder_pedido(evento, '\n'.join(relatos))
