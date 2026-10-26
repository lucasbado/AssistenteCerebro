"""Estado da persistência por aplicação; nunca troca o banco configurado."""
import os

AVISO_LIMITADO = (
    "Estou em modo limitado porque o banco está indisponível. Posso atender controles diretos "
    "do celular, PC e luzes, mas agenda, tarefas, memória e rotinas aprendidas estão pausadas. "
    "Não salvei esse pedido na memória."
)


def modo_limitado(app):
    return bool(getattr(getattr(app, 'state', None), 'modo_limitado', False))


def modo_forcado():
    return os.getenv('OLLIE_MODO_LIMITADO', '').strip().lower() in {'true', '1', 'yes'}


def quota_excedida(erro):
    """Somente a recusa explícita do provedor autoriza a recuperação automática."""
    pendentes, vistos = [erro], set()
    while pendentes:
        atual = pendentes.pop()
        if id(atual) in vistos:
            continue
        vistos.add(id(atual))
        if 'your account or project has exceeded the quota' in str(atual).lower():
            return True
        for nome in ('orig', '__cause__', '__context__'):
            proximo = getattr(atual, nome, None)
            if isinstance(proximo, BaseException):
                pendentes.append(proximo)
    return False


def estado_sistema(app):
    limitado = modo_limitado(app)
    return {'modo': 'limitado' if limitado else 'completo',
            'persistencia_disponivel': not limitado,
            'motivo': getattr(app.state, 'motivo_limitado', None) if limitado else None}
