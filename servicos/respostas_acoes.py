"""Transforma resultados confirmados em conversa, sem LLM ou novas execuções."""
import json
import re
from urllib.parse import parse_qs, urlsplit
from servicos.sites_pc import CONFIG

APPS = {
    'youtube': 'o YouTube', 'com.google.android.youtube': 'o YouTube',
    'spotify': 'o Spotify', 'com.spotify.music': 'o Spotify',
    'whatsapp': 'o WhatsApp', 'com.whatsapp': 'o WhatsApp',
    'telegram': 'o Telegram', 'org.telegram.messenger': 'o Telegram',
    'instagram': 'o Instagram', 'com.instagram.android': 'o Instagram',
    'vscode': 'o VS Code', 'code': 'o VS Code', 'discord': 'o Discord',
    'chrome': 'o Chrome', 'com.android.chrome': 'o Chrome', 'steam': 'a Steam',
    'android_studio': 'o Android Studio', 'valorant': 'o Valorant',
}
SITES = {'youtube.com': 'o YouTube', 'hbomax.com': 'o HBO Max', 'max.com': 'o HBO Max',
         'netflix.com': 'a Netflix', 'primevideo.com': 'o Prime Video',
         'disneyplus.com': 'o Disney+', 'github.com': 'o GitHub',
         'instagram.com': 'o Instagram', 'tiktok.com': 'o TikTok', 'google.com': 'o Google'}
ABERTURAS = {'abrir_app', 'abrir_programa', 'abrir_url', 'open_url', 'open_app',
             'pesquisa_google', 'web_search', 'pesquisar', 'abrir_app_mobile'}


def _curto(texto, limite=160):
    texto = ' '.join(str(texto or '').split())
    return texto if len(texto) <= limite else texto[:limite-1] + '…'


def _juntar(itens):
    return ' e '.join(itens) if len(itens) < 3 else ', '.join(itens[:-1]) + ' e ' + itens[-1]


def nome_abertura(etapa):
    parametro = str(etapa.get('parametro') or etapa.get('app') or etapa.get('url') or '').strip()
    comando = str(etapa.get('comando', '')).lower()
    if comando in {'pesquisa_google', 'web_search', 'pesquisar'}:
        return f'a busca por “{_curto(parametro)}” no Google'
    try:
        url = urlsplit(parametro)
        host = (url.hostname or '').lower().removeprefix('www.')
        query = parse_qs(url.query)
        chave = 'search_query' if host == 'youtube.com' else 'q'
        plataforma = {'youtube.com': 'YouTube', 'google.com': 'Google', 'github.com': 'GitHub'}.get(host)
        if plataforma and query.get(chave) and url.path in {'/results', '/search'}:
            return f'a busca por “{_curto(query[chave][0])}” no {plataforma}'
        if host:
            if host in SITES:
                return SITES[host]
            for site in json.loads(CONFIG.read_text(encoding='utf-8')):
                if urlsplit(site['url']).hostname == url.hostname:
                    return f'o site {_curto(site["nome"])}'
            return f'o site {_curto(host)}'
    except (ValueError, OSError, KeyError, TypeError):
        pass
    nome = parametro.lower().removesuffix('.exe')
    return APPS.get(nome, f'o app {_curto(parametro)}' if parametro else 'o aplicativo')


def _acao(etapa):
    comando, parametro = str(etapa.get('comando', '')).lower(), etapa.get('parametro', '')
    if comando in ABERTURAS:
        return 'abrir ' + nome_abertura(etapa)
    return {
        'volume_sistema': f'ajustar o volume pra {parametro}%',
        'mutar_mic': 'alternar o mudo do microfone',
        'media_play_pause': 'acionar o play/pause', 'media_next': 'passar pra próxima faixa',
        'media_prev': 'voltar uma faixa', 'spotify_play': f'tocar “{_curto(parametro)}” no Spotify',
    }.get(comando, 'concluir essa ação')


def resumir_resultados(resultados, texto_usuario='', interrupcao=''):
    frases, grupo = [], []

    def fechar_grupo():
        if grupo:
            frases.append('Abri ' + _juntar(grupo) + ' no PC.')
            grupo.clear()

    for registro in resultados:
        etapa, status = registro['etapa'], registro['status']
        alvo = etapa.get('alvo', 'PC')
        dispositivo = 'PC' if alvo == 'PC' else 'celular'
        comando = str(etapa.get('comando', '')).lower()
        if alvo == 'PC' and status == 'concluido' and comando in ABERTURAS and registro.get('foco') is not False:
            grupo.append(nome_abertura(etapa))
            continue
        fechar_grupo()
        acao = _acao(etapa)
        if alvo == 'CASA':
            frases.append(f'A luz está {"acesa" if registro["estado"] == "on" else "apagada"}.'
                if status == 'concluido' else 'Não consegui confirmar o estado da luz.')
        elif status == 'pc_offline' or status == 'mobile_offline':
            frases.append(f'O {dispositivo} está desconectado, então não consegui {acao}.')
        elif status == 'sem_confirmacao':
            frases.append(f'Pedi pra {acao} no {dispositivo}, mas ainda não recebi confirmação.')
        elif status == 'erro':
            frases.append(f'Não consegui {acao} no {dispositivo}.')
        elif status == 'enviado':
            frases.append(f'Mandei {acao} no celular.' if alvo == 'MOBILE' else f'Pedi pro PC {acao}.')
        elif registro.get('foco') is False:
            frases.append(f'Abri {nome_abertura(etapa)} no PC, mas não consegui trazer a janela pra frente.')
        else:
            frases.append({
                'volume_sistema': f'Ajustei o volume pra {etapa.get("parametro")}% no PC.',
                'mutar_mic': 'Alternei o mudo do microfone no PC.',
                'media_play_pause': 'Acionei o play/pause no PC.',
                'media_next': 'Passei pra próxima faixa no PC.',
                'media_prev': 'Voltei uma faixa no PC.',
                'spotify_play': f'Pedi pra tocar “{_curto(etapa.get("parametro"))}” no Spotify do PC.',
            }.get(comando, 'Terminei essa ação no PC.'))
    fechar_grupo()
    if interrupcao:
        frases.append(interrupcao)
    texto = ' '.join(frases)
    if resultados and not interrupcao and all(r['status'] == 'concluido' and r.get('foco') is not False for r in resultados):
        prefixo = 'Fechou' if re.search(r'\b(cara|mano|bora|valeu|porra|caralho|merda)\b', str(texto_usuario), re.I) else 'Pronto'
        texto = f'{prefixo}, ' + texto[:1].lower() + texto[1:]
    return texto or 'Não consegui confirmar o que aconteceu.'
