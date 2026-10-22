"""
api/websocket.py
"""
import logging
import json
import asyncio
import time
import uuid
from datetime import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from servicos.confirmacao_pc import ConfirmacoesPC

logger = logging.getLogger("WebSocket")
router = APIRouter()

class GerenciadorNotificacoes:
    def __init__(self):
        self.conexoes_ativas: list[WebSocket] = []
        self._buffer_mensagens: list[dict] = []
        self.pc_master: WebSocket = None # Referência para o PC ligado
        self.mobile_client: WebSocket = None
        self.confirmacoes = ConfirmacoesPC()
        self._ultimo_status_pc = None
        self._capacidades = {}
        self._pedidos_casa = {}

    async def executar_casa(self, identificador, acao, entity_id, timeout=20):
        if len(self._pedidos_casa) >= 32:
            return {"status": "ocupado"}
        ponte = next((ws for ws in (self.pc_master, self.mobile_client) if ws is not None
                      and ws.client_state.value == 1 and "CASA" in self._capacidades.get(ws, set())), None)
        if ponte is None:
            return {"status": "sem_ponte"}
        futuro = asyncio.get_running_loop().create_future()
        self._pedidos_casa[identificador] = (ponte, entity_id, futuro)
        if ponte is self.pc_master:
            msg = {"tipo_ws": "COMANDO_PC", "comando": "casa_acao", "id_comando": identificador,
                   "parametro": json.dumps({"acao": acao, "entity_id": entity_id})}
        else:
            msg = {"tipo_ws": "COMANDO_CASA", "id_comando": identificador,
                   "acao": acao, "entity_id": entity_id}
        try:
            if not await self._enviar_direto(ponte, msg):
                return {"status": "sem_confirmacao"}
            return await asyncio.wait_for(futuro, timeout)
        except asyncio.TimeoutError:
            return {"status": "sem_confirmacao"}
        finally:
            self._pedidos_casa.pop(identificador, None)

    def ponte_casa_disponivel(self):
        return any(ws is not None and ws.client_state.value == 1 and 'CASA' in self._capacidades.get(ws, set())
                   for ws in (self.pc_master, self.mobile_client))

    def confirmar_casa(self, websocket, msg):
        pedido = self._pedidos_casa.get(str(msg.get("id_comando", "")))
        if pedido is None or pedido[0] is not websocket or pedido[2].done():
            return
        resultado = msg.get("resultado")
        valido = (isinstance(resultado, dict) and resultado.get("entity_id") == pedido[1]
                  and resultado.get("state") in {"on", "off"} and msg.get("status") == "concluido")
        pedido[2].set_result({"status": "concluido" if valido else "erro",
                              "resultado": {"entity_id": pedido[1], "state": resultado["state"]} if valido else {}})

    def estado_conexoes(self):
        def conectado(ws):
            return ws is not None and ws.client_state.value == 1
        return {"pc": {"conectado": conectado(self.pc_master),
                       "segundos_sem_status": None if self._ultimo_status_pc is None else
                       round(time.monotonic() - self._ultimo_status_pc, 1)},
                "mobile": {"conectado": conectado(self.mobile_client)}}

    async def enviar_comando_pc(self, mensagem):
        msg = dict(mensagem)
        identificador = str(msg.get("id_comando") or uuid.uuid4())
        if len(identificador) > 128:
            raise ValueError("Identificador de comando inválido")
        if not self.confirmacoes.registrar(identificador, str(msg.get("comando", ""))):
            return self.confirmacoes.consultar(identificador)
        msg.update(tipo_ws="COMANDO_PC", id_comando=identificador)
        if not self.pc_master or not await self._enviar_direto(self.pc_master, msg):
            self.confirmacoes.atualizar(identificador, "pc_offline")
        return self.confirmacoes.consultar(identificador)

    async def enviar_comando_mobile(self, mensagem):
        if self.mobile_client is None:
            return False
        return await self._enviar_direto(self.mobile_client, dict(mensagem))

    async def conectar(self, websocket: WebSocket):
        protocolos = websocket.headers.get("sec-websocket-protocol", "").split(",")
        await websocket.accept(subprotocol="ollie" if "ollie" in [p.strip() for p in protocolos] else None)
        # 🛡️ ANTI-DUPLICIDADE PREVENTIVA: Remove referências a websockets que já fecharam
        self.conexoes_ativas = [ws for ws in self.conexoes_ativas if ws.client_state.value == 1]
        self.conexoes_ativas.append(websocket)
        logger.info(f"✅ [WS] Nova conexão! Total ativos: {len(self.conexoes_ativas)}")
        
        # Pede identificação ao conectar
        try:
            await websocket.send_json({
                "tipo_ws": "SOLICITAR_IDENTIFICACAO"
            })
        except: pass

    def desconectar(self, websocket: WebSocket):
        self._capacidades.pop(websocket, None)
        for ponte, _, futuro in tuple(self._pedidos_casa.values()):
            if ponte is websocket and not futuro.done():
                futuro.set_result({"status": "sem_confirmacao"})
        if websocket in self.conexoes_ativas:
            self.conexoes_ativas.remove(websocket)
        if self.pc_master == websocket:
            self.pc_master = None
            self._ultimo_status_pc = None
            logger.warning("🔌 [WS] PC Master desconectado.")
        if self.mobile_client == websocket:
            self.mobile_client = None
            logger.warning("🔌 [WS] Celular desconectado.")

    async def enviar_alerta(self, payload: dict):
        payload_negocio = payload.get("payload", {})
        dados_para_envio = payload_negocio.copy()
        
        categoria = payload.get("categoria")
        origem = payload.get("origem")
        metadados = payload.get("metadados", {})
        
        # 🌟 REGRA DE OURO DE ROTEAMENTO (REFORÇADA):
        tipo_ws = dados_para_envio.get("tipo_ws", "")
        comando_nome = str(dados_para_envio.get("comando", "")).lower()
        
        # Identifica se é comando para o Celular
        is_mobile_cmd = "_mobile" in comando_nome or ("abrir_app" in comando_nome and "pacote" in dados_para_envio) or (tipo_ws == "COMANDO_SISTEMA")
        tem_comando_pc = ("comando" in dados_para_envio and not is_mobile_cmd) or (categoria == "SISTEMA_COMANDO_PC") or (metadados.get("tipo_destino") == "PC")

        # Define tipo_ws se ausente
        if not tipo_ws:
            if metadados.get("tipo_destino") == "NOTIFICACAO":
                dados_para_envio['tipo_ws'] = 'NOTIFICACAO'
            elif metadados.get("tipo_destino") == "CHAT" or origem == "IA" or categoria == "INTENCAO_NOTIFICACAO":
                dados_para_envio['tipo_ws'] = 'CHAT_RESPONSE'
            else:
                dados_para_envio['tipo_ws'] = 'NOTIFICACAO'
        
        tipo_ws = dados_para_envio.get("tipo_ws") # Atualiza após definição acima

        # Sincroniza campos de texto
        if 'mensagem' in dados_para_envio:
            dados_para_envio['texto'] = dados_para_envio.pop('mensagem')
        
        # 🛡️ GARANTIA DE ENTREGA: Nunca envia resposta de chat vazia
        if tipo_ws == "CHAT_RESPONSE" and not dados_para_envio.get("texto"):
            dados_para_envio["texto"] = "Comando processado com sucesso!"
            
        dados_para_envio.setdefault("titulo", "Assistente")
        dados_para_envio["origem_sistema"] = "OLLIE"
        
        if 'timestamp' in payload:
            ts = payload['timestamp']
            dados_para_envio['timestamp'] = ts.isoformat() if isinstance(ts, datetime) else str(ts)
        dados_para_envio['correlacao_id'] = str(payload.get('correlacao_id', ''))
        dados_para_envio['id'] = str(payload.get('id', ''))

        # Uma resposta pertence ao dispositivo que fez o pedido; não há fallback para outro.
        if tipo_ws == "CHAT_RESPONSE":
            destino = metadados.get("dispositivo_origem") or (
                "PC" if str(payload.get("pacote", "")).startswith("pc.") else "MOBILE")
            dados_para_envio["dispositivo_destino"] = destino
            dados_para_envio["canal_origem"] = metadados.get("canal_origem", "texto")
            cliente = self.pc_master if destino == "PC" else self.mobile_client
            return await self._enviar_direto(cliente, dados_para_envio) if cliente is not None else False

        # ROTEAMENTO RESTRITO:
        # 1. MOBILE: Prioridade para comandos de sistema/luz e chat
        if tipo_ws in ["CHAT_RESPONSE", "NOTIFICACAO", "THINKING", "COMANDO_SISTEMA"] or is_mobile_cmd:
            if self.mobile_client:
                logger.info(f"📱 [WS] Roteando {tipo_ws} para Mobile Client.")
                # Tenta envio direto, se falhar, tenta broadcast
                if await self._enviar_direto(self.mobile_client, dados_para_envio):
                    return

        # 2. PC: Apenas se for comando de PC e tiver PC conectado
        if tem_comando_pc and self.pc_master:
            logger.info(f"⚡ [WS] Roteando comando '{comando_nome}' para PC Master.")
            if await self._enviar_direto(self.pc_master, dados_para_envio):
                return

        # 3. Fallback: Se não tem alvo definido ou alvo offline, avisa e tenta broadcast
        logger.debug(f"📡 [WS] Enviando via broadcast (Fim da fila): {tipo_ws}")
        await self._broadcast(dados_para_envio)

    async def _enviar_direto(self, ws: WebSocket, msg: dict) -> bool:
        """Tenta enviar e retorna sucesso. Se falhar, desconecta o WS."""
        try:
            # Verifica se a conexão ainda está teoricamente aberta
            if ws.client_state.value != 1:
                self.desconectar(ws)
                return False
            await ws.send_text(json.dumps(msg, default=str))
            return True
        except Exception as e:
            logger.error(f"❌ [WS] Falha no envio direto: {e}")
            self.desconectar(ws)
            return False

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

    async def _broadcast(self, msg: dict):
        # Limpeza preventiva antes do broadcast
        self.conexoes_ativas = [ws for ws in self.conexoes_ativas if ws.client_state.value == 1]
        
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
                    resultado = await central_alertas.enviar_comando_pc(msg)
                    await websocket.send_json({"tipo_ws": "COMANDO_ACEITO", **resultado})

                elif tipo == "COMANDO_RESULTADO":
                    # Somente o PC registrado pode confirmar uma execução local.
                    if websocket is central_alertas.pc_master:
                        central_alertas.confirmacoes.atualizar(str(msg.get("id_comando", "")),
                                                               msg.get("status"), msg.get("resultado"))
                        central_alertas.confirmar_casa(websocket, msg)

                elif tipo == "CASA_RESULTADO":
                    central_alertas.confirmar_casa(websocket, msg)
                
                elif msg.get("destino") == "MOBILE":
                    if central_alertas.mobile_client:
                        logger.info(f"📱 [WS RELAY] Encaminhando mensagem para Celular.")
                        await central_alertas._enviar_direto(central_alertas.mobile_client, msg)
                    else:
                        logger.warning("⚠️ [WS RELAY] Mensagem para Mobile recebida, mas Celular está offline.")

                elif tipo == "REGISTRO":
                    cliente_id = msg.get("id")
                    capacidades = msg.get("capacidades", [])
                    if cliente_id in {"PC_MASTER", "MOBILE"}:
                        central_alertas._capacidades[websocket] = {"CASA"} if isinstance(capacidades, list) and "CASA" in capacidades else set()
                    if cliente_id == "PC_MASTER":
                        # 🛡️ ANTI-DUPLICIDADE: Se for a mesma conexão, ignora. 
                        # Se for nova, substitui a antiga para garantir que o link master seja único.
                        if central_alertas.pc_master and central_alertas.pc_master != websocket:
                            logger.warning("🔄 [WS] Novo link PC_MASTER recebido. Finalizando conexão anterior...")
                            old_ws = central_alertas.pc_master
                            try:
                                # Tenta fechar graciosamente para evitar que o cliente entre em loop infinito de reconexão
                                await old_ws.close(1001, "New master session started")
                            except: pass
                            
                        central_alertas.pc_master = websocket
                        logger.info("🖥️ [WS] PC Master autenticado e vinculado.")
                        
                        # Confirma para o cliente que o registro foi aceito
                        try:
                            await websocket.send_json({"tipo_ws": "REGISTRO_OK", "id": "PC_MASTER"})
                        except: pass
                        
                    elif cliente_id == "MOBILE":
                        conn_id = msg.get("connection_id", "legacy")
                        # 🛡️ ANTI-DUPLICIDADE: Só fecha se for uma conexão REALMENTE diferente
                        if central_alertas.mobile_client and central_alertas.mobile_client != websocket:
                            logger.warning(f"🔄 [WS] Novo MOBILE detectado ({conn_id}). Substituindo conexão antiga.")
                            old_ws = central_alertas.mobile_client
                            if old_ws in central_alertas.conexoes_ativas:
                                central_alertas.conexoes_ativas.remove(old_ws)
                            try: await old_ws.close(1001, "Nova conexão MOBILE registrada")
                            except: pass
                        
                        if central_alertas.mobile_client != websocket:
                            central_alertas.mobile_client = websocket
                            logger.info(f"📱 [WS] Celular registrado ({conn_id})!")
                        else:
                            logger.debug(f"📱 [WS] Celular re-confirmou identidade ({conn_id}).")

                elif tipo == "CHAT_MESSAGE":
                    from core.kernel import kernel
                    from servicos.roteamento_pedidos import metadados_entrada
                    from core.tipos import CategoriaEvento, TipoAcao, OrigemEvento, PrioridadeEvento
                    from core.evento import EventoCanonico
                    logger.info(f"💬 [WS] Mensagem de chat recebida: {msg.get('texto')}")
                    dispositivo = ("PC" if websocket is central_alertas.pc_master else "MOBILE"
                        if websocket is central_alertas.mobile_client else
                        "PC" if str(msg.get("pacote", "")).startswith("pc.") else "MOBILE")
                    await kernel.publicar(EventoCanonico(
                        categoria=CategoriaEvento.SISTEMA_COMANDO_USUARIO,
                        acao=TipoAcao.NORMAL,
                        origem=OrigemEvento.USUARIO,
                        pacote=msg.get("pacote", "com.example.assistentecell"),
                        **({"correlacao_id": msg["correlacao_id"]} if isinstance(msg.get("correlacao_id"), str) and 0 < len(msg["correlacao_id"]) <= 128 else {}),
                        prioridade=PrioridadeEvento.ALTA,
                        metadados=metadados_entrada(dispositivo, msg.get("canal")),
                        payload={"texto": msg.get("texto")}
                    ))

                elif tipo in {"FEEDBACK", "SUGGESTION_REJECTED"}:
                    from api.feedback import FeedbackUsuario, receber_feedback
                    feedback = dict(msg)
                    if tipo == "SUGGESTION_REJECTED":
                        feedback["tipo_feedback"] = "SUGGESTION_REJECTED"
                    await receber_feedback(FeedbackUsuario.model_validate(feedback))
                
                elif tipo == "LISTA_APPS":
                    from servicos.pc_control_service import pc_control_service
                    apps = msg.get("apps", [])
                    pc_control_service.salvar_cache_apps(apps)
                
                elif tipo == "STATUS_PC":
                    # Auto-registro se não estiver registrado
                    if not central_alertas.pc_master:
                        central_alertas.pc_master = websocket
                        logger.info("🖥️ [WS] PC Master auto-registrado via Status.")
                    if websocket is not central_alertas.pc_master:
                        continue
                    central_alertas._ultimo_status_pc = time.monotonic()
                    
                    # 🧠 CONSCIÊNCIA: Atualiza a consciência situacional com os dados do PC
                    from servicos.consciencia import consciencia
                    stats = msg.get("stats", {})
                    consciencia.atualizar({
                        "pc_state": {
                            "is_online": stats.get("online", True),
                            "cpu": stats.get("cpu", 0),
                            "ram": stats.get("ram", 0),
                            "audio_state": stats.get("audio_state", {}),
                            "mic_mute": stats.get("mic_mute"),
                            "apps_disponiveis": stats.get("apps_disponiveis", [])
                        }
                    })

                    # Retransmite o status do PC para todos (especialmente para o Celular)
                    logger.info(f"🖥️ [WS] Status do PC recebido: {stats}")
                    await central_alertas._broadcast(msg)

                elif tipo == "PC_ACTIVITY":
                    from core.kernel import kernel
                    from core.tipos import CategoriaEvento, TipoAcao, OrigemEvento
                    from core.evento import EventoCanonico
                    from servicos.consciencia import consciencia
                    
                    payload = msg.get("payload", {})
                    logger.info(f"🖥️ [WS BRIDGE] Atividade do PC recebida via ponte: {payload}")
                    
                    # 🧠 CONSCIÊNCIA: Atualiza o que o usuário está vendo no PC
                    consciencia.atualizar({
                        "pc_state": {
                            "processo_ativo": payload.get("processo"),
                            "janela_ativa": payload.get("titulo"),
                            "is_online": True
                        }
                    })

                    await kernel.publicar(EventoCanonico(
                        categoria=CategoriaEvento.PC_ACTIVITY,
                        acao=TipoAcao.NORMAL,
                        origem=OrigemEvento.PC,
                        pacote="pc.bridge.gui",
                        payload=payload
                    ))
                    
            except Exception as e:
                logger.error(f"Erro ao processar mensagem WS: {e}")
    except WebSocketDisconnect:
        central_alertas.desconectar(websocket)
    except Exception as e:
        logger.error(f"Erro no WebSocket: {e}")
        central_alertas.desconectar(websocket)
    finally:
        central_alertas.desconectar(websocket)
