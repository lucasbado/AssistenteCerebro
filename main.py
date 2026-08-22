# main.py
import asyncio
import logging
import os
from fastapi import FastAPI, Request
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware

from core.kernel import kernel
from core.tipos import CategoriaEvento, TipoAcao, OrigemEvento
from core.evento import EventoCanonico

# Agentes
from agentes.agente_perfil import AgentePerfil
from agentes.agente_inferencia import AgenteInferencia
from agentes.agente_reflexo import AgenteReflexo
from agentes.agente_notificacoes import AgenteNotificacoes
from agentes.agente_roteador_cognitivo import AgenteRoteadorCognitivo
from agentes.agente_episodico import AgenteEpisodico
from agentes.agente_raciocinio import AgenteRaciocinio
from agentes.agente_memoria_trabalho import AgenteMemoriaTrabalho
from agentes.agente_musica import AgenteMusica
from agentes.agente_pesquisa import AgentePesquisa
from agentes.agente_foco import AgenteFoco
from agentes.agente_sumarizador_perfil import AgenteSumarizadorPerfil
from agentes.agente_aprendizagem import AgenteAprendizagem
from agentes.agente_clima import AgenteClima
from agentes.agente_rotina import AgenteRotina
from agentes.agente_bem_estar import AgenteBemEstar
from agentes.agente_pc_executor import AgentePcExecutor

# Serviços
from servicos.agente_contexto_sistema import AgenteContextoSistema
from servicos.pc_control_service import pc_control_service
from banco.database import inicializar_banco, async_engine

# Routers (API)
from api.eventos import router as eventos_router
from api.websocket import router as ws_router
from api.testes import router as testes_router
from api.feedback import router as feedback_router
from api.perfil import router as perfil_router
from api.status import router as status_router
from api.memoria import router as memoria_router
from api.router import router as home_router
from api.voice import router as voice_router
from servicos.router import router as timeline_router
from api.pc_control import router as pc_control_router
from api.contexto import router as contexto_router

# Configuração de Logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Main")

# ==========================================
# 1. GERENCIADOR DE CICLO DE VIDA (LIFESPAN)
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP ---
    logger.info("Initializing AssistantCell Ecosystem...")
    kernel.limpar_listeners() # Evita duplicatas durante recarregamento
    await inicializar_banco()
    
    # Instanciação Única de Agentes
    agentes_inst = {
        "perfil": AgentePerfil(),
        "inferencia": AgenteInferencia(),
        "reflexo": AgenteReflexo(),
        "notificacoes": AgenteNotificacoes(),
        "roteador": AgenteRoteadorCognitivo(),
        "episodico": AgenteEpisodico(),
        "raciocinio": AgenteRaciocinio(),
        "memoria_trabalho": AgenteMemoriaTrabalho(),
        "musica": AgenteMusica(),
        "pesquisa": AgentePesquisa(),
        "foco": AgenteFoco(),
        "sumarizador": AgenteSumarizadorPerfil(),
        "aprendizagem": AgenteAprendizagem(),
        "contexto_sistema": AgenteContextoSistema(),
        "rotina": AgenteRotina(),
        "bem_estar": AgenteBemEstar(),
        "pc_executor": AgentePcExecutor()
    }
    agentes_inst["clima"] = AgenteClima(memoria_trabalho=agentes_inst["memoria_trabalho"])
    app.state.agente_memoria_trabalho = agentes_inst["memoria_trabalho"]

    # Registro no Kernel - Inteligência Seletiva (Economia de Tokens)
    # AgentePerfil: Só anota no caderninho (DB), não pensa agora.
    kernel.registrar(lambda e: e.acao == TipoAcao.NORMAL, agentes_inst["perfil"].processar)
    
    # AgenteInferencia: Só guarda estatísticas, não chama IA.
    kernel.registrar(lambda e: e.acao == TipoAcao.NORMAL, agentes_inst["inferencia"].processar)
    
    # AgenteReflexo: Decide o que merece ser escalado para o Córtex (IA)
    kernel.registrar(lambda e: e.acao == TipoAcao.NORMAL and e.categoria in [CategoriaEvento.NOTIFICACAO, CategoriaEvento.SISTEMA_COMANDO_USUARIO], agentes_inst["reflexo"].processar)
    
    kernel.registrar(lambda e: e.acao == TipoAcao.NORMAL and e.categoria == CategoriaEvento.MEDIA, agentes_inst["musica"].processar)
    
    # Filtro: Foco e Bem-estar são apenas registros, não disparam IA de imediato.
    kernel.registrar(lambda e: e.acao == TipoAcao.NORMAL and e.categoria == CategoriaEvento.APP_FOREGROUND, agentes_inst["foco"].processar)
    
    # ... outros registros mantidos, mas apenas o Raciocínio (IA) é filtrado por Ação Complexa
    kernel.registrar(lambda e: e.acao == TipoAcao.EVENTO_COMPLEXO, agentes_inst["roteador"].processar)
    kernel.registrar(lambda e: e.acao == TipoAcao.INTENCAO_RACIOCINIO, agentes_inst["raciocinio"].processar)
    kernel.registrar(lambda e: e.acao == TipoAcao.INTENCAO_PESQUISA, agentes_inst["pesquisa"].processar)
    kernel.registrar(lambda e: e.acao == TipoAcao.RESULTADO_PESQUISA, agentes_inst["raciocinio"].sintetizar_com_pesquisa)
    
    # 🌟 CRUCIAL: Registro do Agente de Notificações para enviar respostas ao WebSocket
    kernel.registrar(lambda e: e.categoria == CategoriaEvento.INTENCAO_NOTIFICACAO, agentes_inst["notificacoes"].processar)

    kernel.registrar(lambda e: True, agentes_inst["episodico"].processar)
    kernel.registrar(lambda e: e.acao == TipoAcao.GERAR_RESUMO_PERFIL, agentes_inst["sumarizador"].processar)
    kernel.registrar(lambda e: e.acao == TipoAcao.FEEDBACK_USUARIO, agentes_inst["aprendizagem"].processar)
    kernel.registrar(lambda e: e.acao == TipoAcao.NORMAL and e.categoria == CategoriaEvento.NOTIFICACAO, agentes_inst["memoria_trabalho"].processar)
    kernel.registrar(lambda e: e.categoria == CategoriaEvento.SISTEMA_COMANDO_INTERNO and e.acao == TipoAcao.ATUALIZAR_CONTEXTO, agentes_inst["clima"].processar)
    # Registro do Executor do PC (Ouvindo o relógio/celular)
    kernel.registrar(lambda e: e.categoria == CategoriaEvento.SISTEMA_COMANDO_PC, agentes_inst["pc_executor"].processar)
    
    # 🌟 NOVO: WebSocket ouve comandos do PC para rotear para o PC Master (Nuvem -> Local)
    from api.websocket import central_alertas
    kernel.registrar(lambda e: e.categoria == CategoriaEvento.SISTEMA_COMANDO_PC, central_alertas.processar_evento_kernel)

    # Hardware
    pc_control_service.inicializar()

    async def loop_clima():
        while True:
            await kernel.publicar(EventoCanonico(categoria=CategoriaEvento.SISTEMA_COMANDO_INTERNO, acao=TipoAcao.ATUALIZAR_CONTEXTO, origem=OrigemEvento.SISTEMA, pacote="sistema.clima", payload={"alvo": "clima"}))
            await asyncio.sleep(1800)

    async def loop_rotina():
        while True:
            await asyncio.sleep(3600)
            await kernel.publicar(EventoCanonico(categoria=CategoriaEvento.SISTEMA_COMANDO_INTERNO, acao=TipoAcao.NORMAL, origem=OrigemEvento.SISTEMA, pacote="sistema.rotina", payload={"tipo": "REFLEXAO_ROTINA"}))

    tasks = [
        asyncio.create_task(loop_clima()),
        asyncio.create_task(loop_rotina()),
        asyncio.create_task(kernel.iniciar()),
        asyncio.create_task(central_alertas.iniciar_monitor())
    ]
    
    logger.info("🚀 AI Brain & PC Master Control online!")
    yield
    # --- SHUTDOWN ---
    for t in tasks: t.cancel()
    pc_control_service.encerrar()
    await async_engine.dispose()

