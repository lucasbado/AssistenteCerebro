"""
Corretor Fonético de Transcrição de Voz (< 1ms).
Compara o som das palavras ouvidas com expressões do ecossistema Ollie para corrigir transcrições mal ouvidas.
"""
import re
import unicodedata
from difflib import SequenceMatcher

_SO_LETRA = re.compile(r"[^a-z]")

_TROCAS = [
    (re.compile(r"^h"), ""),
    (re.compile(r"ch"), "x"),
    (re.compile(r"lh"), "l"),
    (re.compile(r"nh"), "n"),
    (re.compile(r"ph"), "f"),
    (re.compile(r"sh"), "x"),
    (re.compile(r"th"), "t"),
    (re.compile(r"qu"), "k"),
    (re.compile(r"gu([ei])"), r"g\1"),
    (re.compile(r"sc([ei])"), r"s\1"),
    (re.compile(r"xc([ei])"), r"s\1"),
    (re.compile(r"c([ei])"), r"s\1"),
    (re.compile(r"g([ei])"), r"j\1"),
    (re.compile(r"c"), "k"),
    (re.compile(r"z"), "s"),
    (re.compile(r"y"), "i"),
    (re.compile(r"w"), "v"),
    (re.compile(r"x"), "s"),
    (re.compile(r"l($|[^aeiou])"), r"u\1"),
    (re.compile(r"m($|[^aeiou])"), r"n\1"),
    (re.compile(r"ao$"), "au"),
    (re.compile(r"an$"), "au"),
    (re.compile(r"n$"), ""),
    (re.compile(r"e$"), "i"),
    (re.compile(r"o$"), "u"),
    (re.compile(r"os$"), "us"),
    (re.compile(r"es$"), "is"),
    (re.compile(r"(.)\1+"), r"\1"),
]


def som(texto: str) -> str:
    """Converte o texto para a representação fonética de seus sons."""
    s = str(texto or "").lower().replace("ç", "s")
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    saida = []
    for p in s.split():
        p = _SO_LETRA.sub("", p)
        if not p:
            continue
        for rx, novo in _TROCAS:
            p = rx.sub(novo, p)
        saida.append(p)
    return "".join(saida)


_FRASES = [
    "bom dia", "boa tarde", "boa noite", "boa madrugada",
    "tudo bem", "tudo bom", "tudo certo", "tudo joia",
    "como você está", "com licença", "até logo", "boa sorte",
    "bom dia Ollie", "boa noite Ollie", "boa tarde Ollie", "ei Ollie", "olá Ollie",
    "bloco de notas", "gerenciador de tarefas", "explorador de arquivos",
    "painel de controle", "prompt de comando", "área de trabalho",
    "pasta de download", "pasta de downloads", "minha pasta de download",
    "que horas são", "que dia é hoje", "previsão do tempo", "como está o tempo",
]

_NOMES = [
    "Ollie", "Puck", "Charon", "Fenrir", "Kore", "Aoede", "Thalita", "Francisca", "Antônio",
    "WhatsApp", "YouTube", "Chrome", "Google", "Gmail", "Spotify",
    "Discord", "Telegram", "Instagram", "Facebook", "Windows", "Home Assistant",
]

_COMUNS = set("""
a as o os um uma uns umas de do da dos das em no na nos nas por para pra pro
ao aos na nas pelo pela pelos pelas com sem sob sobre entre ate desde apos contra e ou mas porem entao porque
nem nao ne ta to pois assim tao que quem qual quais quando onde como quanto quanta quantos quantas
eu tu ele ela nos vos eles elas me te se lhe lhes meu minha meus minhas teu tua seu sua seus suas nosso nossa dele dela deles delas
sim nao talvez tambem so apenas ja ainda sempre nunca agora hoje ontem amanha depois antes cedo tarde noite dia manha semana mes ano hora horas minuto segundo
muito muita muitos muitas pouco pouca poucos poucas todo toda todos todas nada tudo algo alguem ninguem outro outra outros outras mesmo mesma qualquer
maior menor mais menos melhor pior tao ser estar ter haver fazer ir vir dar ver saber poder querer dizer falar ficar passar chegar deixar achar levar trazer colocar pegar entrar sair precisar gostar pensar sentir viver morar comprar vender pagar receber
bom boa bons boas legal ruim otimo otima pessimo bonito bonita feio alto alta baixo baixa rapido rapida facil dificil
quase cara entendi bem ola oi tchau valeu obrigado obrigada favor licenca desculpa
abre abra abrir fecha feche fechar apaga apagar organiza organizar pesquisa pesquisar procura procurar busca buscar mostra mostrar analisa analise analisar digita digitar escreve escrever cria criar manda mandar tira tirar poe coloca ativa ativar desativa desativar desfaz desfazer para parar continua continuar espera esperar
computador celular teclado monitor camera internet tela mouse pasta arquivo programa site video imagem foto texto musica noticia noticias
""".split())


