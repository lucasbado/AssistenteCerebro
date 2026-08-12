import asyncio
import socket
import json
import logging
from core.evento import EventoCanonico
from core.tipos import CategoriaEvento, TipoAcao, OrigemEvento, PrioridadeEvento
from core.kernel import kernel
from servicos.pc_control_service import pc_control_service

logger = logging.getLogger("UDPListener")

class UdpListenerService:
    def __init__(self, host="0.0.0.0", port=5005):
        self.host = host
        self.port = port
        self._running = False

    async def iniciar(self):
        self._running = True
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        server_socket.bind((self.host, self.port))
        server_socket.setblocking(False)
        logger.info(f"🟢 [UDP] Escutando na porta {self.port}...")
        loop = asyncio.get_event_loop()
        
        while self._running:
            try:
                data, addr = await loop.sock_recvfrom(server_socket, 4096) # Buffer maior para lista de apps
                pacote = json.loads(data.decode('utf-8'))
                comando = pacote.get("comando")
                
                # --- SINCRONIZAÇÃO GERAL ---
                if comando == "pedir_estado":
                    estado = pc_control_service.obter_estado_completo()
                    resp_json = json.dumps(estado).encode('utf-8')
                    logger.info(f"📤 [UDP] Enviando estado ({len(resp_json)} bytes) para {addr[0]}")
                    server_socket.sendto(resp_json, addr)
                    continue

                # --- PEDIDO DE LISTA DE APPS DO CELULAR ---
                elif comando == "pedir_apps_mobile":
                    resposta = {"mobile_apps": pc_control_service.mobile_apps}
                    resp_json = json.dumps(resposta).encode('utf-8')
                    logger.info(f"📤 [UDP] Enviando {len(pc_control_service.mobile_apps)} apps ({len(resp_json)} bytes) para {addr[0]}")
                    server_socket.sendto(resp_json, addr)
                    continue

                # --- TRATAMENTO DE EVENTOS (Kernel) ---
                categoria_raw = pacote.get("categoria", "SISTEMA_COMANDO_PC")
                
                # 🌟 LOG DE ATIVIDADE: Visibilidade imediata no terminal do PC
                if categoria_raw == "PC_ACTIVITY":
                    inner_payload = pacote.get("payload", {})
                    processo = inner_payload.get("processo", "Desconhecido")
                    logger.info(f"🖥️  [UDP] Atividade do PC detectada: {processo}")

                try:
                    # Tenta converter para o Enum
                    categoria = CategoriaEvento(categoria_raw.upper())
                except:
                    categoria = CategoriaEvento.SISTEMA_COMANDO_PC

                evento = EventoCanonico(
                    categoria=categoria,
                    acao=TipoAcao.NORMAL,
                    origem=OrigemEvento.USUARIO if addr[0] != "127.0.0.1" else OrigemEvento.SISTEMA,
                    prioridade=PrioridadeEvento.NORMAL,
                    pacote="pc.remote.control",
                    payload=pacote,
                    metadados={"sender_ip": addr[0]}
                )
                
                await kernel.publicar(evento)
                
            except Exception as e:
                if self._running:
                    logger.error(f"[UDP] Erro: {e}")
                await asyncio.sleep(0.01)

    def parar(self):
        self._running = False

udp_listener = UdpListenerService()
