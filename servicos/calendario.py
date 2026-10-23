"""Projeção de itens confirmados para cópias no calendário escolhido no Android."""
import os
import logging
from sqlalchemy import select
from banco.database import AsyncSessionLocal
from banco.models import AgendaItemDB, TarefaDB
from servicos.tempo import utc, horario_local


async def avisar_celular():
    """A cópia é eventual: indisponibilidade do celular não desfaz um item já salvo."""
    try:
        from api.websocket import central_alertas
        await central_alertas.solicitar_sincronizacao_calendario()
    except Exception:
        logging.getLogger(__name__).warning('Celular indisponível para atualizar calendário')


def apresentar(item, dominio):
    tarefa = dominio == 'tarefa'
    inicio = item.prazo if tarefa else item.inicio
    ativo = item.estado == ('pendente' if tarefa else 'agendado') and inicio is not None
    if not tarefa and item.tipo == 'alarme': ativo = False
    return {'id': item.id, 'dominio': dominio, 'titulo': item.titulo, 'ativo': ativo,
        'inicio': utc(inicio).isoformat() if inicio else None,
        'data_local': horario_local(inicio).strftime('%Y-%m-%d') if inicio else None,
        'dia_inteiro': bool(item.dia_inteiro), 'fuso': os.getenv('OLLIE_TIMEZONE', 'America/Sao_Paulo'),
        'duracao_minutos': 1 if tarefa else 60,
        'descricao': 'Prazo de tarefa da Ollie. Marcador de um minuto, sem reservar disponibilidade.' if tarefa else
            'Compromisso da Ollie. Duração padrão de uma hora; ajuste no calendário se necessário.'}


async def itens_calendario(conhecidos=()):
    resultado = {}
    async with AsyncSessionLocal() as session:
        for dominio, modelo in [('agenda', AgendaItemDB), ('tarefa', TarefaDB)]:
            filtro = (modelo.estado == 'agendado') & (modelo.tipo != 'alarme') if dominio == 'agenda' else (modelo.estado == 'pendente') & modelo.prazo.is_not(None)
            novos = (await session.execute(select(modelo).where(filtro).order_by(modelo.criado_em.desc()).limit(500))).scalars().all()
            ids = [str(i['id']) for i in conhecidos if i['dominio'] == dominio]
            existentes = (await session.execute(select(modelo).where(modelo.id.in_(ids)))).scalars().all() if ids else []
            for item in [*novos, *existentes]: resultado[f'{dominio}:{item.id}'] = apresentar(item, dominio)
    return {'itens': list(resultado.values())}
