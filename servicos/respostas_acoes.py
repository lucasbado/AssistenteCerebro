"""Transforma resultados confirmados em conversa, sem LLM ou novas execuções."""
import json
import re
from urllib.parse import parse_qs, urlsplit
from servicos.arquivos_pc import COMANDOS_ARQUIVOS, validar_resultado_arquivo
from servicos.comandos_pc import validar_status_pc
from servicos.foco_janelas import COMANDOS_OBSERVACAO_JANELAS, validar_observacao_janelas
from servicos.interface_pc import (
    COMANDO_ACIONAR_CONTROLE, COMANDO_INTERFACE, COMANDOS_INTERFACE_EXPLICITOS,
    validar_resultado_acionamento, validar_resultado_interface,
)
from servicos.sites_pc import CONFIG
from servicos.whatsapp import COMANDO_WHATSAPP_PC

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
ACOES_PC = {
    'buscar_documentos': 'procurar o documento', 'abrir_arquivo': 'abrir o documento',
    'listar_arquivos': 'listar os arquivos', 'janela_focar': 'trazer a janela pra frente',
    'janela_maximizar': 'maximizar a janela', 'janela_minimizar': 'minimizar a janela',
    'janela_fechar': 'fechar a janela', 'janela_fullscreen': 'alternar a tela cheia',
    'capturar_tela': 'capturar a tela', 'system_status': 'consultar o uso de CPU, memória e disco',
    'janela_ativa': 'identificar a janela ativa', 'listar_janelas': 'consultar as janelas abertas',
    COMANDO_INTERFACE: 'consultar os controles da janela',
    COMANDO_ACIONAR_CONTROLE: 'acionar o controle da janela',
    COMANDO_WHATSAPP_PC: 'preparar o rascunho do WhatsApp',
    'criar_pasta': 'criar a pasta', 'copiar_arquivo': 'copiar o arquivo', 'mover_arquivo': 'mover o arquivo',
    'renomear_arquivo': 'renomear o arquivo', 'compactar_arquivo': 'compactar o arquivo',
    'criar_arquivo': 'criar o arquivo', 'ler_arquivo': 'ler o arquivo', 'acrescentar_texto': 'acrescentar o texto',
    'prever_organizacao': 'preparar a prévia', 'organizar_pasta': 'organizar a pasta',
    'desfazer_organizacao': 'desfazer a organização', 'lixeira_arquivo': 'enviar o arquivo à Lixeira',
    'restaurar_lixeira': 'restaurar o arquivo da Lixeira',
}


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
    }.get(comando, ACOES_PC.get(comando, 'concluir essa ação'))


