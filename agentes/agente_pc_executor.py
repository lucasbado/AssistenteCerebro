import logging
import os
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
        # Se estivermos na nuvem (sem VM e sem Pyautogui), não tentamos executar
        if not pc_control_service.vm and os.getenv("RENDER"):
            logger.info(f"☁️ [Agente PC] Rodando em nuvem. Comando '{evento.payload.get('comando')}' será roteado via WebSocket.")
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
        
        logger.info(f"🛠️ [Agente PC] Executando comando: {comando}")
        
        try:
            # --- COMANDOS VOICEMEETER ---
            if comando == "volume_canal":
                pc_control_service.set_gain(evento.payload.get("canal"), evento.payload.get("valor"))
            
            elif comando == "toggle_rota":
                pc_control_service.toggle_rota(evento.payload.get("canal"), evento.payload.get("saida"), evento.payload.get("estado"))
            
            elif comando == "mutar_mic":
                pc_control_service.mutar_mic()
            
            elif comando == "trocar_saida":
                canal = evento.payload.get("canal", 3)
                if pc_control_service.vm:
                    a1 = int(pc_control_service.vm.get(f'Strip[{canal}].A1'))
                    pc_control_service.toggle_rota(canal, "A1", not a1)
                    pc_control_service.toggle_rota(canal, "A2", a1) # Inverte A1 e A2

            elif comando == "ciclar_saida":
                canal = evento.payload.get("canal", 3)
                if pc_control_service.vm:
                    a1 = int(pc_control_service.vm.get(f'Strip[{canal}].A1'))
                    a2 = int(pc_control_service.vm.get(f'Strip[{canal}].A2'))
                    a3 = int(pc_control_service.vm.get(f'Strip[{canal}].A3'))

                    # Lógica de Ciclagem: A1 -> A2 -> A3 -> A1
                    if a1 == 1:
                        pc_control_service.toggle_rota(canal, "A1", False)
                        pc_control_service.toggle_rota(canal, "A2", True)
                        logger.info(f"🔊 [Agente PC] Ciclou para A2 no canal {canal}")
                    elif a2 == 1:
                        pc_control_service.toggle_rota(canal, "A2", False)
                        pc_control_service.toggle_rota(canal, "A3", True)
                        logger.info(f"🔊 [Agente PC] Ciclou para A3 no canal {canal}")
                    else: # Se estiver no A3 ou nenhum ativo
                        pc_control_service.toggle_rota(canal, "A3", False)
                        pc_control_service.toggle_rota(canal, "A1", True)
                        logger.info(f"🔊 [Agente PC] Ciclou para A1 no canal {canal}")

            elif comando == "voicemeeter":
                # 🚀 CARGA UNIVERSAL: Suporta Macro direta ou parâmetros estruturados
                macro = evento.payload.get("macro")
                if macro:
                    pc_control_service.voicemeeter_set(macro)
                else:
                    canal = evento.payload.get("canal") or evento.payload.get("index", 3)
                    saida = evento.payload.get("saida") or evento.payload.get("param") or evento.payload.get("parametro")
                    valor = evento.payload.get("valor") or evento.payload.get("value") or evento.payload.get("estado", 1)
                    
                    if saida and canal is not None:
                        pc_control_service.toggle_rota(canal, saida, int(valor) == 1)
                        logger.info(f"🔊 [Agente PC] Rota {saida} setada para {valor} no canal {canal}")

            # --- COMANDOS SPOTIFY ---
            elif comando.startswith("spotify_"):
                if comando == "spotify_next": pc_control_service.spotify_next()
                elif comando == "spotify_prev": pc_control_service.spotify_prev()
                elif comando == "spotify_play_pause": pc_control_service.spotify_pause()
                elif comando == "spotify_play":
                    query = evento.payload.get("query") or evento.payload.get("app")
                    if query: pc_control_service.tocar_spotify(query)
                elif comando == "spotify_like": pc_control_service.spotify_like()

            # --- COMANDOS MOUSE/TECLADO ---
            elif comando == "mouse_move":
                pc_control_service.mouse_move(evento.payload.get("dx", 0), evento.payload.get("dy", 0))
            elif comando == "mouse_click":
                pc_control_service.mouse_click(evento.payload.get("botao", "left"))
            elif comando == "mouse_scroll":
                pc_control_service.mouse_scroll(evento.payload.get("quantidade", 0))
            elif comando == "executar_macro":
                pc_control_service.executar_macro(evento.payload.get("macro"))

            # --- COMANDOS SISTEMA ---
            elif comando == "abrir_app":
                pc_control_service.abrir_app(evento.payload.get("app"))
            elif comando == "abrir_url":
                pc_control_service.abrir_url(evento.payload.get("url"))
            elif comando == "pesquisa_google":
                pc_control_service.pesquisa_google(evento.payload.get("query"))
            elif comando == "buscar_documentos":
                resultados = pc_control_service.buscar_arquivos(evento.payload.get("termo", ""))
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
