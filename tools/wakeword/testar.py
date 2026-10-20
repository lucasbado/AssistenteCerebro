"""Laboratório local de wake word. Não envia áudio nem executa comandos da Ollie."""
import argparse
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import shutil
import time
import urllib.request
import uuid
import wave

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / '.artifacts/wakeword'
MODELS = WORK / 'modelos'
RATE = 16000
FRAME = 1280  # 80 ms, conforme a API do openWakeWord.
FEATURES = ('melspectrogram', 'embedding_model')


@dataclass
class ActivationGate:
    threshold: float = 0.5
    consecutive: int = 2
    cooldown: float = 5.0
    count: int = 0
    last: float = -math.inf
    armed: bool = True

    def accept(self, score, now):
        if not math.isfinite(score) or score < self.threshold:
            self.count = 0
            self.armed = True
            return False
        self.count += 1
        if not self.armed or self.count < self.consecutive or now - self.last < self.cooldown:
            return False
        self.armed = False
        self.last = now
        return True


def prepare():
    MODELS.mkdir(parents=True, exist_ok=True)
    for name in FEATURES:
        target = MODELS / f'{name}.onnx'
        if target.exists():
            continue
        url = f'https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/{name}.onnx'
        print(f'Baixando modelo compartilhado: {name}', flush=True)
        partial = target.with_suffix('.download')
        try:
            with urllib.request.urlopen(url, timeout=90) as response, partial.open('wb') as output:
                shutil.copyfileobj(response, output)
            # Confere se o download é um grafo carregável antes de promovê-lo.
            import onnxruntime as ort
            ort.InferenceSession(str(partial), providers=['CPUExecutionProvider'])
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)
    print('Modelos compartilhados prontos. Eles ainda não detectam Hey Ollie.')


def load_model(path):
    path = Path(path).resolve()
    if path.suffix.lower() != '.onnx' or not path.is_file():
        raise ValueError('Informe o arquivo .onnx baixado após o treinamento.')
    for name in FEATURES:
        if not (MODELS / f'{name}.onnx').is_file():
            raise ValueError('Execute tools/wakeword/preparar.ps1 primeiro.')
    from openwakeword.model import Model
    return Model(wakeword_models=[str(path)], inference_framework='onnx',
                 melspec_model_path=str(MODELS / 'melspectrogram.onnx'),
                 embedding_model_path=str(MODELS / 'embedding_model.onnx'))


def read_wav(path):
    import numpy as np
    with wave.open(str(path), 'rb') as stream:
        if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate(), stream.getcomptype()) != (1, 2, RATE, 'NONE'):
            raise ValueError(f'{path.name}: use WAV PCM de 16 bits, mono, 16000 Hz.')
        audio = np.frombuffer(stream.readframes(stream.getnframes()), dtype='<i2').copy()
    if audio.size == 0:
        raise ValueError(f'{path.name}: gravação vazia.')
    return audio


def record(args):
    import sounddevice as sd
    directory = WORK / 'audios' / args.tipo
    directory.mkdir(parents=True, exist_ok=True)
    print('Gravações ficam somente neste PC, fora do Git. Ctrl+C cancela.')
    print('positivo: uma chamada por arquivo. negativo: converse sem chamar a Ollie.')
    for index in range(args.quantidade):
        input(f'Gravação {index + 1}/{args.quantidade}: Enter para iniciar {args.segundos}s... ')
        audio = sd.rec(int(args.segundos * RATE), samplerate=RATE, channels=1, dtype='int16', device=args.dispositivo)
        sd.wait()
        name = f'{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}.wav'
        with wave.open(str(directory / name), 'wb') as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(RATE)
            output.writeframes(audio.tobytes())
        print(f'Salvo: {directory / name}')