def _resposta_arquivo(comando, resultado):
    if not validar_resultado_arquivo(comando, resultado):
        return 'O PC não devolveu um resultado de arquivo válido.'
    estado, itens = resultado['arquivo']['estado'], resultado['arquivo']['itens']
    nomes = _juntar([f'“{item}”' for item in itens])
    operacao = {'pasta_criada': 'Criei a pasta', 'copiado': 'Copiei para', 'movido': 'Movi para',
                'renomeado': 'Renomeei para', 'compactado': 'Salvei o ZIP em',
                'na_lixeira': 'Enviei à Lixeira', 'restaurado': 'Restaurei',
                'arquivo_criado': 'Criei', 'texto_acrescentado': 'Acrescentei o texto em'}.get(estado)
    if operacao:
        resposta = f'{operacao} {nomes} no PC.'
        if estado == 'na_lixeira':
            pasta, nome = itens[0].split('/', 1)
            resposta += f' Para voltar, diga “Restaure {nome} da Lixeira em {pasta}”.'
        return resposta
    if estado == 'destino_existe':
        return f'{nomes} já existe. Escolha outro nome ou destino.'
    if estado == 'origem_ausente':
        return 'O arquivo não está nesse caminho. Confira a pasta e o nome completo.'
    if estado == 'lido':
        conteudo = resultado['arquivo']['texto']
        if not conteudo:
            return f'{nomes} está vazio.'
        leitura = 'Início do arquivo' if resultado['arquivo']['parcial'] else 'Conteúdo do arquivo'
        return f'{leitura} {nomes}\n\n{conteudo}'
    if estado == 'previa_organizacao' and itens:
        pasta = itens[0].split('/', 1)[0]
        return f'Prévia de destinos: {nomes}. Para mover esses arquivos, diga “Aplique a organização em {pasta}”.'
    if estado == 'organizado':
        return f'Organizei os arquivos em {nomes}.'
    if estado == 'organizacao_parcial':
        return ('A organização foi interrompida. ' +
                (f'Movi {nomes}. Você pode pedir para desfazer a organização.' if itens else 'Nenhum movimento foi confirmado.'))
    if estado in {'desfeito', 'desfeito_parcial'}:
        volta = f'Voltei {nomes} para o lugar anterior.' if itens else 'Nenhum arquivo precisou voltar.'
        return volta if estado == 'desfeito' else volta + ' Alguns itens mudaram de lugar ou têm conflito de nome.'
    mensagens = {
        'organizacao_sem_itens': 'Não encontrei arquivos que possam ser organizados nesta pasta.',
        'organizacao_sem_previa': 'Peça uma prévia da organização desta pasta primeiro.',
        'previa_desatualizada': 'Os arquivos mudaram desde a prévia. Peça uma nova prévia para continuar.',
        'sem_organizacao': 'Não tenho uma organização registrada para desfazer nesta pasta.',
        'sem_item_lixeira': 'Não tenho um envio desse arquivo à Lixeira registrado pela Ollie.',
        'restauro_nao_confirmado': 'O Windows não confirmou a restauração desse item da Lixeira.',
    }
    if estado in mensagens:
        return mensagens[estado]
    if estado == 'janela_confirmada':
        return f'Abri {nomes} no PC e conferi a janela do documento.'
    if estado == 'capturado':
        return f'Salvei a captura em {nomes} no PC.'
    if estado == 'abertura_enviada':
        return f'Pedi ao Windows para abrir {nomes}, mas não consegui confirmar a janela.'
    if estado == 'ambiguo':
        return f'Encontrei mais de um arquivo: {nomes}. Diga o nome ou o caminho relativo e a pasta que devo usar.'
    if estado == 'nao_encontrado':
        return 'Não encontrei um arquivo compatível com esse nome nas pastas pesquisadas.'
    if estado == 'incompleto':
        return 'Não consegui concluir a busca. ' + (f'Até onde consegui olhar, achei {nomes}.' if itens else 'Experimente indicar a pasta e o nome completo.')
    if estado == 'listado':
        return f'Arquivos da pasta: {nomes}.' if itens else 'A pasta está sem arquivos visíveis para a Ollie.'
    return f'Encontrei {nomes} no PC.'


def _resposta_janelas(comando, resultado, filtro):
    if not validar_observacao_janelas(comando, resultado):
        return 'O PC não devolveu uma observação de janelas válida.'
    janelas, total = resultado['janelas'], resultado['total']
    if comando == 'janela_ativa':
        if not janelas:
            return 'Não identifiquei uma janela de aplicativo em primeiro plano no PC.'
        janela = janelas[0]
        return f'A janela ativa no PC é “{janela["titulo"]}” ({janela["processo"]}).'
    if not janelas:
        return (f'Não encontrei uma janela aberta para “{_curto(filtro)}” no PC.' if filtro
                else 'Não encontrei janelas de aplicativos abertas no PC.')
    nomes = _juntar([f'“{item["titulo"]}” ({item["processo"]})' for item in janelas])
    if total > len(janelas):
        return f'Encontrei {total} janelas no PC. As primeiras {len(janelas)} são {nomes}.'
    return f'Janelas abertas no PC\n\n{nomes}.'


_FALHAS_INTERFACE = {
    'sem_janela': 'Não encontrei a janela. Peça a lista de janelas do PC para conferir o título.',
    'ambigua': 'Encontrei mais de uma janela. Peça a lista de janelas do PC e indique o título exato.',
    'minimizada': 'A janela está minimizada. Traga a janela para frente e tente de novo.',
    'mudou': 'A janela ou o controle mudou durante a consulta. Confira o alvo e tente de novo.',
    'indisponivel': 'Não consegui acessar os controles dessa janela pela acessibilidade do Windows.',
}


