"""Ordens de voz e chat para os controles confirmados do Voicemeeter Banana."""
import re
import uuid
from time import monotonic

from core.tipos import OrigemEvento
from servicos.controle_audio import ALVOS_MIXER, SAIDAS, ComandoAudio
from servicos.controle_casa import normalizar
from servicos.linguagem_mixer import (
    VOICEMEETER, VERBOS_ROTA, SUBIR as _SUBIR, DESCER as _DESCER, RELATIVOS as _RELATIVOS,
    VALOR as _VALOR, destino_mixer, interpretar_por_nome,
)
from servicos.linguagem_pedidos import separar_etapas
from servicos.linguagem_relogio import numeros_falados
from servicos.nomes_mixer import SAIDAS_FISICAS, VIRTUAIS, localizar_nome, nome_alvo
from servicos.roteamento_pedidos import destino_explicito, dispositivo_origem, responder_pedido

COMANDO_AUDIO = 'audio_controle'
_NOME = VOICEMEETER
_SAIDA = r'(?:a\s*[1-3]|b\s*[12])'
_ALVO = rf'(?:{_SAIDA}|(?:entrada|canal)\s*[1-5]|microfone|mic)'
_ARTIGO = r'(?:(?:o|a|do|da|na|no) )?'
_VERBOS = rf'(?:{_RELATIVOS}|ajuste|defina|coloque|deixe|mute|muta|desmute|desmuta|silencie|ligue|desligue|roteie|mostre|consulte)'
_DIVISOR = re.compile(rf'(?:\s+e\s+(?:depois )?|[,;]\s*(?:depois )?)(?=(?:{_VERBOS}|{VERBOS_ROTA}|apelide|renomeie|chame)\b)', re.I)
_ORDINAIS = {'primeir': 1, 'segund': 2, 'terceir': 3}
_AJUDA = ('Diga o canal e o ajuste do Voicemeeter. Você pode dizer “mova o Principal para o fone” '
          'ou “quais são os canais do Voicemeeter?”.')
_ULTIMO_ALVO = {}
_PENDENTES = {}
_ULTIMO_PEDIDO = {}
_SIM = {'sim', 'isso', 'pode', 'pode fazer', 'pode sim', 'ok', 'certo'}
_CANCELAR = {'nao', 'cancela', 'cancelar', 'esquece', 'deixa pra la'}
_PERGUNTA_SAIDA = 'Qual saída você quer usar para {canal}? Fone (A1), Echo Dot (A2) ou Samsung (A3)?'


def _alvo(texto):
    compacto = texto.upper().replace(' ', '')
    if compacto in ('MIC', 'MICROFONE'):
        return 'ENTRADA1'
    return f'ENTRADA{compacto[-1]}' if compacto.startswith(('CANAL', 'ENTRADA')) else compacto


def interpretar_audio(texto):
    t = numeros_falados(normalizar(texto))
    nomeado = bool(re.search(_NOME, t))
    if not nomeado and not re.search(rf'\b{_SAIDA}\b', t):
        return None
    t = re.sub(r'^(?:(?:ei )?ollie[, ]+)?(?:por favor[, ]+)?(?:agora[, ]+)?(?:pode )?', '', t)
    t = re.sub(rf'(?:\b(?:no|do|na|da|pelo) (?:o )?)?{_NOME}(?: banana)?\s*[, :]?', '', t)
    t = re.sub(r'\s+(?:no|pelo|pro|para o) (?:meu |seu )?(?:pc|computador|desktop|notebook|celular|android)$', '', t)
    t = ' '.join(t.strip(' ,:').split())
    if nomeado:
        t = re.sub(r'\b(primeir|segund|terceir)[ao] (saida|entrada|canal)\b',
                   lambda m: ('a' if m[2] == 'saida' else 'canal ') + str(_ORDINAIS[m[1]]), t)
    t = re.sub(r'\b(?:saida|bus) (?=[ab]\s*[1-3]\b)', '', t)

    if nomeado and re.fullmatch(r'(?:(?:mostre|consulte|liste) )?(?:(?:o|as) )?(?:status|estado|saidas|como esta)', t):
        return {'operacao': 'ler_mixer'}
    consulta = re.fullmatch(
        rf'(?:qual (?:e )?o (?:volume|ganho) (?:d[ao] )?'
        rf'|(?:como esta|mostre|consulte)(?: tambem)? (?:(?:o )?estado (?:d[ao] )?|{_ARTIGO}))({_ALVO})', t)
    if consulta:
        return {'operacao': 'ler_mixer', 'alvo': _alvo(consulta[1])}
    mudo = re.fullmatch(rf'(mute|muta|mutar|silencie|desmute|desmuta|desmutar|tire do mudo) {_ARTIGO}({_ALVO})', t)
    if mudo:
        return {'operacao': 'mudo_mixer', 'alvo': _alvo(mudo[2]), 'valor': int(mudo[1] in {'mute', 'muta', 'mutar', 'silencie'})}
    rota = re.fullmatch(rf'(roteie|mande|envie|ligue|ative|desligue|desative) {_ARTIGO}({_ALVO}) (?:para|pra|em|na|no|d[ae]) {_ARTIGO}({_SAIDA})', t)
    if rota:
        return {'operacao': 'rota_mixer', 'alvo': _alvo(rota[2]), 'rota': _alvo(rota[3]),
                'valor': int(rota[1] not in {'desligue', 'desative'})}
    ganho = re.fullmatch(rf'(ajuste|defina|coloque|deixe|{_RELATIVOS}) {_ARTIGO}'
                         rf'(?:(?:volume|ganho) (?:d[ao] )?)?({_ALVO}) (para|em|pra|a) ({_VALOR}) (?:db|decibeis?)', t)
    if ganho:
        valor = float(ganho[4].replace('menos ', '-').replace('mais ', '+').replace(',', '.'))
        relativo = ganho[1] in (_SUBIR | _DESCER) and ganho[3] == 'em'
        if relativo:
            valor = abs(valor) if ganho[1] in _SUBIR else -abs(valor)
        return {'operacao': 'ajustar_ganho_mixer' if relativo else 'ganho_mixer', 'alvo': _alvo(ganho[2]), 'valor': valor}
    if nomeado and re.match(rf'^{_VERBOS}\b', t):
        raise ValueError(_AJUDA)
    return None


