"""Ponte local do Tauri: comandos fixos e argumentos tratados como dados."""
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def executar(comando, parametro, service=None):
    if comando == 'audio_controle':
        from servicos.controle_audio import executar_audio
        return executar_audio(json.loads(parametro), service)
    if comando == "casa_acao":
        from servicos.home_assistant_service import home_assistant_service
        pedido = json.loads(parametro)
        return asyncio.run(home_assistant_service.controlar_luz_confirmada(pedido["acao"], pedido["entity_id"]))
    if comando == "ha_status":
        from servicos.home_assistant_service import home_assistant_service
        resultado = asyncio.run(home_assistant_service.verificar_conexao())
        if not resultado["conectado"]:
            raise RuntimeError("Home Assistant não está acessível/autenticado neste PC")
        return resultado
    if comando == "executar_cenario":
        from servicos.cenarios import ServicoCenarios
        return ServicoCenarios().executar(parametro)
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
        from servicos.sites_pc import resolver_site_pc
        site = resolver_site_pc(parametro or comando)
        if site:
            resultado = service.abrir_url(site)
        else:
            resultado = service.abrir_app(parametro or comando)
        if resultado is False:
            raise RuntimeError("Aplicativo não pôde ser aberto")
        return resultado if isinstance(resultado, dict) else {"status": "ok"}
    elif comando in {"pesquisa_google", "web_search", "pesquisar"}:
        from servicos.buscas_web import url_busca
        resultado = service.abrir_url(url_busca(parametro))
        return resultado if isinstance(resultado, dict) else {"status": "ok"}
    elif comando in {"abrir_url", "open_url"}:
        from servicos.sites_pc import resolver_site_pc
        parametro = resolver_site_pc(parametro) or parametro
        parsed = urlparse(parametro)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("URL HTTP(S) inválida")
        resultado = service.abrir_url(parametro)
        return resultado if isinstance(resultado, dict) else {"status": "ok"}
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
        if service.set_system_volume(valor) is False:
            raise RuntimeError("Controle de volume indisponível")
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
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        comando, parametro = sys.argv[1:3]
        resultado = executar(comando, parametro)
        print(json.dumps(resultado, ensure_ascii=True, default=str))
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
