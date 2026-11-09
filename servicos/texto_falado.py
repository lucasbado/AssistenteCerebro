"""Adapta a apresentação do texto à escuta, sem modificar a resposta no chat."""
import re


def preparar_fala(texto: str) -> str:
    texto = re.sub(r'(?m)^[ \t]*```[^\n]*(?:\n|$)', '', texto)
    texto = re.sub(r'!?\[([^\[\]\n]+)\]\(https?://[^\s)]+\)', r'\1', texto)
    texto = re.sub(r'(?m)^[ \t]*(?:#{1,6}|>|[-*+])[ \t]+', '', texto)
    texto = re.sub(r'(\*\*|__|~~)(?=\S)([^\n]+?)(?<=\S)\1', r'\2', texto)
    texto = re.sub(r'`([^`\n]+)`', r'\1', texto)
    texto = re.sub(r'(?<=\d)[ \t]*%(?![\w])', ' por cento', texto)
    texto = re.sub(r'(?<=\d)\s*°\s*C\b', ' graus Celsius', texto)
    linhas = [linha.strip() for linha in texto.splitlines() if linha.strip()]
    return ' '.join(linha if linha.endswith(('.', '?', '!', '…', ',', ';')) or indice == len(linhas) - 1
                    else linha.rstrip(':') + '.' for indice, linha in enumerate(linhas))