def _nome_alvo(alvo):
    return f'canal {alvo[-1]}' if alvo.startswith('ENTRADA') else f'saída {alvo}'


def _formatar_audio(pedido, resultado, catalogo=None):
    status = (resultado or {}).get('status')
    audio = (resultado or {}).get('resultado', {}).get('audio', {})
    if status == 'pc_offline':
        return 'O Desk está desconectado. Preciso dele aberto para acessar o Voicemeeter.'
    if status == 'sem_confirmacao':
        return 'O Voicemeeter ainda não confirmou o pedido.'
    if audio.get('status') == 'parcial':
        return 'Enviei o ajuste ao Voicemeeter, mas não consegui confirmar o valor no mixer.'
    if audio.get('status') == 'ocupado':
        return 'O Voicemeeter está atendendo outro ajuste. Tente de novo em instantes.'
    if audio.get('codigo') == 'apelido_em_uso':
        return 'Esse apelido já pertence a outro canal. Diga um nome diferente.'
    if status != 'concluido' or audio.get('status') not in {'concluido', 'sem_alteracao'}:
        return 'Não consegui ler o Voicemeeter. Confira se o Banana está aberto no PC.'

    valores = audio.get('depois', {})
    alvo = pedido.alvo
    if pedido.operacao == 'catalogo_mixer':
        return _mostrar_catalogo(audio['catalogo']) if audio.get('catalogo') else 'Não recebi a lista de canais do mixer.'
    if pedido.operacao == 'apelidar_mixer':
        if audio.get('nome') != pedido.nome:
            return 'Não recebi a confirmação do apelido no Voicemeeter.'
        return f'Apelidei {nome_alvo(alvo, catalogo)} de “{pedido.nome}” no Voicemeeter. Já pode usar esse nome.'
    if pedido.operacao == 'mover_rota_mixer':
        prefixo = ALVOS_MIXER[alvo]
        if any(valores.get(f'{prefixo}.{s}') != int(s == pedido.rota) for s in SAIDAS_FISICAS):
            return 'Não recebi uma confirmação completa das saídas físicas do canal.'
        return f'{nome_alvo(alvo, catalogo)} está saindo por {nome_alvo(pedido.rota, catalogo)}.'
    if pedido.operacao == 'ler_mixer':
        leituras = []
        for canal in (alvo,) if alvo else SAIDAS:
            prefixo = ALVOS_MIXER[canal]
            if f'{prefixo}.Gain' not in valores or f'{prefixo}.Mute' not in valores:
                return 'Não recebi uma leitura completa do Voicemeeter.'
            ganho = f"{valores[f'{prefixo}.Gain']:g}".replace('.', ',')
            mudo = ', no mudo' if valores[f'{prefixo}.Mute'] else ''
            nome = nome_alvo(canal, catalogo) if canal in VIRTUAIS or catalogo else _nome_alvo(canal)
            leituras.append(f'{nome} em {ganho} dB{mudo}')
        texto = f"No Voicemeeter, {'; '.join(leituras)}."
        if alvo and alvo.startswith('ENTRADA'):
            rotas = [nome_alvo(r, catalogo) for r in SAIDAS if valores.get(f'{ALVOS_MIXER[alvo]}.{r}') == 1]
            texto += f" Está ligado a {', '.join(rotas)}." if rotas else ' Está sem rota de saída.'
        return texto
    campo = pedido.rota or ('Mute' if pedido.operacao == 'mudo_mixer' else 'Gain')
    valor = valores.get(f'{ALVOS_MIXER[alvo]}.{campo}')
    if valor is None:
        return 'Recebi a confirmação do PC, mas o mixer não informou o valor final.'
    nome = nome_alvo(alvo, catalogo) if alvo in VIRTUAIS or catalogo else _nome_alvo(alvo)
    if campo == 'Gain':
        return f"No Voicemeeter, {nome} ficou em {f'{valor:g}'.replace('.', ',')} dB."
    if campo == 'Mute':
        return f"No Voicemeeter, {nome} {'está no mudo' if valor else 'está com o som ativo'}."
    return f"No Voicemeeter, {nome} {'está ligado à' if valor else 'foi desligado da'} saída {campo}."


