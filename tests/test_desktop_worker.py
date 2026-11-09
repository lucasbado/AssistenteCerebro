import json
from types import SimpleNamespace

from tools.wakeword.desktop_worker import Conversation, ESPERA_INICIAL, ESPERA_CONTINUACAO, PAUSA_FINAL, MAXIMO_FALA

SILENCIO = bytes(2560)
FALA = b'\xe8\x03' * 1280


class Detector:
    def __init__(self):
        self.calls = self.resets = 0
    def reset(self):
        self.resets += 1
    def predict(self, audio):
        self.calls += 1
        return {'hey_ollie': .9}


def recognizer(text='como esta a luz do quarto'):
    return SimpleNamespace(AcceptWaveform=lambda pcm: pcm == b'final',
                           Result=lambda: json.dumps({'text': text}),
                           PartialResult=lambda: json.dumps({'partial': ''}),
                           FinalResult=lambda: json.dumps({'text': ''}))


def test_wake_exige_duas_janelas_e_comando_e_emitido_uma_unica_vez():
    events, detector = [], Detector()
    session = Conversation(detector, recognizer, events.append)
    session.resume(-2)
    session.process(bytes(2560), 0)
    assert session.state == 'wake'
    session.process(bytes(2560), .08)
    assert session.state == 'listening'
    session.process(b'final', .16)
    assert session.state == 'listening'
    session.process(SILENCIO, .16 + PAUSA_FINAL + .1)
    assert session.state == 'thinking'
    for time in (1, 2, 3):
        session.process(b'final', time)
    assert [e for e in events if e['type'] == 'transcript'] == [
        {'type': 'transcript', 'text': 'como esta a luz do quarto'}]
    assert detector.calls == 2


def test_pausa_bloqueia_detector_e_stt_e_resume_descarta_audio_antigo():
    events, detector = [], Detector()
    session = Conversation(detector, recognizer, events.append)
    session.listen(0)
    session.process(b'parcial', .1)
    session.pause()
    session.process(b'final', 1)
    assert not any(e['type'] == 'transcript' for e in events)
    assert detector.calls == 0
    session.resume(2)
    session.process(bytes(2560), 2.9)
    assert detector.calls == 0
    session.process(bytes(2560), 3)
    assert session.state == 'wake'
    session.process(bytes(2560), 3.08)
    assert session.state == 'listening'


def test_silencio_tem_timeout_e_nao_vira_comando_vazio():
    events = []
    rec = recognizer('')
    rec.PartialResult = lambda: '{"partial":""}'
    session = Conversation(Detector(), lambda: rec, events.append, transcriber=lambda _: '')
    session.listen(0)
    session.process(SILENCIO, 12)
    assert session.state == 'listening'
    session.process(SILENCIO, ESPERA_INICIAL)
    assert session.state == 'thinking'
    assert session.pending_audio is None
    assert not any(e['type'] == 'transcript' for e in events)
    assert len([e for e in events if e['type'] == 'no_speech']) == 1


def test_pausa_no_meio_e_comando_acima_de_12s_preservam_os_trechos():
    events, instances = [], []
    def factory():
        value = recognizer()
        value.PartialResult = lambda: '{"partial":""}'
        value.FinalResult = lambda: '{"text":"e depois desligue a luz"}'
        instances.append(value)
        return value
    session = Conversation(Detector(), factory, events.append)
    session.listen(0)
    session.process(FALA, 10)
    session.process(b'final', 11)
    session.process(SILENCIO, 12)
    assert session.state == 'listening'
    session.process(FALA, 13)
    session.process(SILENCIO, 13 + PAUSA_FINAL + .1)
    assert [e['text'] for e in events if e['type'] == 'transcript'] == [
        'como esta a luz do quarto e depois desligue a luz']
    session.resume(18)
    session.listen(20, followup=True)
    assert len(instances) == 2
    assert session.recognizer is instances[1]
    session.process(SILENCIO, 20 + ESPERA_CONTINUACAO)
    assert events[-1]['type'] == 'no_speech' and events[-1]['followup'] is True


def test_ruido_continuo_respeita_teto_de_captura():
    events = []
    session = Conversation(Detector(), recognizer, events.append, transcriber=lambda _: '')
    session.listen(0)
    for tempo in range(MAXIMO_FALA + 1):
        session.process(FALA, tempo)
    assert session.state == 'thinking' and session.pending_audio
