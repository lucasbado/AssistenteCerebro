"""Separa ordens sem cortar consultas, texto citado ou nomes com 'e'."""
import re

VERBOS = r'(?:abre|abra|abrir|acesse|acessa|acessar|entre|visite|inicie|pesquise|pesquisa|busque|procure|procura|ligue|liga|desligue|desliga|apaga|apague|acenda|alterna|alterne|mute|mutar|ajuste|coloque|execute)\b'
SEPARADOR = re.compile(r'(?:\s+e\s+(?:depois\s+)?|,?\s+(?:depois|em seguida)\s+|;\s*)(?=(?:por favor\s+)?' + VERBOS + ')', re.I)


def separar_etapas(texto):
    texto = str(texto)
    protegidos, aspas, parenteses = set(), None, 0
    for indice, caractere in enumerate(texto):
        if aspas:
            if caractere == ('”' if aspas == '“' else aspas) and (not indice or texto[indice-1] != '\\'):
                aspas = None
        elif caractere in {'"', '“'}:
            aspas = caractere
        elif caractere == "'" and not (indice and indice + 1 < len(texto) and texto[indice-1].isalnum() and texto[indice+1].isalnum()):
            aspas = caractere
        if not aspas:
            parenteses += 1 if caractere == '(' else -1 if caractere == ')' and parenteses else 0
        if aspas or parenteses:
            protegidos.add(indice)
    partes, inicio = [], 0
    for match in SEPARADOR.finditer(texto):
        if match.start() not in protegidos:
            partes.append(texto[inicio:match.start()].strip(' ,;'))
            inicio = match.end()
    partes.append(texto[inicio:].strip(' ,;'))
    return [p for p in partes if p]