def _mostrar_catalogo(catalogo):
    entradas = []
    for alvo in VIRTUAIS:
        nome_original = 'Voicemeeter Input' if alvo == 'ENTRADA4' else 'Voicemeeter AUX Input'
        destinos = ', '.join(nome_alvo(s, catalogo) for s in catalogo[alvo]['rotas']) or 'nenhuma saída'
        entradas.append(f'{nome_alvo(alvo, catalogo)} ({nome_original}) está ligado a {destinos}.')
    saidas = ', '.join(nome_alvo(s, catalogo) for s in SAIDAS_FISICAS)
    return (' '.join(entradas) + f' As saídas físicas são {saidas}. '
            'Posso trocar a saída de cada canal, acrescentar ou tirar uma rota, consultar ou ajustar o ganho, '
            'colocar no mudo e salvar apelidos. Tente “mova o Principal para o fone” ou “apelide o Auxiliar de Jogo”.')


async def _executar_pedido(evento, pedido):
    from api.websocket import central_alertas
    resultado = await central_alertas.enviar_comando_pc({
        'comando': COMANDO_AUDIO, 'id_comando': pedido.id_comando, 'correlacao_id': evento.correlacao_id,
        'parametro': pedido.model_dump_json(exclude_none=True),
    }, mixer_explicito=True)
    if (resultado or {}).get('status') == 'enviado':
        return await central_alertas.confirmacoes.aguardar(pedido.id_comando)
    return resultado


def _pedido(evento, indice, dados):
    return ComandoAudio(id_comando=str(uuid.uuid5(uuid.NAMESPACE_URL, f'ollie:mixer:{evento.correlacao_id}:{indice}')),
                        **dados)


