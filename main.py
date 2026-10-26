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
from agentes.agente_pc_profiler import AgentePcProfiler
from agentes.agente_botoes import AgenteBotoes
from agentes.agente_casa import AgenteCasa
from agentes.agente_celular import AgenteCelular
from agentes.agente_plano import AgentePlano
from agentes.agente_agenda import AgenteAgenda
from agentes.agente_tarefas import AgenteTarefas
from agentes.agente_mensagens import AgenteMensagens

# Serviços
from servicos.agente_contexto_sistema import AgenteContextoSistema
from servicos.pc_control_service import pc_control_service
from servicos.pc_listener_service import pc_listener_service
from banco.database import inicializar_banco, async_engine
from servicos.disponibilidade import modo_forcado, quota_excedida, estado_sistema

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
from api.router_capabilities import router as capabilities_router
from servicos.router import router as timeline_router
from api.pc_control import router as pc_control_router
from api.router_ha import router as ha_router
from api.contexto import router as contexto_router
from api.agenda import router as agenda_router
from api.tarefas import router as tarefas_router
from api.calendario import router as calendario_router
from api.mensagens import router as mensagens_router

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
    app.state.modo_limitado = False
    motivo_limitado = 'configurado' if modo_forcado() else None
    if not motivo_limitado:
        try:
            await inicializar_banco()
        except Exception as erro:
            if not quota_excedida(erro):
                raise
            motivo_limitado = 'quota_banco_excedida'
            logger.error('Cota do banco esgotada. Iniciando controles e interpretação sem persistência; memória e rotinas aprendidas pausadas.')
    if motivo_limitado:
        from servicos.execucao_limitada import executar_modo_limitado
        async with executar_modo_limitado(app, motivo_limitado):
            yield
        return
    
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
        "pc_executor": AgentePcExecutor(),
        "pc_profiler": AgentePcProfiler()
    }
    agentes_inst["clima"] = AgenteClima(memoria_trabalho=agentes_inst["memoria_trabalho"])
    agentes_inst["botoes"] = AgenteBotoes()
    agentes_inst["casa"] = AgenteCasa()
    agentes_inst["celular"] = AgenteCelular()
    kernel.registrar(lambda e: e.categoria == CategoriaEvento.CELULAR_ACAO_SOLICITADA,
                     agentes_inst["celular"].processar)
    agentes_inst["plano"] = AgentePlano()
    agentes_inst["agenda"] = AgenteAgenda()
    agentes_inst["tarefas"] = AgenteTarefas()
    agentes_inst['mensagens'] = AgenteMensagens()
    kernel.registrar(lambda e: e.categoria == CategoriaEvento.MENSAGEM_SOLICITADA
        or (e.categoria == CategoriaEvento.NOTIFICACAO and e.acao == TipoAcao.NORMAL)
        or (e.categoria == CategoriaEvento.SISTEMA_COMANDO_INTERNO and e.payload.get('tipo') == 'TICK_MENSAGENS'),
        agentes_inst['mensagens'].processar)
    kernel.registrar(lambda e: e.categoria in {CategoriaEvento.TAREFA_SOLICITADA, CategoriaEvento.NOTIFICACAO}
        or (e.categoria == CategoriaEvento.SISTEMA_COMANDO_INTERNO and e.payload.get('tipo') == 'TICK_TAREFAS'),
        agentes_inst['tarefas'].processar)
    kernel.registrar(lambda e: e.categoria in {CategoriaEvento.AGENDA_SOLICITADA, CategoriaEvento.NOTIFICACAO}
        or (e.categoria == CategoriaEvento.SISTEMA_COMANDO_INTERNO and e.payload.get('tipo') == 'TICK_AGENDA'),
        agentes_inst["agenda"].processar)
    kernel.registrar(lambda e: e.categoria == CategoriaEvento.PLANO_SOLICITADO,
                     agentes_inst["plano"].processar)
    kernel.registrar(lambda e: e.categoria == CategoriaEvento.CASA_ACAO_SOLICITADA,
                     agentes_inst["casa"].processar)
    kernel.registrar(lambda e: e.categoria == CategoriaEvento.BOTAO_ACIONADO,
                     agentes_inst["botoes"].processar)
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
    
    # 🌟 ATIVAÇÃO: Agente de Bem-Estar (Monitora pausas em lazer)
    kernel.registrar(lambda e: e.categoria == CategoriaEvento.APP_FOREGROUND, agentes_inst["bem_estar"].processar)

    # 🌟 ATIVAÇÃO: Agente de Rotinas (Automações do routines.json)
    kernel.registrar(lambda e: e.categoria in [CategoriaEvento.APP_FOREGROUND, CategoriaEvento.SISTEMA_COMANDO_INTERNO, CategoriaEvento.PC_ACTIVITY], agentes_inst["rotina"].processar)

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
    
    # 🌟 NOVO: Profiler de PC
    kernel.registrar(lambda e: e.categoria == CategoriaEvento.SISTEMA_COMANDO_PC, agentes_inst["pc_profiler"].processar)
    
    # O adaptador WebSocket atende os executores de PC e casa, fora do kernel.
    from api.websocket import central_alertas

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

    async def loop_sumarizador():
        """Gera um resumo do perfil a cada 24 horas."""
        while True:
            await asyncio.sleep(86400)
            await kernel.publicar(EventoCanonico(
                categoria=CategoriaEvento.SISTEMA_COMANDO_INTERNO, 
                acao=TipoAcao.GERAR_RESUMO_PERFIL, 
                origem=OrigemEvento.SISTEMA, 
                pacote="sistema.sumarizador"
            ))

    async def loop_relogio_rotinas():
        """Horários têm um evento próprio; notificações não disparam o relógio."""
        while True:
            await kernel.publicar(EventoCanonico(
                categoria=CategoriaEvento.SISTEMA_COMANDO_INTERNO,
                origem=OrigemEvento.SISTEMA, pacote="sistema.relogio",
                payload={"tipo": "TICK_ROTINA"}))
            await asyncio.sleep(60)

    async def loop_agenda():
        while True:
            await kernel.publicar(EventoCanonico(categoria=CategoriaEvento.SISTEMA_COMANDO_INTERNO,
                origem=OrigemEvento.SISTEMA, pacote='sistema.agenda', payload={'tipo': 'TICK_AGENDA'}))
            await kernel.publicar(EventoCanonico(categoria=CategoriaEvento.SISTEMA_COMANDO_INTERNO,
                origem=OrigemEvento.SISTEMA, pacote='sistema.tarefas', payload={'tipo': 'TICK_TAREFAS'}))
            await asyncio.sleep(30)

    async def loop_limpeza_mensagens():
        while True:
            await kernel.publicar(EventoCanonico(categoria=CategoriaEvento.SISTEMA_COMANDO_INTERNO,
                origem=OrigemEvento.SISTEMA, pacote='sistema.mensagens', payload={'tipo': 'TICK_MENSAGENS'}))
            await asyncio.sleep(3600)

    tasks = [
        asyncio.create_task(loop_clima()),
        asyncio.create_task(loop_rotina()),
        asyncio.create_task(loop_sumarizador()),
        asyncio.create_task(loop_relogio_rotinas()),
        asyncio.create_task(loop_agenda()),
        asyncio.create_task(loop_limpeza_mensagens()),
        asyncio.create_task(kernel.iniciar()),
        asyncio.create_task(central_alertas.iniciar_monitor())
    ]
    from servicos.queue_worker import queue_worker
    tasks.append(asyncio.create_task(queue_worker.iniciar()))
    
    # 🖥️ LOCAL ONLY: Inicia listener UDP apenas se não estiver no Render / Cloud Linux
    is_render = os.getenv("RENDER", "False").lower() in ["true", "1", "yes"] or os.name != "nt"
    
    if not is_render:
        tasks.append(asyncio.create_task(pc_listener_service.iniciar()))

    logger.info("🚀 AI Brain & PC Master Control online!")
    try:
        yield
    finally:
        for t in tasks: t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if not is_render:
            pc_listener_service.parar()
        pc_control_service.encerrar()
        await async_engine.dispose()

