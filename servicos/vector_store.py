# servicos/vector_store.py
import sqlite3
import os
import logging
from sqlalchemy import event
from sqlalchemy.engine import Engine
import sqlite_vec

logger = logging.getLogger("VectorStore")

def configurar_pragmas_e_extensoes(dbapi_connection, connection_record):
    """
    Executado em cada conexão SQLite criada.
    Garante WAL mode, timeout e carregamento da extensão sqlite-vec.
    """
    if isinstance(dbapi_connection, sqlite3.Connection):
        try:
            dbapi_connection.execute("PRAGMA journal_mode=WAL")
            dbapi_connection.execute("PRAGMA synchronous=NORMAL")
            dbapi_connection.execute("PRAGMA busy_timeout=5000")
            
            # Carrega sqlite-vec
            dbapi_connection.enable_load_extension(True)
            sqlite_vec.load(dbapi_connection)
            dbapi_connection.enable_load_extension(False)
        except Exception as e:
            logger.error(f"⚠️ [VectorStore] Erro ao configurar PRAGMAs ou sqlite-vec: {e}")

def inicializar_tabelas_virtuais_e_fts(engine):
    """
    Cria tabelas virtuais FTS5 e sqlite-vec (vec0) caso não existam.
    """
    with engine.connect() as conn:
        raw_conn = conn.connection.dbapi_connection
        if isinstance(raw_conn, sqlite3.Connection):
            try:
                # 1. Tabela FTS5 para busca textual em facts
                raw_conn.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts
                    USING fts5(text, keywords, content='facts', content_rowid='id')
                """)
                
                # Triggers para manter FTS5 sincronizado com a tabela facts
                raw_conn.executescript("""
                    CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON facts BEGIN
                      INSERT INTO facts_fts(rowid, text, keywords) VALUES (new.id, new.text, new.keywords);
                    END;
                    CREATE TRIGGER IF NOT EXISTS facts_ad AFTER DELETE ON facts BEGIN
                      INSERT INTO facts_fts(facts_fts, rowid, text, keywords) VALUES('delete', old.id, old.text, old.keywords);
                    END;
                    CREATE TRIGGER IF NOT EXISTS facts_au AFTER UPDATE ON facts BEGIN
                      INSERT INTO facts_fts(facts_fts, rowid, text, keywords) VALUES('delete', old.id, old.text, old.keywords);
                      INSERT INTO facts_fts(rowid, text, keywords) VALUES (new.id, new.text, new.keywords);
                    END;
                """)

                # 2. Tabela sqlite-vec para embeddings (768 dimensões para nomic-embed-text)
                raw_conn.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS facts_vec 
                    USING vec0(embedding float[768])
                """)
                raw_conn.commit()
                logger.info("✅ [VectorStore] Tabelas virtuais FTS5 e sqlite-vec inicializadas com sucesso.")
            except Exception as e:
                logger.error(f"❌ [VectorStore] Erro ao criar FTS5/vec0: {e}")

def registrar_hooks_conexao():
    from banco.database import async_engine
    sync_eng = async_engine.sync_engine
    event.listens_for(sync_eng, "connect")(configurar_pragmas_e_extensoes)
    inicializar_tabelas_virtuais_e_fts(sync_eng)