def _resposta_interface(resultado):
    if not validar_resultado_interface(resultado):
        return 'O PC não devolveu uma leitura válida da interface.'
    estado = resultado['estado']
    if estado != 'lida':
        return _FALHAS_INTERFACE[estado]
    titulo, itens = resultado['janela'], resultado['itens']
    if not itens:
        if resultado['parcial']:
            return f'Não encontrei controles com rótulo na parte que consegui ler em “{titulo}”.'
        return f'Não encontrei controles com rótulo acessível em “{titulo}”.'
    rotulos = _juntar([f'{item["tipo"]} “{item["nome"]}”' + ('' if item['habilitado'] else ' (desabilitado)')
                      for item in itens])
    prefixo = 'Parte dos controles em' if resultado['parcial'] else 'Controles em'
    return f'{prefixo} “{titulo}”\n\n{rotulos}.'


def _resposta_acionamento(resultado):
    if not validar_resultado_acionamento(resultado):
        return 'O PC não devolveu um resultado válido para o controle.'
    return {
        **_FALHAS_INTERFACE,
        'sem_controle': 'Não encontrei um controle visível com esse nome e tipo na janela indicada.',
        'controle_ambiguo': 'Encontrei mais de um controle visível com esse nome. Indique um controle com nome único.',
        'desabilitado': 'Encontrei o controle, mas ele está desabilitado.',
        'sem_padrao': 'O aplicativo não oferece um comando de acessibilidade para acionar esse controle.',
        'ocupado': 'Já estou aguardando o resultado de outra ação na interface do PC.',
        'aba_selecionada': 'Selecionei a aba e confirmei que ela ficou selecionada.',
        'aba_ja_selecionada': 'A aba já estava selecionada.',
        'mudanca_observada': 'Acionei o botão e observei uma mudança nos controles visíveis da janela.',
        'enviada_sem_confirmacao': 'Enviei a ação ao aplicativo. Ainda não consegui confirmar o efeito.',
        'envio_incerto': 'O aplicativo não confirmou se recebeu a ação. Confira a janela antes de repetir.',
    }[resultado['estado']]


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
        elif comando in COMANDOS_ARQUIVOS:
            frases.append(_resposta_arquivo(comando, registro.get('resultado')))
        elif comando in COMANDOS_OBSERVACAO_JANELAS:
            frases.append(_resposta_janelas(comando, registro.get('resultado'), etapa.get('parametro')))
        elif comando == COMANDO_INTERFACE:
            frases.append(_resposta_interface(registro.get('resultado')))
        elif comando == COMANDO_ACIONAR_CONTROLE:
            frases.append(_resposta_acionamento(registro.get('resultado')))
        elif comando == COMANDO_WHATSAPP_PC:
            frases.append('Deixei o rascunho do WhatsApp em Mensagens no PC. Confira o número e o texto antes de abrir a conversa.')
        elif comando == 'system_status':
            dados = registro.get('resultado')
            if validar_status_pc(dados):
                sistema = dados['sistema']
                frases.append(f'O PC está com {sistema["cpu"]:.0f}% de uso de CPU, {sistema["ram"]:.0f}% de memória '
                              f'e {sistema["disco"]:.0f}% de ocupação na unidade do usuário.')
            else:
                frases.append('O PC não devolveu uma medição válida.')
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
                'janela_focar': 'Trouxe a janela pra frente no PC.',
                'janela_maximizar': 'Maximizei a janela no PC.', 'janela_minimizar': 'Minimizei a janela no PC.',
                'janela_fechar': 'Fechei a janela no PC.', 'janela_fullscreen': 'Alternei a tela cheia no navegador do PC.',
            }.get(comando, 'Terminei essa ação no PC.'))
    fechar_grupo()
    if interrupcao:
        frases.append(interrupcao)
    texto = ' '.join(frases)
    if resultados and not interrupcao and all(r['status'] == 'concluido' and r.get('foco') is not False
            and r['etapa'].get('comando') not in COMANDOS_ARQUIVOS | COMANDOS_INTERFACE_EXPLICITOS | {'system_status', COMANDO_WHATSAPP_PC} for r in resultados):
        prefixo = 'Fechou' if re.search(r'\b(cara|mano|bora|valeu|porra|caralho|merda)\b', str(texto_usuario), re.I) else 'Pronto'
        texto = f'{prefixo}, ' + texto[:1].lower() + texto[1:]
    return texto or 'Não consegui confirmar o que aconteceu.'
