from fastapi import APIRouter, Request, HTTPException
from servicos.pc_control_service import pc_control_service
from core.evento import EventoCanonico
from core.tipos import CategoriaEvento, TipoAcao, OrigemEvento, PrioridadeEvento
from core.kernel import kernel

router = APIRouter(tags=["PC Control"])


@router.get("/conexoes")
async def get_conexoes():
    from api.websocket import central_alertas
    return central_alertas.estado_conexoes()


@router.get("/comando/{identificador}")
async def get_confirmacao(identificador: str):
    from api.websocket import central_alertas
    resultado = central_alertas.confirmacoes.consultar(identificador)
    if resultado is None:
        raise HTTPException(status_code=404, detail="Comando ainda não roteado ou fora do histórico recente")
    return resultado

@router.get("/mobile-apps")
async def get_mobile_apps():
    count = len(pc_control_service.mobile_apps)
    print(f"📊 [API] Relógio/Celular pedindo lista de apps mobile. Enviando {count} apps.")
    return {
        "count": count,
        "apps": pc_control_service.mobile_apps
    }

@router.get("/pc-apps")
async def get_pc_apps():
    """
    Retorna os atalhos de aplicativos configurados para abrir no PC.
    """
    apps = [
        {"n": "VS Code", "k": "vscode", "c": "#007ACC"},
        {"n": "Spotify", "k": "spotify", "c": "#1DB954"},
        {"n": "LoL", "k": "lol", "c": "#C1AA74"},
        {"n": "Android Studio", "k": "android_studio", "c": "#3DDC84"},
        {"n": "Pasta Jogos", "k": "D:\\games", "c": "#FFA000"},
        {"n": "Discord", "k": "discord", "c": "#5865F2"}
    ]
    return {"apps": apps}

@router.post("/comando")
async def receber_comando(request: Request):
    """
    Recebe comandos via HTTP (mais robusto que UDP para redes externas/VPN).
    """
    dados = await request.json()
    comando = dados.get("comando")
    
    if not comando:
        return {"status": "erro", "motivo": "Comando ausente"}

    print(f"📡 [API] Recebido comando via HTTP: {comando}")

    # Cria um evento canônico para ser processado pelo AgentePcExecutor
    evento = EventoCanonico(
        categoria=CategoriaEvento.SISTEMA_COMANDO_PC,
        acao=TipoAcao.NORMAL,
        origem=OrigemEvento.USUARIO,
        prioridade=PrioridadeEvento.ALTA,
        payload=dados,
        pacote="pc.http.control"
    )
    
    await kernel.publicar(evento)
    return {"status": "ok", "id": evento.id}

@router.get("/intervention/policy")
async def get_intervention_policy():
    from servicos.intervention_governor import intervention_governor
    return intervention_governor.policy

@router.post("/intervention/policy")
async def update_intervention_policy(request: Request):
    from servicos.intervention_governor import intervention_governor
    dados = await request.json()
    updated = intervention_governor.atualizar_politica(dados)
    return {"status": "ok", "policy": updated}
