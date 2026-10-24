import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx
import pytest
from sqlalchemy import select, update
from banco.models import CacheIADB, UsoIADB
from servicos.consumo_ia import ConsumoIA, LimiteIA, uso_ia, escopo_ia
from servicos.cache_resumo_ia import resumo_cacheado
from servicos import triagem_notificacoes as triagem
from servicos.cloudflare_ia import CloudflareProvider, MODELO
from servicos.llm_providers import GroqProvider
from servicos.ponte_ia_pc import PonteIAPC
from tests.test_llm_providers import erro, resposta


async def test_reservas_concorrentes_compartilham_orcamento_e_preservam_pedidos(banco_teste, monkeypatch):
    monkeypatch.setenv('OLLIE_IA_AUTO_TOKENS_1H', '800')
    a, b = ConsumoIA(), ConsumoIA()
    async def automatico(servico):
        with uso_ia('notificacoes'):
            try: return await servico.reservar('modelo', 'oi', 'JSON', 200)
            except LimiteIA: return None
    resultados = await asyncio.gather(automatico(a), automatico(b), automatico(a))
    assert sum(r is not None for r in resultados) == 1
    with uso_ia('conversa', True):
        direto = await b.reservar('modelo', 'oi', 'JSON', 200)
    await b.concluir(direto, SimpleNamespace(prompt_tokens=21, completion_tokens=32))
    resumo = await a.resumo()
    assert resumo['tokens_automaticos'] == 458
    assert resumo['tokens_groq'] == 511
    assert {g['funcao'] for g in resumo['por_funcao']} == {'notificacoes', 'conversa'}
    assert escopo_ia.get() == ('interno', False)


async def test_janela_expira_e_falha_sem_confirmacao_conserva_estimativa(banco_teste, monkeypatch):
    c = ConsumoIA()
    with uso_ia('conversa', True):
        r = await c.reservar('modelo', 'oi', 'JSON', 200)
    await c.concluir(r)
    assert (await c.resumo())['tokens_groq'] > 0
    async with banco_teste() as s, s.begin():
        await s.execute(update(UsoIADB).values(criado_em=datetime.now(timezone.utc) - timedelta(hours=25)))
    assert (await ConsumoIA().resumo())['tokens_groq'] == 0


async def test_cooldown_429_e_compartilhado_entre_providers(banco_teste, monkeypatch):
    monkeypatch.setenv('GROQ_FALLBACK_MODELS', '')
    criar = AsyncMock(side_effect=erro(429, 'rate_limit_exceeded', 'Please try again in 11m19.968s.'))
    cliente = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=criar)))
    with uso_ia('conversa', True):
        with pytest.raises(Exception): await GroqProvider(client=cliente).gerar('oi', 'JSON', 20)
        with pytest.raises(LimiteIA): await GroqProvider(client=cliente).gerar('oi', 'JSON', 20)
    criar.assert_awaited_once()
    assert (await ConsumoIA().resumo())['tokens_groq'] == 0
    assert GroqProvider._tempo_espera(criar.side_effect) > 679


async def test_orcamento_negado_nao_chama_api(banco_teste, monkeypatch):
    monkeypatch.setenv('OLLIE_IA_TOKENS_24H', '0')
    criar = AsyncMock(return_value=resposta())
    provider = GroqProvider(client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=criar))))
    with uso_ia('conversa', True):
        with pytest.raises(LimiteIA): await provider.gerar('oi', 'JSON', 20)
    criar.assert_not_awaited()


async def test_cache_perfil_reusa_mudancas_pequenas_e_conserva_ultimo_resumo(banco_teste):
    gerar = AsyncMock(return_value={'resumo': 'Perfil útil', 'cards': []})
    assert (await resumo_cacheado('A', gerar))['resumo'] == 'Perfil útil'
    await resumo_cacheado('A', gerar)
    await resumo_cacheado('B', gerar)
    gerar.assert_awaited_once()
    async with banco_teste() as s, s.begin():
        await s.execute(update(CacheIADB).where(CacheIADB.chave == 'resumo_perfil').values(
            atualizado_em=datetime.now(timezone.utc) - timedelta(hours=2)))
    gerar.side_effect = RuntimeError('quota')
    assert (await resumo_cacheado('B', gerar))['resumo'] == 'Perfil útil'
    await resumo_cacheado('B', gerar)
    assert gerar.await_count == 2


