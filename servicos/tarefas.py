"""Pendências persistentes. Prazo vencido não encerra a tarefa e sugestão não autoriza aviso."""
import asyncio
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from banco.database import AsyncSessionLocal
from banco.models import TarefaDB, TarefaContextoDB
from servicos.tempo import utc, horario_local

ABERTAS = ('sugestao', 'pendente')


class ConflitoTarefa(ValueError):
    pass


def apresentar(item, agora=None):
    agora = agora or datetime.now(timezone.utc)
    prazo = utc(item.prazo) if item.prazo else None
    local = horario_local(prazo) if prazo else None
    atrasada = bool(prazo and item.estado == 'pendente' and (
        local.date() < horario_local(agora).date() if item.dia_inteiro else prazo < agora))
    return {'id': item.id, 'titulo': item.titulo, 'prazo': prazo.isoformat() if prazo else None,
        'dia_inteiro': bool(item.dia_inteiro), 'estado': item.estado, 'atrasada': atrasada,
        'origem': item.origem, 'contexto': item.contexto, 'versao': item.versao,
        'quando': local.strftime('%d/%m/%Y') + ('' if item.dia_inteiro else local.strftime(' às %H:%M')) if local else 'Sem prazo',
        'aviso': 'No horário do prazo, uma vez' if prazo and not item.dia_inteiro else 'Sem aviso em horário definido'}


class Tarefas:
    def __init__(self): self._lock = asyncio.Lock()

    async def salvar(self, titulo, prazo=None, dia_inteiro=False, origem='pedido', contexto='', confirmar=True, chave_evento=None):
        titulo = str(titulo).strip()
        if not titulo or len(titulo) > 255: raise ValueError('Diga uma tarefa com até 255 caracteres.')
        if prazo is None and dia_inteiro: raise ValueError('Informe a data do prazo ou deixe sem prazo.')
        prazo = utc(prazo) if prazo else None
        chave = hashlib.sha256(str(chave_evento or uuid.uuid4()).encode()).hexdigest()
        async with self._lock:
            try:
                async with AsyncSessionLocal() as session, session.begin():
                    item = (await session.execute(select(TarefaDB).where(TarefaDB.chave_evento == chave))).scalar_one_or_none()
                    if item is not None: return apresentar(item)
                    # Repetir um pedido aberto não empilha a mesma tarefa. Um novo pedido após concluir é permitido.
                    if confirmar:
                        item = (await session.execute(select(TarefaDB).where(TarefaDB.estado == 'pendente',
                            TarefaDB.titulo == titulo, TarefaDB.prazo == prazo, TarefaDB.origem == origem).limit(1))).scalar_one_or_none()
                        if item: return apresentar(item)
                    agora = datetime.now(timezone.utc)
                    item = TarefaDB(id=str(uuid.uuid4()), chave_evento=chave, titulo=titulo, prazo=prazo,
                        dia_inteiro=int(dia_inteiro), estado='pendente' if confirmar else 'sugestao', origem=origem[:255],
                        contexto=contexto[:500], versao=1, criado_em=agora, atualizado_em=agora)
                    session.add(item)
                    await session.flush()
                    return apresentar(item)
            except IntegrityError:
                async with AsyncSessionLocal() as session:
                    item = (await session.execute(select(TarefaDB).where(TarefaDB.chave_evento == chave))).scalar_one()
                    return apresentar(item)

    async def listar(self, estado='abertas'):
        if estado not in {'abertas', 'pendente', 'sugestao', 'concluida', 'descartada'}: raise ValueError('Filtro de tarefas inválido.')
        async with AsyncSessionLocal() as session:
            query = select(TarefaDB).where(TarefaDB.estado.in_(ABERTAS) if estado == 'abertas' else TarefaDB.estado == estado)
            ordem = (TarefaDB.prazo.asc().nulls_last(), TarefaDB.criado_em) if estado in (*ABERTAS, 'abertas') else (TarefaDB.atualizado_em.desc(),)
            itens = (await session.execute(query.order_by(*ordem).limit(200))).scalars().all()
            return [apresentar(item) for item in itens]

    async def obter(self, identificador):
        async with AsyncSessionLocal() as session:
            item = await session.get(TarefaDB, identificador)
            if item is None: raise LookupError('Não encontrei essa tarefa.')
            return apresentar(item)

    async def alterar(self, identificador, acao, prazo=None, dia_inteiro=False, versao=None):
        if acao not in {'aceitar', 'concluir', 'descartar', 'adiar'}: raise ValueError('Ação de tarefa inválida.')
        agora = datetime.now(timezone.utc)
        prazo_passado = True
        if prazo is not None:
            prazo_passado = horario_local(prazo).date() < horario_local(agora).date() if dia_inteiro else utc(prazo) <= agora
        if acao == 'adiar' and prazo_passado:
            raise ValueError('Para quando você quer adiar? Escolha uma data futura.')
        async with AsyncSessionLocal() as session, session.begin():
            item = (await session.execute(select(TarefaDB).where(TarefaDB.id == identificador).with_for_update())).scalar_one_or_none()
            if item is None: raise LookupError('Não encontrei essa tarefa.')
            destino = {'aceitar': 'pendente', 'concluir': 'concluida', 'descartar': 'descartada', 'adiar': 'pendente'}[acao]
            if acao != 'adiar' and item.estado == destino: return apresentar(item)
            if versao is not None and versao != item.versao: raise ConflitoTarefa('Essa tarefa mudou. Atualize a lista antes de tentar novamente.')
            if item.estado not in ABERTAS: raise ConflitoTarefa('Essa tarefa já foi encerrada. Crie outra para um novo pedido.')
            if acao in {'concluir', 'adiar'} and item.estado == 'sugestao':
                raise ValueError('Revise e aceite a sugestão antes de concluir ou adiar.')
            if acao == 'adiar':
                item.prazo = utc(prazo)
                item.dia_inteiro = int(dia_inteiro)
                item.avisado_em = None
            item.estado = destino
            item.versao += 1
            item.atualizado_em = datetime.now(timezone.utc)
            return apresentar(item)

    async def contexto(self, chave):
        async with AsyncSessionLocal() as session:
            item = await session.get(TarefaContextoDB, chave)
            return dict(item.dados) if item and utc(item.expira) > datetime.now(timezone.utc) else None

    async def guardar_contexto(self, chave, dados):
        from sqlalchemy import delete
        async with AsyncSessionLocal() as session, session.begin():
            if dados is None: await session.execute(delete(TarefaContextoDB).where(TarefaContextoDB.chave == chave))
            else: await session.merge(TarefaContextoDB(chave=chave, dados=dados,
                expira=datetime.now(timezone.utc) + timedelta(minutes=10)))

    async def pendentes_aviso(self):
        agora = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as session:
            itens = (await session.execute(select(TarefaDB).where(TarefaDB.estado == 'pendente', TarefaDB.dia_inteiro == 0,
                TarefaDB.prazo <= agora, TarefaDB.prazo >= agora - timedelta(hours=1),
                TarefaDB.avisado_em.is_(None)).order_by(TarefaDB.prazo).limit(100))).scalars().all()
            return [apresentar(i) for i in itens]

    async def marcar_aviso(self, identificador, versao):
        async with AsyncSessionLocal() as session, session.begin():
            resultado = await session.execute(update(TarefaDB).where(TarefaDB.id == identificador,
                TarefaDB.estado == 'pendente', TarefaDB.versao == versao, TarefaDB.avisado_em.is_(None))
                .values(avisado_em=datetime.now(timezone.utc)))
            return resultado.rowcount == 1


tarefas = Tarefas()
