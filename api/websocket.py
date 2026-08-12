"""
api/websocket.py
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
        self._buffer_mensagens: list[dict] = []
        self.pc_master: WebSocket = None # Referência para o PC ligado
        self.mobile_client: WebSocket = None

    async def conectar(self, websocket: WebSocket):
        await websocket.accept()
        self.conexoes_ativas.append(websocket)
        logger.info(f"✅ [WS] Nova conexão! Total ativos: {len(self.conexoes_ativas)}")
        
        # Pede identificação ao conectar
        try:
            await websocket.send_json({
                "tipo_ws": "SOLICITAR_IDENTIFICACAO"
            })
        except: pass

    def desconectar(self, websocket: WebSocket):
        if websocket in self.conexoes_ativas:
            self.conexoes_ativas.remove(websocket)
        if self.pc_master == websocket:
            self.pc_master = None
            logger.warning("🔌 [WS] PC Master desconectado.")
        if self.mobile_client == websocket:
            self.mobile_client = None
            logger.warning("🔌 [WS] Celular desconectado.")

    async def enviar_alerta(self, payload: dict):
        payload_negocio = payload.get("payload", {})
        dados_para_envio = payload_negocio.copy()
        
        tipo_ws_original = payload.get("tipo_ws")
        
        # Identifica se deve ir para o CHAT, preservando se já existir um tipo específico
        if 'tipo_ws' not in dados_para_envio:
            if 'tipo_ws' in payload:
                dados_para_envio['tipo_ws'] = payload['tipo_ws']
            else:
                origem = payload.get("origem")
                categoria = payload.get("categoria")
                metadados = payload.get("metadados", {})
                if metadados.get("tipo_destino") == "CHAT" or origem == "IA" or categoria == "INTENCAO_NOTIFICACAO":
                    dados_para_envio['tipo_ws'] = 'CHAT_RESPONSE'
                else:
                    dados_para_envio['tipo_ws'] = 'NOTIFICACAO'

        tipo_ws = dados_para_envio.get("tipo_ws")
        logger.info(f"📣 [WS] Processando alerta: tipo={tipo_ws}, id={payload.get('correlacao_id')}")

        if 'mensagem' in dados_para_envio:
            dados_para_envio['texto'] = dados_para_envio.pop('mensagem')
        dados_para_envio.setdefault("titulo", "Assistente")
        dados_para_envio["origem_sistema"] = "OLLIE"
        
        if 'timestamp' in payload:
            ts = payload['timestamp']
            dados_para_envio['timestamp'] = ts.isoformat() if isinstance(ts, datetime) else str(ts)
            
        dados_para_envio['correlacao_id'] = str(payload.get('correlacao_id', ''))

        # ROTEAMENTO INTELIGENTE:
        tipo_ws = dados_para_envio.get("tipo_ws")

        # 1. Se for comando de hardware (PC_COMMAND), manda prioritariamente para o PC Master
        if tipo_ws == "PC_COMMAND" or "comando" in dados_para_envio:
            if self.pc_master:
                logger.info(f"⚡ [WS] Roteando comando '{dados_para_envio.get('comando')}' para PC Master.")
                await self._enviar_direto(self.pc_master, dados_para_envio)
                return
            else:
                logger.warning(f"⚠️ [WS] Comando recebido mas PC Master está offline.")
        
        # 2. Se for resposta de chat ou notificação, tenta mandar prioritariamente para o Celular
        if tipo_ws in ["CHAT_RESPONSE", "NOTIFICACAO", "THINKING"]:
            if self.mobile_client:
                logger.info(f"📱 [WS] Roteando {tipo_ws} para Mobile Client (Handshake OK).")
                await self._enviar_direto(self.mobile_client, dados_para_envio)
                return
            else:
                logger.warning(f"⚠️ [WS] Tentativa de enviar {tipo_ws} mas Mobile Client não está registrado!")
                logger.info("📡 [WS] Tentando broadcast como fallback...")

        # 3. Fallback: Envia para todos (Broadcast)
        await self._broadcast(dados_para_envio)

    async def enviar_evento_log(self, evento_dict: dict):
        ts = evento_dict.get("timestamp")
        ts_str = ts.isoformat() if isinstance(ts, datetime) else str(ts)
        log_dto = {
            "tipo_ws": "EVENTO_LOG",
            "id": str(evento_dict.get("id")),
            "categoria": str(evento_dict.get("categoria")),
            "resumo": str(evento_dict.get("resumo", "Evento")),
            "timestamp": ts_str,
            "origem": str(evento_dict.get("origem")),
            "icone": "circle"
        }
        await self._broadcast(log_dto)

    async def _enviar_direto(self, ws: WebSocket, msg: dict):
        try:
            await ws.send_text(json.dumps(msg, default=str))
        except Exception as e:
            logger.error(f"❌ [WS] Falha no envio direto: {e}")
            self.desconectar(ws)

    async def _broadcast(self, msg: dict):
        if not self.conexoes_ativas:
            logger.debug("⚠️ [WS] Nenhum cliente conectado para broadcast.")
            if msg.get("tipo_ws") in ["CHAT_RESPONSE", "NOTIFICACAO"]:
                self._buffer_mensagens.append(msg)
                if len(self._buffer_mensagens) > 20: self._buffer_mensagens.pop(0)
            return

        logger.info(f"📡 [WS] Fazendo broadcast para {len(self.conexoes_ativas)} clientes.")
        payload_str = json.dumps(msg, default=str)
        tasks = []
        for ws in self.conexoes_ativas:
            tasks.append(asyncio.wait_for(ws.send_text(payload_str), timeout=3.0))
        
        try:
            resultados = await asyncio.gather(*tasks, return_exceptions=True)
            for i, res in enumerate(resultados):
                if isinstance(res, Exception):
                    logger.error(f"❌ [WS] Erro no broadcast para cliente {i}: {res}")
        except Exception as e:
            logger.error(f"❌ [WS] Erro geral no broadcast: {e}")

    async def processar_evento_kernel(self, evento):
        """Método para o Kernel chamar diretamente."""
        await self.enviar_alerta(evento.model_dump())

    async def iniciar_monitor(self):
        """Loop para logar status das conexões no servidor."""
        while True:
            logger.info(f"📊 [WS Status] Ativos: {len(self.conexoes_ativas)} | Master: {'ON' if self.pc_master else 'OFF'} | Mobile: {'ON' if self.mobile_client else 'OFF'}")
            await asyncio.sleep(15)

central_alertas = GerenciadorNotificacoes()

@router.websocket("/ws/alertas")
async def websocket_endpoint(websocket: WebSocket):
    await central_alertas.conectar(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            logger.info(f"📥 [WS] Mensagem recebida: {data}")
            try:
                msg = json.loads(data)
                tipo = msg.get("tipo_ws")
                
                # Roteamento de comandos entre dispositivos (Relé)
                if tipo == "COMANDO_PC" or msg.get("destino") == "PC_MASTER":
                    if central_alertas.pc_master:
                        logger.info(f"⚡ [WS RELAY] Encaminhando comando para PC Master: {msg.get('comando')}")
                        await central_alertas._enviar_direto(central_alertas.pc_master, msg)
                    else:
                        logger.warning("⚠️ [WS RELAY] Comando para PC recebido, mas PC Master está offline.")
                
                elif msg.get("destino") == "MOBILE":
                    if central_alertas.mobile_client:
                        logger.info(f"📱 [WS RELAY] Encaminhando mensagem para Celular.")
                        await central_alertas._enviar_direto(central_alertas.mobile_client, msg)
                    else:
                        logger.warning("⚠️ [WS RELAY] Mensagem para Mobile recebida, mas Celular está offline.")

                elif tipo == "REGISTRO":
                    cliente_id = msg.get("id")
                    if cliente_id == "PC_MASTER":
                        central_alertas.pc_master = websocket
                        logger.info("🖥️ [WS] PC Master registrado com sucesso!")
                    elif cliente_id == "MOBILE":
                        central_alertas.mobile_client = websocket
                        logger.info("📱 [WS] Celular registrado com sucesso!")
                
                elif tipo == "LISTA_APPS":
                    from servicos.pc_control_service import pc_control_service
                    apps = msg.get("apps", [])
                    pc_control_service.salvar_cache_apps(apps)
                
                elif tipo == "STATUS_PC":
                    # Auto-registro se não estiver registrado
                    if not central_alertas.pc_master:
                        central_alertas.pc_master = websocket
                        logger.info("🖥️ [WS] PC Master auto-registrado via Status.")
                    
                    # Retransmite o status do PC para todos (especialmente para o Celular)
                    logger.info(f"🖥️ [WS] Status do PC recebido: {msg.get('stats')}")
                    await central_alertas._broadcast(msg)
                    
            except Exception as e:
                logger.error(f"Erro ao processar mensagem WS: {e}")
    except WebSocketDisconnect:
        central_alertas.desconectar(websocket)
    except Exception as e:
        logger.error(f"Erro no WebSocket: {e}")
        central_alertas.desconectar(websocket)