async def test_cache_perfil_concorrente_so_gera_uma_vez(banco_teste):
    inicio, fim = asyncio.Event(), asyncio.Event()
    async def gerar():
        inicio.set(); await fim.wait()
        return {'resumo': 'Pronto', 'cards': []}
    task = asyncio.create_task(resumo_cacheado('perfil', gerar))
    await inicio.wait()
    assert 'preparado' in (await resumo_cacheado('perfil', gerar))['resumo']
    fim.set(); await task


@pytest.mark.parametrize('texto,esperado', [('Tudo certo.', False), ('sincronizando mensagens', False),
    ('Você vem amanhã?', True), ('Reunião amanhã às 15h', True), ('Tentativa de acesso bloqueada', True)])
def test_triagem_antes_da_ia(texto, esperado):
    assert triagem.relevante('com.whatsapp', 'Ana', texto) is esperado


async def test_notificacao_renovada_nao_gasta_de_novo_e_contatos_nao_se_misturam(banco_teste):
    a = await triagem.reservar('com.whatsapp', 'Ana', 'Bora conversar?')
    assert a
    assert await triagem.reservar('com.whatsapp', 'Ana', 'Bora conversar?') is None
    assert await triagem.reservar('com.whatsapp', 'Bia', 'Bora conversar?')
    await triagem.finalizar([a])
    async with banco_teste() as s:
        item = await s.get(CacheIADB, a)
        assert item.bloqueado_ate > datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=23)


async def test_revisao_resolvida_nao_reanalisa(banco_teste):
    from servicos.mensagens import caixa_mensagens
    texto = 'Você confirma a reunião amanhã?'
    item = await caixa_mensagens.registrar('com.whatsapp', {'titulo': 'Ana', 'texto': texto}, datetime.now(timezone.utc))
    await caixa_mensagens.mudar_estado(item['id'], 1, 'resolvida')
    assert await triagem.reservar('com.whatsapp', 'Ana', texto) is None


def cloudflare(monkeypatch, handler, consumo=None):
    monkeypatch.setenv('CLOUDFLARE_ACCOUNT_ID', 'a' * 32)
    monkeypatch.setenv('CLOUDFLARE_API_TOKEN', 'token-teste')
    return CloudflareProvider(client=httpx.MockTransport(handler), consumo=consumo)


async def test_cloudflare_usa_modelo_permitido_json_e_contabiliza_uso(banco_teste, monkeypatch):
    chamadas = []
    def handler(req):
        chamadas.append(req)
        return httpx.Response(200, json={'success': True, 'result': {'response': {'resposta': 'Pareidolia é ver rostos nas nuvens.'},
            'usage': {'prompt_tokens': 100, 'completion_tokens': 30}}})
    p = cloudflare(monkeypatch, handler)
    with uso_ia('conversa', True):
        assert 'Pareidolia' in await p.gerar('O que é pareidolia?', 'JSON', 900)
    assert chamadas[0].url.path.endswith(MODELO)
    assert json.loads(chamadas[0].content)['response_format'] == {'type': 'json_object'}
    resumo = await ConsumoIA().resumo()
    assert resumo['tokens_groq'] == 0
    assert resumo['por_funcao'][0]['tokens'] == 130


async def test_cloudflare_nao_consume_fallback_com_analises_automaticas(banco_teste, monkeypatch):
    chamada = []
    p = cloudflare(monkeypatch, lambda req: chamada.append(req))
    with uso_ia('notificacoes'):
        with pytest.raises(LimiteIA): await p.gerar('terceiros', 'JSON')
    assert chamada == []


