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
        
        # Identifica se deve ir para o CHAT
        if 'tipo_ws' not in dados_para_envio:
            origem = payload.get("origem")
            categoria = payload.get("categoria")
            metadados = payload.get("metadados", {})
            if metadados.get("tipo_destino") == "CHAT" or origem == "IA" or categoria == "INTENCAO_NOTIFICACAO":
                dados_para_envio['tipo_ws'] = 'CHAT_RESPONSE'
            else:
                dados_para_envio['tipo_ws'] = 'NOTIFICACAO'

        if 'mensagem' in dados_para_envio:
            dados_para_envio['texto'] = dados_para_envio.pop('mensagem')
        dados_para_envio.setdefault("titulo", "Assistente")
        dados_para_envio["origem_sistema"] = "OLLIE"
        
        if 'timestamp' in payload:
            ts = payload['timestamp']
            dados_para_envio['timestamp'] = ts.isoformat() if isinstance(ts, datetime) else str(ts)
            
        dados_para_envio['correlacao_id'] = str(payload.get('correlacao_id', ''))

        # ROTEAMENTO INTELIGENTE:
        # Se for comando de hardware, manda pro PC.
        if "comando" in dados_para_envio:
            if self.pc_master:
                logger.info(f"⚡ [WS] Enviando comando '{dados_para_envio['comando']}' para PC Master.")
                await self._enviar_direto(self.pc_master, dados_para_envio)
            else:
                logger.warning("⚠️ [WS] Comando de hardware recebido mas PC Master está offline.")
            return

        # Notificações e Chat vão para todos (ou apenas mobile se quisermos economizar)
        await self._broadcast(dados_para_envio)

    async def enviar_evento_log(self, evento_dict: dict):
        ts = evento_dict.get("timestamp")
        ts_str = ts.isoformat() if isinstance(ts, datetime) else str(ts)
        log_dto = {
            "tipo_ws": "EVENTO_LOG",
            "id": str(evento_dict.get("id")),
            "categoria": str(evento_dict.get("categoria")),
            "resumo": self._gerar_resumo_amigavel(evento_dict),
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
            if msg.get("tipo_ws") in ["CHAT_RESPONSE", "NOTIFICACAO"]:
                self._buffer_mensagens.append(msg)
                if len(self._buffer_mensagens) > 20: self._buffer_mensagens.pop(0)
            return

        payload_str = json.dumps(msg, default=str)
        tasks = []
        for ws in self.conexoes_ativas:
            tasks.append(asyncio.wait_for(ws.send_text(payload_str), timeout=2.0))
        
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        except: pass

    async def processar_evento_kernel(self, evento):
        """Método para o Kernel chamar diretamente."""
        await self.enviar_alerta(evento.model_dump())

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
                
                # Handshake de identificação
                if tipo == "REGISTRO":
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
                    
            except Exception as e:
                logger.error(f"Erro ao processar mensagem WS: {e}")
    except WebSocketDisconnect:
        central_alertas.desconectar(websocket)
    except Exception as e:
        central_alertas.desconectar(websocket)
