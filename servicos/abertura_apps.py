"""Pedidos explícitos e sugestões de abertura não executam inferências de texto externo."""
import json
import re
from servicos.controle_casa import normalizar
from core.tipos import CategoriaEvento, OrigemEvento, TipoAcao


def pedido_explicito_de_abertura(texto):
    t = normalizar(texto)
    if re.search(r"\b(nao|nunca|quando|se|como|devo|deveria)\b", t):
        return False
    return bool(re.match(r"^(?:ollie[, ]+)?(?:por favor[, ]+)?(?:pode |poderia |quero que voce |quero )?(?:abr[aei]|abrir|inicie|inicia|iniciar|abra)\b", t))


def metadados_abertura(decisao):
    return {"abertura_autorizada": True, "abertura_modo": decisao["modo"],
            "importance_score": decisao.get("importance_score", 1.0)}


async def sugerir_abertura(evento, alvo, comando, parametro, motivo):
    from core.kernel import kernel
    from servicos.intervention_governor import identidade
    pc = alvo == "PC"
    link_recebido = False
    sem_link = False
    if not pc and evento.categoria == CategoriaEvento.NOTIFICACAO:
        from servicos.links_notificacao import destino_de_link
        link_recebido, url = destino_de_link(evento.payload, comando, parametro)
        if link_recebido:
            sem_link = url is None
            comando = "OPEN_APP" if sem_link else "OPEN_URL"
            parametro = evento.pacote if sem_link else url
    nome = {"whatsapp": "WhatsApp", "instagram": "Instagram", "spotify": "Spotify",
            "vscode": "VS Code", "telegram": "Telegram"}.get(identidade(parametro), str(parametro or "o aplicativo"))
    acao = "PC_COMMAND" if pc else ("OPEN_APP" if "app" in comando else comando.upper())
    parametro_acao = json.dumps({"alvo": "PC", "acao": comando, "parametro": parametro}) if pc else parametro
    texto = f"Quer abrir {nome} {'no PC' if pc else 'no celular'}?"
    if link_recebido:
        texto = ("Há uma sugestão relacionada a uma mensagem. Abra o aplicativo de origem para escolher o conteúdo."
                 if sem_link else "Recebi um link na mensagem. Quer abrir esse conteúdo?")
    await kernel.publicar(evento.clonar(
        categoria=CategoriaEvento.INTENCAO_NOTIFICACAO, acao=TipoAcao.INTENCAO_INTERACAO,
        origem=OrigemEvento.IA, pacote="sistema.sugestao_app",
        payload={"titulo": "Link recebido" if link_recebido and not sem_link else "Sugestão de aplicativo", "texto": texto,
                 "tipo_ws": "NOTIFICACAO", "acao_tipo": acao, "acao_parametro": parametro_acao,
                 "acao_texto": "Ver mensagem" if sem_link else ("Abrir link" if link_recebido else ("Abrir no PC" if pc else "Abrir aplicativo")),
                 "chave_deduplicacao": f"abertura:{alvo}:{parametro}"},
        metadados={"tipo_destino": "NOTIFICACAO", "motivo_sugestao": motivo}))