async def encaminhar_audio(evento):
    if evento.origem not in {OrigemEvento.USUARIO, OrigemEvento.PC, OrigemEvento.ANDROID}:
        return False
    original = str(evento.payload.get('texto') or '').strip()
    texto = normalizar(original)
    origem = dispositivo_origem(evento)
    anterior = monotonic() - _ULTIMO_PEDIDO.get(origem, float('-inf')) < 120
    pendente = _PENDENTES.get(origem)
    if pendente and monotonic() - pendente[0] >= 120:
        _PENDENTES.pop(origem, None)
        pendente = None
    catalogo = None

    async def obter_catalogo():
        nonlocal catalogo
        if catalogo is None:
            pedido = _pedido(evento, 'nomes', {'operacao': 'catalogo_mixer'})
            retorno = await _executar_pedido(evento, pedido)
            catalogo = (retorno or {}).get('resultado', {}).get('audio', {}).get('catalogo', {})
        return catalogo

    try:
        continuacao = re.fullmatch(rf'(?:agora )?({_RELATIVOS}) mais (\d{{1,2}}(?:[.,]\d{{1,2}})?) (?:db|decibeis?)',
                                  numeros_falados(texto))
        if continuacao:
            ultimo = _ULTIMO_ALVO.get(origem)
            if ultimo is None or monotonic() - ultimo[0] > 300:
                raise ValueError(_AJUDA)
            valor = float(continuacao[2].replace(',', '.'))
            acoes = [{'operacao': 'ajustar_ganho_mixer', 'alvo': ultimo[1],
                      'valor': valor if continuacao[1] in _SUBIR else -valor}]
        else:
            partes = separar_etapas(original, _DIVISOR)
            nomeado = bool(re.search(_NOME, texto))
            acoes = []
            for parte in partes:
                trecho = f'{parte} no voicemeeter' if nomeado and not re.search(_NOME, parte, re.I) else parte
                acoes.append(interpretar_por_nome(trecho, anterior) or interpretar_audio(trecho))
            if not any(acoes):
                if pendente:
                    if texto in _CANCELAR:
                        _PENDENTES.pop(origem, None)
                        await responder_pedido(evento, 'Cancelei a troca de saída do Voicemeeter.')
                        return True
                    if texto in _SIM:
                        await responder_pedido(evento, _PERGUNTA_SAIDA.format(canal=nome_alvo(pendente[1])), pergunta=True)
                        return True
                    if len(texto) <= 40:
                        resposta = destino_mixer(texto)
                        if not resposta:
                            resposta = destino_mixer(texto, await obter_catalogo())
                        if resposta in SAIDAS:
                            acoes = [{'operacao': 'rotear_por_nome', 'referencia': pendente[1],
                                      'destino': resposta, 'estado': pendente[2]}]
                if not any(acoes) and anterior and texto in _SIM:
                    await responder_pedido(evento, 'Para continuar no Voicemeeter, diga qual canal ou saída você quer ajustar.')
                    return True
            if not any(acoes):
                _PENDENTES.pop(origem, None)
                _ULTIMO_PEDIDO.pop(origem, None)
                return False
            if len(acoes) > 4 or not all(acoes):
                raise ValueError('Posso ajustar até quatro etapas do Voicemeeter de uma vez. Diga o canal de cada uma.')
        if destino_explicito(texto) == 'MOBILE':
            raise ValueError('O Voicemeeter fica no PC. Pode pedir o controle por aqui e indicar o PC.')
        _ULTIMO_PEDIDO[origem] = monotonic()
        _PENDENTES.pop(origem, None)
        pedidos = []
        for indice, dados in enumerate(acoes):
            referencia = dados.pop('referencia', None)
            if referencia is not None:
                ref = numeros_falados(referencia)
                alvo = localizar_nome(ref)
                if alvo is None:
                    alvo = localizar_nome(ref, await obter_catalogo())
                if alvo is None:
                    raise ValueError(f'Não encontrei o canal “{referencia}” no Voicemeeter. Diga Principal ou Auxiliar.')
                dados['alvo'] = alvo
            if dados['operacao'] == 'rotear_por_nome':
                alvo = dados['alvo']
                if alvo in SAIDAS:
                    raise ValueError('Escolha a entrada que quer redirecionar, como Principal ou Auxiliar.')
                destino = dados.pop('destino')
                estado = dados.pop('estado')
                try:
                    rota = destino_mixer(destino) if destino else None
                    if destino and not rota:
                        rota = destino_mixer(destino, await obter_catalogo())
                except ValueError:
                    if len(acoes) == 1:
                        _PENDENTES[origem] = (monotonic(), alvo, estado)
                    raise
                if rota not in SAIDAS:
                    if len(acoes) == 1:
                        _PENDENTES[origem] = (monotonic(), alvo, estado)
                    await responder_pedido(evento, _PERGUNTA_SAIDA.format(canal=nome_alvo(alvo, catalogo)), pergunta=True)
                    return True
                if estado is None and rota in SAIDAS_FISICAS:
                    dados.update(operacao='mover_rota_mixer', rota=rota)
                else:
                    dados.update(operacao='rota_mixer', rota=rota, valor=1 if estado is None else estado)
            pedidos.append(_pedido(evento, indice, dados))
    except ValueError as erro:
        _ULTIMO_PEDIDO[origem] = monotonic()
        await responder_pedido(evento, _AJUDA if hasattr(erro, 'errors') else str(erro), pergunta=True)
        return True

    respostas = []
    for pedido in pedidos:
        resultado = await _executar_pedido(evento, pedido)
        respostas.append(_formatar_audio(pedido, resultado, catalogo))
        audio = (resultado or {}).get('resultado', {}).get('audio', {})
        if (resultado or {}).get('status') != 'concluido' or audio.get('status') not in {'concluido', 'sem_alteracao'}:
            if len(respostas) < len(pedidos):
                respostas.append('Parei nessa etapa.')
            break
        if pedido.alvo is not None:
            _ULTIMO_ALVO[origem] = (monotonic(), pedido.alvo)
    await responder_pedido(evento, ' '.join(respostas))
    return True
