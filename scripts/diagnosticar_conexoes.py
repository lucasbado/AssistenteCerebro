"""Diagnóstico sem tokens/mensagens pessoais no relatório. Não registra outro PC/mobile."""
import argparse
import asyncio
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx
import websockets
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


async def diagnosticar(testar_pc=False, wake=False):
    cfg = dotenv_values(ROOT / ".env")
    ws_url = cfg.get("OLLIE_CLOUD_URL") or "wss://assistentecellfront.onrender.com/api/v1/ws/alertas"
    if cfg.get("ENVIRONMENT") == "development":
        ws_url = cfg.get("OLLIE_LOCAL_URL") or "ws://localhost:8000/api/v1/ws/alertas"
    parsed = urlsplit(ws_url)
    api = urlunsplit(("https" if parsed.scheme == "wss" else "http", parsed.netloc, "", "", ""))
    token = cfg.get("OLLIE_API_TOKEN") or ""
    relatorio = {"timestamp_utc": datetime.now(timezone.utc).isoformat(),
                 "backend_host": parsed.hostname, "testes_pc": []}
    async with httpx.AsyncClient(timeout=12, follow_redirects=False) as client:
        for nome, path, autenticado in [("servidor", "/", False),
                ("autenticacao", "/api/v1/status/", True),
                ("bloqueio_sem_token", "/api/v1/pc/pc-apps", False),
                ("conexoes", "/api/v1/pc/conexoes", True)]:
            try:
                r = await client.get(api + path, headers={"Authorization": "Bearer " + token} if autenticado else {})
                relatorio[nome] = {"http": r.status_code}
                if nome == "conexoes" and r.status_code == 200:
                    dados = r.json()
                    relatorio[nome].update({k: dados[k] for k in ("pc", "mobile") if k in dados})
            except httpx.HTTPError as e:
                relatorio[nome] = {"erro": type(e).__name__}
        ha_url = (cfg.get("HA_URL") or "").rstrip("/")
        if ha_url and cfg.get("HA_TOKEN"):
            try:
                r = await client.get(ha_url + "/api/", headers={"Authorization": "Bearer " + cfg["HA_TOKEN"]})
                relatorio["home_assistant_local"] = {"http": r.status_code}
            except httpx.HTTPError as e:
                relatorio["home_assistant_local"] = {"erro": type(e).__name__}
        else:
            relatorio["home_assistant_local"] = {"configurado": False}
    try:
        async with websockets.connect(ws_url, subprotocols=["ollie", "bearer." + token], open_timeout=15) as ws:
            relatorio["websocket"] = "conectado_como_observador"
            comandos = [("snapshot", ""), ("executar_cenario", "diagnostico"), ("ha_status", "")] if testar_pc else []
            if wake:
                comandos.append(("wake_ollie", ""))
            if not comandos:
                comandos = [(None, None)]
            for comando, parametro in comandos:
                identificador = "diagnostico-" + str(uuid.uuid4())
                resultado = {"comando": comando, "status": "sem_confirmacao"}
                if comando:
                    await ws.send(json.dumps({"tipo_ws": "COMANDO_PC", "comando": comando,
                                              "parametro": parametro, "id_comando": identificador}))
                prazo = asyncio.get_running_loop().time() + (35 if comando else 10)
                while asyncio.get_running_loop().time() < prazo:
                    try:
                        msg = json.loads(await asyncio.wait_for(ws.recv(), prazo - asyncio.get_running_loop().time()))
                    except asyncio.TimeoutError:
                        break
                    if msg.get("tipo_ws") == "STATUS_PC":
                        relatorio["telemetria_pc"] = True
                        ultimo = msg.get("stats", {}).get("ultimo_comando") or {}
                        if comando and ultimo.get("id") == identificador:
                            resultado["status"] = ultimo.get("status")
                            break
                    if msg.get("tipo_ws") == "COMANDO_ACEITO" and msg.get("id") == identificador and msg.get("status") == "pc_offline":
                        resultado["status"] = "pc_offline"
                        break
                if comando:
                    relatorio["testes_pc"].append(resultado)
                    print(json.dumps(resultado, ensure_ascii=False), flush=True)
    except Exception as e:
        relatorio["websocket"] = {"erro": type(e).__name__}
    return relatorio


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--testar-pc", action="store_true", help="Executa snapshot, cenário de diagnóstico e consulta ao HA pelo PC")
    parser.add_argument("--wake", action="store_true", help="Traz a janela da Ollie para frente e foca o chat")
    args = parser.parse_args()
    dados = asyncio.run(diagnosticar(args.testar_pc, args.wake))
    destino = ROOT / ".artifacts/diagnostico-conexoes.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(dados, ensure_ascii=False, indent=2))
    falhas = any(x.get("status") != "concluido" for x in dados["testes_pc"])
    sys.exit(1 if falhas else 0)
