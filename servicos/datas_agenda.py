"""Datas em português com referência explícita e fuso do usuário; sem chutes de horário."""
import re
from datetime import datetime, timedelta, timezone
from servicos.tempo import horario_local
from servicos.controle_casa import normalizar

DIAS = {'segunda': 0, 'terca': 1, 'quarta': 2, 'quinta': 3, 'sexta': 4, 'sabado': 5, 'domingo': 6}
MESES = {'janeiro': 1, 'fevereiro': 2, 'marco': 3, 'abril': 4, 'maio': 5, 'junho': 6,
         'julho': 7, 'agosto': 8, 'setembro': 9, 'outubro': 10, 'novembro': 11, 'dezembro': 12}
DATA = re.compile(r'\b(?:depois de amanh[ãa]|amanh[ãa]|hoje|(?:segunda|ter[cç]a|quarta|quinta|sexta)(?:-feira)?|s[áa]bado|domingo|\d{1,2}/\d{1,2}(?:/\d{4})?|(?:dia\s+)?\d{1,2}\s+de\s+(?:janeiro|fevereiro|mar[çc]o|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)(?:\s+de\s+\d{4})?|dia\s+\d{1,2})\b', re.I)
HORA = re.compile(r'\b(?:(?:[àa]s|pelas|para as)\s+)?(?P<h>\d{1,2})(?:(?P<sep>[:h])(?P<m>\d{2})?|\s+horas?)(?:\s*(?:da|de)\s+(?P<periodo>manh[ãa]|tarde|noite))?\b|\b(?:[àa]s|pelas)\s+(?P<simples>\d{1,2})(?:\s+da\s+(?P<per>manh[ãa]|tarde|noite))?\b', re.I)
HORA = re.compile(r'(?:' + HORA.pattern + r')(?:\s+e\s+(?P<fracao>quarenta e cinco|meia|quinze|trinta|\d{1,2}))?(?:\s+(?:da|de)\s+(?P<periodo_final>manh[ãa]|tarde|noite))?', re.I)
VERBOS = r'me lembra(?:r)?|me lembre|lembre-me|lembra|lembre|me avisa|me avise|avise-me|agende|agendar|agenda|marque|marcar|marca|anote|anota|guarde|guarda|salve|salva|reserve|reserva|crie|criar|cria|coloque|coloca|bota|bote|defina|programe|me acorde|me acorda'


def extrair_data(texto, referencia, proxima_ocorrencia=False):
    try:
        return _extrair_data(texto, referencia, proxima_ocorrencia)
    except (OverflowError, ValueError) as erro:
        if str(erro).startswith(('Esse ', 'Essa ', 'Você ')): raise
        raise ValueError('Essa data não é válida. Qual data devo usar?') from erro


def _extrair_data(texto, referencia, proxima_ocorrencia=False):
    agora = horario_local(referencia)
    if re.search(r'\b\d{1,2}[:h]\d\b', texto, re.I):
        raise ValueError('Esse horário ficou incompleto. Diga, por exemplo, 7h30.')
    if len(list(DATA.finditer(texto))) > 1 or len(list(HORA.finditer(texto))) > 1:
        raise ValueError('Você mencionou mais de uma data ou horário. Vamos marcar um de cada vez: qual devo usar?')
    rel = re.search(r'\b(?:daqui\s+a|em)\s+(\d+)\s+(minutos?|horas?|dias?)\b', texto, re.I)
    if rel:
        quantidade = int(rel[1])
        if not 1 <= quantidade <= 525600:
            raise ValueError('Esse intervalo não parece válido. Diga outra data ou horário.')
        unidade = normalizar(rel[2])
        delta = timedelta(minutes=quantidade) if unidade.startswith('min') else timedelta(hours=quantidade) if unidade.startswith('hora') else timedelta(days=quantidade)
        return {'inicio': (agora + delta).astimezone(timezone.utc), 'dia_inteiro': False, 'trecho': rel[0]}
    data, hora = DATA.search(texto), HORA.search(texto)
    if not data and not hora:
        return None
    dia = agora.date()
    if data:
        valor = normalizar(data[0]).replace('-feira', '')
        if valor == 'amanha': dia += timedelta(days=1)
        elif valor == 'depois de amanha': dia += timedelta(days=2)
        elif valor in DIAS:
            dia += timedelta(days=(DIAS[valor] - dia.weekday()) % 7)
        elif '/' in valor:
            partes = list(map(int, valor.split('/')))
            dia = datetime(partes[2] if len(partes) == 3 else agora.year, partes[1], partes[0]).date()
            if len(partes) == 2 and dia < agora.date():
                dia = dia.replace(year=dia.year + 1)
        elif ' de ' in valor:
            partes = valor.removeprefix('dia ').split(' de ')
            dia = datetime(int(partes[2]) if len(partes) == 3 else agora.year, MESES[partes[1]], int(partes[0])).date()
            if len(partes) == 2 and dia < agora.date(): dia = dia.replace(year=dia.year + 1)
        elif valor.startswith('dia '):
            numero = int(valor.split()[1])
            mes, ano = agora.month, agora.year
            if numero < agora.day:
                mes, ano = (mes + 1, ano) if mes < 12 else (1, ano + 1)
            dia = datetime(ano, mes, numero).date()
    h, m = 0, 0
    if hora:
        h, m = int(hora['h'] or hora['simples']), int(hora['m'] or 0)
        fracao = hora['fracao']
        if fracao:
            if m: raise ValueError('Esse horário ficou ambíguo. Diga, por exemplo, 7h30.')
            m = {'meia': 30, 'quinze': 15, 'trinta': 30, 'quarenta e cinco': 45}.get(fracao.lower(), int(fracao) if fracao.isdigit() else 0)
        periodo = normalizar(hora['periodo'] or hora['per'] or hora['periodo_final'] or '')
        if periodo in {'tarde', 'noite'} and h < 12: h += 12
        if periodo == 'manha' and h == 12: h = 0
        if not 0 <= h <= 23 or not 0 <= m <= 59:
            raise ValueError('Esse horário não é válido. Qual é o horário certo?')
    inicio = datetime.combine(dia, datetime.min.time(), tzinfo=agora.tzinfo).replace(hour=h, minute=m)
    if not data and hora and proxima_ocorrencia and inicio <= agora:
        inicio += timedelta(days=1)
    primeiro = min(x.start() for x in (data, hora) if x)
    ultimo = max(x.end() for x in (data, hora) if x)
    return {'inicio': inicio.astimezone(timezone.utc), 'dia_inteiro': hora is None, 'trecho': texto[primeiro:ultimo]}


