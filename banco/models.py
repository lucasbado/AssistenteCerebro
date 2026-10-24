from sqlalchemy import Column, Integer, String, Float, JSON, DateTime, ForeignKey, LargeBinary, Index, text as sql_text
from sqlalchemy.orm import declarative_base
from datetime import datetime, timezone

Base = declarative_base()


class ControleIADB(Base):
    __tablename__ = 'controle_ia'
    chave = Column(String(100), primary_key=True)
    versao = Column(Integer, nullable=False, default=0)
    dados = Column(JSON, nullable=False, default=dict)


class UsoIADB(Base):
    __tablename__ = 'uso_ia'
    id = Column(String(36), primary_key=True)
    criado_em = Column(DateTime(timezone=True), nullable=False, index=True)
    provider = Column(String(30), nullable=False)
    modelo = Column(String(150), nullable=False)
    funcao = Column(String(40), nullable=False)
    solicitado = Column(Integer, nullable=False)
    entrada = Column(Integer, nullable=False)
    saida = Column(Integer, nullable=False)
    estimado = Column(Integer, nullable=False, default=1)
    estado = Column(String(30), nullable=False)


class CacheIADB(Base):
    __tablename__ = 'cache_ia'
    chave = Column(String(100), primary_key=True)
    assinatura = Column(String(64), nullable=False, default='')
    resultado = Column(JSON, nullable=True)
    atualizado_em = Column(DateTime(timezone=True), nullable=True)
    bloqueado_ate = Column(DateTime(timezone=True), nullable=False)


class MensagemRevisaoDB(Base):
    __tablename__ = 'mensagens_revisao'
    id = Column(String(36), primary_key=True)
    assinatura = Column(String(64), nullable=False, unique=True)
    conversa = Column(String(64), nullable=False, index=True)
    origem_conversa = Column(String(64), nullable=False, default='')
    pacote = Column(String(255), nullable=False)
    remetente = Column(String(150), nullable=False)
    texto = Column(String(4000), nullable=False)
    referencia_notificacao = Column(String(100), nullable=False, default='')
    sinais = Column(JSON, nullable=False)
    estado = Column(String(20), nullable=False, default='revisar', index=True)
    rascunho = Column(String(2000), nullable=False, default='')
    agenda_id = Column(String(36), nullable=True)
    tarefa_id = Column(String(36), nullable=True)
    recebido_em = Column(DateTime(timezone=True), nullable=False, index=True)
    versao = Column(Integer, nullable=False, default=1)
    analise = Column(JSON, nullable=True)


class ConversaRevisaoDB(Base):
    __tablename__ = 'conversas_revisao'
    conversa = Column(String(64), primary_key=True)
    mensagens = Column(JSON, nullable=False)
    atualizado_em = Column(DateTime(timezone=True), nullable=False, index=True)


class TarefaDB(Base):
    __tablename__ = 'tarefas_pessoais'
    id = Column(String(36), primary_key=True)
    chave_evento = Column(String(64), nullable=False, unique=True)
    titulo = Column(String(255), nullable=False)
    prazo = Column(DateTime(timezone=True), nullable=True, index=True)
    dia_inteiro = Column(Integer, nullable=False, default=0)
    estado = Column(String(20), nullable=False, index=True)
    origem = Column(String(255), nullable=False)
    contexto = Column(String(500), nullable=False, default='')
    versao = Column(Integer, nullable=False, default=1)
    criado_em = Column(DateTime(timezone=True), nullable=False)
    atualizado_em = Column(DateTime(timezone=True), nullable=False)
    avisado_em = Column(DateTime(timezone=True), nullable=True)


class TarefaContextoDB(Base):
    __tablename__ = 'tarefas_contextos'
    chave = Column(String(20), primary_key=True)
    dados = Column(JSON, nullable=False)
    expira = Column(DateTime(timezone=True), nullable=False)


class AgendaRascunhoDB(Base):
    __tablename__ = 'agenda_rascunhos'
    chave = Column(String(20), primary_key=True)
    texto = Column(String(3000), nullable=False)
    expira = Column(DateTime(timezone=True), nullable=False)


class AgendaItemDB(Base):
    __tablename__ = 'agenda_itens'
    id = Column(String(36), primary_key=True)
    assinatura = Column(String(64), nullable=False, unique=True)
    tipo = Column(String(20), nullable=False)
    titulo = Column(String(255), nullable=False)
    inicio = Column(DateTime(timezone=True), nullable=False, index=True)
    dia_inteiro = Column(Integer, nullable=False, default=0)
    antecedencia_minutos = Column(Integer, nullable=False, default=0)
    estado = Column(String(20), nullable=False, index=True)
    origem = Column(String(255), nullable=False)
    criado_em = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    avisado_em = Column(DateTime(timezone=True), nullable=True)


class CatalogoRotinasDB(Base):
    """Estado persistente das sugestões, aprovações e rejeições do usuário."""
    __tablename__ = "catalogo_rotinas"
    id = Column(Integer, primary_key=True)
    versao = Column(Integer, nullable=False, default=1)
    dados = Column(JSON, nullable=False)


class PoliticaIntervencaoDB(Base):
    __tablename__ = "politica_intervencao"
    id = Column(Integer, primary_key=True)
    dados = Column(JSON, nullable=False)

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
    locked_until = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)

class MetaDB(Base):
    __tablename__ = "meta"
    key = Column(String(100), primary_key=True)
    value = Column(String, nullable=False)

