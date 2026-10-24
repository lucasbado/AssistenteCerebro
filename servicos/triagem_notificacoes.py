"""Decide o que precisa de interpretação, antes de chamar um modelo."""
import hashlib
import re
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, delete, update
from banco.database import AsyncSessionLocal
from banco.models import CacheIADB, MensagemRevisaoDB
from servicos.consumo_ia import travar_controle, utc
from servicos.mensagens import sinais_mensagem, chave_conversa
from servicos.controle_casa import normalizar


def relevante(pacote, titulo, texto, tipo='MSG'):
    if tipo != 'MSG' or not isinstance(texto, str) or not texto.strip() or not titulo: return False
    if pacote in {'android', 'com.android.systemui', 'com.example.assistentecell', 'br.com.assistentecell'}: return False
    t = normalizar(str(titulo) + ' ' + texto)
    if re.search(r'\b(?:sincronizando|procurando novas mensagens|whatsapp web|backup em andamento|servico em execucao)\b', t): return False
    if sinais_mensagem(texto): return True
    return bool(re.search(r'\b(?:urgente|emergencia|fraude|compra (?:aprovada|recusada)|tentativa de (?:acesso|login)|vence (?:hoje|amanha)|reuniao|consulta|compromisso)\b', t))


async def reservar(pacote, remetente, texto, referencia=None):
    agora = datetime.now(timezone.utc)
    conversa = chave_conversa(pacote, remetente, referencia)
    assinatura = hashlib.sha256(f'{conversa}|{normalizar(texto)}'.encode()).hexdigest()
    chave = 'notificacao:' + assinatura
    async with AsyncSessionLocal() as s, s.begin():
        await travar_controle(s, 'triagem_notificacoes')
        await s.execute(delete(CacheIADB).where(CacheIADB.chave.like('notificacao:%'), CacheIADB.bloqueado_ate < agora - timedelta(days=2)))
        # Uma revisão encerrada não volta a mobilizar IA por atualização da notificação.
        encerradas = (await s.execute(select(MensagemRevisaoDB.texto).where(MensagemRevisaoDB.conversa == conversa,
            MensagemRevisaoDB.estado.in_(['resolvida', 'ignorada']), MensagemRevisaoDB.recebido_em > agora - timedelta(days=14)))).scalars().all()
        if any(normalizar(t) == normalizar(texto) for t in encerradas): return None
        item = await s.get(CacheIADB, chave)
        if item is not None and utc(item.bloqueado_ate) > agora: return None
        if item is None:
            item = CacheIADB(chave=chave, assinatura=assinatura)
            s.add(item)
        item.bloqueado_ate = agora + timedelta(minutes=10)
        item.atualizado_em = agora
        return chave


async def finalizar(chaves, sucesso=True):
    chaves = [c for c in chaves if isinstance(c, str) and c.startswith('notificacao:')]
    if not chaves: return
    async with AsyncSessionLocal() as s, s.begin():
        await s.execute(update(CacheIADB).where(CacheIADB.chave.in_(chaves)).values(
            bloqueado_ate=datetime.now(timezone.utc) + timedelta(hours=24) if sucesso else datetime.now(timezone.utc) + timedelta(minutes=10)))
