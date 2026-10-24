"""Workers AI pela API oficial. Um único modelo gratuito permitido, sem upgrade automático."""
import json
import os
import re
from types import SimpleNamespace
import httpx
from servicos.consumo_ia import consumo_ia

MODELO = '@cf/meta/llama-3.1-8b-instruct'


class CloudflareProvider:
    def __init__(self, client=None, consumo=None):
        self.account = os.getenv('CLOUDFLARE_ACCOUNT_ID', '').strip()
        self.token = os.getenv('CLOUDFLARE_API_TOKEN', '').strip()
        self.client = client
        self.consumo = consumo if consumo is not None else consumo_ia

    def disponivel(self):
        return bool(re.fullmatch(r'[a-fA-F0-9]{32}', self.account) and self.token)

    async def gerar(self, prompt, system, max_tokens=900):
        if not self.disponivel(): raise ValueError('Cloudflare Workers AI não configurado.')
        max_tokens = min(max_tokens, 1200)
        system += '\nRetorne somente um objeto JSON válido.'
        reserva = await self.consumo.reservar(MODELO, prompt, system, max_tokens, provider='cloudflare')
        try:
            async with httpx.AsyncClient(timeout=20, transport=self.client) as client:
                resp = await client.post(f'https://api.cloudflare.com/client/v4/accounts/{self.account}/ai/run/{MODELO}',
                    headers={'Authorization': 'Bearer ' + self.token},
                    json=dict(messages=[dict(role='system', content=system), dict(role='user', content=prompt)],
                        max_tokens=max_tokens, temperature=0.1, stream=False, response_format={'type': 'json_object'}))
            resp.raise_for_status()
            body = resp.json()
            if body.get('success') is not True: raise ValueError('Workers AI recusou a solicitação.')
            result = body.get('result', {})
            usage = result.get('usage', {})
            await self.consumo.concluir(reserva, SimpleNamespace(prompt_tokens=usage.get('prompt_tokens'), completion_tokens=usage.get('completion_tokens')))
            reserva = None
            resposta = result.get('response')
            texto = json.dumps(resposta, ensure_ascii=False) if isinstance(resposta, dict) else resposta
            if not isinstance(texto, str) or not isinstance(json.loads(texto), dict):
                raise ValueError('Workers AI devolveu resposta inválida.')
            return texto
        except Exception as erro:
            status = getattr(getattr(erro, 'response', None), 'status_code', None)
            if reserva is not None: await self.consumo.concluir(reserva, recusado=status in {401, 403, 404, 429})
            if status in {401, 403, 429}:
                # Não insistir na cota esgotada ou credencial inválida a cada pergunta.
                segundos = 60
                if status == 429:
                    try: segundos = max(60, min(86400, float(erro.response.headers.get('retry-after', '60'))))
                    except ValueError: pass
                await self.consumo.bloquear(MODELO, segundos, provider='cloudflare')
            raise
