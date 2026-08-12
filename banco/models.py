from sqlalchemy import Column, Integer, String, Float, JSON, DateTime, ForeignKey
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
