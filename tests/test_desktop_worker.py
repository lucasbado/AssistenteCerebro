import json
from types import SimpleNamespace

from tools.wakeword.desktop_worker import Conversation


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
                           PartialResult=lambda: json.dumps({'partial': 'como esta'}),
                           FinalResult=lambda: json.dumps({'text': text}))


def test_wake_exige_duas_janelas_e_comando_e_emitido_uma_unica_vez():
    events, detector = [], Detector()
    session = Conversation(detector, recognizer, events.append)
    session.resume(-2)
    session.process(bytes(2560), 0)
    assert session.state == 'wake'
    session.process(bytes(2560), .08)
    assert session.state == 'listening'
    session.process(b'final', .16)
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
    session = Conversation(Detector(), lambda: recognizer(''), events.append)
    session.listen(0)
    session.process(b'parcial', 12)
    assert session.state == 'thinking'
    assert not any(e['type'] == 'transcript' for e in events)
    assert len([e for e in events if e['type'] == 'no_speech']) == 1


def test_timeout_finaliza_fala_parcial_e_nova_sessao_recebe_novo_reconhecedor():
    events, instances = [], []
    def factory():
        value = recognizer()
        instances.append(value)
        return value
    session = Conversation(Detector(), factory, events.append)
    session.listen(0)
    session.process(b'parcial', 12)
    assert any(e['type'] == 'transcript' for e in events)
    session.resume(13)
    session.listen(15)
    assert len(instances) == 2
    assert session.recognizer is instances[1]
