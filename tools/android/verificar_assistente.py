"""Verifica, sem alterar configuracoes, o vinculo Android da assistente Ollie.

Execute depois de instalar o APK ou encerrar testes instrumentados. Um processo
vivo ou a selecao da assistente padrao nao garantem que o sistema esteja ligado
ao servico. O resultado nao inclui transcricoes, preferencias ou tokens.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

COMPONENT = "com.example.assistentecell/.assistant.OllieAssistantService"


def verificar(adb, serial=None):
    prefix = [str(adb)] + (["-s", serial] if serial else [])

    def run(*args):
        result = subprocess.run(prefix + list(args), capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=15, check=True)
        return result.stdout.strip()

    if run("get-state") != "device":
        raise RuntimeError("Conecte e autorize o celular no ADB.")
    selected = run("shell", "settings", "get", "secure", "voice_interaction_service")
    state = run("shell", "dumpsys", "voiceinteraction")
    # Only the manager's main service, never the nested session-service binder.
    binding = re.search(r"^  mBound=(true|false) mService=([^\r\n]+)", state, re.M)
    bound = bool(binding and binding[1] == "true" and binding[2].strip() != "null")
    component_matches = f"mComponent={COMPONENT}" in state
    return {"ollie_selecionada": selected == COMPONENT, "servico_conectado": bound and component_matches,
            "formato_reconhecido": binding is not None}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    fallback = Path(os.environ.get("LOCALAPPDATA", "")) / "Android/Sdk/platform-tools/adb.exe"
    parser.add_argument("--adb", default=shutil.which("adb") or str(fallback))
    parser.add_argument("--serial")
    args = parser.parse_args()
    try:
        result = verificar(args.adb, args.serial)
        print(json.dumps(result, ensure_ascii=False))
        raise SystemExit(0 if result["ollie_selecionada"] and result["servico_conectado"] else 1)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(2, f"Nao foi possivel verificar o servico ({type(error).__name__}). Confira a conexao ADB.\n")
