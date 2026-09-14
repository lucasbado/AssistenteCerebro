import logging
import json
import os
from datetime import datetime

from core.evento import EventoCanonico
from core.tipos import CategoriaEvento, TipoAcao, OrigemEvento
from core.kernel import kernel

logger = logging.getLogger("AgenteRotina")

class AgenteRotina:
    """
    Motor de Automação Inteligente.
    Carrega regras de routines.json e as aplica baseando-se em gatilhos de eventos.
    """
    def __init__(self):
        # Caminho dinâmico para funcionar em qualquer diretório (Local ou Render)
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.config_path = os.path.join(base_dir, "config", "routines.json")
        self.routines = []
        self._carregar_rotinas()

    def _carregar_rotinas(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    self.routines = json.load(f)
                logger.info(f"📂 [AgenteRotina] {len(self.routines)} rotinas carregadas com sucesso de {self.config_path}")
            except Exception as e:
                logger.error(f"Erro ao carregar rotinas: {e}")
        else:
            logger.warning(f"⚠️ [AgenteRotina] Arquivo de rotinas não encontrado em: {self.config_path}")

    def _salvar_rotinas(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.routines, f, indent=4)
        except Exception as e:
            logger.error(f"Erro ao salvar rotinas: {e}")

    async def processar(self, evento: EventoCanonico):
        # 0. Comando para criar nova rotina (Vindo da IA)
        if evento.acao == TipoAcao.NORMAL and evento.payload.get("comando") == "criar_rotina":
            nova_rotina = evento.payload.get("rotina")
            if nova_rotina:
                self.routines.append(nova_rotina)
                self._salvar_rotinas()
                logger.info(f"✅ Nova rotina criada: {nova_rotina['nome']}")
                return

        # 1. Verifica gatilhos dinâmicos baseados em eventos
        for rotina in self.routines:
            if not rotina.get("ativa", True): continue
            
            gatilho = rotina.get("gatilho", {})
            logger.debug(f"🔍 Verificando rotina '{rotina['nome']}' para evento {evento.categoria}")
            if self._validar_gatilho(gatilho, evento):
                logger.info(f"🚀 Gatilho de rotina detectado: {rotina['nome']}")
                await self._executar_acoes(rotina.get("acoes", []), evento)

        # 2. Gatilhos de Status (Bateria baixa, etc)
        if evento.payload.get("tipo_ws") == "DEVICE_STATUS":
            await self._verificar_status_dispositivo(evento.payload)

        # 3. Lógica Legada (Compatibilidade)
        if evento.categoria == CategoriaEvento.SISTEMA_COMANDO_INTERNO:
            tipo_comando = evento.payload.get("tipo")
            if tipo_comando == "MUDANCA_LOCAL":
                await self._reagir_chegada_local(evento.payload.get("local"), evento)
            elif tipo_comando == "REFLEXAO_ROTINA":
                await self._analisar_padroes_gerais()

    def _validar_gatilho(self, gatilho: dict, evento: EventoCanonico) -> bool:
        tipo = gatilho.get("tipo")
        
        # Gatilho: Abertura de App
        if tipo == "APP_OPENED" and evento.categoria == CategoriaEvento.APP_FOREGROUND:
            return evento.pacote == gatilho.get("pacote")
            
        # Gatilho: Atividade no PC (Processo)
        if tipo == "PC_ACTIVITY" and evento.categoria == CategoriaEvento.PC_ACTIVITY:
            processo_gatilho = str(gatilho.get("processo")).lower()
            processo_evento = str(evento.payload.get("processo")).lower()
            logger.info(f"🧪 [AgenteRotina] Comparando Gatilho '{processo_gatilho}' com Evento '{processo_evento}'")
            return processo_gatilho in processo_evento
            
        # Gatilho: Evento de Sistema (ex: PC_LOGIN)
        if tipo == "EVENTO_SISTEMA" and evento.categoria == CategoriaEvento.SISTEMA_COMANDO_INTERNO:
            return evento.payload.get("alvo") == gatilho.get("evento")

        # Gatilho: Faixa de Horário
        if tipo == "TIME_RANGE":
            agora = datetime.now().time()
            inicio = datetime.strptime(gatilho.get("inicio"), "%H:%M").time()
            fim = datetime.strptime(gatilho.get("fim"), "%H:%M").time()
            if inicio <= agora <= fim:
                # Se for TIME_RANGE, geralmente precisa de um evento secundário (ex: PC_LOGIN)
                evento_secundario = gatilho.get("evento")
                if evento_secundario:
                    return self._validar_gatilho({"tipo": "EVENTO_SISTEMA", "evento": evento_secundario}, evento)
                return True

        return False

    async def _executar_acoes(self, acoes: list, evento_origem: EventoCanonico):
        for acao in acoes:
            try:
                alvo = acao.get("alvo")
                comando = acao.get("comando")
                param = acao.get("parametro")

                if alvo == "PC":
                    await kernel.publicar(EventoCanonico(
                        categoria=CategoriaEvento.SISTEMA_COMANDO_PC,
                        acao=TipoAcao.NORMAL,
                        origem=OrigemEvento.SISTEMA,
                        pacote="sistema.rotina",
                        payload={"comando": comando, "parametro": param}
                    ))
                elif alvo == "IA":
                    # Gera uma notificação ou interação da IA
                    # 🌟 AJUSTE: Adicionamos metadados para garantir que chegue como NOTIFICACAO no Android
                    await kernel.publicar(evento_origem.clonar(
                        categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
                        acao=TipoAcao.INTENCAO_INTERACAO,
                        origem=OrigemEvento.IA,
                        pacote="sistema.rotina",
                        payload={
                            "texto": param, 
                            "tipo_interacao": comando,
                            "tipo_ws": "NOTIFICACAO",  # Força o tipo correto
                            "urgencia": "ALTA"
                        },
                        metadados={"tipo_destino": "NOTIFICACAO"}
                    ))
                elif alvo == "MOBILE":
                    # Comando para o SystemCommandHandler do Android
                    from api.websocket import central_alertas
                    await central_alertas._broadcast({
                        "tipo_ws": "COMANDO_SISTEMA",
                        "acao": comando,
                        "parametro": param
                    })
            except Exception as e:
                logger.error(f"❌ [AgenteRotina] Erro ao executar ação {acao}: {e}")

    async def _reagir_chegada_local(self, local: str, evento_origem: EventoCanonico):
        # ... mantida a lógica legada se desejar ...
        pass

    async def _verificar_status_dispositivo(self, status: dict):
        bateria = status.get("bateria", 100)
        carregando = status.get("charging", False)
        
        if bateria < 15 and not carregando:
            await kernel.publicar(EventoCanonico(
                categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
                acao=TipoAcao.INTENCAO_INTERACAO,
                origem=OrigemEvento.SISTEMA,
                payload={
                    "titulo": "Bateria Crítica",
                    "texto": f"Seu celular está com {bateria}%. Quer que eu ative o modo economia no PC também?",
                    "acao_tipo": "PC_COMMAND",
                    "acao_parametro": "modo_imersao", # Exemplo de economia
                    "acao_texto": "Bora"
                }
            ))

    async def _analisar_padroes_gerais(self):
        # ... mantida a lógica legada ...
        pass
