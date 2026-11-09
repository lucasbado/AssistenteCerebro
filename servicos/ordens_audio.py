"""Ordens de voz e chat para os controles confirmados do Voicemeeter Banana."""
import re
import uuid
from time import monotonic

from core.tipos import OrigemEvento
from servicos.controle_audio import ALVOS_MIXER, SAIDAS, ComandoAudio
from servicos.controle_casa import normalizar
from servicos.linguagem_pedidos import separar_etapas
from servicos.linguagem_relogio import numeros_falados
from servicos.roteamento_pedidos import destino_explicito, dispositivo_origem, responder_pedido

COMANDO_AUDIO = 'audio_controle'
_NOME = r'\bvoice\s*mee?ter\b'
_SAIDA = r'(?:a\s*[1-3]|b\s*[12])'
_ALVO = rf'(?:{_SAIDA}|(?:entrada|canal)\s*[1-5]|microfone|mic)'
_ARTIGO = r'(?:(?:o|a|do|da|na|no) )?'
_VALOR = r'(?:menos |mais |[+-])?\d{1,2}(?:[.,]\d{1,2})?'
_SUBIR = {'aumente', 'aumenta', 'suba', 'sobe'}
_DESCER = {'abaixe', 'abaixa', 'baixe', 'baixa', 'diminua', 'diminui', 'reduza', 'reduz'}
_RELATIVOS = '|'.join(sorted(_SUBIR | _DESCER))
_VERBOS = rf'(?:{_RELATIVOS}|ajuste|defina|coloque|deixe|mute|muta|desmute|desmuta|silencie|ligue|desligue|roteie|mostre|consulte)'
_DIVISOR = re.compile(rf'(?:\s+e\s+(?:depois )?|[,;]\s*(?:depois )?)(?={_VERBOS}\b)')
_AJUDA = ('Diga qual canal do Voicemeeter devo ajustar. Por exemplo, '
          '“abaixe a saída A1 em 3 dB”, “mute o canal 2 no Voicemeeter” ou “mostre o estado do Voicemeeter”.')
_ULTIMO_ALVO = {}


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
    t = re.sub(r'\b(?:saida|bus) (?=[ab]\s*[1-3]\b)', '', t)

    if nomeado and re.fullmatch(r'(?:(?:mostre|consulte|liste) )?(?:(?:o|as) )?(?:status|estado|saidas|como esta)', t):
        return {'operacao': 'ler_mixer'}
    consulta = re.fullmatch(rf'(?:qual (?:e )?o (?:volume|ganho) (?:d[ao] )?|(?:como esta|mostre|consulte) {_ARTIGO})({_ALVO})', t)
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


def _formatar_audio(pedido, resultado):
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
    if status != 'concluido' or audio.get('status') not in {'concluido', 'sem_alteracao'}:
        return 'Não consegui ler o Voicemeeter. Confira se o Banana está aberto no PC.'

    valores = audio.get('depois', {})
    alvo = pedido.alvo
    if pedido.operacao == 'ler_mixer':
        leituras = []
        for canal in (alvo,) if alvo else SAIDAS:
            prefixo = ALVOS_MIXER[canal]
            if f'{prefixo}.Gain' not in valores or f'{prefixo}.Mute' not in valores:
                return 'Não recebi uma leitura completa do Voicemeeter.'
            ganho = f"{valores[f'{prefixo}.Gain']:g}".replace('.', ',')
            mudo = ', no mudo' if valores[f'{prefixo}.Mute'] else ''
            leituras.append(f'{_nome_alvo(canal)} em {ganho} dB{mudo}')
        texto = f"No Voicemeeter, {'; '.join(leituras)}."
        if alvo and alvo.startswith('ENTRADA'):
            rotas = [r for r in SAIDAS if valores.get(f'{ALVOS_MIXER[alvo]}.{r}') == 1]
            texto += f" Está ligado a {', '.join(rotas)}." if rotas else ' Está sem rota de saída.'
        return texto
    campo = pedido.rota or ('Mute' if pedido.operacao == 'mudo_mixer' else 'Gain')
    valor = valores.get(f'{ALVOS_MIXER[alvo]}.{campo}')
    if valor is None:
        return 'Recebi a confirmação do PC, mas o mixer não informou o valor final.'
    nome = _nome_alvo(alvo)
    if campo == 'Gain':
        return f"No Voicemeeter, {nome} ficou em {f'{valor:g}'.replace('.', ',')} dB."
    if campo == 'Mute':
        return f"No Voicemeeter, {nome} {'está no mudo' if valor else 'está com o som ativo'}."
    return f"No Voicemeeter, {nome} {'está ligado à' if valor else 'foi desligado da'} saída {campo}."


async def encaminhar_audio(evento):
    if evento.origem not in {OrigemEvento.USUARIO, OrigemEvento.PC, OrigemEvento.ANDROID}:
        return False
    texto = normalizar(evento.payload.get('texto', ''))
    origem = dispositivo_origem(evento)
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
            partes = separar_etapas(texto, _DIVISOR)
            nomeado = bool(re.search(_NOME, texto))
            acoes = [interpretar_audio(f'{parte} no voicemeeter' if nomeado and not re.search(_NOME, parte) else parte)
                     for parte in partes]
            if not any(acoes):
                return False
            if len(acoes) > 4 or not all(acoes):
                raise ValueError('Posso ajustar até quatro etapas do Voicemeeter de uma vez. Diga o canal de cada uma.')
        if destino_explicito(texto) == 'MOBILE':
            raise ValueError('O Voicemeeter fica no PC. Pode pedir o controle por aqui e indicar o PC.')
        pedidos = [ComandoAudio(id_comando=str(uuid.uuid5(uuid.NAMESPACE_URL, f'ollie:mixer:{evento.correlacao_id}:{i}')), **dados)
                   for i, dados in enumerate(acoes)]
    except ValueError as erro:
        await responder_pedido(evento, _AJUDA if hasattr(erro, 'errors') else str(erro), pergunta=True)
        return True

    from api.websocket import central_alertas
    respostas = []
    for pedido in pedidos:
        resultado = await central_alertas.enviar_comando_pc({
            'comando': COMANDO_AUDIO, 'id_comando': pedido.id_comando, 'correlacao_id': evento.correlacao_id,
            'parametro': pedido.model_dump_json(exclude_none=True),
        }, mixer_explicito=True)
        if (resultado or {}).get('status') == 'enviado':
            resultado = await central_alertas.confirmacoes.aguardar(pedido.id_comando)
        respostas.append(_formatar_audio(pedido, resultado))
        audio = (resultado or {}).get('resultado', {}).get('audio', {})
        if (resultado or {}).get('status') != 'concluido' or audio.get('status') not in {'concluido', 'sem_alteracao'}:
            if len(respostas) < len(pedidos):
                respostas.append('Parei nessa etapa.')
            break
        if pedido.alvo is not None:
            _ULTIMO_ALVO[origem] = (monotonic(), pedido.alvo)
    await responder_pedido(evento, ' '.join(respostas))
    return True
