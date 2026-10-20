"""Contrato e orçamento de interrupções, independentes do transporte WebSocket."""
import time
from collections import deque


class PoliticaNotificacoes:
    def __init__(self, relogio=time.monotonic):
        self._relogio = relogio
        self._ultimas = {}
        self._envios = deque()

    def preparar(self, evento):
        payload = dict(evento.payload)
        conteudo = payload.get("conteudo") or {}
        if not isinstance(conteudo, dict):
            conteudo = {}
        texto = payload.get("texto") or payload.get("mensagem") or conteudo.get("text")
        if not isinstance(texto, str) or not texto.strip():
            return None, "conteudo_vazio"
        payload["texto"] = texto.strip()
        payload["titulo"] = payload.get("titulo") or conteudo.get("title") or "Ollie"
        chat = payload.get("tipo_ws") == "CHAT_RESPONSE" or evento.metadados.get("tipo_destino") == "CHAT"
        payload["tipo_ws"] = "CHAT_RESPONSE" if chat else "NOTIFICACAO"
        if chat:
            return payload, "resposta_solicitada"
        if evento.metadados.get("atencao", {}).get("pode_interagir") is False:
            return None, "interacao_desabilitada"
        agora = self._relogio()
        self._ultimas = {chave: ts for chave, ts in self._ultimas.items() if agora - ts < 3600}
        while self._envios and agora - self._envios[0] >= 3600:
            self._envios.popleft()
        chave = str(payload.get("chave_deduplicacao") or
                    (payload["titulo"], payload.get("acao_tipo"), payload.get("acao_parametro"), payload["texto"]))
        if chave in self._ultimas:
            return None, "repetida_na_ultima_hora"
        urgente = str(payload.get("urgencia", "")).upper() == "ALTA"
        if not urgente and (len(self._envios) >= 3 or
                            (self._envios and agora - self._envios[-1] < 600)):
            return None, "orcamento_de_interrupcoes"
        self._ultimas[chave] = agora
        self._envios.append(agora)
        return payload, "aprovada"
