"""Endereços de pesquisa: termos são dados, nunca comandos ou domínios inventados."""
from urllib.parse import urlencode, urlsplit
from servicos.controle_casa import normalizar
from servicos.sites_pc import resolver_site_pc


def url_busca(termo, site=None):
    termo = str(termo or '').strip().strip('"')
    if not termo or len(termo) > 2000:
        raise ValueError('Diga o que você quer pesquisar (até 2000 caracteres).')
    nome = normalizar(site or 'google')
    if nome in {'google', 'web', 'internet', 'navegador'}:
        return 'https://www.google.com/search?' + urlencode({'q': termo})
    if nome in {'youtube', 'you tube'}:
        return 'https://www.youtube.com/results?' + urlencode({'search_query': termo})
    if nome == 'github':
        return 'https://github.com/search?' + urlencode({'q': termo})
    url = resolver_site_pc(site)
    if not url:
        raise ValueError('Qual é o endereço do site em que você quer pesquisar?')
    host = urlsplit(url).hostname
    if host in {'www.youtube.com', 'youtube.com'}:
        return url_busca(termo, 'youtube')
    if host in {'www.github.com', 'github.com'}:
        return url_busca(termo, 'github')
    return url_busca(f'site:{host} {termo}')
