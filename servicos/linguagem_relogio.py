"""Pedidos de relógio em português; independentes de agenda, LLM e persistência."""
import re
from datetime import datetime, timedelta, timezone

from servicos.controle_casa import normalizar
from servicos.datas_agenda import DATA, HORA, extrair_data
from servicos.tempo import horario_local

NUMEROS = {
    'zero': 0, 'um': 1, 'uma': 1, 'dois': 2, 'duas': 2, 'tres': 3, 'quatro': 4,
    'cinco': 5, 'seis': 6, 'sete': 7, 'oito': 8, 'nove': 9, 'dez': 10,
    'onze': 11, 'doze': 12, 'treze': 13, 'catorze': 14, 'quatorze': 14,
    'quinze': 15, 'dezesseis': 16, 'dezessete': 17, 'dezoito': 18, 'dezenove': 19,
    'vinte': 20, 'trinta': 30, 'quarenta': 40, 'cinquenta': 50,
}
for dezena, valor in list(NUMEROS.items()):
    if valor in {20, 30, 40, 50}:
        for unidade, numero in list(NUMEROS.items()):
            if 1 <= numero <= 9:
                NUMEROS[dezena + ' e ' + unidade] = valor + numero


def numeros_falados(texto):
    texto = normalizar(texto).replace('meia noite', '00:00').replace('meio dia', '12:00')
    return re.sub(r'\b(?:' + '|'.join(sorted(map(re.escape, NUMEROS), key=len, reverse=True)) + r')\b',
                  lambda m: str(NUMEROS[m[0]]), texto)


PREFIXO = r'(?:(?:ei )?ollie[, ]+)?(?:por favor[, ]+)?(?:(?:voce )?(?:pode|poderia|consegue) |quero que voce )?'
PEDIDO_ALARME = re.compile(PREFIXO + r'(?:'
    r'(?:me acord[ae]|acord[ae]-me|me despert[ae]|despert[ae]-me|quero acordar|preciso acordar)'
    r'|(?:crie|cria|criar|coloque|coloca|colocar|bote|bota|botar|marque|marca|defina|ative|ativa|programe|programa|configure|configura|ponha|poe) '
    r'(?:(?:um|o|meu) )?(?:(?:alarme|despertador)|(?:pra|para) (?:me )?(?:despertar|acordar))'
    r'|(?:alarme|despertador))\b\s*(.*)$')


def interpretar_relogio(texto, referencia=None, intencao_confirmada=False):
    t = normalizar(texto).strip(' .!?')
    if not intencao_confirmada and re.search(r';|\s+e\s+(?:depois\s+)?(?:ligue|liga|desligue|desliga|abra|abre|ative|coloque)\b', t):
        return None
    if not intencao_confirmada and re.search(r'\b(?:nao|nunca|se|quando|ontem|talvez)\b', t):
        return None
    match = PEDIDO_ALARME.fullmatch(t)
    if not match:
        return None
    tail = re.sub(r' (?:no|pelo) (?:meu )?(?:celular|telefone|android)\b', '', match[1])
    if re.search(r'\b(?:no|pelo) (?:pc|computador)\b', tail):
        return None
    tail = re.sub(r'(?: por favor| pra mim| para mim)$', '', tail)
    dias = None
    if re.search(r'\b(?:todos os dias|todo dia|diariamente)\b', tail):
        dias = list(range(1, 8))
        tail = re.sub(r'\b(?:todos os dias|todo dia|diariamente)\b', '', tail)
    elif re.search(r'\b(?:de segunda a sexta|segunda a sexta|dias uteis)\b', tail):
        dias = [2, 3, 4, 5, 6]
        tail = re.sub(r'\b(?:de segunda a sexta|segunda a sexta|dias uteis)\b', '', tail)
    tail = numeros_falados(tail).strip()
    tail = re.sub(r'\bpras\b', 'as', tail)
    sem_data = DATA.sub('', tail).strip()
    sem_data = re.sub(r'^(?:para|pra|pras|para as)\s+', '', sem_data)
    if not HORA.search(tail) and re.fullmatch(r'\d{1,2}(?:\s+e\s+(?:meia|\d{1,2}))?(?:\s+(?:da|de)\s+(?:manha|tarde|noite))?', sem_data):
        tail = DATA.sub('', tail).strip() + ' ' + ' '.join(m[0] for m in DATA.finditer(tail))
        tail = 'as ' + tail.strip()
    if not HORA.search(tail) and not re.search(r'\b(?:daqui a|em) \d+ (?:minutos?|horas?)\b', tail):
        return {'esclarecimento': 'Que horas você quer que o despertador toque?', 'pergunta': True,
                'continuacao_relogio': texto}
    agora = referencia or datetime.now(timezone.utc)
    try:
        data = extrair_data(tail, agora, proxima_ocorrencia=True)
    except ValueError as erro:
        return {'esclarecimento': str(erro), 'pergunta': True, 'continuacao_relogio': texto}
    if not data or data['dia_inteiro']:
        return {'esclarecimento': 'Que horas você quer que o despertador toque?', 'pergunta': True,
                'continuacao_relogio': texto}
    local, atual = horario_local(data['inicio']), horario_local(agora)
    if local <= atual and DATA.search(tail):
        return {'esclarecimento': 'Esse horário já passou. Quando você quer que toque?', 'pergunta': True,
                'continuacao_relogio': 'me acorde'}
    proximo = atual.replace(hour=local.hour, minute=local.minute, second=0, microsecond=0)
    if proximo <= atual:
        proximo += timedelta(days=1)
    if dias is None and local.replace(second=0, microsecond=0) != proximo:
        return {'acoes': [{'acao': 'clock.open', 'parametros': {}}],
                'nota': 'Para essa data específica, ajuste o dia no Relógio. A integração de despertador do Android usa a próxima ocorrência do horário.'}
    args = {'hora': local.hour, 'minuto': local.minute}
    if dias:
        args['dias'] = dias
    return {'acoes': [{'acao': 'alarm.create', 'parametros': args}]}


def resposta_de_horario(texto):
    t = numeros_falados(texto)
    return len(t) < 100 and bool(re.fullmatch(r'(?:hoje |amanha )?(?:as |pelas |para as )?\d{1,2}(?:(?::|h)\d{0,2}| horas?)?(?: e (?:meia|\d{1,2}))?(?: (?:da|de) (?:manha|tarde|noite))?(?: hoje| amanha)?', t))
