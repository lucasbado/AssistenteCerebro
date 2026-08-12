import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

# Prioriza a URL da nuvem (Neon.tech/Postgres), senão usa SQLite local
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///D:/Programacao/AssistenteCell/agente_local.db")

# Configurações de conexão
connect_args = {}

# Ajuste específico para asyncpg (Postgres na nuvem)
if "postgresql" in DATABASE_URL:
    # O driver asyncpg não aceita 'sslmode' na URL, então removemos a query string
    if "?" in DATABASE_URL:
        DATABASE_URL = DATABASE_URL.split("?")[0]
    
    # Garante o uso do driver assíncrono asyncpg
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")
    
    # Ativa SSL via argumentos de conexão para o Neon.tech
    connect_args["ssl"] = True
else:
    # Configuração específica para SQLite local
    connect_args["check_same_thread"] = False

async_engine = create_async_engine(
    DATABASE_URL, 
    connect_args=connect_args,
    echo=False
)

# Fábrica de Sessões assíncronas
AsyncSessionLocal = sessionmaker(
    bind=async_engine, 
    class_=AsyncSession, 
    autocommit=False, 
    autoflush=False
)

async def obter_sessao_banco():
    """Dependency injection ou context manager para os agentes operarem no banco assincronamente."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
            
            
async def inicializar_banco():
    """
    Constrói a estrutura do banco de dados assíncrono caso ela não exista.
    Importação tardia (lazy import) de Base para evitar dependência circular.
    """
    from banco.models import Base
    async with async_engine.begin() as conn:
        # run_sync é usado para executar a rotina síncrona de DDL do SQLAlchemy
        # sem bloquear o Event Loop.
        await conn.run_sync(Base.metadata.create_all)
