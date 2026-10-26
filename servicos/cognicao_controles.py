"""Interpretação de pedidos diretos sem depender da memória persistente."""
import asyncio
import json
import time
import uuid
from collections import deque

from servicos.cloudflare_ia import CloudflareProvider
from servicos.consumo_ia import LimiteIA


class OrcamentoVolatil:
    def __init__(self, relogio=time.monotonic):
        self.relogio = relogio
        self.registros = {}
        self.bloqueios = {}
        self.lock = asyncio.Lock()

    async def reservar(self, modelo, prompt, system, max_tokens, provider='cloudflare'):
        async with self.lock:
            now = self.relogio()
            self.registros = {k: v for k, v in self.registros.items() if now - v[0] < 86400}
            if self.bloqueios.get(modelo, 0) > now:
                raise LimiteIA('Interpretação em espera após limite do provedor.')
            tokens = (len(prompt.encode()) + len(system.encode())) // 3 + max_tokens + 256
            if len(self.registros) >= 300 or sum(v[1] for v in self.registros.values()) + tokens > 40000:
                raise LimiteIA('Limite da interpretação temporária atingido.')
            if sum(1 for v in self.registros.values() if now - v[0] < 60) >= 6:
                raise LimiteIA('Muitos pedidos de interpretação neste minuto.')
            ident = str(uuid.uuid4())
            self.registros[ident] = (now, tokens)
            return ident

    async def concluir(self, identificador, usage=None, recusado=False):
        # Conservador: mantém a reserva mesmo se a rede falhar; nunca perde o orçamento em retentativas.
        pass

    async def bloquear(self, modelo, segundos, provider='cloudflare'):
        self.bloqueios[modelo] = self.relogio() + segundos


class CognicaoControles:
    def __init__(self):
        self.cloudflare = CloudflareProvider(consumo=OrcamentoVolatil())
        self.lock = asyncio.Lock()
        self.ultimos = deque(maxlen=6)

    async def gerar(self, dados, instrucoes):
        from servicos.ponte_ia_pc import ponte_ia_pc
        if self.lock.locked():
            raise ValueError('Estou interpretando outro pedido. Tente novamente em instantes.')
        async with self.lock:
            now = time.monotonic()
            if len(self.ultimos) == 6 and now - self.ultimos[0] < 60:
                raise LimiteIA('Vamos dar um instante entre os pedidos.')
            self.ultimos.append(now)
            prompt = json.dumps(dados, ensure_ascii=False)
            if len(prompt) + len(instrucoes) > 24000:
                raise ValueError('Esse contexto ficou muito grande para interpretar.')
            if ponte_ia_pc.disponivel():
                try:
                    resposta = await ponte_ia_pc.gerar(prompt, instrucoes, max_tokens=450, timeout=14, registrar_uso=False)
                    return self._json(resposta)
                except (ValueError, asyncio.TimeoutError):
                    pass
            if self.cloudflare.disponivel():
                resposta = await asyncio.wait_for(self.cloudflare.gerar(prompt, instrucoes, max_tokens=450), timeout=12)
                return self._json(resposta)
            raise ValueError('A interpretação está sem conexão com a IA do PC e com a alternativa remota.')

    @staticmethod
    def _json(raw):
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            raise ValueError('A interpretação não retornou um plano válido.')
        return obj


cognicao_controles = CognicaoControles()
