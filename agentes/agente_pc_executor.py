import logging
import os
import asyncio
from core.evento import EventoCanonico
from core.tipos import CategoriaEvento, TipoAcao, OrigemEvento
from servicos.pc_control_service import pc_control_service

logger = logging.getLogger("AgentePcExecutor")

class AgentePcExecutor:
    """
    Este agente é o braço físico da IA no PC. 
    Ele escuta comandos do usuário (via UDP) ou intenções da própria IA 
    e as executa no hardware (Voicemeeter, Teclado, Mouse).
    """
    
    async def processar(self, evento: EventoCanonico):
        comando = evento.payload.get("comando")
        from servicos.intervention_governor import e_abertura, intervention_governor
        from servicos.abertura_apps import metadados_abertura, sugerir_abertura
        if (e_abertura(comando) or evento.acao == TipoAcao.EXECUTAR_PROGRAMA) and not evento.metadados.get("abertura_autorizada"):
            alvo_app = (evento.payload.get("app") or evento.payload.get("url")
                        or evento.payload.get("parametro") or evento.payload.get("programa"))
            decisao = await intervention_governor.avaliar_abertura(alvo_app, "PC",
                evento.metadados.get("importance_score"),
                explicito=evento.origem == OrigemEvento.USUARIO or evento.metadados.get("pedido_explicito") is True)
            if not decisao["permitida"]:
                await sugerir_abertura(evento, "PC", comando or "abrir_app", alvo_app, decisao["motivo"])
                return
            evento = evento.clonar(metadados={**evento.metadados, **metadados_abertura(decisao)})
        # ☁️ ROTEAMENTO CLOUD: Se estivermos no Render ou Linux (Cloud), o comando deve ir via WebSocket para o PC Master
        is_render = os.getenv("RENDER", "False").lower() in ["true", "1", "yes"] or os.name != "nt"
        if is_render or comando == "wake_ollie":
            comando = evento.payload.get("comando")
            if evento.acao == TipoAcao.EXECUTAR_PROGRAMA:
                comando = "abrir_app"
            if comando:
                logger.info(f"☁️ [Agente PC] Rodando em nuvem. Comando '{comando}' sendo roteado via WebSocket para PC Master.")
                from api.websocket import central_alertas
                # Prepara o payload para o PC Master local (Relé)
                payload_ws = {
                    **evento.model_dump()["payload"],
                    "tipo_ws": "COMANDO_PC",
                    "comando": comando,
                    "parametro": evento.payload.get("parametro") or evento.payload.get("programa"),
                    "origem": evento.origem.value,
                    **{k: evento.metadados[k] for k in ("abertura_autorizada", "abertura_modo", "importance_score") if k in evento.metadados},
                    "valor": evento.payload.get("valor"),
                    "app": evento.payload.get("app"),
                    "url": evento.payload.get("url"),
                    "id_comando": evento.payload.get("id_comando") or evento.id,
                    "correlacao_id": evento.correlacao_id
                }
                resultado = await central_alertas.enviar_comando_pc(payload_ws)
                if e_abertura(comando) and evento.metadados.get("pedido_usuario"):
                    from servicos.roteamento_pedidos import responder_pedido
                    from servicos.respostas_acoes import resumir_resultados
                    etapa = {'alvo': 'PC', 'comando': comando, 'parametro': payload_ws.get('app') or payload_ws.get('url') or payload_ws.get('parametro')}
                    status = (resultado or {}).get('status', 'pc_offline')
                    await responder_pedido(evento, resumir_resultados([{'etapa': etapa, 'status': status,
                        'foco': (resultado or {}).get('resultado', {}).get('primeiro_plano')}]))
            return

        if evento.acao == TipoAcao.EXECUTAR_PROGRAMA:
            programa = evento.payload.get("programa")
            if programa:
                logger.info(f"🛠️ [Agente PC] Executando programa por associação aprendida: {programa}")
                try:
                    pc_control_service.abrir_app(programa)
                except Exception as e:
                    logger.error(f"[Agente PC] Falha ao executar '{programa}': {e}")
            return

        comando = evento.payload.get("comando")
        if not comando: return
        
        # 🚀 NORMALIZAÇÃO DE PAYLOAD: Garante que os parâmetros cheguem aos serviços
        # Priorizamos campos específicos para evitar que o nome do comando vaze como parâmetro
        payload = evento.payload
        param = payload.get("app") or \
                payload.get("url") or \
                payload.get("parametro") or \
                payload.get("valor") or \
                payload.get("query") or \
                payload.get("macro")
        
        # 🛡️ PROTEÇÃO: Se o param for None ou o próprio nome do comando (loop), limpa ele
        if param == comando:
            param = None

        logger.info(f"🛠️ [Agente PC] Executando: {comando} | Param: {param}")
        resultado_abertura = None
        
        try:
            from servicos.comandos_pc import COMANDOS_COMPARTILHADOS, executar_compartilhado
            from servicos.arquivos_pc import COMANDOS_ARQUIVOS
            if comando in COMANDOS_COMPARTILHADOS:
                if comando == 'mouse_move':
                    param = f'{payload.get("dx", 0)},{payload.get("dy", 0)}' if 'dx' in payload or 'dy' in payload else param
                elif comando == 'mouse_click':
                    param = payload.get('botao', param)
                elif comando == 'mouse_scroll':
                    param = payload.get('quantidade', param)
                elif comando in COMANDOS_ARQUIVOS:
                    param = payload.get('termo') or payload.get('caminho') or param
                resultado = await asyncio.to_thread(executar_compartilhado, comando, param if param is not None else '', pc_control_service)
                if comando in COMANDOS_ARQUIVOS | {'system_status'} and evento.metadados.get('pedido_usuario'):
                    from servicos.respostas_acoes import resumir_resultados
                    from servicos.roteamento_pedidos import responder_pedido
                    await responder_pedido(evento, resumir_resultados([{'etapa': {'alvo': 'PC', 'comando': comando},
                        'status': 'concluido', 'resultado': resultado}]))
                return
            # --- COMANDOS DE MANUTENÇÃO / INTERFACE ---
            if comando == "executar_cenario":
                from servicos.cenarios import ServicoCenarios
                await asyncio.to_thread(ServicoCenarios().executar, param)
                return
            if comando == "estudar_pc":
                logger.info("🧠 [Agente PC] Iniciando mapeamento geográfico do PC...")
                pastas = await asyncio.to_thread(pc_control_service.mapear_estrutura_usuario)
                from api.websocket import central_alertas
                await central_alertas._broadcast({"tipo_ws": "PC_STRUCTURE", "pastas": pastas, "id": "PC_MASTER"})
                return

            elif comando == "inicializar_hardware":
                await asyncio.to_thread(pc_control_service.inicializar)
                return

            # --- COMANDOS VOICEMEETER ---
            if comando == "voicemeeter":
                if isinstance(param, str) and "=" in param:
                    # Passa a string bruta se contiver múltiplos comandos ou usa split seguro
                    if "," in param:
                        pc_control_service.set_vm_param(param, None)
                    else:
                        parts = param.split("=", 1)
                        pc_control_service.set_vm_param(parts[0].strip(), parts[1].strip())
                else:
                    # Fallback para parâmetros individuais
                    pc_control_service.toggle_rota(
                        evento.payload.get("canal", 3),
                        evento.payload.get("saida", "A1"),
                        evento.payload.get("estado") or evento.payload.get("valor") == 1
                    )

            elif comando == "volume_canal":
                pc_control_service.set_gain(evento.payload.get("canal"), evento.payload.get("valor") or param)
            
            elif comando == "mutar_mic":
                pc_control_service.mutar_mic()

            # --- COMANDOS SPOTIFY ---
            elif comando == "spotify_play" and param:
                pc_control_service.tocar_spotify(param)

            # --- COMANDOS SISTEMA ---
            elif comando == "abrir_app" or comando == "abrir_programa":
                resultado_abertura = pc_control_service.abrir_app(param)
                if resultado_abertura is False:
                    raise RuntimeError("O sistema não conseguiu abrir esse aplicativo")

            elif comando == "abrir_url" or comando == "open_url":
                resultado_abertura = pc_control_service.abrir_url(param)
            elif comando in {"pesquisa_google", "web_search", "pesquisar"}:
                from servicos.buscas_web import url_busca
                resultado_abertura = await asyncio.to_thread(pc_control_service.abrir_url, url_busca(param))

            elif comando in ["ligar_luz", "desligar_luz", "toggle_luz"]:
                from servicos.home_assistant_service import home_assistant_service
                entity_id = param if param and param.startswith("light.") else "light.yeelink_color5_027d_light"
                success = False
                if comando == "ligar_luz":
                    success = await home_assistant_service.ligar_luz(entity_id)
                elif comando == "desligar_luz":
                    success = await home_assistant_service.desligar_luz(entity_id)
                elif comando == "toggle_luz":
                    success = await home_assistant_service.toggle_luz(entity_id)
                
                if success:
                    logger.info(f"💡 [Agente PC] Comando Home Assistant executado com sucesso: {comando} em {entity_id}")
                else:
                    logger.error(f"❌ [Agente PC] Falha ao executar comando Home Assistant: {comando} em {entity_id}")
                    from core.kernel import kernel
                    await kernel.publicar(evento.clonar(
                        categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
                        acao=TipoAcao.INTENCAO_INTERACAO,
                        origem=OrigemEvento.IA,
                        payload={
                            "texto": f"Tentei controlar a luz no Home Assistant, mas a requisição falhou. Verifique se o HASS está acessível em {home_assistant_service.base_url} e se é necessário configurar um token (HA_TOKEN).",
                            "tipo_ws": "CHAT_RESPONSE"
                        }
                    ))

            elif comando == "volume_sistema":
                valor = evento.payload.get("valor") or evento.payload.get("parametro")
                if str(valor).isdigit():
                    pc_control_service.set_system_volume(int(valor))

            elif comando == "encerrar_processo":
                alvo = evento.payload.get("processo") or evento.payload.get("parametro")
                pc_control_service.encerrar_processo(alvo)

            elif comando == "modo_imersao":
                # Se não passar estado, assume True para ligar
                estado = evento.payload.get("estado", True)
                pc_control_service.set_modo_imersao(estado)
            
            elif comando == "executar_macro_personalizada":
                nome_macro = evento.payload.get("nome")
                from servicos.macro_service import macro_service
                from core.kernel import kernel
                await macro_service.executar_macro(nome_macro, kernel)

            # --- COMANDOS MOBILE (RETRANSMISSÃO) ---
            elif comando == "abrir_app_mobile":
                package_name = evento.payload.get("pacote")
                if package_name:
                    await pc_control_service.abrir_app_mobile(package_name)
            
            elif comando == "abrir_url_mobile":
                url = evento.payload.get("url")
                if url:
                    await pc_control_service.abrir_url_mobile(url)

        except Exception as e:
            logger.error(f"[Agente PC] Falha ao executar {comando}: {e}")
            if e_abertura(comando) and evento.metadados.get("pedido_usuario"):
                from servicos.roteamento_pedidos import responder_pedido
                from servicos.respostas_acoes import resumir_resultados
                await responder_pedido(evento, resumir_resultados([{'etapa': {'alvo': 'PC', 'comando': comando, 'parametro': param}, 'status': 'erro'}]))
        else:
            if comando in {"abrir_app", "abrir_programa", "abrir_url", "open_url", "pesquisa_google", "web_search", "pesquisar"} and evento.metadados.get("pedido_usuario"):
                from servicos.roteamento_pedidos import responder_pedido
                from servicos.respostas_acoes import resumir_resultados
                await responder_pedido(evento, resumir_resultados([{'etapa': {'alvo': 'PC', 'comando': comando, 'parametro': param},
                    'status': 'concluido', 'foco': resultado_abertura.get('primeiro_plano') if isinstance(resultado_abertura, dict) else None}]))