async def test_cloudflare_quota_nao_repete_chamada_em_outro_provider(banco_teste, monkeypatch):
    chamadas = []
    def handler(req):
        chamadas.append(req)
        return httpx.Response(429, headers={'Retry-After': '600'}, json={'success': False})
    p = cloudflare(monkeypatch, handler)
    with uso_ia('conversa', True):
        with pytest.raises(httpx.HTTPStatusError): await p.gerar('oi', 'JSON')
        with pytest.raises(LimiteIA): await cloudflare(monkeypatch, handler).gerar('oi', 'JSON')
    assert len(chamadas) == 1


async def test_cadeia_pedidos_diretos_e_background_nao_usa_pc(monkeypatch):
    from servicos.llm import ServicoLLM
    s = object.__new__(ServicoLLM)
    a = SimpleNamespace(gerar=AsyncMock(side_effect=RuntimeError('429')), disponivel=lambda: True)
    b = SimpleNamespace(gerar=AsyncMock(side_effect=RuntimeError('429')), disponivel=lambda: True)
    c = SimpleNamespace(gerar=AsyncMock(return_value='{"resposta":"Tudo certo"}'), disponivel=lambda: True)
    s._pick_provider = lambda: a
    s.cloudflare, s.pc, s.ollama = b, c, SimpleNamespace(disponivel=lambda: False)
    assert 'Tudo certo' in await s._gerar('oi', 'JSON', solicitado=True)
    a.gerar.assert_awaited_once(); b.gerar.assert_awaited_once(); c.gerar.assert_awaited_once()
    with pytest.raises(RuntimeError): await s._gerar('terceiros', 'JSON', solicitado=False)
    assert b.gerar.await_count == c.gerar.await_count == 1


async def test_broker_so_aceita_resposta_do_socket_original_e_desconecta(banco_teste, monkeypatch):
    import api.websocket as wsmod
    class WS:
        client_state = SimpleNamespace(value=1)
        def __init__(self): self.sent = asyncio.Queue()
        async def send_text(self, text): await self.sent.put(json.loads(text))
    pc, impostor = WS(), WS()
    central = wsmod.GerenciadorNotificacoes()
    central.pc_master = pc; central._capacidades[pc] = {'LOCAL_LLM'}
    monkeypatch.setattr(wsmod, 'central_alertas', central)
    ponte = PonteIAPC()
    tarefa = asyncio.create_task(ponte.gerar('pergunta', 'JSON'))
    request = await pc.sent.get()
    response = dict(id=request['id'], status='concluido', texto='{"resposta":"Olá"}', modelo='teste', entrada=10, saida=5)
    assert not ponte.confirmar(impostor, response)
    assert not tarefa.done()
    assert ponte.confirmar(pc, response)
    assert not ponte.confirmar(pc, response)
    assert 'Olá' in await tarefa
    tarefa = asyncio.create_task(ponte.gerar('outra pergunta', 'JSON'))
    await pc.sent.get()
    ponte.desconectar(pc)
    with pytest.raises(ValueError): await tarefa
    assert ponte.pendentes == {}


async def test_broker_timeout_remove_pendente(monkeypatch):
    import api.websocket as wsmod
    pc = object()
    monkeypatch.setattr(wsmod.central_alertas, '_enviar_direto', AsyncMock(return_value=True))
    p = PonteIAPC(); monkeypatch.setattr(p, 'cliente', lambda: pc)
    with pytest.raises(asyncio.TimeoutError): await p.gerar('oi', 'JSON', timeout=.01)
    assert not p.pendentes


async def test_endpoint_consumo_requer_autenticacao_e_nao_expoe_textos(banco_teste):
    from fastapi import FastAPI
    from api.auth import AuthMiddleware
    from api.ia import router
    app = FastAPI(); app.add_middleware(AuthMiddleware); app.include_router(router, prefix='/ia')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://teste') as c:
        assert (await c.get('/ia/consumo')).status_code == 401
        r = await c.get('/ia/consumo', headers={'Authorization': 'Bearer token-de-teste'})
        assert r.status_code == 200 and r.json()['tokens_groq'] == 0
        assert 'token-de-teste' not in r.text and 'prompt' not in r.text
