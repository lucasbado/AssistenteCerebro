"""Ordens explícitas de PC compartilhadas pelo modo normal e pelo limitado."""
import json
import re
import uuid

from servicos.arquivos_pc import COMANDOS_ARQUIVOS, EXTENSOES, parametros_arquivo
from servicos.controle_casa import normalizar
from servicos.roteamento_pedidos import contexto_pedido, destino_explicito, dispositivo_origem, responder_pedido


JANELAS = {'maximize': 'janela_maximizar', 'minimize': 'janela_minimizar',
           'feche': 'janela_fechar', 'foque': 'janela_focar'}
COMANDOS_JANELAS = frozenset({*JANELAS.values(), 'janela_fullscreen'})
COMANDOS_DIRETOS = COMANDOS_ARQUIVOS | COMANDOS_JANELAS | {'system_status'}
DESTINO = r'(?:no|pelo|pro|para o)\s+(?:(?:meu|seu|este|esse)\s+)?(?:pc|computador|desktop|notebook|celular|telefone|smartphone|android)'
PASTA = r'downloads?|documentos|documents|[áa]rea de trabalho|desktop'
ABRIR = r'(?:abra|abre|abrir)'
BUSCAR = r'(?:ache|acha|encontre|encontra|procure|procura|busque|busca|localize|pesquise|pesquisa|procurar|buscar|encontrar)'
TIPOS = {'pdf': '.pdf', 'planilha': '.xlsx', 'apresentacao': '.pptx'}


def interpretar_ordem_pc(texto):
    texto = re.sub(r'^(?:ei\s+)?ollie\b[,\s]*|^por favor\b[,\s]*', '', str(texto).strip(), flags=re.I)
    texto = re.sub(r'[,\s]+por favor$', '', texto.rstrip('.!?').strip(), flags=re.I).strip()
    abrir_depois = re.search(rf'(?:,\s*|\s+e\s+(?:depois\s+)?)'
                             rf'{ABRIR}(?:-o|-a|\s+(?:o arquivo|ele|ela))?'
                             rf'(?:\s+{DESTINO})?(?:\s+e\s+(?:me\s+)?(?:diga|avise)\s+se\s+abriu)?$', texto, re.I)
    texto = texto[:abrir_depois.start()].strip() if abrir_depois else texto
    texto = re.sub(rf'\s+{DESTINO}$', '', texto, flags=re.I)
    if re.fullmatch(r'(?:(?:mostre|consulte)\s+o\s+)?status\s+(?:do\s+)?(?:pc|computador)|como\s+est[aá]\s+o\s+(?:pc|computador)', texto, re.I):
        return 'system_status', ''
    captura = re.fullmatch(rf'(?:tire|fa[çc]a|salve)\s+(?:um |uma )?(?:print|captura)(?:\s+da\s+tela)?'
                           rf'(?:\s+(?:em|na)\s+({PASTA}))?', texto, re.I)
    if captura and not abrir_depois:
        return 'capturar_tela', json.dumps({'pasta': captura[1] or 'Downloads'}, ensure_ascii=False)
    janela = re.fullmatch(r'(maximize|minimize|feche|foque)\s+(?:a\s+)?janela(?:\s+(?:do|da|de)\s+(.+)|\s+ativa)?', texto, re.I)
    if janela and not abrir_depois:
        return JANELAS[janela[1].lower()], (janela[2] or '').strip(' "“”')
    if re.fullmatch(r'(?:ative|altern[ea]r?|coloque em)\s+(?:a\s+)?tela cheia(?:\s+na janela ativa)?', texto, re.I):
        return 'janela_fullscreen', ''
    listar = re.fullmatch(rf'(?:liste|lista|mostre|mostra)\s+(?:os\s+)?arquivos\s+(?:em|no|na|de)\s+({PASTA})', texto, re.I)
    if listar and not abrir_depois:
        return 'listar_arquivos', json.dumps({'pasta': listar[1]}, ensure_ascii=False)
    pedido = re.fullmatch(rf'({BUSCAR}|{ABRIR})\s+(?:(?:o|a|um|uma)\s+)?(.+)', texto, re.I)
    if not pedido:
        return None
    termo = pedido[2].strip()
    localizar = r'(?:(?:\s*,\s*|\s+e\s+)(?:me\s+)?(?:mostr[ea]|dig[ae]|informe|passe)\s+(?:onde\s+(?:est[aá]|fica)|o\s+caminho(?:\s+completo)?|a\s+localiza[çc][aã]o))?'
    pasta = re.search(rf'\s+(?:em|no|na|dos|da|de)\s+(?:pasta\s+(?:de\s+)?)?({PASTA}){localizar}$', termo, re.I)
    nome = termo[:pasta.start()].strip() if pasta else termo
    tipo = re.match(r'^(arquivo|documento|pdf|planilha|apresenta[çc][aã]o|pasta|instalador)\s+(?:(?:chamad[oa]|d[oea])\s+)?', nome, re.I)
    nome = (nome[tipo.end():] if tipo else nome).strip(' "“”')
    if not tipo and not pasta and not any(nome.casefold().endswith(ext) for ext in EXTENSOES):
        return None
    if re.search(r'\b(?:e|depois)\s+(?:abra|abra-o|envie|mande|apague|copie|mova|renomeie|publique|me diga)\b', nome, re.I):
        raise ValueError('Peça a busca ou abertura do documento separadamente das outras ações.')
    if re.search(r'\b(?:no|na|pelo|pela)\s+(?:google|youtube|whatsapp|internet|web)\b', nome, re.I):
        return None
    comando = 'abrir_arquivo' if abrir_depois or re.fullmatch(ABRIR, pedido[1], re.I) else 'buscar_documentos'
    parametro = {'nome': nome, 'pasta': pasta[1] if pasta else '',
                 'extensao': TIPOS.get(normalizar(tipo[1]), '') if tipo else ''}
    parametros_arquivo(comando, parametro)
    return comando, json.dumps(parametro, ensure_ascii=False)


async def encaminhar_ordem_pc(evento):
    from core.kernel import kernel
    from core.tipos import CategoriaEvento, OrigemEvento, TipoAcao

    if evento.origem not in {OrigemEvento.USUARIO, OrigemEvento.PC, OrigemEvento.ANDROID}:
        return False
    texto = str(evento.payload.get('texto') or '')
    try:
        ordem = interpretar_ordem_pc(texto)
        if not ordem:
            return False
        comando, parametro = ordem
        destino = destino_explicito(texto)
        if destino == 'MOBILE' or (not destino and dispositivo_origem(evento) == 'MOBILE'
                                  and comando in COMANDOS_JANELAS | {'capturar_tela'}):
            await responder_pedido(evento, 'Esse controle é do PC. Diga “no PC” para executar lá.')
            return True
    except ValueError as erro:
        await responder_pedido(evento, str(erro))
        return True
    etapa = {'alvo': 'PC', 'comando': comando, 'parametro': parametro,
             'id_comando': str(uuid.uuid5(uuid.NAMESPACE_URL, f'ollie:{evento.correlacao_id}:0'))}
    await kernel.publicar(evento.clonar(categoria=CategoriaEvento.PLANO_SOLICITADO, acao=TipoAcao.NORMAL,
        payload={'etapas': [etapa], 'texto_pedido': texto}, metadados=contexto_pedido(evento)))
    return True
