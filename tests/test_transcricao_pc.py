import json
import threading
from types import SimpleNamespace

import pytest

from tools.wakeword.desktop_worker import Conversation
from tools.wakeword.transcricao import clean_text, TranscriptionJobs, LocalTranscriber, load_transcriber
from tests.test_desktop_worker import Detector, recognizer


def test_buffer_inclui_a_janela_que_disparou_e_nao_espera_proximo_inicio():
    events, primed = [], []
    def factory():
        rec = recognizer('')
        rec.AcceptWaveform = lambda pcm: primed.append(pcm) or pcm == b'final'
        return rec
    class DelayedDetector(Detector):
        def predict(self, audio):
            self.calls += 1
            return {'hey_ollie': .1 if self.calls == 1 else .9}
    session = Conversation(DelayedDetector(), factory, events.append, transcriber=lambda _: '')
    session.resume(-2)
    first, triggering = bytes(2560), bytes([1, 0]) * 1280
    session.process(bytes([2, 0]) * 1280, 0)
    session.process(first, .08)
    session.process(triggering, .16)
    assert primed == [first + triggering]
    session.process(b'final', .24)  # Vosk encerra mesmo sem reconhecer as palavras estrangeiras.
    revision, audio = session.pending_audio
    assert audio == first + triggering + b'final'
    assert not any(e['type'] == 'transcript' for e in events)
    session.complete(revision, 'Abra WhatsApp no PC')
    assert [e['text'] for e in events if e['type'] == 'transcript'] == ['Abra WhatsApp no PC']
    session.complete(revision, 'duplicado')
    assert len([e for e in events if e['type'] == 'transcript']) == 1


@pytest.mark.parametrize('action', ['pause', 'resume', 'listen'])
def test_cancelamento_ignora_resultado_de_reconhecimento_anterior(action):
    events = []
    session = Conversation(Detector(), recognizer, events.append, transcriber=lambda _: '')
    session.listen(0)
    session.process(b'final', 1)
    revision, _ = session.pending_audio
    getattr(session, action)(*[2] if action != 'pause' else [])
    session.complete(revision, 'ligue a luz do quarto')
    assert not any(e['type'] == 'transcript' for e in events)
    assert session.pending_audio is None
    assert not session.audio


def test_inferencia_lenta_nao_bloqueia_o_controle_e_preserva_negacao():
    started, release = threading.Event(), threading.Event()
    def decode(pcm):
        started.set()
        assert release.wait(2)
        return 'Não ligue a luz'
    jobs = TranscriptionJobs(decode)
    jobs.submit(3, b'audio')
    try:
        assert started.wait(2)
        assert list(jobs.poll()) == []
        jobs.submit(4, b'antigo')
        jobs.submit(5, b'novo')  # Um unico pedido aguardando, sem fila ilimitada.
        assert jobs.pending.qsize() == 1
    finally:
        release.set()
    revision, text, failed = jobs.results.get(timeout=2)
    assert (revision, text, failed) == (3, 'Não ligue a luz', False)


@pytest.mark.parametrize('raw,expected', [
    ('Ei Ollie, ligue a luz.', 'ligue a luz.'),
    ('Não ligue a luz.', 'Não ligue a luz.'),
    ('Ollie, não abra WhatsApp.', 'não abra WhatsApp.'),
    ('Abre Valorant PC.', 'Abre Valorant no PC.'),
    ('Abre WhatsApp no PC.', 'Abre WhatsApp no PC.'),
    ('Abre YouTube celular', 'Abre YouTube no celular'),
    ('Abre YouTube PC ou celular', 'Abre YouTube PC ou celular'),
    ('O Valorant PC está aberto?', 'O Valorant PC está aberto?'),
])
def test_normalizacao_nao_inventa_intencao_e_respeita_destino(raw, expected):
    assert clean_text(raw) == expected


def test_whisper_recebe_audio_inteiro_e_vocabulario_aberto():
    import numpy as np
    calls = []
    decoder = LocalTranscriber.__new__(LocalTranscriber)
    def transcribe(audio, **kwargs):
        calls.append((audio, kwargs))
        return iter([SimpleNamespace(text='Não ligue a luz do quarto.')]), None
    decoder.model = SimpleNamespace(transcribe=transcribe)
    audio = np.array([1, -2, 1234, -5678], dtype='<i2')
    assert decoder(audio.tobytes()) == 'Não ligue a luz do quarto.'
    np.testing.assert_allclose(calls[0][0], audio.astype('float32') / 32768)
    assert calls[0][1]['vad_parameters']['speech_pad_ms'] == 300
    assert calls[0][1]['condition_on_previous_text'] is False
    assert 'Valorant' in calls[0][1]['hotwords']


def test_preparo_nao_exige_whisper_em_instalacoes_antigas(tmp_path):
    assert load_transcriber(tmp_path) is None
    (tmp_path / 'desktop-speech.json').write_text(json.dumps({'engine': 'faster-whisper'}))
    with pytest.raises(ValueError, match='ausente'):
        load_transcriber(tmp_path)
