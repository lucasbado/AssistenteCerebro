"""Agenda persistente: sugestão não é compromisso confirmado nem despertador instalado."""
import asyncio
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from banco.database import AsyncSessionLocal
from banco.models import AgendaItemDB, AgendaRascunhoDB
from servicos.tempo import utc, horario_local


def apresentar(item):
    inicio = utc(item.inicio)
    local = horario_local(inicio)
    return {'id': item.id, 'tipo': item.tipo, 'titulo': item.titulo, 'inicio': inicio.isoformat(),
        'dia_inteiro': bool(item.dia_inteiro), 'antecedencia_minutos': item.antecedencia_minutos,
        'estado': item.estado, 'origem': item.origem,
        'quando': local.strftime('%d/%m/%Y') + ('' if item.dia_inteiro else local.strftime(' às %H:%M'))}


class Agenda:
    def __init__(self): self._lock = asyncio.Lock()

    async def rascunho(self, chave):
        async with AsyncSessionLocal() as session:
            item = await session.get(AgendaRascunhoDB, chave)
            return item.texto if item and utc(item.expira) > datetime.now(timezone.utc) else None

    async def guardar_rascunho(self, chave, texto):
        async with AsyncSessionLocal() as session, session.begin():
            await session.merge(AgendaRascunhoDB(chave=chave, texto=texto[:3000],
                expira=datetime.now(timezone.utc) + timedelta(minutes=10)))

    async def limpar_rascunho(self, chave):
        from sqlalchemy import delete
        async with AsyncSessionLocal() as session, session.begin():
            await session.execute(delete(AgendaRascunhoDB).where(AgendaRascunhoDB.chave == chave))

    async def salvar(self, tipo, titulo, inicio, dia_inteiro=False, origem='pedido', confirmar=False, antecedencia_minutos=0):
        if tipo not in {'compromisso', 'lembrete', 'alarme'} or not str(titulo).strip():
            raise ValueError('Diga o que você quer guardar na agenda.')
        if dia_inteiro and tipo in {'alarme', 'lembrete'}:
            raise ValueError('Escolha um horário para o despertador ou lembrete.')
        inicio = utc(inicio)
        agora = datetime.now(timezone.utc)
        if inicio < agora - (timedelta(days=1) if dia_inteiro else timedelta(minutes=1)):
            raise ValueError('Essa data já passou. Qual data devo usar?')
        if not 0 <= antecedencia_minutos <= 10080:
            raise ValueError('O lembrete antecipado deve ficar entre zero e sete dias.')
        assinatura = hashlib.sha256(f'{tipo}|{titulo.strip().casefold()}|{inicio.isoformat()}|{origem}'.encode()).hexdigest()
        async with self._lock:
            try:
                async with AsyncSessionLocal() as session, session.begin():
                    item = (await session.execute(select(AgendaItemDB).where(AgendaItemDB.assinatura == assinatura))).scalar_one_or_none()
                    if item is None:
                        item = AgendaItemDB(id=str(uuid.uuid4()), assinatura=assinatura, tipo=tipo, titulo=titulo.strip()[:255],
                            inicio=inicio, dia_inteiro=int(dia_inteiro), origem=origem[:255], antecedencia_minutos=antecedencia_minutos,
                            estado=('preparado' if tipo == 'alarme' else 'agendado') if confirmar else 'sugestao')
                        session.add(item)
                        await session.flush()
                    elif confirmar and item.estado == 'sugestao':
                        item.estado = 'preparado' if tipo == 'alarme' else 'agendado'
                    elif confirmar and item.estado in {'cancelado', 'concluido'}:
                        raise ValueError('Esse item já foi encerrado. Diga outra data ou título para criar um novo.')
                    return apresentar(item)
            except IntegrityError:
                async with AsyncSessionLocal() as session:
                    item = (await session.execute(select(AgendaItemDB).where(AgendaItemDB.assinatura == assinatura))).scalar_one()
                    return apresentar(item)

    async def listar(self):
        async with AsyncSessionLocal() as session:
            itens = (await session.execute(select(AgendaItemDB).where(AgendaItemDB.estado.in_(['sugestao', 'agendado', 'preparado']),
                AgendaItemDB.inicio >= datetime.now(timezone.utc) - timedelta(days=1)).order_by(AgendaItemDB.inicio).limit(100))).scalars().all()
            return [apresentar(i) for i in itens]

    async def obter(self, identificador):
        async with AsyncSessionLocal() as session:
            item = await session.get(AgendaItemDB, identificador)
            if item is None: raise LookupError('Esse item não está mais na agenda.')
            return apresentar(item)

    async def alterar_estado(self, identificador, estado, antecedencia_minutos=None):
        if estado not in {'agendado', 'cancelado', 'concluido'}: raise ValueError('Estado de agenda inválido.')
        if antecedencia_minutos is not None and not 0 <= antecedencia_minutos <= 10080:
            raise ValueError('O lembrete antecipado deve ficar entre zero e sete dias.')
        async with AsyncSessionLocal() as session, session.begin():
            item = (await session.execute(select(AgendaItemDB).where(AgendaItemDB.id == identificador).with_for_update())).scalar_one_or_none()
            if item is None: raise LookupError('Esse item não está mais na agenda.')
            if estado == 'agendado' and item.estado in {'cancelado', 'concluido'}:
                raise ValueError('Esse item já foi encerrado. Crie outro para remarcar.')
            if estado == 'agendado' and utc(item.inicio) < datetime.now(timezone.utc) and not item.dia_inteiro:
                raise ValueError('Esse horário já passou. Crie outro item com a data certa.')
            item.estado = 'preparado' if estado == 'agendado' and item.tipo == 'alarme' else estado
            if antecedencia_minutos is not None: item.antecedencia_minutos = antecedencia_minutos
            return apresentar(item)

    async def pendentes_aviso(self):
        async with AsyncSessionLocal() as session:
            itens = (await session.execute(select(AgendaItemDB).where(AgendaItemDB.estado == 'agendado',
                AgendaItemDB.tipo != 'alarme', AgendaItemDB.dia_inteiro == 0, AgendaItemDB.avisado_em.is_(None),
                AgendaItemDB.inicio >= datetime.now(timezone.utc) - timedelta(hours=1),
                AgendaItemDB.inicio <= datetime.now(timezone.utc) + timedelta(days=7)).limit(100))).scalars().all()
            agora = datetime.now(timezone.utc)
            return [apresentar(i) for i in itens if utc(i.inicio) - timedelta(minutes=i.antecedencia_minutos) <= agora]

    async def marcar_aviso(self, identificador):
        async with AsyncSessionLocal() as session, session.begin():
            resultado = await session.execute(update(AgendaItemDB).where(AgendaItemDB.id == identificador,
                AgendaItemDB.avisado_em.is_(None), AgendaItemDB.estado == 'agendado').values(avisado_em=datetime.now(timezone.utc)))
            return resultado.rowcount == 1


agenda = Agenda()