def titulo_sem_data(texto):
    valor = re.sub(r'\b(?:daqui\s+a|em)\s+\d+\s+(?:minutos?|horas?|dias?)\b', '', texto, flags=re.I)
    valor = DATA.sub('', HORA.sub('', valor))
    valor = re.sub(r'^(?:ollie[, ]+)?(?:por favor[, ]+)?(?:(?:pode|consegue)\s+)?(?:' + VERBOS + r')\s*', '', valor, flags=re.I)
    valor = re.sub(r'^(?:(?:um|uma|o|a)\s+)?(?:compromisso|lembrete|alarme|despertador)\s*(?:para|pra|de)?\s*', '', valor, flags=re.I)
    valor = re.sub(r'^(?:de|para|pra)\s+', '', valor, flags=re.I)
    valor = re.sub(r'\s+(?:para|pra|[àa]s|no dia|dia|em|por favor)\s*$', '', valor, flags=re.I)
    return ' '.join(valor.strip(' ,.!?').split())[:255]


def intencao_agenda(texto):
    t = normalizar(texto)
    if re.match(r'^(?:ollie[, ]+)?(?:qual|quais|mostr[ae]|ver|lista|listar|minha|meus|o que tenho)\b', t) and re.search(r'\b(?:agenda|compromissos|lembretes|agendado|tenho)\b', t):
        return 'listar'
    if re.match(r'^(?:ollie[, ]+)?(?:por favor[, ]+)?(?:(?:pode|consegue)\s+)?(?:' + VERBOS + r')\b', t):
        if re.search(r'\b(?:alarme|despertador|acorde|acorda)\b', t): return 'alarme'
        if re.search(r'\b(?:lembra|lembrar|lembre|lembrete|avisa|avise|tarefa)\b', t): return 'lembrete'
        if re.search(r'\b(?:compromisso|reuniao|consulta|dentista|agenda|agende|agendar|marque|marcar|marca|aniversario|importante)\b', t) or DATA.search(texto): return 'compromisso'
    return None


def completar_rascunho(anterior, resposta):
    # Uma correção substitui a data/horário anterior, sem virar dois compromissos.
    if DATA.search(resposta): anterior = DATA.sub('', anterior)
    if HORA.search(resposta): anterior = HORA.sub('', anterior)
    return anterior + ' ' + resposta


def data_importante(texto):
    t = normalizar(texto)
    if re.search(r'\b(?:nao|cancel\w*|remarc\w*|talvez|se der)\b', t): return False
    return bool(re.search(r'\b(?:consulta|reuniao|aniversario|compromisso|importante|prova|entrevista)\b', t) and DATA.search(texto))


def continua_rascunho(texto, rascunho):
    if not rascunho: return False
    t = normalizar(texto).strip(' .!?')
    if t in {'cancelar', 'cancela', 'deixa pra la', 'esquece', 'nao quero mais'}: return True
    if DATA.search(texto) or HORA.search(texto) or re.search(r'\b(?:daqui a|em) \d+ (?:minutos?|horas?|dias?)\b', t): return True
    # Só captura um título curto quando a data já foi informada; outras ordens seguem seu caminho.
    return bool(DATA.search(rascunho) or HORA.search(rascunho)) and len(t) < 150 and not re.search(
        r'\b(?:abra|abre|abrir|acesse|ligue|desligue|como|qual|quem|porque|pesquise|me diga|me fale)\b', t)
