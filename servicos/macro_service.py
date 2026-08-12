import json
import os
import logging
from typing import List, Dict

logger = logging.getLogger("MacroService")

class MacroService:
    def __init__(self):
        self.config_path = "D:/Programacao/AssistenteCell/config/macros.json"
        self._carregar_macros()

    def _carregar_macros(self):
        if not os.path.exists(os.path.dirname(self.config_path)):
            os.makedirs(os.path.dirname(self.config_path))
        
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    self.macros = json.load(f)
            except Exception as e:
                logger.error(f"Erro ao carregar macros: {e}")
                self.macros = {}
        else:
            self.macros = {
                "modo_imersao": [
                    {"alvo": "PC", "comando": "mutar_mic", "parametro": ""},
                    {"alvo": "PC", "comando": "executar_macro", "parametro": "win_d"}
                ]
            }
            self.salvar_macros()

    def salvar_macros(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.macros, f, indent=4)
        except Exception as e:
            logger.error(f"Erro ao salvar macros: {e}")

    def criar_macro(self, nome: str, comandos: List[Dict]):
        """Cria ou atualiza uma macro."""
        safe_name = nome.lower().strip().replace(" ", "_")
        self.macros[safe_name] = comandos
        self.salvar_macros()
        return safe_name

    def obter_macros(self) -> Dict:
        return self.macros

    async def executar_macro(self, nome: str, kernel):
        """Executa a sequência de comandos da macro via kernel."""
        safe_name = nome.lower().strip().replace(" ", "_")
        if safe_name not in self.macros:
            logger.warning(f"Macro '{nome}' não encontrada.")
            return False

        logger.info(f"🚀 Executando Macro: {nome}")
        comandos = self.macros[safe_name]
        
        for cmd_data in comandos:
            from core.evento import EventoCanonico
            from core.tipos import CategoriaEvento, TipoAcao, OrigemEvento
            
            alvo = cmd_data.get("alvo", "PC")
            comando = cmd_data.get("comando")
            param = cmd_data.get("parametro", "")

            # Converte macro em eventos para o AgentePcExecutor
            payload = {"comando": comando}
            if alvo == "PC":
                if comando == "abrir_app": payload["app"] = param
                elif comando == "executar_macro": payload["macro"] = param
                elif comando == "abrir_url": payload["url"] = param
                
                await kernel.publicar(EventoCanonico(
                    categoria=CategoriaEvento.SISTEMA_COMANDO_PC,
                    acao=TipoAcao.NORMAL,
                    origem=OrigemEvento.IA,
                    payload=payload
                ))
            # Adicionar MOBILE se necessário
        
        return True

macro_service = MacroService()
