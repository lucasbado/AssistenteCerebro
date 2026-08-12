import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

# Prioriza a URL da nuvem (Neon.tech/Postgres), senão usa SQLite local
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///D:/Programacao/AssistenteCell/agente_local.db")

# Ajuste específico para asyncpg (Neon/Postgres requer sslmode)
if DATABASE_URL.startswith("postgresql"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")
    # Neon exige sslmode=require
    if "sslmode" not in DATABASE_URL:
        DATABASE_URL += "?sslmode=require"

async_engine = create_async_engine(
    DATABASE_URL, 
    # check_same_thread apenas para SQLite
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
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