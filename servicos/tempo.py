"""Conversão explícita de UTC (persistência) para o horário do usuário."""
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def utc(timestamp: datetime) -> datetime:
    return timestamp.replace(tzinfo=timezone.utc) if timestamp.tzinfo is None else timestamp.astimezone(timezone.utc)


def horario_local(timestamp: datetime) -> datetime:
    # SQLite devolve timestamps sem tzinfo; os eventos são persistidos em UTC.
    return utc(timestamp).astimezone(ZoneInfo(os.getenv("OLLIE_TIMEZONE", "America/Sao_Paulo")))


def periodo_do_dia(timestamp: datetime) -> str:
    hora = horario_local(timestamp).hour
    if 6 <= hora < 12:
        return "MANHA"
    if 12 <= hora < 18:
        return "TARDE"
    if 18 <= hora < 24:
        return "NOITE"
    return "MADRUGADA"
