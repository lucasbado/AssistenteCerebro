# pc_client.py
import socket
import time
import json
import logging
import threading
import os
import subprocess

# Tente importar as bibliotecas específicas do Windows
try:
    import win32gui
    import win32process
    import psutil
    WINDOWS_LIBS_AVAILABLE = True
except ImportError:
    WINDOWS_LIBS_AVAILABLE = False

# --- Configurações ---
OLLIE_HOST = "127.0.0.1" 
OLLIE_PORT = 5005
LISTEN_PORT = 5006
# Aumentado para 3s para capturar padrões sem sobrecarregar
POLL_INTERVAL = 3.0

PROCESS_BLACKLIST = ["explorer.exe", "svchost.exe", "dwm.exe", "ctfmon.exe", "python.exe", "py.exe", "conhost.exe", "powershell.exe", "cmd.exe"]

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [PC_CLIENT] - %(message)s')

def get_active_window_process_name() -> str | None:
    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd: return None
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if not pid: return None
        process = psutil.Process(pid)
        return process.name()
    except: return None

def command_listener():
    """Escuta comandos vindos do servidor principal."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", LISTEN_PORT))
    
    while True:
        try:
            data, addr = sock.recvfrom(1024)
            msg = json.loads(data.decode('utf-8'))
            acao = msg.get("acao")
            alvo = msg.get("alvo")
            if acao == "ABRIR":
                if "\\" in alvo or ":" in alvo: os.startfile(alvo)
                else: subprocess.Popen(alvo, shell=True)
        except: pass

def main():
    if not WINDOWS_LIBS_AVAILABLE:
        print("❌ ERRO: Bibliotecas do Windows (pywin32, psutil) não encontradas!")
        print("Tente rodar: pip install pywin32 psutil")
        return
    
    print("🖥️  Ollie Client PC Ativo! Monitorando janelas...")
    threading.Thread(target=command_listener, daemon=True).start()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    last_process_name = None
    try:
        while True:
            process_name = get_active_window_process_name()
            if process_name and process_name != last_process_name and process_name not in PROCESS_BLACKLIST:
                data = {
                    "categoria": "PC_ACTIVITY",
                    "comando": "notificar_atividade",
                    "payload": {"processo": process_name}
                }
                sock.sendto(json.dumps(data).encode('utf-8'), (OLLIE_HOST, OLLIE_PORT))
                last_process_name = process_name
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt: pass
    finally: sock.close()

if __name__ == "__main__":
    main()
