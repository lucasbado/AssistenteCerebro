from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.perfil import router as perfil_router
from api.status import router as status_router
from api.memoria import router as memoria_router
# 🌟 CORREÇÃO: O router da timeline foi movido para a camada de API, seguindo a arquitetura.
from api.router_timeline import router as timeline_router
from api.router import router as home_router
from api.router_capabilities import router as capabilities_router
from api.contexto import router as contexto_router

def criar_app_api():
    """
    Cria e configura a instância principal da aplicação FastAPI para a API externa.
    """
    app = FastAPI(
        title="AssistenteCell - Camada de Consulta Cognitiva",
        description="API para servir conhecimento processado ao cliente Android.",
        version="1.0.0"
    )

    # Adiciona o middleware de CORS para permitir requisições do frontend
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Em produção, restrinja para o domínio do seu frontend
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # O endpoint /home é o principal e mais importante
    app.include_router(home_router, prefix="/api/v1/home", tags=["Home"])

    # Os demais endpoints servem as telas específicas
    app.include_router(perfil_router, prefix="/api/v1/perfil", tags=["Perfil"])
    app.include_router(status_router, prefix="/api/v1/status", tags=["Status"])
    app.include_router(memoria_router, prefix="/api/v1/memory", tags=["Memória"])
    app.include_router(timeline_router, prefix="/api/v1/timeline", tags=["Timeline"])
    # 🌟 NOVO: Registra os endpoints GET e PUT para /capabilities
    app.include_router(capabilities_router, prefix="/api/v1/capabilities", tags=["Capabilities"])
    # 🧠 NOVO: Recebe o snapshot de consciência do ambiente
    app.include_router(contexto_router, prefix="/api/v1/contexto", tags=["Contexto"])

    return app

app_api = criar_app_api()