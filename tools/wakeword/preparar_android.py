"""Copia os modelos locais validados e, opcionalmente, fixtures privadas para o Android."""
import argparse
import hashlib
import json
from pathlib import Path

if __package__:
    from .testar import MODELS, FRAME, RATE, ActivationGate, load_model, read_wav
else:
    from testar import MODELS, FRAME, RATE, ActivationGate, load_model, read_wav

FILES = ('melspectrogram.onnx', 'embedding_model.onnx', 'hey_ollie.onnx')


def prepare(project, recordings=None):
    import numpy as np
    root = project.resolve()
    if not (root / 'app/build.gradle.kts').is_file():
        raise ValueError('Informe a raiz do projeto Android em --projeto.')
    target = root / 'app/src/main/assets/wakeword'
    assert target.resolve().is_relative_to(root)
    detector = load_model(MODELS / 'hey_ollie.onnx')
    target.mkdir(parents=True, exist_ok=True)
    hashes = []
    for name in FILES:
        data = (MODELS / name).read_bytes()
        temporary = target / (name + '.parcial')
        temporary.write_bytes(data)
        temporary.replace(target / name)
        hashes.append(f'{name}={hashlib.sha256(data).hexdigest()}')
    (target / 'models.properties').write_text('\n'.join(hashes) + '\n', encoding='ascii')
    print('Modelos copiados; mantenha a pasta wakeword fora do Git.')
    if recordings is None:
        return
    fixture_dir = root / 'app/src/androidTest/assets/wakeword-fixtures'
    assert fixture_dir.resolve().is_relative_to(root)
    fixture_dir.mkdir(parents=True, exist_ok=True)
    cases = []
    for label in ('positivo', 'negativo'):
        paths = sorted((recordings / label).glob('*.wav'))
        if not paths:
            raise ValueError(f'Nao ha gravacoes na pasta {label}.')
        for index, path in enumerate(paths):
            # Dois segundos iniciais colocam a chamada depois do aquecimento.
            audio = np.pad(read_wav(path), (2 * RATE, RATE))
            audio = np.pad(audio, (0, (-len(audio)) % FRAME))
            detector.reset()
            gate = ActivationGate()
            scores, hits = [], 0
            for offset in range(0, len(audio), FRAME):
                score = float(next(iter(detector.predict(audio[offset:offset + FRAME]).values())))
                frame = offset // FRAME + 1
                score = score if frame >= 32 else 0.0
                scores.append(score)
                hits += gate.accept(score, frame * .08)
            if (hits > 0) != (label == 'positivo'):
                raise ValueError(f'A gravacao {path.name} nao passa no modelo do PC; nao serve como referencia positiva/negativa.')
            name = f'{label}-{index + 1:02}.pcm'
            (fixture_dir / name).write_bytes(audio.astype('<i2').tobytes())
            cases.append({'file': name, 'scores': scores, 'hits': hits})
    (fixture_dir / 'expected.json').write_text(json.dumps(cases, indent=2), encoding='utf-8')
    print(f'{len(cases)} fixtures privadas preparadas para comparar inferencia no celular e no Python.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--projeto', type=Path, required=True)
    parser.add_argument('--audios', type=Path, help='Pasta local com positivo/ e negativo/; so para teste instrumentado.')
    args = parser.parse_args()
    prepare(args.projeto, args.audios)
