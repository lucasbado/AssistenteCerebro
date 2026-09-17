import socket
import json
import asyncio
import logging
from core.evento import EventoCanonico
from core.tipos import CategoriaEvento, TipoAcao, OrigemEvento
from core.kernel import kernel

logger = logging.getLogger("PcListenerService")

class PcActivityProtocol(asyncio.DatagramProtocol):
    def datagram_received(self, data: bytes, addr: tuple):
        try:
            msg = json.loads(data.decode('utf-8'))
            comando = msg.get('comando')
            
            # 🔇 SILÊNCIO: Loga apenas comandos reais de atividade, não polling de status
            if comando == "notificar_atividade":
                logger.info(f"📥 [UDP] Atividade recebida de {addr}")
                
                # Converte a mensagem bruta do ClientPc em um EventoCanonico
                asyncio.create_task(kernel.publicar(EventoCanonico(
                    categoria=CategoriaEvento.PC_ACTIVITY,
                    acao=TipoAcao.NORMAL,
                    origem=OrigemEvento.PC,
                    pacote="pc.client.monitor",
                    payload=msg.get("payload", {})
                )))
            else:
                logger.debug(f"📥 [UDP] Comando silencioso de {addr}: {comando}")
        except Exception as e:
            logger.error(f"❌ [UDP] Erro ao processar datagrama: {e}")

class PcListenerService:
    def __init__(self, host="0.0.0.0", port=5005):
        self.host = host
        self.port = port
        self.transport = None
        self.protocol = None

    async def iniciar(self):
        logger.info(f"🚀 Iniciando Listener UDP na porta {self.port}...")
        loop = asyncio.get_running_loop()
        self.transport, self.protocol = await loop.create_datagram_endpoint(
            lambda: PcActivityProtocol(),
            local_addr=(self.host, self.port)
        )
        logger.info(f"✅ Listener UDP Ativo em {self.host}:{self.port}")

    def parar(self):
        if self.transport:
            self.transport.close()
            logger.info("🛑 Listener UDP parado.")

pc_listener_service = PcListenerService()