# ==========================================
# 2. APP CONFIGURATION
# ==========================================
app = FastAPI(title="AssistenteCell Master", lifespan=lifespan)

# Middleware para Logar todas as requisições (ajuda a achar 404)
@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"REQ: {request.method} {request.url.path}")
    return await call_next(request)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Endpoints
@app.get("/")
@app.head("/")
async def root():
    return {"status": "AssistenteCell Ecosystem is Live", "version": "0.3.0-beta"}

# 🧠 SNAPSHOT DE CONTEXTO (Direto no Main para evitar 404)
@app.post("/api/v1/contexto/snapshot", tags=["Contexto"])
async def receber_snapshot_direto(request: Request):
    from servicos.consciencia import consciencia
    try:
        body = await request.json()
        consciencia.atualizar(body)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Erro no snapshot: {e}")
        return {"status": "error", "message": str(e)}

app.include_router(eventos_router, tags=["Gateway"])
app.include_router(ws_router, prefix="/api/v1", tags=["WebSocket"])
app.include_router(testes_router, tags=["Testes"])
app.include_router(feedback_router, tags=["Feedback"])
app.include_router(home_router, prefix="/api/v1/home", tags=["Home"])
app.include_router(perfil_router, prefix="/api/v1/perfil", tags=["Perfil"])
app.include_router(status_router, prefix="/api/v1/status", tags=["Status"])
app.include_router(memoria_router, prefix="/api/v1/memory", tags=["Memória"])
app.include_router(timeline_router, prefix="/api/v1/timeline", tags=["Timeline"])
app.include_router(pc_control_router, prefix="/api/v1/pc", tags=["PC Control"])
app.include_router(voice_router, prefix="/api/v1/voice", tags=["Voz"])
app.include_router(contexto_router, prefix="/api/v1/contexto", tags=["Contexto"])

if __name__ == "__main__":
    import uvicorn
    import os
    # Render fornece a variável PORT automaticamente
    port = int(os.environ.get("PORT", 8000))
    # Em produção (Render), host deve ser 0.0.0.0
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
