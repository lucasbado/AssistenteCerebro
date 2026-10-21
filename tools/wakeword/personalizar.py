"""Treina um candidato pessoal local sobre os embeddings do openWakeWord.

Nao instala o candidato, captura audio nem envia gravacoes. A validacao cruzada
separa arquivos antes das variacoes; ainda e necessario um teste independente.
"""
import argparse
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path

if __package__:
    from .testar import FRAME, RATE, load_model, read_wav
else:
    from testar import FRAME, RATE, load_model, read_wav


@dataclass
class Clip:
    name: str
    positive: bool
    variants: list


def features(detector, audio):
    import numpy as np
    detector.reset()
    padded = np.pad(audio, (2 * RATE, RATE))
    rows = []
    for offset in range(0, len(padded), FRAME):
        frame = padded[offset:offset + FRAME]
        frame = np.pad(frame, (0, FRAME - len(frame)))
        detector.predict(frame)
        rows.append(detector.preprocessor.get_features(16).reshape(-1).copy())
    return np.asarray(rows), np.arange(1, len(rows) + 1) * FRAME / RATE - 2


def speech_end(audio):
    """Delimita uma chamada curta isolada ao redor de seu pico de energia."""
    import numpy as np
    audio = np.pad(audio, (0, (-len(audio)) % 800)).astype(np.float32)
    rms = np.sqrt(np.mean(audio.reshape(-1, 800) ** 2, axis=1))
    peak = int(np.argmax(rms))
    if rms[peak] < 450 or rms[peak] < 4 * np.median(rms):
        raise ValueError('Chamada sem fala suficientemente distinta do ruido. Grave novamente.')
    end = peak
    while end + 1 < len(rms) and (rms[end + 1] > max(450, rms[peak] * .12) or end < peak + 3):
        end += 1
    return (end + 1) * .05


def prepare_clip(path, positive, detector):
    import numpy as np
    from scipy.signal import resample_poly
    audio = read_wav(path)
    variants = []
    for speed in ([90, 100, 110] if positive else [100]):
        changed = np.clip(resample_poly(audio, 100, speed), -32768, 32767).astype(np.int16) if speed != 100 else audio
        x, times = features(detector, changed)
        end = speech_end(changed) if positive else 0
        labels = ((times >= end + .08) & (times <= end + .40)).astype(int) if positive else np.zeros(len(x), int)
        # Prefixos incompletos da chamada nao sao rotulados como fala negativa.
        keep = labels.astype(bool) | (times < end - 1.5) | (times > end + 1.0) if positive else np.ones(len(x), bool)
        variants.append((x, labels, keep, speed))
    return Clip(f'{path.parent.name}/{path.name}', positive, variants)


def training_data(clips, backgrounds, excluded=()):
    import numpy as np
    # Exclusao por gravacao inteira: inclui TODAS as suas variacoes de velocidade.
    items = [variant for index, clip in enumerate(clips) if index not in excluded for variant in clip.variants]
    xs = [v[0][v[2]] for v in items] + backgrounds
    ys = [v[1][v[2]] for v in items] + [np.zeros(len(x), int) for x in backgrounds]
    return np.concatenate(xs), np.concatenate(ys)


def fit(clips, backgrounds, excluded=()):
    from sklearn.linear_model import LogisticRegression
    x, y = training_data(clips, backgrounds, excluded)
    # Regularizacao fixa; o limiar de ativacao do app permanece em 0.5.
    classifier = LogisticRegression(C=.001, class_weight='balanced', max_iter=2000, random_state=0)
    return classifier.fit(x, y)


def sustained(scores):
    return float(max((min(a, b) for a, b in zip(scores, scores[1:])), default=0))


def cross_validate(clips, backgrounds):
    rows = []
    positives = [i for i, clip in enumerate(clips) if clip.positive]
    negatives = [i for i, clip in enumerate(clips) if not clip.positive]
    for fold in range(max(len(positives), len(negatives))):
        held = [group[fold] for group in (positives, negatives) if fold < len(group)]
        classifier = fit(clips, backgrounds, held)
        for i in held:
            clip = clips[i]
            x = next(v[0] for v in clip.variants if v[3] == 100)
            score = sustained(classifier.predict_proba(x)[:, 1])
            rows.append({'arquivo': clip.name, 'positivo': clip.positive,
                         'pico_dois_frames': score, 'detectado': score >= .5})
    return rows


def calibration_threshold(rows):
    """Escolhe o meio da margem em logits, somente na validacao do treino."""
    positive = min(r['pico_dois_frames'] for r in rows if r['positivo'])
    negative = max(r['pico_dois_frames'] for r in rows if not r['positivo'])
    if positive <= max(.5, negative):
        raise ValueError('Chamadas e frases se sobrepoem. Colete mais exemplos antes de calibrar.')
    def logit(score):
        score = min(1 - 1e-7, max(1e-7, score))
        return math.log(score / (1 - score))
    return max(.5, 1 / (1 + math.exp(-(logit(positive) + logit(negative)) / 2)))


