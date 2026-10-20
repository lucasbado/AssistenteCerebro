"""Catálogo da casa e ordens simples; não conhece hardware, rede ou agentes."""
import json
import re
import unicodedata
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config/casa.json"
ACOES = {"ligar_luz": "ligar", "turn_on_light": "ligar", "desligar_luz": "desligar",
         "turn_off_light": "desligar", "toggle_luz": "alternar", "toggle_light": "alternar",
         "consultar_luz": "consultar"}


def normalizar(texto):
    return " ".join("".join(c for c in unicodedata.normalize("NFD", str(texto).lower())
                            if unicodedata.category(c) != "Mn").strip(" .!?,").split())


class ControleCasa:
    def __init__(self, path=CONFIG_PATH):
        self.path = Path(path)

    def catalogo(self):
        dados = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(dados, dict):
            raise ValueError("Catálogo da casa inválido")
        for chave, item in dados.items():
            if not re.fullmatch(r"[a-z0-9_-]+", chave) or not isinstance(item, dict):
                raise ValueError("Dispositivo inválido no catálogo")
            if not re.fullmatch(r"light\.[a-z0-9_]+", item.get("entity_id", "")):
                raise ValueError("Luz sem entidade válida no catálogo")
        return dados

    def resolver(self, alvo):
        nome = normalizar(alvo)
        candidatos = []
        for chave, item in self.catalogo().items():
            nomes = [chave, item.get("nome", ""), item["entity_id"], *item.get("apelidos", [])]
            if nome in {normalizar(n) for n in nomes}:
                candidatos.append({"id": chave, **item})
        if len(candidatos) != 1:
            raise LookupError("Não identifiquei uma única luz cadastrada com esse nome. Diga qual luz você quer controlar.")
        return candidatos[0]

    def interpretar(self, texto):
        t = normalizar(texto)
        t = re.sub(r"^ollie[, ]+", "", t)
        t = re.sub(r"^por favor[, ]+", "", t)
        t = re.sub(r"^(?:voce\s+)?(?:pode|poderia|consegue)\s+", "", t)
        t = re.sub(r"^(?:eu\s+)?quero que (?:voce\s+)?", "", t)
        t = re.sub(r"[, ]+(?:por favor|pra mim|para mim)$", "", t)
        consulta = re.fullmatch(r"(?:como (?:esta|estao)|qual (?:e )?o estado (?:da|das)|(?:a|as))\s+(.+?)(?:\s+(?:esta|estao)\s+(?:acesa|acesas|apagada|apagadas|ligada|ligadas|desligada|desligadas))?", t)
        ordem = re.fullmatch(r"(desliga[r]?|desligue|apaga[r]?|apague|liga[r]?|ligue|acende[r]?|acenda|alterna[r]?|alterne)\s+(.+)", t)
        if not ordem and not consulta:
            return None
        alvo = ordem.group(2) if ordem else consulta.group(1)
        alvo = re.sub(r"^(?:a|as|minha|minhas)\s+", "", alvo)
        alvo = alvo.replace("do meu ", "do ").replace("da minha ", "da ")
        # O parser só captura luzes; ordens de PC e outros pedidos seguem seu fluxo.
        if not re.search(r"\b(?:luz|luzes|lampada|lampadas|luzinha|iluminacao)\b", alvo):
            return None
        if re.search(r"\b(?:e|mas|depois|se|quando|nao)\b", alvo):
            return None
        acao = "consultar"
        if ordem:
            verbo = ordem.group(1)
            acao = "desligar" if verbo.startswith(("deslig", "apag")) else "ligar" if verbo.startswith(("lig", "acend")) else "alternar"
        return {"acao": acao, "alvo": alvo}


controle_casa = ControleCasa()
