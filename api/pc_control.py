from fastapi import APIRouter, Request
from servicos.pc_control_service import pc_control_service
from core.evento import EventoCanonico
from core.tipos import CategoriaEvento, TipoAcao, OrigemEvento
from core.kernel import kernel

router = APIRouter(tags=["PC Control"])

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
        payload=dados,
        pacote="pc.http.control"
    )
    
    await kernel.publicar(evento)
    return {"status": "ok", "id": evento.id}
