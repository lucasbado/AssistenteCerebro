"""
api/websocket.py - Gerenciador central de conexões WebSocket.
Garante o roteamento de mensagens entre PC Master, Mobile e outros clientes.
"""
import logging
import json
import asyncio
from datetime import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger("WebSocket")
router = APIRouter()

class GerenciadorNotificacoes:
    def __init__(self):
        self.conexoes_ativas: list[WebSocket] = []
        self._cache_saida: dict[str, float] = {} # Texto -> Timestamp
        self.pc_master: WebSocket = None 
        self.mobile_client: WebSocket = None

    async def conectar(self, websocket: WebSocket):
        """Aceita a conexão e solicita identificação."""
        try:
            await websocket.accept()
            # Limpa conexões inativas antes de adicionar a nova
            self.conexoes_ativas = [ws for ws in self.conexoes_ativas if ws.client_state.value == 1]
            self.conexoes_ativas.append(websocket)
            logger.info(f"✅ [WS] Conexão estabelecida. Ativos: {len(self.conexoes_ativas)}")
            
            # Solicita identificação imediata
            await websocket.send_json({"tipo_ws": "SOLICITAR_IDENTIFICACAO"})
        except Exception as e:
            logger.error(f"❌ [WS] Erro no handshake: {e}")
            raise # Repassa para o endpoint tratar

    def desconectar(self, websocket: WebSocket):
        """Remove o websocket das listas de ativos e referências."""
        if websocket in self.conexoes_ativas:
            self.conexoes_ativas.remove(websocket)
        
        if self.pc_master == websocket:
            self.pc_master = None
            logger.warning("🔌 [WS] PC Master desconectado.")
        if self.mobile_client == websocket:
            self.mobile_client = None
            logger.warning("🔌 [WS] Celular desconectado.")

    async def enviar_alerta(self, payload: dict):
        """Roteia eventos vindo do Kernel para os dispositivos certos."""
        payload_negocio = payload.get("payload", {})
        
        # 🛡️ DEDUPLICAÇÃO DE SAÍDA: Evita que a Ollie fale a mesma coisa duas vezes seguidas
        texto_saida = str(payload_negocio.get("texto", ""))
        if texto_saida:
            agora = asyncio.get_event_loop().time()
            if texto_saida in self._cache_saida:
                if agora - self._cache_saida[texto_saida] < 10.0: # 10 segundos de silêncio para repetidas
                    return
            self._cache_saida[texto_saida] = agora
            if len(self._cache_saida) > 50: self._cache_saida.clear()

        dados_para_envio = payload_negocio.copy()
        
        # Sincroniza metadados e timestamp
        if 'timestamp' in payload:
            ts = payload['timestamp']
            dados_para_envio['timestamp'] = ts.isoformat() if isinstance(ts, datetime) else str(ts)
        dados_para_envio['correlacao_id'] = str(payload.get('correlacao_id', ''))
        dados_para_envio.setdefault("origem_sistema", "OLLIE")

        tipo_ws = dados_para_envio.get("tipo_ws", "NOTIFICACAO")
        
        # Lógica de Roteamento
        # 1. Se for comando Mobile ou Chat, tenta o Mobile primeiro
        if tipo_ws in ["CHAT_RESPONSE", "COMANDO_SISTEMA", "THINKING"]:
            if self.mobile_client:
                if await self._enviar_direto(self.mobile_client, dados_para_envio):
                    return

        # 2. Se for comando de PC, vai pro Master
        if payload.get("categoria") == "SISTEMA_COMANDO_PC" or tipo_ws == "COMANDO_PC":
            if self.pc_master:
                if await self._enviar_direto(self.pc_master, dados_para_envio):
                    return

        # 3. Fallback: Broadcast geral
        await self._broadcast(dados_para_envio)

    async def _enviar_direto(self, ws: WebSocket, msg: dict) -> bool:
        """Tenta enviar uma mensagem para um socket específico."""
        try:
            if not ws or ws.client_state.value != 1: return False
            await ws.send_text(json.dumps(msg, default=str))
            return True
        except Exception as e:
            logger.error(f"❌ [WS] Erro no envio direto: {e}")
            return False

    async def _broadcast(self, msg: dict):
        """Envia mensagem para todos os conectados."""
        if not self.conexoes_ativas: return
        
        payload_str = json.dumps(msg, default=str)
        tasks = [asyncio.wait_for(ws.send_text(payload_str), timeout=3.0) 
                 for ws in self.conexoes_ativas if ws.client_state.value == 1]
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def processar_evento_kernel(self, evento):
        """Ponte entre o Kernel de eventos e o WebSocket."""
        await self.enviar_alerta(evento.model_dump())

    async def iniciar_monitor(self):
        """Loop para logar status das conexões no servidor."""
        while True:
            try:
                logger.info(f"📊 [WS Status] Ativos: {len(self.conexoes_ativas)} | Master: {'ON' if self.pc_master else 'OFF'} | Mobile: {'ON' if self.mobile_client else 'OFF'}")
            except: pass
            await asyncio.sleep(15)

central_alertas = GerenciadorNotificacoes()

@router.websocket("/ws/alertas")
async def websocket_endpoint(websocket: WebSocket):
    try:
        await central_alertas.conectar(websocket)
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                tipo = msg.get("tipo_ws")
                
                # 🛠️ HANDLER DE REGISTRO
                if tipo == "REGISTRO":
                    id_cliente = msg.get("id")
                    if id_cliente == "PC_MASTER":
                        central_alertas.pc_master = websocket
                        logger.info("🖥️ [WS] PC Master registrado.")
                        await websocket.send_json({"tipo_ws": "REGISTRO_OK", "id": "PC_MASTER"})
                    elif id_cliente == "MOBILE":
                        central_alertas.mobile_client = websocket
                        logger.info("📱 [WS] Celular registrado.")
                        await websocket.send_json({"tipo_ws": "REGISTRO_OK", "id": "MOBILE"})

                # 🛠️ HANDLER DE STATUS (CONSCIÊNCIA)
                elif tipo == "STATUS_PC":
                    from servicos.consciencia import consciencia
                    consciencia.atualizar({"pc_state": msg.get("stats", {})})
                
                # 🛠️ HANDLER DE MENSAGENS (CHAT)
                elif tipo == "CHAT_MESSAGE":
                    from core.kernel import kernel
                    from core.evento import EventoCanonico
                    from core.tipos import CategoriaEvento, TipoAcao, OrigemEvento
                    
                    metadados = {"correlacao_id": msg.get("correlacao_id")} if msg.get("correlacao_id") else {}
                    await kernel.publicar(EventoCanonico(
                        categoria=CategoriaEvento.SISTEMA_COMANDO_USUARIO,
                        acao=TipoAcao.NORMAL,
                        origem=OrigemEvento.USUARIO,
                        payload={"texto": msg.get("texto")},
                        metadados=metadados
                    ))

            except Exception as e:
                logger.error(f"⚠️ [WS] Erro ao processar mensagem: {e}")
                
    except WebSocketDisconnect:
        central_alertas.desconectar(websocket)
    except Exception as e:
        logger.error(f"❌ [WS] Erro fatal no endpoint: {e}")
        central_alertas.desconectar(websocket)
