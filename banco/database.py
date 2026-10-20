import logging
import os
from pathlib import Path
from sqlalchemy import inspect
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)
default_sqlite = "sqlite+aiosqlite:///" + (Path(__file__).resolve().parents[1] / "agente_local.db").as_posix()
DATABASE_URL = os.getenv("DATABASE_URL", default_sqlite)

def _criar_motor(url: str):
    parsed = make_url(url)
    connect_args = {}
    if parsed.drivername in ("postgres", "postgresql", "postgresql+asyncpg"):
        query = dict(parsed.query)
        sslmode = query.pop("sslmode", None)
        query.pop("channel_binding", None)
        if sslmode and sslmode != "disable":
            connect_args["ssl"] = "require" if sslmode in ("require", "prefer", "allow") else sslmode
        parsed = parsed.set(drivername="postgresql+asyncpg", query=query)
    engine = create_async_engine(parsed, connect_args=connect_args, echo=False)
    if engine.dialect.name == "sqlite":
        from servicos.vector_store import registrar_hooks_conexao
        registrar_hooks_conexao(engine)
    return engine

async_engine = _criar_motor(DATABASE_URL)
AsyncSessionLocal = sessionmaker(bind=async_engine, class_=AsyncSession,
                                expire_on_commit=False, autoflush=False)

async def obter_sessao_banco():
    async with AsyncSessionLocal() as session:
        yield session

async def inicializar_banco(engine=None):
    """Inicializa apenas o banco configurado; falhas não trocam a fonte de dados."""
    from banco.models import Base
    from servicos.vector_store import inicializar_tabelas_virtuais_e_fts
    engine = engine or async_engine
    async with engine.begin() as conn:
        # Migra bancos existentes antes de create_all criar índices das colunas novas.
        def migrar(sync_conn):
            inspector = inspect(sync_conn)
            if inspector.has_table("task_queue"):
                if "locked_until" not in {c["name"] for c in inspector.get_columns("task_queue")}:
                    tipo_data = "TIMESTAMP WITH TIME ZONE" if sync_conn.dialect.name == "postgresql" else "TIMESTAMP"
                    sync_conn.exec_driver_sql(f"ALTER TABLE task_queue ADD COLUMN locked_until {tipo_data}")
            if inspector.has_table("facts"):
                colunas = {c["name"] for c in inspector.get_columns("facts")}
                for nome, tipo in (("source_file", "VARCHAR(255)"), ("source_hash", "VARCHAR(64)")):
                    if nome not in colunas:
                        sync_conn.exec_driver_sql(f"ALTER TABLE facts ADD COLUMN {nome} {tipo}")
        await conn.run_sync(migrar)
        await conn.run_sync(Base.metadata.create_all)
        if engine.dialect.name == "sqlite":
            await inicializar_tabelas_virtuais_e_fts(conn)
