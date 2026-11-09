"""Nomes falados para os canais do Voicemeeter Banana."""
import re

from servicos.linguagem_relogio import numeros_falados

SAIDAS = ('A1', 'A2', 'A3', 'B1', 'B2')
SAIDAS_FISICAS = SAIDAS[:3]
VIRTUAIS = ('ENTRADA4', 'ENTRADA5')
ALVOS_MIXER = {**{saida: f'Bus[{i}]' for i, saida in enumerate(SAIDAS)},
               **{f'ENTRADA{i + 1}': f'Strip[{i}]' for i in range(5)}}
NOMES = {
    'ENTRADA4': ('Principal', 'Voicemeeter Input', 'Voicemeeter VAIO', 'VAIO', 'canal principal'),
    'ENTRADA5': ('Auxiliar', 'Voicemeeter AUX Input', 'Voicemeeter AUX', 'AUX Input', 'AUX', 'canal auxiliar'),
    'A1': ('Fone', 'Headset', 'Fone de ouvido'),
    'A2': ('Echo Dot', 'Alexa'),
    'A3': ('Samsung',),
}


def nome_falado(texto):
    nome = numeros_falados(texto)
    nome = re.sub(r'\bvoice[e ]*m[e]+ter\b', 'voicemeeter', nome)
    return re.sub(r'^(?:(?:o|a(?!\s+[1-3]\b)|no|na|do|da|pro|pra|para)\s+)+', '', nome).strip(' "“”')


def localizar_nome(texto, catalogo=None):
    nome = nome_falado(texto)
    codigo = re.fullmatch(r'(?:(?:saida|bus)\s*)?([ab])\s*([1-3])', nome)
    if codigo:
        alvo = (codigo[1] + codigo[2]).upper()
        return alvo if alvo in SAIDAS else None
    canal = re.fullmatch(r'(?:canal|entrada)\s*([1-5])', nome)
    if canal:
        return f'ENTRADA{canal[1]}'
    if nome in ('microfone', 'mic'):
        return 'ENTRADA1'

    fixo = next((alvo for alvo, aliases in NOMES.items() if nome in map(nome_falado, aliases)), None)
    if fixo:
        return fixo
    achados = [alvo for alvo, info in (catalogo or {}).items()
               if nome and nome in {nome_falado(info.get(campo, '')) for campo in ('apelido', 'rotulo', 'dispositivo')}]
    if len(achados) > 1:
        raise ValueError('Esse nome identifica mais de um canal. Use o código da saída ou o número da entrada.')
    return achados[0] if achados else None


def nome_alvo(alvo, catalogo=None):
    info = (catalogo or {}).get(alvo, {})
    apelido = info.get('apelido') or info.get('rotulo') or (NOMES.get(alvo) or ('',))[0]
    if alvo in SAIDAS:
        return f'{apelido} ({alvo})' if apelido else f'saída {alvo}'
    return apelido or f'canal {alvo[-1]}'


def apelido_valido(nome):
    return (isinstance(nome, str) and 1 <= len(nome) <= 32 and nome == nome.strip()
            and bool(re.fullmatch(r'[\w .-]+', nome)) and any(c.isalnum() for c in nome))
