"""Orçamento compartilhado: reservas antes da rede, uso real depois, sem prompts no ledger."""
import logging
import os
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, update, delete
from banco.database import AsyncSessionLocal
from banco.models import ControleIADB, UsoIADB

logger = logging.getLogger(__name__)
escopo_ia = ContextVar('escopo_ia', default=('interno', False))


class LimiteIA(ValueError): pass


@contextmanager
def uso_ia(funcao, solicitado=False):
    token = escopo_ia.set((funcao, bool(solicitado)))
    try: yield
    finally: escopo_ia.reset(token)


async def travar_controle(session, chave='orcamento'):
    # INSERT ... DO NOTHING e UPDATE adquirem também o lock de escrita do SQLite.
    dialect = session.bind.dialect.name
    if dialect == 'postgresql':
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    await session.execute(insert(ControleIADB).values(chave=chave, versao=0, dados={}).on_conflict_do_nothing(index_elements=['chave']))
    await session.execute(update(ControleIADB).where(ControleIADB.chave == chave).values(versao=ControleIADB.versao + 1))
    return (await session.execute(select(ControleIADB).where(ControleIADB.chave == chave).execution_options(populate_existing=True))).scalar_one()


def utc(dt):
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


class ConsumoIA:
    def limites(self):
        return {'total_24h': max(0, int(os.getenv('OLLIE_IA_TOKENS_24H', '100000'))),
                'automatico_24h': max(0, int(os.getenv('OLLIE_IA_AUTO_TOKENS_24H', '20000'))),
                'automatico_1h': max(0, int(os.getenv('OLLIE_IA_AUTO_TOKENS_1H', '4000')))}

    async def reservar(self, modelo, prompt, system, max_tokens, provider='groq'):
        funcao, solicitado = escopo_ia.get()
        entrada = (len(prompt.encode()) + len(system.encode())) // 3 + 256
        agora = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as s, s.begin():
            controle = await travar_controle(s)
            bloqueado = controle.dados.get(provider + ':' + modelo, 0)
            if bloqueado > agora.timestamp(): raise LimiteIA('Modelo em espera após limite do provedor.')
            await s.execute(delete(UsoIADB).where(UsoIADB.criado_em < agora - timedelta(days=30)))
            itens = (await s.execute(select(UsoIADB).where(UsoIADB.provider == provider, UsoIADB.criado_em > agora - timedelta(hours=24)))).scalars().all()
            total = sum(i.entrada + i.saida for i in itens)
            auto = sum(i.entrada + i.saida for i in itens if not i.solicitado)
            hora = sum(i.entrada + i.saida for i in itens if not i.solicitado and utc(i.criado_em) > agora - timedelta(hours=1))
            limites = self.limites()
            if provider == 'cloudflare':
                # Teto conservador próprio, não equivale ao saldo de neurons da conta.
                limites = dict(total_24h=60000, automatico_24h=0, automatico_1h=0)
            previsto = entrada + max_tokens
            if total + previsto > limites['total_24h'] or (not solicitado and (
                auto + previsto > limites['automatico_24h'] or hora + previsto > limites['automatico_1h'])):
                raise LimiteIA('Orçamento de IA atingido; capacidade reservada para pedidos diretos.')
            identificador = str(uuid.uuid4())
            s.add(UsoIADB(id=identificador, criado_em=agora, provider=provider, modelo=modelo,
                funcao=funcao, solicitado=int(solicitado), entrada=entrada, saida=max_tokens, estimado=1, estado='reservado'))
            return identificador

    async def concluir(self, identificador, usage=None, recusado=False):
        async with AsyncSessionLocal() as s, s.begin():
            item = await s.get(UsoIADB, identificador)
            if item is None: return
            if recusado:
                item.entrada = item.saida = 0
                item.estimado, item.estado = 0, 'recusado'
            elif usage is not None and isinstance(getattr(usage, 'prompt_tokens', None), int) and isinstance(getattr(usage, 'completion_tokens', None), int):
                item.entrada, item.saida = max(0, usage.prompt_tokens), max(0, usage.completion_tokens)
                item.estimado, item.estado = 0, 'concluido'
            else:
                item.estado = 'estimado'

    async def bloquear(self, modelo, segundos, provider='groq'):
        async with AsyncSessionLocal() as s, s.begin():
            controle = await travar_controle(s)
            dados = dict(controle.dados)
            chave = provider + ':' + modelo
            dados[chave] = max(dados.get(chave, 0), datetime.now(timezone.utc).timestamp() + segundos)
            controle.dados = dados

    async def registrar_local(self, modelo, entrada, saida):
        funcao, solicitado = escopo_ia.get()
        async with AsyncSessionLocal() as s, s.begin():
            s.add(UsoIADB(id=str(uuid.uuid4()), criado_em=datetime.now(timezone.utc), provider='pc', modelo=modelo[:150],
                funcao=funcao, solicitado=int(solicitado), entrada=max(0, entrada), saida=max(0, saida), estimado=0, estado='concluido'))

    async def resumo(self):
        agora = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as s:
            itens = (await s.execute(select(UsoIADB).where(UsoIADB.criado_em > agora - timedelta(hours=24)))).scalars().all()
        grupos = {}
        for i in itens:
            chave = (i.provider, i.modelo, i.funcao, bool(i.solicitado))
            g = grupos.setdefault(chave, dict(provider=i.provider, modelo=i.modelo, funcao=i.funcao, solicitado=bool(i.solicitado), tokens=0, chamadas=0, estimativas=0))
            g['tokens'] += i.entrada + i.saida
            g['chamadas'] += 1
            g['estimativas'] += i.estimado
        groq = [i for i in itens if i.provider == 'groq']
        total = sum(i.entrada + i.saida for i in groq)
        return dict(janela='ultimas_24h', limites=self.limites(), tokens_groq=total,
            tokens_automaticos=sum(i.entrada + i.saida for i in groq if not i.solicitado),
            restante_groq=max(0, self.limites()['total_24h'] - total), por_funcao=list(grupos.values()))


consumo_ia = ConsumoIA()
