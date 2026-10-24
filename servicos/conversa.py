"""Reconhece explicações e valida respostas sem conceder ações a dispositivos."""
import re
from servicos.controle_casa import normalizar
from servicos.linguagem_pedidos import separar_etapas


def pedido_de_explicacao(texto):
    texto = str(texto or '').strip()
    if len(separar_etapas(texto)) > 1:
        return False  # Uma pergunta junto de uma ordem precisa do planejamento completo.
    t = re.sub(r'^(?:(?:ei )?ollie[,!: ]+)?(?:por favor[, ]+)?', '', normalizar(texto))
    explicacao = bool(re.match(
        r'^(?:por que\b|porque\b|por qual motivo\b|o ?que (?:e|era|foi|seria|sao|significa|quer dizer)\b'
        r'|como (?:funciona\w*|surgiu|surgiram|acontece\w*)\b|qual (?:e )?a diferenca\b'
        r'|(?:me )?(?:explique|explica|explique-me|ensine|ensina)\b'
        r'|(?:me )?(?:conte|conta|diga) (?:uma |alguma )?curiosidade\b)', t))
    if explicacao:
        return True
    # Outras perguntas e continuações também usam o caminho curto. Consultas
    # pessoais ou de estado ficam com o contexto e os controladores completos.
    pergunta = re.match(r'^(?:e )?(?:qual|quais|quem|onde|quando|quanto|quantos|quantas|como|por que|do que|de que)\b', t)
    contexto_pessoal = re.search(r'\b(?:meu|minha|meus|minhas|nosso|nossa|voce|agenda|compromisso|reuniao|tarefas?|rotinas?|mensagens?'
        r'|pc|computador|celular|bateria|volume|microfone|conexao|cpu|temperatura|luz|lampada|agora|hoje|amanha|atual)\b', t)
    return bool(pergunta and not contexto_pessoal)


def resposta_pendente(texto):
    """Um recibo sem resposta nem ação não conclui um pedido do usuário."""
    t = re.sub(r'[^\w\s]', '', normalizar(str(texto or ''))).strip()
    return not t or bool(re.fullmatch(
        r'(?:(?:ok|certo|entendido|pronto)\s+)?(?:'
        r'(?:comando|pedido|solicitacao|pergunta|mensagem) (?:recebid[oa]|registrad[oa]|processad[oa](?: com sucesso)?)'
        r'|(?:recebi|registrei) (?:o seu |sua |seu |o |a )?(?:comando|pedido|solicitacao|pergunta|mensagem)'
        r'|(?:processando|analisando) (?:o |a |seu |sua )?(?:comando|pedido|solicitacao|pergunta|mensagem)'
        r'|vou (?:verificar|pesquisar|processar|analisar)(?: (?:isso|seu pedido|sua pergunta))?'
        r')', t))


def ler_resposta_conversa(data):
    if not isinstance(data, dict):
        raise ValueError('Resposta de conversa fora do contrato JSON.')
    texto = next((data[k].strip() for k in ('resposta', 'mensagem_dinamica', 'texto', 'mensagem')
                  if isinstance(data.get(k), str) and data[k].strip()), '')
    if resposta_pendente(texto):
        raise ValueError('A IA retornou apenas um recibo, sem responder.')
    # Uma explicação nunca herda ferramentas ou memória permanente da saída do modelo.
    return {'intencao_captada': 'CONVERSA', 'tipo_interacao': 'NOTIFICAR',
        'mensagem_dinamica': texto, 'aguarda_resposta': data.get('aguarda_resposta') is True,
        'execucao_direta': []}


def falha_conversa(erro):
    limite = getattr(erro, 'status_code', None) == 429 or any(
        termo in str(erro).lower() for termo in ('rate limit', 'rate_limit', '429', 'orçamento de ia', 'limite do provedor'))
    texto = ('A IA atingiu o limite de uso agora e não consegui responder. Tente de novo mais tarde.'
             if limite else 'Não consegui gerar uma resposta agora. Tente de novo em instantes.')
    return {'intencao_captada': 'FALLBACK_ERRO', 'tipo_interacao': 'NOTIFICAR',
        'mensagem_dinamica': texto, 'aguarda_resposta': False, 'execucao_direta': []}