# ==========================================
# 2. APP CONFIGURATION
# ==========================================
app = FastAPI(title="AssistenteCell Master", lifespan=lifespan)
from api.auth import AuthMiddleware
from api.disponibilidade import DisponibilidadeMiddleware
app.add_middleware(DisponibilidadeMiddleware)
app.add_middleware(AuthMiddleware)

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
async def root(request: Request):
    return {"status": "AssistenteCell Ecosystem is Live", "version": "0.3.0-beta", **estado_sistema(request.app)}

@app.get('/health')
async def health(request: Request):
    # HTTP 200 informa que o serviço de controles está vivo; o corpo distingue o modo.
    return {'status': 'online', **estado_sistema(request.app)}

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
app.include_router(capabilities_router, prefix="/api/v1/capabilities", tags=["Capabilities"])
app.include_router(ha_router, prefix="/api/v1/ha", tags=["Home Assistant"])
app.include_router(voice_router, prefix="/api/v1/voice", tags=["Voz"])
app.include_router(contexto_router, prefix="/api/v1/contexto", tags=["Contexto"])
app.include_router(agenda_router, prefix='/api/v1/agenda')
app.include_router(tarefas_router, prefix='/api/v1/tarefas')
app.include_router(calendario_router, prefix='/api/v1/calendario')
app.include_router(mensagens_router, prefix='/api/v1/mensagens')
from api.ia import router as ia_router
app.include_router(ia_router, prefix='/api/v1/ia', tags=['IA'])

if __name__ == "__main__":
    import uvicorn
    import os
    # Render fornece a variável PORT automaticamente
    port = int(os.environ.get("PORT", 8000))
    # Em produção (Render), host deve ser 0.0.0.0
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