def export(classifier, path, raw_threshold=.5):
    import numpy as np
    import onnx
    from onnx import helper, numpy_helper, TensorProto
    nodes = [helper.make_node('Flatten', ['input'], ['flat'], axis=1),
             helper.make_node('Gemm', ['flat', 'weights', 'bias'], ['logit'], transB=1),
             helper.make_node('Sigmoid', ['logit'], ['output'])]
    # Incorpora o corte calibrado no intercepto: o worker ainda exige score >= .5.
    offset = math.log(raw_threshold / (1 - raw_threshold))
    weights = [numpy_helper.from_array(classifier.coef_.astype(np.float32), 'weights'),
               numpy_helper.from_array((classifier.intercept_ - offset).astype(np.float32), 'bias')]
    graph = helper.make_graph(nodes, 'OlliePersonal',
                              [helper.make_tensor_value_info('input', TensorProto.FLOAT, [1, 16, 96])],
                              [helper.make_tensor_value_info('output', TensorProto.FLOAT, [1, 1])], weights)
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid('', 17)], ir_version=8)
    onnx.checker.check_model(model)
    onnx.save(model, path)


def train(folder, base, output, backgrounds, calibrate=False):
    detector = load_model(base)
    clips = []
    paths = []
    for kind in ('positivo', 'negativo'):
        recordings = sorted((folder / kind).glob('*.wav'))
        if len(recordings) < 6:
            raise ValueError(f'Use pelo menos seis gravacoes independentes na pasta {kind}.')
        for path in recordings:
            clips.append(prepare_clip(path, kind == 'positivo', detector))
            paths.append(path)
    bg_paths = sorted(backgrounds.glob('*.wav'))
    if not bg_paths:
        raise ValueError('Informe uma pasta de fundos WAV para ampliar os exemplos negativos.')
    recording_hashes = {hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    if len(recording_hashes) != len(paths):
        raise ValueError('Gravacoes duplicadas nao sao exemplos independentes. Grave novas chamadas e frases.')
    if any(hashlib.sha256(p.read_bytes()).hexdigest() in recording_hashes for p in bg_paths):
        raise ValueError('Fundos nao podem reutilizar as gravacoes da validacao, mesmo renomeadas.')
    bg_features = [features(detector, read_wav(path))[0] for path in bg_paths]
    rows = cross_validate(clips, bg_features)
    raw_threshold = calibration_threshold(rows) if calibrate else .5
    for row in rows:
        row['detectado_antes_calibracao'] = row['detectado']
        row['detectado'] = row['pico_dois_frames'] >= raw_threshold
    output.mkdir(parents=True, exist_ok=True)
    model_path = output / 'hey_ollie.onnx'
    export(fit(clips, bg_features), model_path, raw_threshold)
    report = {'tipo': 'candidato_pessoal_experimental', 'classificador': 'regressao_logistica_C_0.001_sobre_embeddings_OWW',
              'chamadas_detectadas': sum(r['positivo'] and r['detectado'] for r in rows),
              'total_chamadas': sum(c.positive for c in clips),
              'frases_com_ativacao_indevida': sum(not r['positivo'] and r['detectado'] for r in rows),
              'total_frases': sum(not c.positive for c in clips), 'fundos': len(bg_paths),
              'corte_bruto_incorporado_no_intercepto': raw_threshold,
              'calibracao': 'Corte escolhido na validacao cruzada; estes resultados nao sao um teste independente.' if calibrate else 'Sem calibracao.',
              'limiar': .5, 'frames_consecutivos': 2, 'resultados_validacao_cruzada': rows,
              'modelo_sha256': hashlib.sha256(model_path.read_bytes()).hexdigest(),
              'gravacoes_sha256': {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
              'limite': 'Validacao cruzada em amostra pequena. Exige novas gravacoes independentes; nao instala no app.'}
    (output / 'relatorio.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pasta', type=Path, required=True, help='Contem positivo/ e negativo/, WAV mono PCM16 a 16 kHz.')
    parser.add_argument('--modelo-base', type=Path, required=True)
    parser.add_argument('--fundos', type=Path, required=True)
    parser.add_argument('--saida', type=Path, required=True)
    parser.add_argument('--calibrar', action='store_true', help='Aumentar o corte usando a margem da validacao do treino; exige teste independente.')
    args = parser.parse_args()
    train(args.pasta, args.modelo_base, args.saida, args.fundos, args.calibrar)