def _monta_indice():
    entradas = []
    tri = {}
    for texto, e_nome in [(f, False) for f in _FRASES] + [(n, True) for n in _NOMES]:
        chave = som(texto)
        if not chave:
            continue
        item = (chave, len(chave), tuple(som(p) for p in texto.split()), texto, e_nome)
        idx = len(entradas)
        entradas.append(item)
        for g in _trigramas(chave):
            tri.setdefault(g, []).append(idx)
    return entradas, tri


def _trigramas(chave: str):
    if len(chave) < 3:
        return [chave]
    return [chave[i:i + 3] for i in range(len(chave) - 2)]


_ENTRADAS, _TRI = _monta_indice()
_MAIOR_JANELA = max(len(e[2]) for e in _ENTRADAS) if _ENTRADAS else 1

_PISO_FRASE = 0.85
_PISO_CURTO = 0.90
_PISO_NOME = 0.85
_PISO_JUNCAO = 0.85
_MINIMO_SONS_SOZINHA = 5

_PALAVRA = re.compile(r"[0-9A-Za-zÀ-ÿ]+")


def _e_comum(palavra: str) -> bool:
    s = unicodedata.normalize("NFD", str(palavra or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn") in _COMUNS


def _candidatos(chave: str):
    conta = {}
    for g in _trigramas(chave):
        for idx in _TRI.get(g, ()):
            conta[idx] = conta.get(idx, 0) + 1
    minimo = 1 if len(chave) <= 4 else 2
    return [_ENTRADAS[i] for i, c in conta.items() if c >= minimo]


def _melhor(chave: str, grupo: list, comuns: list, sons: list):
    tam = len(grupo)
    n = len(chave)
    escolha, melhor_r = None, 0.0
    for chave_cat, n_cat, sons_cat, texto_cat, e_nome in _candidatos(chave):
        dw = abs(len(sons_cat) - tam)
        if dw > 1:
            continue
        if dw == 0:
            if abs(n_cat - n) > 2 + n // 8:
                continue
            if tam == 1:
                if comuns[0] or n < _MINIMO_SONS_SOZINHA:
                    continue
                piso = _PISO_NOME if e_nome else 1.0
            else:
                piso = _PISO_CURTO if min(n, n_cat) <= 5 else _PISO_FRASE
        else:
            piso = _PISO_JUNCAO
        r = 1.0 if chave == chave_cat else SequenceMatcher(None, chave, chave_cat).ratio()
        if r >= piso and r > melhor_r:
            escolha, melhor_r = texto_cat, r
    return escolha


def corrigir_fala(texto: str) -> str:
    """Corrige transcrições de fala aproximando foneticamente dos termos cadastrados."""
    bruto = str(texto or "").strip()
    if not bruto:
        return ""
    achados = list(_PALAVRA.finditer(bruto))
    if not achados:
        return bruto

    palavras = [m.group(0) for m in achados]
    comuns = [_e_comum(p) for p in palavras]
    sons = [som(p) for p in palavras]
    total = len(palavras)

    saida = list(palavras)
    i = 0
    while i < total:
        andou = 0
        limite = i
        for tam in range(min(_MAIOR_JANELA, total - i), 0, -1):
            grupo = palavras[i:i + tam]
            chave = som(" ".join(grupo))
            if len(chave) < 3:
                continue
            certo = _melhor(chave, grupo, comuns[i:i + tam], sons[i:i + tam])
            if certo is not None and certo.lower() != " ".join(grupo).lower():
                saida[i] = certo
                for k in range(1, tam):
                    saida[i + k] = ""
                andou = tam
                break
        i += andou or 1

    return " ".join([p for p in saida if p])
