"""Intenções de tarefas e sugestões de mensagens, sem executar texto de terceiros."""
import re
from servicos.controle_casa import normalizar
from servicos.datas_agenda import DATA, HORA, titulo_sem_data

ACOES = r'pagar|entregar|enviar|comprar|levar|buscar|responder|preparar|terminar|revisar|devolver|renovar|agendar|ligar para'
RECUSA = re.compile(r'\b(?:nao precisa|nao e preciso|nao tenho|nao quero|nao vou|cancelad\w*|remarcad\w*|ja foi|talvez|se der)\b')


def limpar_alvo(texto):
    valor = titulo_sem_data(texto)
    valor = re.sub(r'^(?:ollie[, ]+)?(?:por favor[, ]+)?', '', valor, flags=re.I)
    valor = re.sub(r'^(?:(?:adicione|adiciona|crie|cria|anote|anota|guarde|guarda)\s+)?(?:(?:uma|a|essa|esta|minha)\s+)?(?:tarefa|pend[êe]ncia)\s*(?::|de|para|pra)?\s*', '', valor, flags=re.I)
    valor = re.sub(r'^(?:preciso|tenho que|tenho de)\s+', '', valor, flags=re.I)
    valor = re.sub(r'\s+at[ée]\s*$', '', valor, flags=re.I)
    valor = re.sub(r'^(?:a|o|essa|esta|esse|este|minha|minhas|as|os)\s+', '', valor, flags=re.I)
    return ' '.join(valor.strip(' .,:!?').split())


def interpretar_tarefa(texto):
    t = normalizar(texto).strip(' .!?')
    t = re.sub(r'^(?:ollie[, ]+)?(?:por favor[, ]+)?(?:(?:pode|consegue)\s+)?', '', t)
    if re.match(r'^(?:minhas|meus|quais|mostra|mostre|lista|liste|listar|ver|o que)', t) and re.search(r'\b(?:tarefas|pendencias|pendente|pendentes|preciso fazer)\b', t):
        return {'acao': 'listar', 'texto': texto, 'alvo': ''}
    if re.match(r'^(?:nao|se|quando|talvez)\b', t): return None
    for acao, verbos in [('aceitar', r'aceite|aceita|aceitar'),
                         ('concluir', r'conclua|conclui|concluir|finalize|finaliza|terminei|ja terminei|ja fiz|ja resolvi'),
                         ('descartar', r'descarte|descarta|cancele|cancela|cancelar|remova|remove|exclua'),
                         ('adiar', r'adie|adia|adiar|postergue')]:
        match = re.match(r'^(?:' + verbos + r')\s+(.+)$', t)
        if match:
            # Ações sobre alarmes, sites e dispositivos não pertencem ao domínio de tarefas.
            if re.search(r'\b(?:alarme|despertador|compromisso|reuniao)\b', match[1]): return None
            if acao == 'descartar' and not re.search(r'\b(?:tarefa|pendencia|isso|' + ACOES + r')\b', match[1]): return None
            return {'acao': acao, 'texto': texto, 'alvo': limpar_alvo(match[1])}
    feito = re.match(r'^(?:ja )?(paguei|entreguei|comprei|enviei|devolvi)\s+(.+)$', t)
    if feito:
        verbo = {'paguei': 'pagar', 'entreguei': 'entregar', 'comprei': 'comprar', 'enviei': 'enviar', 'devolvi': 'devolver'}[feito[1]]
        return {'acao': 'concluir', 'texto': texto, 'alvo': verbo + ' ' + limpar_alvo(feito[2])}
    explicita = re.match(r'^(?:adicione|adiciona|crie|cria|anote|anota|guarde|guarda)\s+(?:(?:uma|a)\s+)?(?:tarefa|pendencia)\b', t)
    declarada = re.match(r'^(?:preciso|tenho que|tenho de)\s+(?:' + ACOES + r')\b', t)
    if explicita or declarada:
        return {'acao': 'criar', 'texto': texto, 'alvo': limpar_alvo(texto)}
    return None


def pendencia_mensagem(texto):
    t = normalizar(texto)
    if RECUSA.search(t) or not (DATA.search(texto) or HORA.search(texto)): return False
    return bool(re.search(r'\b(?:' + ACOES + r'|pague|entregue|envie|compre|prepare|revise|devolva)\b', t))


def palavras_alvo(texto):
    ignoradas = {'tarefa', 'pendencia', 'favor', 'para', 'pra', 'uma', 'que', 'essa', 'esta', 'esse', 'este', 'isso', 'aquela', 'aquele'}
    return {p for p in normalizar(texto).split() if len(p) > 2 and p not in ignoradas}


def continua_tarefa(texto, contexto):
    if not contexto or not contexto.get('pedido'): return False
    t = normalizar(texto).strip(' .!?')
    if len(t) > 300 or re.match(r'^(?:abra|abre|acesse|ligue|desligue|pesquise|como|quem)\b', t): return False
    return True
