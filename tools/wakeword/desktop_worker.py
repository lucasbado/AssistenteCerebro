"""Captura local do desktop: openWakeWord -> comando pt-BR -> pausa.

JSON por stdin/stdout. Audio fica em memoria; o processo nao conhece servidor,
token, automacoes ou TTS. O desktop controla a retomada depois da resposta.
"""
import argparse
from collections import deque
import json
from pathlib import Path
import queue
import sys
import threading
import time

if __package__:
    from .testar import ActivationGate, FRAME, RATE
else:
    from testar import ActivationGate, FRAME, RATE

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / '.artifacts/wakeword/modelos'
ESPERA_INICIAL = 18
ESPERA_CONTINUACAO = 20
PAUSA_FINAL = 3.2
MAXIMO_FALA = 60


class Conversation:
    def __init__(self, detector, recognizer_factory, emit, threshold=.5, transcriber=None):
        self.detector, self.factory, self.emit = detector, recognizer_factory, emit
        self.threshold = threshold
        self.state = 'paused'
        self.recognizer = None
        self.started = 0.0
        self.speech_started = None
        self.last_activity = 0.0
        self.segments = []
        self.followup = False
        self.ready_at = 0.0
        self.partial = ''
        self.gate = ActivationGate(threshold)
        self.transcriber = transcriber
        self.history = deque(maxlen=2)  # 160ms: preserva a transicao sem repetir boa parte do nome.
        self.audio = bytearray()
        self.revision = 0
        self.waiting = None
        self.pending_audio = None

    def invalidate(self):
        self.revision += 1
        self.waiting = self.pending_audio = None
        self.audio.clear()
        self.history.clear()

    def set_state(self, state):
        self.state = state
        self.emit({'type': 'state', 'state': state})

    def resume(self, now):
        self.invalidate()
        self.detector.reset()
        self.recognizer = None
        self.gate = ActivationGate(self.threshold)
        self.ready_at = now + 1.0
        self.set_state('wake')

    def pause(self):
        self.invalidate()
        self.recognizer = None
        self.partial = ''
        self.detector.reset()
        self.set_state('paused')

    def listen(self, now, preroll=b'', *, followup=False):
        self.invalidate()
        self.recognizer = self.factory()
        self.audio.extend(preroll)
        if preroll:
            self.recognizer.AcceptWaveform(preroll)
        self.started, self.partial = now, ''
        self.speech_started = None
        self.last_activity = now
        self.segments.clear()
        self.followup = followup
        self.set_state('listening')

    def finish(self, text, *, heard=True):
        self.recognizer = None
        self.set_state('thinking')
        if self.transcriber is not None and heard:
            self.waiting = self.revision
            self.pending_audio = (self.revision, bytes(self.audio))
            self.audio.clear()
            return
        self.publish_text(text)

    def complete(self, revision, text, failed=False):
        if revision != self.revision or self.waiting != revision or self.state != 'thinking':
            return
        self.waiting = None
        self.publish_text('' if failed else text)

    def publish_text(self, text):
        text = str(text).strip()
        if text:
            self.emit({'type': 'transcript', 'text': text})
        else:
            self.emit({'type': 'no_speech', 'followup': self.followup,
                       'message': 'Não ouvi o pedido. Você pode chamar a Ollie de novo.'})

    def process_speech(self, pcm, now):
        self.audio.extend(pcm)
        accepted = self.recognizer.AcceptWaveform(pcm)
        if accepted:
            segment = json.loads(self.recognizer.Result()).get('text', '').strip()
            if segment:
                self.segments.append(segment)
            partial = ''
        else:
            segment = ''
            partial = json.loads(self.recognizer.PartialResult()).get('partial', '').strip()

        samples = memoryview(pcm).cast('h') if len(pcm) % 2 == 0 else ()
        # Energy keeps an open-vocabulary utterance alive even when Vosk has no words.
        audible = bool(samples and sum(s * s for s in samples) > len(samples) * 300 ** 2)
        if audible or (partial and partial != self.partial):
            self.last_activity = now
            if self.speech_started is None:
                self.speech_started = now
        elif segment and self.speech_started is None:
            self.speech_started = self.last_activity = now

        if partial != self.partial or segment:
            self.partial = partial
            self.emit({'type': 'partial', 'text': ' '.join([*self.segments, partial]).strip()})

        if self.speech_started is None:
            espera = ESPERA_CONTINUACAO if self.followup else ESPERA_INICIAL
            if now - self.started >= espera:
                self.finish('', heard=False)
        elif now - self.last_activity >= PAUSA_FINAL or now - self.speech_started >= MAXIMO_FALA:
            final = json.loads(self.recognizer.FinalResult()).get('text', '').strip()
            self.finish(' '.join(t for t in [*self.segments, final] if t))

    def process(self, pcm, now):
        if self.state == 'wake' and now >= self.ready_at:
            self.history.append(pcm)
            import numpy as np
            score = float(next(iter(self.detector.predict(np.frombuffer(pcm, dtype=np.int16)).values())))
            if self.gate.accept(score, now):
                self.emit({'type': 'wake', 'score': score})
                self.listen(now, b''.join(self.history))
        elif self.state == 'listening':
            self.process_speech(pcm, now)


