from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest


@pytest.mark.asyncio
async def test_ia_pc_pontual_nao_registra_no_banco(monkeypatch):
    from servicos.ponte_ia_pc import PonteIAPC, consumo_ia
    from api.websocket import central_alertas
    ponte = PonteIAPC(); ws = object()
    monkeypatch.setattr(ponte, 'cliente', lambda: ws)
    metricas = AsyncMock(side_effect=AssertionError('Abriu o banco'))
    monkeypatch.setattr(consumo_ia, 'registrar_local', metricas)
    async def enviar(cliente, msg):
        assert cliente is ws
        assert ponte.confirmar(ws, {'id': msg['id'], 'status': 'concluido', 'texto': '{"acoes":[]}'})
        return True
    monkeypatch.setattr(central_alertas, '_enviar_direto', enviar)
    assert await ponte.gerar('pedido', 'system', registrar_uso=False) == '{"acoes":[]}'
    metricas.assert_not_awaited()


@pytest.mark.asyncio
async def test_pc_falha_e_cloudflare_entra_sem_ledger_sql(monkeypatch):
    from servicos.cognicao_controles import CognicaoControles
    from servicos.ponte_ia_pc import ponte_ia_pc
    from servicos.cloudflare_ia import CloudflareProvider
    from servicos.cognicao_controles import OrcamentoVolatil
    from servicos import consumo_ia
    factory = AsyncMock(side_effect=AssertionError('Usou SQL'))
    monkeypatch.setattr(consumo_ia, 'AsyncSessionLocal', factory)
    monkeypatch.setattr(ponte_ia_pc, 'disponivel', lambda: True)
    pc = AsyncMock(side_effect=TimeoutError())
    monkeypatch.setattr(ponte_ia_pc, 'gerar', pc)
    chamadas = []
    def rede(req):
        chamadas.append(req)
        return httpx.Response(200, json={'success': True, 'result': {'response': '{"acoes":[]}', 'usage': {'prompt_tokens': 40, 'completion_tokens': 10}}})
    c = CognicaoControles()
    c.cloudflare = CloudflareProvider(client=httpx.MockTransport(rede), consumo=OrcamentoVolatil())
    c.cloudflare.account, c.cloudflare.token = 'a'*32, 'token-falso'
    assert await c.gerar({'pedido_usuario': 'teste'}, 'system') == {'acoes': []}
    assert pc.call_args.kwargs['registrar_uso'] is False
    assert len(chamadas) == 1
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_captura_correlacionada_nao_aceita_outro_app():
    from servicos.ponte_celular import PonteCelular
    p = PonteCelular()
    ws = SimpleNamespace(client_state=SimpleNamespace(value=1))
    async def enviar(cliente, msg):
        dados = {'pacote': 'com.outro', 'captura': 'a'*36, 'nodes': []}
        ack = {'id_comando': msg['id_comando'], 'acao': 'ui.snapshot', 'status': 'concluido', 'texto': 'Tela.', 'resultado': dados}
        assert not p.confirmar(ws, ack)
        dados['pacote'] = 'com.certo'
        assert p.confirmar(ws, ack)
        return True
    resultado = await p.executar(ws, enviar, 'ui.snapshot', {'pacote': 'com.certo'})
    assert resultado['resultado']['pacote'] == 'com.certo'