def evaluate(args):
    import numpy as np
    model = load_model(args.modelo)
    paths = sorted(args.pasta.glob('*.wav'))
    if not paths:
        raise ValueError('Nenhum WAV encontrado nessa pasta.')
    rows = []
    for path in paths:
        audio = read_wav(path)
        seconds = len(audio) / RATE
        # Inclui silêncio ao final para que a janela do detector termine de avançar.
        audio = np.pad(audio, (0, RATE))
        model.reset()
        gate = ActivationGate(args.limiar)
        detected = []
        peak = 0.0
        for start in range(0, len(audio), FRAME):
            chunk = audio[start:start + FRAME]
            chunk = np.pad(chunk, (0, FRAME - len(chunk)))
            prediction = model.predict(chunk)
            score = float(next(iter(prediction.values())))
            if math.isfinite(score):
                peak = max(peak, score)
            at = (start + FRAME) / RATE
            if gate.accept(score, at):
                detected.append(round(at, 3))
        row = {'arquivo': path.name, 'segundos': seconds, 'pico': peak, 'ativacoes': detected}
        rows.append(row)
        print(f'{path.name}: pico={peak:.3f}, ativações={len(detected)}')
    total = sum(row['segundos'] for row in rows)
    hits = sum(bool(row['ativacoes']) for row in rows)
    summary = {'tipo': args.tipo, 'arquivos': len(rows), 'segundos': total,
               'limiar': args.limiar, 'frames_consecutivos': 2,
               'modelo_sha256': hashlib.sha256(args.modelo.read_bytes()).hexdigest(), 'resultados': rows}
    if args.tipo == 'positivo':
        summary['fracao_de_arquivos_detectados'] = hits / len(rows)
        print(f'Chamadas detectadas: {hits}/{len(rows)} (uma chamada esperada por arquivo).')
    else:
        count = sum(len(row['ativacoes']) for row in rows)
        summary['ativacoes_indevidas'] = count
        summary['ativacoes_por_hora_observada'] = count * 3600 / total
        print(f'Ativações indevidas: {count} em {total:.1f}s. Amostra curta não estima o uso diário.')
    report = WORK / f'relatorio-{args.tipo}-{time.time_ns()}.json'
    report.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Relatório: {report}')


def listen(args):
    import sounddevice as sd
    import numpy as np
    model = load_model(args.modelo)
    gate = ActivationGate(args.limiar)
    print('Teste local: diga Ei Ollie. Apenas mostra detecções; Ctrl+C encerra. Não salva áudio.')
    with sd.RawInputStream(samplerate=RATE, blocksize=FRAME, channels=1, dtype='int16', device=args.dispositivo) as stream:
        while True:
            frame, overflow = stream.read(FRAME)
            if overflow:
                model.reset()
                gate = ActivationGate(args.limiar)
                print('Áudio interrompido; detector reiniciado.')
                continue
            score = float(next(iter(model.predict(np.frombuffer(frame, dtype=np.int16)).values())))
            if gate.accept(score, time.monotonic()):
                print(f'Chamada detectada! score={score:.3f}', flush=True)


def threshold(value):
    number = float(value)
    if not 0 < number <= 1:
        raise argparse.ArgumentTypeError('O limiar deve estar entre 0 (exclusivo) e 1.')
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    subs.add_parser('preparar')
    subs.add_parser('microfones')
    rec = subs.add_parser('gravar')
    rec.add_argument('--tipo', choices=['positivo', 'negativo'], required=True)
    rec.add_argument('--quantidade', type=int, choices=range(1, 101), default=10)
    rec.add_argument('--segundos', type=int, choices=range(1, 121), default=4)
    rec.add_argument('--dispositivo', type=int)
    for command in ('avaliar', 'ouvir'):
        sub = subs.add_parser(command)
        sub.add_argument('--modelo', type=Path, required=True)
        sub.add_argument('--limiar', type=threshold, default=0.5)
        if command == 'avaliar':
            sub.add_argument('--pasta', type=Path, required=True)
            sub.add_argument('--tipo', choices=['positivo', 'negativo'], required=True)
        else:
            sub.add_argument('--dispositivo', type=int)
    args = parser.parse_args()
    try:
        if args.command == 'preparar': prepare()
        elif args.command == 'microfones':
            import sounddevice as sd
            print(sd.query_devices())
        elif args.command == 'gravar': record(args)
        elif args.command == 'avaliar': evaluate(args)
        else: listen(args)
    except KeyboardInterrupt:
        print('\nTeste encerrado.')
    except Exception as exc:
        parser.exit(1, f'Erro: {exc}\n')


if __name__ == '__main__':
    main()
