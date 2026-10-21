"""Captura local do desktop: openWakeWord -> comando pt-BR -> pausa.

JSON por stdin/stdout. Audio fica em memoria; o processo nao conhece servidor,
token, automacoes ou TTS. O desktop controla a retomada depois da resposta.
"""
import argparse
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


class Conversation:
    def __init__(self, detector, recognizer_factory, emit, threshold=.5):
        self.detector, self.factory, self.emit = detector, recognizer_factory, emit
        self.threshold = threshold
        self.state = 'paused'
        self.recognizer = None
        self.started = 0.0
        self.ready_at = 0.0
        self.partial = ''
        self.gate = ActivationGate(threshold)

    def set_state(self, state):
        self.state = state
        self.emit({'type': 'state', 'state': state})

    def resume(self, now):
        self.detector.reset()
        self.recognizer = None
        self.gate = ActivationGate(self.threshold)
        self.ready_at = now + 1.0
        self.set_state('wake')

    def pause(self):
        self.recognizer = None
        self.partial = ''
        self.detector.reset()
        self.set_state('paused')

    def listen(self, now):
        self.recognizer = self.factory()
        self.started, self.partial = now, ''
        self.set_state('listening')

    def finish(self, text):
        text = str(text).strip()
        self.recognizer = None
        self.set_state('thinking')
        if text:
            self.emit({'type': 'transcript', 'text': text})
        else:
            self.emit({'type': 'no_speech', 'message': 'Nao ouvi o comando. Tente novamente.'})

    def process(self, pcm, now):
        if self.state == 'wake' and now >= self.ready_at:
            import numpy as np
            score = float(next(iter(self.detector.predict(np.frombuffer(pcm, dtype=np.int16)).values())))
            if self.gate.accept(score, now):
                self.emit({'type': 'wake', 'score': score})
                self.listen(now)
        elif self.state == 'listening':
            if self.recognizer.AcceptWaveform(pcm):
                text = json.loads(self.recognizer.Result()).get('text', '')
                if text.strip():
                    self.finish(text)
                    return
            partial = json.loads(self.recognizer.PartialResult()).get('partial', '')
            if partial != self.partial:
                self.partial = partial
                self.emit({'type': 'partial', 'text': partial})
            if now - self.started >= 12:
                self.finish(json.loads(self.recognizer.FinalResult()).get('text', ''))


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
    else:
        from testar import load_model
    SetLogLevel(-1)
    language = MODELS / 'vosk-model-small-pt-0.3'
    if not language.is_dir():
        raise RuntimeError('Modelo de portugues do PC ainda nao foi preparado.')
    detector = load_model(MODELS / 'hey_ollie.onnx')
    speech_model = Model(str(language))
    return Conversation(detector, lambda: KaldiRecognizer(speech_model, RATE), publish)


def run(device=None):
    import sounddevice as sd
    import numpy as np
    conversation = create_conversation()
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
                elif action == 'listen':
                    open_stream()
                    conversation.listen(time.monotonic())
                if 'request_id' in command:
                    emit({'ack': command['request_id']})
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
