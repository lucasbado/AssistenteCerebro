from unittest.mock import Mock
import asyncio
import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
import api.voice as modulo


@pytest.mark.parametrize('nome,esperado', [(None, 'pt-BR-ThalitaMultilingualNeural'),
    ('pt-BR-ThalitaNeural', 'pt-BR-ThalitaMultilingualNeural'),
    ('pt-BR-FranciscaNeural', 'pt-BR-FranciscaNeural'), ('pt-BR-AntonioNeural', 'pt-BR-AntonioNeural')])
async def test_voz_escolhida_velocidade_e_tom_chegam_ao_sintetizador(monkeypatch, nome, esperado):
    async def stream():
        yield {'type': 'audio', 'data': b'audio-amostra'}
    comunicar = Mock(return_value=Mock(stream=stream))
    monkeypatch.setattr(modulo.edge_tts, 'Communicate', comunicar)
    app = FastAPI(); app.include_router(modulo.router)
    params = {'text': 'Oi! Eu sou a Ollie.', 'rate': 1.2, 'pitch': .9}
    if nome: params['voice'] = nome
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://teste') as client:
        r = await client.get('/speak', params=params)
    assert r.status_code == 200 and r.content == b'audio-amostra'
    assert r.headers['content-type'].startswith('audio/mpeg')
    comunicar.assert_called_once_with('Oi! Eu sou a Ollie.', esperado, rate='+20%', pitch='-10Hz')


async def test_falha_na_voz_nao_retorna_audio_de_outra_voz(monkeypatch):
    monkeypatch.setattr(modulo.edge_tts, 'Communicate', Mock(side_effect=ValueError('Voz indisponível')))
    app = FastAPI(); app.include_router(modulo.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://teste') as client:
        r = await client.get('/speak', params={'text': 'Amostra', 'voice': 'indisponivel'})
    assert r.status_code == 500 and r.headers['content-type'].startswith('application/json')


async def test_sintese_prepara_pausas_e_preserva_os_dados_da_resposta(monkeypatch):
    async def stream():
        yield {'type': 'audio', 'data': b'mp3'}

    comunicar = Mock(return_value=Mock(stream=stream))
    monkeypatch.setattr(modulo.edge_tts, 'Communicate', comunicar)
    app = FastAPI()
    app.include_router(modulo.router)
    texto = '## Estado do PC\n- **CPU**: 23%\n- Temperatura: 42°C\n[Ver detalhes](https://example.com/detalhes)'
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://teste') as client:
        resposta = await client.post('/speak', json={'text': texto})
    assert resposta.content == b'mp3'
    assert resposta.headers['Cache-Control'] == 'no-store'
    comunicar.assert_called_once_with(
        'Estado do PC. CPU: 23 por cento. Temperatura: 42 graus Celsius. Ver detalhes',
        modulo.DEFAULT_VOICE, rate='+0%', pitch='+0Hz')


async def test_stream_libera_o_primeiro_bloco_e_fecha_o_provedor_ao_cancelar(monkeypatch):
    libera = asyncio.Event()
    fechou = asyncio.Event()

    async def stream():
        try:
            yield {'type': 'SentenceBoundary', 'data': b'ignorar'}
            yield {'type': 'audio', 'data': b'primeiro'}
            await libera.wait()
            yield {'type': 'audio', 'data': b'ultimo'}
        finally:
            fechou.set()

    monkeypatch.setattr(modulo.edge_tts, 'Communicate', Mock(return_value=Mock(stream=stream)))
    async with asyncio.timeout(1):
        resposta = await modulo.sintetizar(modulo.PedidoDeVoz(text='Oi', stream=True))
        assert await anext(resposta.body_iterator) == b'primeiro'
        assert not fechou.is_set()
        await resposta.body_iterator.aclose()
        assert fechou.is_set()
