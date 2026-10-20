"""Ponte local do Tauri: comandos fixos e argumentos tratados como dados."""
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def executar(comando, parametro, service=None):
    if service is None:
        from servicos.pc_control_service import pc_control_service
        service = pc_control_service
    macros = {"alt_tab", "win_d", "print_screen", "task_mgr", "alt_f4", "win_tab", "media_play_pause", "media_next", "media_prev"}
    apps = {"vscode", "android_studio", "spotify", "discord", "lol", "chrome", "steam", "clone_hero"}
    simples = {
        "bloquear_pc": "bloquear_pc", "dormir_pc": "dormir_pc", "suspender_pc": "dormir_pc",
        "hibernar_pc": "hibernar_pc", "desligar_pc": "desligar_pc", "reiniciar_pc": "reiniciar_pc",
        "mutar_mic": "mutar_mic", "inicializar_hardware": "inicializar",
    }
    if comando == "snapshot":
        return service.obter_estado_completo()
    if comando in {"executar_macro", "macro"} | macros:
        service.inicializar()
        service.executar_macro(parametro or comando)
    elif comando in {"abrir_app", "abrir_programa"} | apps:
        service.abrir_app(parametro or comando)
    elif comando in {"abrir_url", "open_url"}:
        parsed = urlparse(parametro)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("URL HTTP(S) inválida")
        service.abrir_url(parametro)
    elif comando in simples:
        if comando != "inicializar_hardware":
            service.inicializar()
        getattr(service, simples[comando])()
    elif comando == "spotify_play":
        service.inicializar()
        service.tocar_spotify(parametro)
    elif comando == "volume_sistema":
        valor = int(parametro)
        if not 0 <= valor <= 100:
            raise ValueError("Volume deve estar entre 0 e 100")
        service.inicializar()
        service.set_system_volume(valor)
    elif comando == "voicemeeter":
        chave, valor = parametro.split("=", 1)
        service.inicializar()
        service.set_vm_param(chave.strip(), valor.strip())
    elif comando == "volume_canal":
        canal, valor = parametro.split(",", 1) if "," in parametro else ("3", parametro)
        service.inicializar()
        service.set_gain(int(canal), float(valor))
    elif comando == "ciclar_saida":
        service.inicializar()
        service.ciclar_saida(int(parametro or 3))
    elif comando == "estudar_pc":
        return service.mapear_estrutura_usuario()
    elif comando in {"ligar_luz", "desligar_luz", "toggle_luz"}:
        from servicos.home_assistant_service import home_assistant_service
        if not asyncio.run(getattr(home_assistant_service, comando)(parametro or "light.yeelink_color5_027d_light")):
            raise RuntimeError("Home Assistant não confirmou o comando")
    else:
        raise ValueError(f"Comando não permitido: {comando}")
    return {"status": "ok"}

if __name__ == "__main__":
    try:
        comando, parametro = sys.argv[1:3]
        resultado = executar(comando, parametro)
        print(json.dumps(resultado, ensure_ascii=True, default=str))
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
