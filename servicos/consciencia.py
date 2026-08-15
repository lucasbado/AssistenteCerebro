import logging
from typing import Any

logger = logging.getLogger(__name__)

class ConscienciaSituacional:
    """
    Gerencia o estado global do ambiente (Casa, PC, Dispositivos)
    para fornecer contexto imediato à IA.
    """
    def __init__(self):
        self._snapshot = {
            "home_state": {},
            "pc_state": {},
            "device_state": {},
            "timestamp": None
        }

    def atualizar(self, data: dict[str, Any]):
        if "home_state" in data and data["home_state"]:
            self._snapshot["home_state"].update(data["home_state"])
        
        if "pc_state" in data and data["pc_state"]:
            self._snapshot["pc_state"].update(data["pc_state"])
            
        if "device_state" in data and data["device_state"]:
            self._snapshot["device_state"].update(data["device_state"])
            
        self._snapshot["timestamp"] = data.get("timestamp")
        logger.info("🧠 [Consciência] Estado situacional atualizado.")

    def obter_resumo_para_llm(self) -> str:
        """Gera uma string amigável para o prompt da IA."""
        resumo = []
        
        # Luzes
        luzes = self._snapshot.get("home_state", {})
        if luzes:
            resumo.append("### AMBIENTE (CASA):")
            for eid, info in luzes.items():
                nome = info.get("friendly_name", eid)
                estado = "ligada" if info.get("state") == "on" else "desligada"
                brilho = info.get("brightness")
                txt = f"- {nome}: {estado}"
                if brilho:
                    percent = int((brilho / 255) * 100)
                    txt += f" ({percent}% de brilho)"
                resumo.append(txt)

        # PC
        pc = self._snapshot.get("pc_state", {})
        if pc:
            resumo.append("### PC MASTER:")
            status = "Online" if pc.get("is_online") else "Offline"
            resumo.append(f"- Status: {status}")
            if pc.get("is_online"):
                resumo.append(f"- CPU: {pc.get('cpu')}% | RAM: {pc.get('ram')}%")
                apps = pc.get("apps_disponiveis", [])
                if apps:
                    resumo.append(f"- Apps/Jogos Prontos: {', '.join(apps)}")

        if not resumo:
            return "Ambiente atual: Desconhecido (Sem sensores)."

        return "\n".join(resumo)

# Instância única global
consciencia = ConscienciaSituacional()
