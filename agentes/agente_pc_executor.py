import logging
import os
import asyncio
from core.evento import EventoCanonico
from core.tipos import EstadoEvento, TipoAcao
from servicos.pc_control_service import pc_control_service

logger = logging.getLogger("AgentePcExecutor")

class AgentePcExecutor:
    """
    Este agente é o braço físico da IA no PC. 
    Ele escuta comandos do usuário (via UDP) ou intenções da própria IA 
    e as executa no hardware (Voicemeeter, Teclado, Mouse).
    """
    
    async def processar(self, evento: EventoCanonico):
        # ☁️ ROTEAMENTO CLOUD: Se estivermos no Render, o comando deve ir via WebSocket para o PC Master
        is_render = os.getenv("RENDER", "False").lower() in ["true", "1", "yes"]
        if is_render:
            comando = evento.payload.get("comando")
            if comando:
                logger.info(f"☁️ [Agente PC] Rodando em nuvem. Comando '{comando}' sendo roteado via WebSocket para PC Master.")
                from api.websocket import central_alertas
                # Prepara o payload para o PC Master local (Relé)
                payload_ws = {
                    "tipo_ws": "COMANDO_PC",
                    "comando": comando,
                    "parametro": evento.payload.get("parametro"),
                    "valor": evento.payload.get("valor"),
                    "app": evento.payload.get("app"),
                    "url": evento.payload.get("url")
                }
                await central_alertas._broadcast(payload_ws)
                evento.estado = EstadoEvento.CONCLUIDO
            return

        if evento.acao == TipoAcao.EXECUTAR_PROGRAMA:
            programa = evento.payload.get("programa")
            if programa:
                logger.info(f"🛠️ [Agente PC] Executando programa por associação aprendida: {programa}")
                try:
                    pc_control_service.abrir_app(programa)
                    evento.estado = EstadoEvento.CONCLUIDO
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
        
        try:
            # --- COMANDOS DE MANUTENÇÃO / INTERFACE ---
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
            elif comando.startswith("spotify_"):
                if comando == "spotify_next": pc_control_service.spotify_next()
                elif comando == "spotify_prev": pc_control_service.spotify_prev()
                elif comando == "spotify_play_pause": pc_control_service.spotify_pause()
                elif comando == "spotify_play":
                    if param: pc_control_service.tocar_spotify(param)
                elif comando == "spotify_like": pc_control_service.spotify_like()

            # --- COMANDOS MOUSE/TECLADO ---
            elif comando == "mouse_move":
                pc_control_service.mouse_move(evento.payload.get("dx", 0), evento.payload.get("dy", 0))
            elif comando == "mouse_click":
                pc_control_service.mouse_click(evento.payload.get("botao", "left"))
            elif comando == "mouse_scroll":
                pc_control_service.mouse_scroll(evento.payload.get("quantidade", 0))
            elif comando == "executar_macro":
                macro_alvo = evento.payload.get("macro") or param
                logger.info(f"⚡ [Agente PC] Disparando Macro: {macro_alvo}")
                pc_control_service.executar_macro(macro_alvo)

            # --- COMANDOS MÍDIA (DIRETO) ---
            elif comando == "media_play_pause":
                pc_control_service.executar_macro("media_play_pause")
            elif comando == "media_next":
                pc_control_service.executar_macro("media_next")
            elif comando == "media_prev":
                pc_control_service.executar_macro("media_prev")

            # --- COMANDOS SISTEMA ---
            elif comando == "abrir_app" or comando == "abrir_programa":
                foi_focada = pc_control_service.abrir_app(param)
                
                if foi_focada:
                    from core.kernel import kernel
                    from core.tipos import CategoriaEvento, OrigemEvento
                    await kernel.publicar(evento.clonar(
                        categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
                        acao=TipoAcao.INTENCAO_INTERACAO,
                        origem=OrigemEvento.IA,
                        payload={
                            "texto": f"O {param} já estava aberto, trouxe a janela para frente!",
                            "tipo_ws": "CHAT_RESPONSE"
                        }
                    ))

            elif comando == "abrir_url":
                pc_control_service.abrir_url(param)

            elif comando == "abrir_arquivo":
                if pc_control_service.abrir_arquivo(param):
                    evento.estado = EstadoEvento.CONCLUIDO
                else:
                    logger.warning(f"Não foi possível abrir o arquivo: {param}")

            elif comando == "listar_arquivos":
                caminho = evento.payload.get("caminho") or evento.payload.get("parametro")
                itens = pc_control_service.listar_diretorio(caminho)
                texto_res = f"📂 Arquivos em {caminho or 'Home'}:\n" + "\n".join(itens[:15]) # Top 15 para não poluir
                
                from core.kernel import kernel
                from core.tipos import CategoriaEvento, OrigemEvento
                await kernel.publicar(evento.clonar(
                    categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
                    acao=TipoAcao.INTENCAO_INTERACAO,
                    origem=OrigemEvento.IA,
                    payload={"texto": texto_res, "tipo_ws": "CHAT_RESPONSE"}
                ))

            elif comando == "volume_sistema":
                valor = evento.payload.get("valor") or evento.payload.get("parametro")
                if str(valor).isdigit():
                    pc_control_service.set_system_volume(int(valor))

            elif comando == "encerrar_processo":
                alvo = evento.payload.get("processo") or evento.payload.get("parametro")
                pc_control_service.encerrar_processo(alvo)

            elif comando == "buscar_documentos":
                termo = evento.payload.get("termo") or evento.payload.get("parametro", "")
                resultados = pc_control_service.buscar_arquivos(termo)
                if resultados:
                    texto_res = f"🔎 Encontrei isso para '{termo}':\n" + "\n".join([os.path.basename(r) for r in resultados])
                else:
                    texto_res = f"❌ Não achei nenhum arquivo com o nome '{termo}'."
                if resultados:
                    texto_res = "Encontrei estes arquivos:\n" + "\n".join(resultados)
                else:
                    texto_res = "Não encontrei nenhum arquivo com esse nome."
                
                # Feedback via Chat (Ollie responde o resultado da busca)
                from core.kernel import kernel
                from core.tipos import CategoriaEvento, OrigemEvento
                await kernel.publicar(evento.clonar(
                    categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
                    acao=TipoAcao.INTENCAO_INTERACAO,
                    origem=OrigemEvento.IA,
                    payload={"texto": texto_res, "tipo_ws": "CHAT_RESPONSE"}
                ))

            elif comando == "bloquear_pc":
                pc_control_service.bloquear_pc()
            elif comando == "dormir_pc":
                pc_control_service.dormir_pc()
            elif comando == "hibernar_pc":
                pc_control_service.hibernar_pc()
            elif comando == "desligar_pc":
                pc_control_service.desligar_pc()
            elif comando == "reiniciar_pc":
                pc_control_service.reiniciar_pc()
            elif comando == "modo_imersao":
                # Se não passar estado, assume True para ligar
                estado = evento.payload.get("estado", True)
                pc_control_service.set_modo_imersao(estado)
            
            elif comando == "janela_fullscreen":
                pc_control_service.janela_fullscreen(evento.payload.get("parametro") or evento.payload.get("app"))
            elif comando == "janela_maximizar":
                pc_control_service.janela_maximizar(evento.payload.get("parametro") or evento.payload.get("app"))
            elif comando == "janela_minimizar":
                pc_control_service.janela_minimizar(evento.payload.get("parametro") or evento.payload.get("app"))
            
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

            evento.estado = EstadoEvento.CONCLUIDO
        except Exception as e:
            logger.error(f"[Agente PC] Falha ao executar {comando}: {e}")
