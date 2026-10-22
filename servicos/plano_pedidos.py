"""Compõe ordens do usuário; valida o plano inteiro antes de produzir efeitos."""
import re
import uuid
from servicos.controle_casa import ACOES, controle_casa, normalizar
from servicos.roteamento_pedidos import interpretar_abertura, resolver_abertura, destino_explicito, APPS, ALIASES
from servicos.abertura_apps import pedido_explicito_de_abertura
from servicos.intervention_governor import e_abertura
from servicos.sites_pc import url_explicita, resolver_site_pc
from servicos.linguagem_pedidos import separar_etapas

MAX_ETAPAS = 6
def interpretar_composto(texto):
    partes = separar_etapas(texto)
    if len(partes) < 2:
        return None
    if len(partes) > MAX_ETAPAS:
        raise ValueError(f'Consigo organizar até {MAX_ETAPAS} ações por pedido. Divida esse pedido em dois.')
    acoes, site = [], None
    for parte in partes:
        abertura = interpretar_abertura(parte, site_busca=site)
        if abertura:
            acao = abertura['execucao_direta'][0]
            if acao['comando'] == 'abrir_app':
                nome = normalizar(acao['parametro'])
                app = APPS.get(ALIASES.get(nome, nome))
                site = app[0][1] if app and app[0][0] == 'abrir_url' else resolver_site_pc(acao['parametro'])
            acoes.append({**acao, 'trecho': parte})
            continue
        casa = controle_casa.interpretar(parte)
        if not casa:
            return None  # A LLM interpreta a frase inteira, sem executar a metade conhecida.
        comando = {'ligar': 'ligar_luz', 'desligar': 'desligar_luz', 'alternar': 'toggle_luz', 'consultar': 'consultar_luz'}[casa['acao']]
        acoes.append({'alvo': 'CASA', 'comando': comando, 'parametro': casa['alvo'], 'trecho': parte})
    return {'execucao_direta': acoes, 'mensagem_dinamica': '', 'tipo_interacao': 'NOTIFICAR'}


def preparar_plano(evento, acoes):
    if not isinstance(acoes, list) or not 1 <= len(acoes) <= MAX_ETAPAS:
        raise ValueError(f'Um pedido pode ter de 1 a {MAX_ETAPAS} ações. Divida o pedido para continuar.')
    texto = str(evento.payload.get('texto', ''))
    if re.search(r'\b(?:e|mas|depois)\s+(?:nao|nunca)\b', normalizar(texto)):
        raise ValueError('Seu pedido mistura ações e uma restrição. Pode separar quais ações devo executar?')
    partes = separar_etapas(texto)
    try:
        destino_global = destino_explicito(texto)
    except ValueError:
        destino_global = None
    plano = []
    for indice, item in enumerate(acoes):
        if not isinstance(item, dict):
            raise ValueError('Não consegui organizar todas as ações. Pode reformular o pedido?')
        trecho = str(item.get('trecho') or texto).strip()
        # Um modelo não pode inventar uma ordem ou um destino que não foi dito.
        if normalizar(trecho) not in {normalizar(p) for p in [texto, *partes]}:
            raise ValueError('Não consegui relacionar uma das ações ao seu pedido. Pode reformular?')
        if len(partes) == len(acoes) and not item.get('trecho'):
            trecho = partes[indice]
        alvo = str(item.get('alvo', 'ORIGEM')).upper()
        comando = str(item.get('comando') or item.get('action') or '').lower().strip()
        parametro = str(item.get('parametro') or item.get('param') or item.get('value') or '').strip()
        if e_abertura(comando):
            if not pedido_explicito_de_abertura(trecho):
                raise ValueError('Diga explicitamente o que devo abrir ou pesquisar em cada etapa.')
            texto_destino = trecho
            if not destino_explicito(trecho) and destino_global:
                texto_destino += ' no ' + ('PC' if destino_global == 'PC' else 'celular')
            elif not destino_explicito(trecho) and not destino_global:
                # Duas menções só são válidas quando cada etapa determina seu destino.
                destino_explicito(texto)
            alvo, comando, parametro = resolver_abertura(evento, comando, parametro, texto_destino)
            if comando in {'abrir_url', 'OPEN_URL'}:
                url = url_explicita(parametro)
                if not url:
                    raise ValueError('Preciso de um endereço HTTP(S) válido para abrir esse site.')
                parametro = url
            if not parametro or len(parametro) > 2500:
                raise ValueError('Faltou o aplicativo, endereço ou termo de busca de uma etapa.')
        elif comando in ACOES:
            dispositivo = controle_casa.resolver(parametro)
            alvo, parametro = 'CASA', dispositivo['entity_id']
            comando = ACOES[comando]
        elif alvo == 'PC' and comando in {'volume_sistema', 'mutar_mic', 'media_play_pause', 'media_next', 'media_prev', 'spotify_play'}:
            if destino_explicito(trecho) == 'MOBILE':
                raise ValueError('Esse controle ainda é do PC; não vou executá-lo no lugar do controle solicitado no celular.')
            if comando == 'volume_sistema' and (not parametro.isdigit() or not 0 <= int(parametro) <= 100):
                raise ValueError('O volume do PC precisa estar entre zero e cem.')
        else:
            raise ValueError(f'A ação “{comando or "sem nome"}” ainda não está disponível em pedidos com várias etapas.')
        plano.append({'alvo': alvo, 'comando': comando, 'parametro': parametro,
                      'id_comando': str(uuid.uuid5(uuid.NAMESPACE_URL, f'ollie:{evento.correlacao_id}:{indice}'))})
    return plano
