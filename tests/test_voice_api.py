from unittest.mock import AsyncMock, Mock
import asyncio
import base64
import json
from io import BytesIO
import wave
import httpx
import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
import api.voice as modulo
from servicos.gemini_tts import GeminiTTSService


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


async def test_voz_gemini_envia_chave_so_no_header_e_retorna_wav(monkeypatch):
    pcm = b'\x12\x00\x28\x00' * 120
    def responder(request):
        assert request.url.path.endswith('/gemini-2.5-flash-preview-tts:generateContent')
        assert not request.url.query and 'authorization' not in request.headers
        assert request.headers['x-goog-api-key'] == 'AQ-chave-ficticia'
        config = json.loads(request.content)['generationConfig']
        assert config['responseModalities'] == ['AUDIO'] and 'responseMimeType' not in config
        assert config['speechConfig']['voiceConfig']['prebuiltVoiceConfig']['voiceName'] == 'Kore'
        return httpx.Response(200, json={'candidates': [{'content': {'parts': [{'inlineData': {
            'mimeType': 'audio/L16;codec=pcm;rate=24000', 'data': base64.b64encode(pcm).decode(),
        }}]}}]})
    service = GeminiTTSService('AQ-chave-ficticia', httpx.MockTransport(responder))
    monkeypatch.setattr(modulo, 'gemini_tts_service', service)
    resposta = await modulo.sintetizar(modulo.PedidoDeVoz(text='Oi', voice='Kore', provider='auto'))
    assert resposta.media_type == 'audio/wav' and resposta.headers['X-Voice-Provider'] == 'gemini'
    with wave.open(BytesIO(resposta.body)) as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 24000)
        assert wav.readframes(wav.getnframes()) == pcm


async def test_voz_continua_com_falha_multilinha_sem_expor_chave(monkeypatch):
    falha = AsyncMock(side_effect=ValueError('Erro\r\nhttps://exemplo.test/?key=chave-ficticia'))
    monkeypatch.setattr(modulo.gemini_tts_service, 'sintetizar', falha)

    async def stream():
        yield {'type': 'audio', 'data': b'mp3'}

    monkeypatch.setattr(modulo.edge_tts, 'Communicate', Mock(return_value=Mock(stream=stream)))
    app = FastAPI(); app.include_router(modulo.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://teste') as client:
        auto = await client.post('/speak', json={'text': 'Oi', 'voice': 'Kore', 'provider': 'auto', 'stream': True})
        explicito = await client.post('/speak', json={'text': 'Oi', 'voice': 'Kore', 'provider': 'gemini'})
    assert auto.status_code == 200 and auto.content == b'mp3'
    assert auto.headers['X-Voice-Used'] == 'pt-BR-ThalitaMultilingualNeural'
    assert auto.headers['X-Voice-Fallback'] == 'true'
    assert explicito.status_code == 503 and 'chave-ficticia' not in explicito.text
    assert auto.headers['X-Gemini-Error'] == explicito.headers['X-Gemini-Error'] == 'synthesis_failed'


async def test_gemini_respeita_espera_apos_429_sem_requisitar_de_novo(monkeypatch):
    handler = Mock(return_value=httpx.Response(429, headers={'Retry-After': '60'}))
    service = GeminiTTSService('chave-ficticia', httpx.MockTransport(handler), relogio=lambda: 100)
    monkeypatch.setattr(modulo, 'gemini_tts_service', service)
    app = FastAPI(); app.include_router(modulo.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://teste') as client:
        for _ in range(2):
            r = await client.post('/speak', json={'text': 'Oi', 'provider': 'gemini'})
            assert r.status_code == 503 and r.headers['X-Gemini-Error'] == 'rate_limited'
        assert (await client.get('/diagnostic')).json()['gemini_test_error'] == 'rate_limited'
    assert handler.call_count == 1
