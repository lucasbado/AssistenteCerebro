"""Interpreta nomes e destinos do mixer sem confundi-los com ordens do Windows."""
import re

from servicos.controle_casa import normalizar
from servicos.linguagem_relogio import numeros_falados
from servicos.nomes_mixer import SAIDAS, VIRTUAIS, localizar_nome

VOICEMEETER = r'\bvoice[e ]*m[e]+ter\b'
VERBOS_ROTA = r'(?:coloque|coloca|mova|move|mude|muda|troque|troca|passe|passa|bote|bota|jogue|joga|direcione|mande|manda|envie|roteie|deixe|deixa|ative|ligue|liga|desative|desligue|desliga)'
_LIGACAO = r'\s+(?:(?:para|pra) (?:sair|tocar) (?:(?:so|somente) )?(?:no|na|por|pelo|pela)|no|na|para|pra|pro|por|pelo|pela|em)\s+'
_MUDO = r'(?:mute|muta|mutar|silencie|desmute|desmuta|desmutar|tire do mudo)'
_PREFIXO = r'^(?:(?:ei )?ollie[, ]+)?(?:por favor[, ]+)?(?:agora[, ]+)?(?:pode )?'
SUBIR = {'aumente', 'aumenta', 'suba', 'sobe'}
DESCER = {'abaixe', 'abaixa', 'baixe', 'baixa', 'diminua', 'diminui', 'reduza', 'reduz'}
RELATIVOS = '|'.join(sorted(SUBIR | DESCER))
VALOR = r'(?:menos |mais |[+-])?\d{1,2}(?:[.,]\d{1,2})?'


def _sem_contexto(texto):
    texto = re.sub(r'\s+(?:no|pelo) (?:meu |seu )?(?:pc|computador|desktop|notebook|celular|android)$', '', texto, flags=re.I)
    return re.sub(rf'\s+(?:no|do|pelo|com) (?:o )?{VOICEMEETER}(?: banana)?$', '', texto, flags=re.I).strip()


def destino_mixer(texto, catalogo=None):
    destino, *complemento = re.split(r'\s+que e\s+', normalizar(texto), maxsplit=1)
    alvo = localizar_nome(numeros_falados(destino), catalogo)
    apelido = localizar_nome(numeros_falados(complemento[0]), catalogo) if complemento else None
    if alvo and apelido and alvo != apelido:
        raise ValueError(f'O código {alvo} e o apelido indicam saídas diferentes. Qual você quer usar?')
    return alvo


def interpretar_por_nome(texto, em_contexto=False):
    texto = texto.strip().rstrip(' .!?')
    texto = re.sub(_PREFIXO, '', texto, flags=re.I)
    nomeado = bool(re.search(VOICEMEETER, texto, re.I))
    t = _sem_contexto(numeros_falados(normalizar(texto)))
    if nomeado and re.fullmatch(r'(?:(?:o que (?:voce )?(?:pode|consegue) fazer|quais (?:sao )?(?:os )?(?:comandos|canais|apelidos)|(?:liste|mostre) (?:os )?(?:canais|apelidos)|(?:ajuda|comandos|canais|apelidos)))(?: (?:no|do))?$', t):
        return {'operacao': 'catalogo_mixer'}

    apelido = re.fullmatch(r'(?:apelide|chame|renomeie|de o apelido para) (.+?) (?:de|para|pra|como) (.+)',
                           _sem_contexto(texto), flags=re.I)
    if not apelido:
        apelido = re.fullmatch(r'(?:dê|de) o apelido (.+?) (?:para|pro|pra) (.+)', _sem_contexto(texto), flags=re.I)
        alvo, nome = (apelido[2], apelido[1]) if apelido else (None, None)
    else:
        alvo, nome = apelido.groups()
    if alvo and (nomeado or em_contexto or localizar_nome(numeros_falados(alvo))):
        return {'operacao': 'apelidar_mixer', 'referencia': alvo, 'nome': nome.strip(' "“”')}

    antecipado = re.fullmatch(rf'(.+?)[, ]+({VERBOS_ROTA}) (?:ele|ela|o audio) (?:para|pra) (?:sair|tocar)(?: (?:(?:so|somente) )?(?:no|na|por|pelo|pela) (.+))?', t)
    rota = re.fullmatch(rf'({VERBOS_ROTA}) (.+?){_LIGACAO}(.+)', t) if not antecipado else None
    incompleto = re.fullmatch(rf'({VERBOS_ROTA}) (?:onde sai )?(.+?)(?: (?:para|pra) (?:sair|tocar))?', t)
    if antecipado:
        canal, verbo, destino = antecipado.groups()
    elif rota:
        verbo, canal, destino = rota.groups()
    elif incompleto:
        verbo, canal = incompleto.groups()
        destino = None
    else:
        verbo = canal = destino = None
    if canal:
        canal = re.sub(r'\s+tambem$', '', canal)
        canal = re.sub(r'^(?:(?:o|a) )?(?:audio|som|saida|rota) d[oa] ', '', canal)
        fixo = localizar_nome(canal)
        saida = destino and re.split(r'\s+que e\s+', destino, maxsplit=1)[0]
        if nomeado or fixo in VIRTUAIS or (saida and localizar_nome(saida) in SAIDAS):
            # O parser antigo continua cuidando de ganho e mudo por código.
            if not re.search(r'\b(?:db|decibeis?)$', t):
                estado = (1 if verbo in {'ative', 'ligue', 'liga', 'roteie'} else
                          0 if verbo in {'desative', 'desligue', 'desliga'} else None)
                return {'operacao': 'rotear_por_nome', 'referencia': canal, 'destino': destino, 'estado': estado}

    consulta = re.fullmatch(r'(?:onde (?:sai|toca)|(?:por|em) (?:onde|qual saida) (?:esta )?(?:saindo|toca|sai)|(?:qual (?:e )?a )?saida (?:d[oa] )?|mostre (?:as )?rotas (?:d[oa] )?|qual (?:e )?o (?:volume|ganho) (?:d[ao] )?|como esta) (.+)', t)
    if consulta and (nomeado or em_contexto or localizar_nome(consulta[1]) in VIRTUAIS + SAIDAS):
        return {'operacao': 'ler_mixer', 'referencia': consulta[1]}
    mudo = re.fullmatch(rf'({_MUDO}) (.+)', t)
    if mudo and (nomeado or em_contexto or localizar_nome(mudo[2]) in VIRTUAIS + SAIDAS):
        return {'operacao': 'mudo_mixer', 'referencia': mudo[2],
                'valor': int(mudo[1] in {'mute', 'muta', 'mutar', 'silencie'})}
    ganho = re.fullmatch(rf'(ajuste|defina|coloque|deixe|{RELATIVOS}) (.+?) (para|em|pra|a) ({VALOR}) (?:db|decibeis?)', t)
    if ganho:
        alvo = re.sub(r'^(?:(?:o|a) )?(?:volume|ganho) d[ao] ', '', ganho[2])
        if nomeado or em_contexto or localizar_nome(alvo) in VIRTUAIS + SAIDAS:
            valor = float(ganho[4].replace('menos ', '-').replace('mais ', '+').replace(',', '.'))
            relativo = ganho[1] in (SUBIR | DESCER) and ganho[3] == 'em'
            if relativo:
                valor = abs(valor) if ganho[1] in SUBIR else -abs(valor)
            return {'operacao': 'ajustar_ganho_mixer' if relativo else 'ganho_mixer',
                    'referencia': alvo, 'valor': valor}
    return None
