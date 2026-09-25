import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

# Prioriza a URL da nuvem (Neon.tech/Postgres), senão usa SQLite local
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///D:/Programacao/AssistenteCell/agente_local.db")

def _criar_motor(url: str):
    connect_args = {}
    if "postgresql" in url:
        if "?" in url:
            url = url.split("?")[0]
        url = url.replace("postgresql://", "postgresql+asyncpg://")
        connect_args["ssl"] = True
    else:
        connect_args["check_same_thread"] = False
    
    return create_async_engine(
        url, 
        connect_args=connect_args,
        echo=False
    )

async_engine = _criar_motor(DATABASE_URL)

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
    Faz fallback automático para SQLite local se houver falha no Postgres (ex: quota excedida).
    """
    from banco.models import Base
    global async_engine
    try:
        async with async_engine.begin() as conn:
            # run_sync é usado para executar a rotina síncrona de DDL do SQLAlchemy
            # sem bloquear o Event Loop.
            await conn.run_sync(Base.metadata.create_all)
    except Exception as e:
        print(f"\n[AVISO CRÍTICO] Falha ao conectar ao banco remoto PostgreSQL ({e}).")
        print("[AVISO CRÍTICO] O projeto excedeu a cota ou está sem conexão. Realizando fallback automático para SQLite local...\n")
        
        fallback_url = "sqlite+aiosqlite:///D:/Programacao/AssistenteCell/agente_local.db"
        async_engine = _criar_motor(fallback_url)
        AsyncSessionLocal.configure(bind=async_engine)
        
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        print("[SUCESSO] Fallback para SQLite local (`agente_local.db`) ativado com sucesso!\n")