def emit(event):
    print(json.dumps(event, ensure_ascii=False, allow_nan=False), flush=True)


def input_devices():
    import sounddevice as sd
    devices, apis = sd.query_devices(), sd.query_hostapis()
    return [{'id': index, 'name': device['name'], 'default': index == sd.default.device[0]}
            for index, device in enumerate(devices) if device['max_input_channels'] > 0
            and (sys.platform != 'win32' or apis[device['hostapi']]['name'] == 'MME')]


def create_conversation(publish=emit):
    from vosk import Model, KaldiRecognizer, SetLogLevel
    if __package__:
        from .testar import load_model
        from .transcricao import load_transcriber
    else:
        from testar import load_model
        from transcricao import load_transcriber
    SetLogLevel(-1)
    language = MODELS / 'vosk-model-small-pt-0.3'
    if not language.is_dir():
        raise RuntimeError('Modelo de portugues do PC ainda nao foi preparado.')
    detector = load_model(MODELS / 'hey_ollie.onnx')
    speech_model = Model(str(language))
    return Conversation(detector, lambda: KaldiRecognizer(speech_model, RATE), publish,
                        transcriber=load_transcriber(MODELS.parent))


def run(device=None):
    import sounddevice as sd
    import numpy as np
    conversation = create_conversation()
    if __package__:
        from .transcricao import TranscriptionJobs
    else:
        from transcricao import TranscriptionJobs
    jobs = TranscriptionJobs(conversation.transcriber) if conversation.transcriber is not None else None
    commands = queue.Queue()
    def read_commands():
        for line in sys.stdin:
            try:
                commands.put(json.loads(line))
            except ValueError:
                continue
        commands.put({'action': 'stop'})
    threading.Thread(target=read_commands, daemon=True).start()
    stream = None
    last_level = 0.0
    def close_stream():
        nonlocal stream
        if stream is not None:
            stream.close()
            stream = None
    def open_stream():
        nonlocal stream
        if stream is None:
            stream = sd.RawInputStream(samplerate=RATE, blocksize=FRAME, device=device,
                                       channels=1, dtype='int16')
            stream.start()
    try:
        open_stream()
        conversation.resume(time.monotonic())
        while True:
            try:
                command = commands.get(timeout=.1) if conversation.state not in ('wake', 'listening') else commands.get_nowait()
            except queue.Empty:
                command = None
            if command:
                action = command.get('action')
                close_stream()  # ACK somente depois de liberar a captura.
                if action == 'stop':
                    break
                if action == 'pause':
                    conversation.pause()
                elif action == 'resume':
                    open_stream()
                    conversation.resume(time.monotonic())
                elif action in ('listen', 'followup'):
                    open_stream()
                    conversation.listen(time.monotonic(), followup=action == 'followup')
                if 'request_id' in command:
                    emit({'ack': command['request_id']})
            if jobs:
                for revision, text, failed in jobs.poll():
                    conversation.complete(revision, text, failed)
            if conversation.state not in ('wake', 'listening'):
                close_stream()
                continue
            if stream is None:
                open_stream()
            data, overflow = stream.read(FRAME)
            now = time.monotonic()
            if overflow:
                conversation.pause()
                close_stream()
                emit({'type': 'error', 'message': 'A captura de audio foi interrompida. Ative a escuta novamente.'})
                continue
            pcm = bytes(data)
            conversation.process(pcm, now)
            if conversation.state not in ('wake', 'listening'):
                close_stream()
            if jobs and conversation.pending_audio is not None:
                revision, audio = conversation.pending_audio
                conversation.pending_audio = None
                jobs.submit(revision, audio)  # Captura ja fechada; ACKs continuam sendo atendidos.
            if now - last_level >= 1:
                samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
                level = float(np.sqrt(np.mean(samples * samples)) / 32768)
                emit({'type': 'level', 'level': min(1.0, level)})
                last_level = now
    finally:
        close_stream()


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--devices', action='store_true')
    parser.add_argument('--device', type=int)
    args = parser.parse_args()
    try:
        if args.devices:
            print(json.dumps(input_devices(), ensure_ascii=False))
        else:
            run(args.device)
        return 0
    except Exception as error:
        emit({'type': 'error', 'message': str(error)})
        print(f'{type(error).__name__}: {error}', file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
