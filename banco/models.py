from sqlalchemy import Column, Integer, String, Float, JSON, DateTime, ForeignKey, LargeBinary, Index, text as sql_text
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime, timezone

Base = declarative_base()

class EventoEpisodicoDB(Base):
    """
    MEMÓRIA EPISÓDICA (O histórico permanente do cérebro).
    Salva rigorosamente todos os Eventos Canônicos que passaram pelo Filtro de Atenção.
    Garante rastreabilidade estrita da linhagem de pensamento (id -> pai -> correlacao).
    """
    __tablename__ = "memoria_episodica"

    id = Column(String(36), primary_key=True) # UUID convertido para String
    correlacao_id = Column(String(36), index=True)
    evento_pai_id = Column(String(36), index=True, nullable=True)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    
    origem = Column(String(100), index=True) # Ex: 'android.sensor.notification'
    tipo = Column(String(100), index=True)   # Ex: 'NOTIFICACAO_RECEBIDA'
    
    score_atencao = Column(Float, default=0.0)
    payload = Column(JSON) # Armazena o dicionário arbitrário do evento imutável

class EntidadeSemanticaDB(Base):
    """
    MEMÓRIA SEMÂNTICA (Fatos puros e o grafo de conhecimento local).
    """
    __tablename__ = "memoria_semantica"
    id = Column(Integer, primary_key=True)
    tipo = Column(String(50), index=True)   # Ex: ARTISTA, APP, CONTATO
    chave = Column(String(255), index=True) # Ex: Staind, com.whatsapp
    dados_json = Column(JSON)               # Fatos e metadados estruturados

class PerfilUsuarioDB(Base):
    """
    MEMÓRIA DE PERFIL E HÁBITOS (Estatísticas vivas com suporte a decaimento temporal).
    """
    __tablename__ = "memoria_perfil"
    id = Column(Integer, primary_key=True)
    categoria = Column(String(50), index=True) # Ex: GENERO_MUSICAL, APP_USO
    valor = Column(String(255), index=True)    # Ex: Post-Grunge, com.whatsapp
    score = Column(Integer, default=0)         # Frequência absoluta de ativação
    confianca = Column(Float, default=0.0)     # Score normalizado de 0.0 a 1.0
    
    # CRUCIAL: Timestamp para o Agente de Memória aplicar fórmulas de esquecimento (Decay)
    ultima_atualizacao = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

class MemoriaTrabalhoDB(Base):
    """
    MEMÓRIA DE TRABALHO (Short-Term / Working Memory).
    Armazena contexto ativo sobre conversas e tarefas em andamento.
    Possui um mecanismo de esquecimento para se manter relevante.
    """
    __tablename__ = "memoria_trabalho"
    id = Column(Integer, primary_key=True)
    chave_conversa = Column(String(255), unique=True, index=True) # Ex: 'whatsapp::minha fadona❤️'
    resumo_contexto = Column(JSON) # Lista de mensagens recentes ou um resumo da LLM
    relevancia = Column(Float, default=0.0, index=True)
    ultima_interacao = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)


# ==========================================
# NOVOS MODELOS DE MEMÓRIA EM CAMADAS (PROD)
# ==========================================

class FactDB(Base):
    __tablename__ = "facts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(50), default="default", index=True)
    text = Column(String, nullable=False)
    keywords = Column(JSON) # Lista JSON de palavras-chave
    embedding = Column(LargeBinary) # float32 packed 768d
    importance = Column(Float, default=0.5, index=True)
    last_used = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    source_msg_id = Column(String(36), nullable=True)
    source_file = Column(String(255), nullable=True, index=True)
    source_hash = Column(String(64), nullable=True, index=True)

    __table_args__ = (
        Index(
            "idx_facts_source",
            user_id,
            source_file,
            source_hash,
            unique=True,
            sqlite_where=sql_text("source_hash IS NOT NULL"),
            postgresql_where=sql_text("source_hash IS NOT NULL")
        ),
    )

class SummaryDB(Base):
    __tablename__ = "summaries"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(50), default="default", index=True)
    scope = Column(String(50), index=True) # "session:abc" | "global"
    text = Column(String, nullable=False)
    embedding = Column(LargeBinary, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)

class SemanticCacheDB(Base):
    __tablename__ = "semantic_cache"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(50), default="default", index=True)
    query_hash = Column(String(64), index=True)
    query_embedding = Column(LargeBinary, nullable=True)
    facts_version = Column(Integer, default=1)
    response = Column(String, nullable=False)
    hits = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)

class TaskQueueDB(Base):
    __tablename__ = "task_queue"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(50), default="default", index=True)
    task_type = Column(String(50), index=True) # "summarize" | "extract_facts" | "embed"
    payload = Column(JSON)
    status = Column(String(20), default="pending", index=True) # "pending" | "processing" | "done" | "dead"
    attempts = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)

class MetaDB(Base):
    __tablename__ = "meta"
    key = Column(String(100), primary_key=True)
    value = Column(String, nullable=False)

