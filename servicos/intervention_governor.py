import logging

logger = logging.getLogger("InterventionGovernor")

class InterventionGovernor:
    def __init__(self):
        # Por padrão, auto-open começa desativado para respeitar a governança do usuário
        self.policy = {
            "auto_open_enabled": False,
            "min_priority_score": 0.85,
            "whitelist": ["whatsapp", "telegram", "vscode"],
            "blacklist": ["jogo", "netflix", "youtube"]
        }

    def atualizar_politica(self, nova_politica: dict) -> dict:
        self.policy.update(nova_politica)
        logger.info(f"🛡️ [Governor] Política de intervenção atualizada: {self.policy}")
        return self.policy

    def permitir_abertura_automatica(self, alvo: str) -> bool:
        if not self.policy.get("auto_open_enabled", False):
            logger.warning(f"🛡️ [Governor] Abertura automática/proativa de '{alvo}' bloqueada (Auto-Open desativado nas configurações).")
            return False
        
        alvo_lower = str(alvo).lower()
        for item in self.policy.get("blacklist", []):
            if item in alvo_lower:
                logger.warning(f"🛡️ [Governor] Abertura de '{alvo}' bloqueada por estar na Blacklist.")
                return False
                
        return True

intervention_governor = InterventionGovernor()
