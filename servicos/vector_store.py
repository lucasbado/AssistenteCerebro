"""Inicialização SQLite compatível com o adaptador assíncrono aiosqlite."""
import logging
from sqlalchemy import event
import sqlite_vec

logger = logging.getLogger("VectorStore")

def registrar_hooks_conexao(engine):
    sync_engine = engine.sync_engine
    if event.contains(sync_engine, "connect", configurar_pragmas_e_extensoes):
        return
    event.listen(sync_engine, "connect", configurar_pragmas_e_extensoes)

def configurar_pragmas_e_extensoes(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()
    async def carregar(connection):
        await connection.enable_load_extension(True)
        try:
            await connection.load_extension(sqlite_vec.loadable_path())
        finally:
            await connection.enable_load_extension(False)
    try:
        dbapi_connection.run_async(carregar)
    except Exception:
        logger.exception("sqlite-vec indisponível; busca textual continua habilitada")

async def inicializar_tabelas_virtuais_e_fts(conn):
    existente = (await conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE name='facts_fts'")).first()
    await conn.exec_driver_sql("CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(text, keywords, content='facts', content_rowid='id')")
    for nome, operacao, corpo in (
        ("facts_ai", "INSERT", "INSERT INTO facts_fts(rowid,text,keywords) VALUES(new.id,new.text,new.keywords);"),
        ("facts_ad", "DELETE", "INSERT INTO facts_fts(facts_fts,rowid,text,keywords) VALUES('delete',old.id,old.text,old.keywords);"),
        ("facts_au", "UPDATE", "INSERT INTO facts_fts(facts_fts,rowid,text,keywords) VALUES('delete',old.id,old.text,old.keywords); INSERT INTO facts_fts(rowid,text,keywords) VALUES(new.id,new.text,new.keywords);"),
    ):
        await conn.exec_driver_sql(f"CREATE TRIGGER IF NOT EXISTS {nome} AFTER {operacao} ON facts BEGIN {corpo} END")
    if not existente:
        await conn.exec_driver_sql("INSERT INTO facts_fts(facts_fts) VALUES('rebuild')")
    # O módulo pode faltar em instalações sem suporte a extensões.
    modules = (await conn.exec_driver_sql("PRAGMA module_list")).scalars().all()
    if "vec0" in modules:
        await conn.exec_driver_sql("CREATE VIRTUAL TABLE IF NOT EXISTS facts_vec USING vec0(embedding float[768])")
