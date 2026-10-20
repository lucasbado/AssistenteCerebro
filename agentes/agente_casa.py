"""A Ollie coordena a casa e confirma o resultado obtido pelo executor local."""
import logging
import asyncio

from core.tipos import CategoriaEvento, OrigemEvento, TipoAcao
from core.kernel import kernel
from servicos.controle_casa import controle_casa

logger = logging.getLogger(__name__)


class AgenteCasa:
    def __init__(self):
        self._locks = {}

    async def processar(self, evento):
        try:
            dispositivo = controle_casa.resolver(evento.payload.get("alvo", ""))
            acao = evento.payload.get("acao")
            if acao not in {"ligar", "desligar", "alternar", "consultar"}:
                raise ValueError("Ação de iluminação não reconhecida")
            from api.websocket import central_alertas
            async with self._locks.setdefault(dispositivo["entity_id"], asyncio.Lock()):
                resultado = await central_alertas.executar_casa(
                    evento.id, acao, dispositivo["entity_id"])
            if resultado.get("status") != "concluido":
                motivo = resultado.get("status")
                if motivo == "sem_ponte":
                    texto = "Preciso de uma conexão local com o Home Assistant. Abra a Ollie no PC ou configure o Home Assistant no celular."
                elif motivo == "sem_confirmacao":
                    texto = "Enviei o pedido, mas não recebi confirmação da luz. Não vou afirmar que ela mudou de estado."
                else:
                    texto = "Não consegui confirmar a ação no Home Assistant. Verifique a conexão local e a disponibilidade da luz."
            else:
                estado = resultado.get("resultado", {}).get("state")
                if estado not in {"on", "off"}:
                    texto = "O Home Assistant respondeu, mas não confirmou o estado da luz."
                else:
                    from servicos.consciencia import consciencia
                    consciencia.atualizar({"home_state": {dispositivo["entity_id"]: {
                        "friendly_name": dispositivo["nome"], "state": estado}}})
                    texto = f"A {dispositivo['nome']} está {'acesa' if estado == 'on' else 'apagada'}."
        except LookupError as e:
            texto = str(e)
        except (ValueError, OSError):
            texto = "Não consegui identificar a luz na configuração da casa."
        except Exception:
            logger.exception("Falha ao controlar a casa: %s", evento.id)
            texto = "A conexão com a casa falhou antes de confirmar o resultado."
        rotina = evento.metadados.get("rotina_aprovada")
        await kernel.publicar(evento.clonar(
            categoria=CategoriaEvento.INTENCAO_NOTIFICACAO,
            acao=TipoAcao.INTENCAO_INTERACAO, origem=OrigemEvento.IA,
            payload={"texto": texto, "titulo": rotina or "Ollie",
                     "tipo_ws": "NOTIFICACAO" if rotina else "CHAT_RESPONSE",
                     **({"chave_deduplicacao": f"rotina:{rotina}"} if rotina else {})},
            metadados={**evento.metadados, "tipo_destino": "NOTIFICACAO" if rotina else "CHAT"}))
