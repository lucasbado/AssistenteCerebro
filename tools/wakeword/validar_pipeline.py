"""Valida o pipeline real em Linux/Python 3.11, sem treinar um detector utilizavel.

Requer o workspace preparado por colab_ollie.py. Gera um positivo Piper e um
negativo adversarial OOV, uma aumentacao, silencio e UMA atualizacao Adam real.
Nao baixa bases de dados, nao usa microfone e nao publica/substitui modelos.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import random
import subprocess
import sys
import time
import traceback
import wave


# Importar cada dependencia explicitamente permite identificar mais de uma falha.
# Inclui imports locais ao caminho de negativos adversariais (dp.phonemizer),
# que o simples import de openwakeword.train nao exercita.
IMPORTS = (
    ('numpy', 'numpy'), ('scipy', 'scipy'), ('scipy.signal', 'scipy'),
    ('onnxruntime', 'onnxruntime'), ('onnx', 'onnx'),
    ('google.protobuf', 'protobuf'), ('sklearn', 'scikit-learn'),
    ('torch', 'torch'), ('torchvision', 'torchvision'), ('torchaudio', 'torchaudio'),
    ('torchinfo', 'torchinfo'), ('matplotlib', 'matplotlib'),
    ('matplotlib.pyplot', 'matplotlib'), ('torchmetrics', 'torchmetrics'),
    ('speechbrain', 'speechbrain'), ('speechbrain.dataio.dataio', 'speechbrain'),
    ('speechbrain.processing.signal_processing', 'speechbrain'),
    ('audiomentations', 'audiomentations'),
    ('torch_audiomentations', 'torch-audiomentations'), ('acoustics', 'acoustics'),
    ('mutagen', 'mutagen'), ('pronouncing', 'pronouncing'),
    ('dp.phonemizer', 'deep-phonemizer'), ('huggingface_hub', 'huggingface-hub'),
    ('soundfile', 'soundfile'), ('librosa', 'librosa'), ('numba', 'numba'),
    ('pandas', 'pandas'), ('yaml', 'PyYAML'), ('requests', 'requests'),
    ('tqdm', 'tqdm'), ('setuptools', 'setuptools'), ('webrtcvad', 'webrtcvad'),
    ('piper_phonemize', 'piper-phonemize'), ('piper_train.vits.commons', None),
    ('generate_samples', None), ('openwakeword', 'openwakeword'),
    ('openwakeword.data', 'openwakeword'), ('openwakeword.utils', 'openwakeword'),
    ('openwakeword.train', 'openwakeword'),
)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def import_audit():
    """Tenta todos os imports e retorna falhas com o traceback original."""
    rows = []
    for module_name, distribution in IMPORTS:
        started = time.monotonic()
        row = {'modulo': module_name, 'distribuicao': distribution}
        try:
            module = importlib.import_module(module_name)
            row.update(ok=True, origem=getattr(module, '__file__', None))
        except Exception as error:
            row.update(ok=False, erro=f'{type(error).__name__}: {error}',
                       traceback=traceback.format_exc())
        if distribution:
            try:
                row['versao'] = importlib.metadata.version(distribution)
            except importlib.metadata.PackageNotFoundError:
                row['versao'] = None
        row['segundos'] = round(time.monotonic() - started, 3)
        rows.append(row)
        print(f"Import {'OK' if row['ok'] else 'FALHOU'}: {module_name}"
              f" ({row.get('versao', 'fonte local')})", flush=True)
        if not row['ok']:
            print(row['traceback'], flush=True)
    return rows


def check_wav(path):
    """Valida o contrato de audio antes de entregar amostras aos modelos."""
    import numpy as np
    with wave.open(str(path), 'rb') as source:
        info = {'canais': source.getnchannels(), 'taxa_hz': source.getframerate(),
                'bytes_por_amostra': source.getsampwidth(),
                'frames': source.getnframes(), 'compressao': source.getcomptype()}
        if (info['canais'], info['taxa_hz'], info['bytes_por_amostra'], info['compressao']) != (1, 16000, 2, 'NONE'):
            raise ValueError(f'Esperado WAV mono PCM16 a 16000 Hz: {info}')
        samples = np.frombuffer(source.readframes(info['frames']), dtype='<i2').copy()
    if not samples.size or not np.any(samples):
        raise ValueError('Piper gerou audio vazio ou somente silencio.')
    info.update(duracao_segundos=samples.size / 16000,
                pico_absoluto=int(np.abs(samples.astype(np.int32)).max()),
                rms=float(np.sqrt(np.mean(samples.astype(np.float64) ** 2))),
                sha256=sha256(path), caminho=str(path))
    return samples, info


def commit_at(repository):
    result = subprocess.run(['git', '-C', str(repository), 'rev-parse', 'HEAD'],
                            capture_output=True, text=True, check=True)
    return result.stdout.strip()


def pipeline(workspace, output, report):
    # A verificacao executa em CPU para reproduzir gratuitamente em um runner
    # Linux. Isso nao valida CUDA nem o consumo de energia do Android.
    os.environ['CUDA_VISIBLE_DEVICES'] = ''
    if __package__:
        from . import colab_ollie as helper
    else:
        import colab_ollie as helper
    helper.WORK = workspace
    helper.configure_runtime()
    helper.configure_sources()
    sys.path.insert(0, str(workspace / 'piper-sample-generator'))
    os.chdir(workspace)
    report['fontes'] = {
        'openwakeword_commit': commit_at(workspace / 'openwakeword'),
        'piper_commit': commit_at(workspace / 'piper-sample-generator'),
        'helper_sha256': sha256(Path(helper.__file__)),
    }
    report['imports'] = import_audit()
    failures = [row['modulo'] for row in report['imports'] if not row['ok']]
    if failures:
        raise RuntimeError('Falharam os imports: ' + ', '.join(failures))

    import matplotlib
    import numpy as np
    import onnx
    import onnxruntime as ort
    import torch
    from generate_samples import generate_samples
    from openwakeword.data import augment_clips, generate_adversarial_texts
    from openwakeword.train import Model as TrainingModel
    from openwakeword.utils import AudioFeatures

    random.seed(42)
    np.random.seed(42)
    torch.manual_seed(42)
    torch.set_num_threads(2)
    report['runtime'].update(matplotlib_backend=matplotlib.get_backend(),
                             torch_cuda_disponivel=torch.cuda.is_available(),
                             dispositivo='cpu', threads_torch=torch.get_num_threads())
    model_path = workspace / 'piper-sample-generator/models/en_US-libritts_r-medium.pt'
    for required in (model_path, Path(str(model_path) + '.json')):
        if not required.is_file():
            raise FileNotFoundError(f'Arquivo Piper necessario: {required}')
    report['piper_modelo_sha256'] = sha256(model_path)
    audio_dir = output / 'audio'
    audio_dir.mkdir()
    started = time.monotonic()
    generate_samples(text='hey ollie', model=model_path, output_dir=audio_dir,
                     max_samples=1, batch_size=1, file_names=['hey_ollie.wav'],
                     length_scales=[1.1], noise_scales=[0.7], noise_scale_ws=[0.7],
                     auto_reduce_batch_size=False)
    clips = list(audio_dir.glob('*.wav'))
    if len(clips) != 1:
        raise RuntimeError(f'Esperada exatamente uma amostra Piper; geradas {len(clips)}.')
    samples, report['audio_piper'] = check_wav(clips[0])
    report['audio_piper']['geracao_segundos'] = round(time.monotonic() - started, 3)
    report['audio_piper']['amostras_geradas'] = 1

    # Reproduz o caminho ausente no teste com "hey ollie": palavra fora do CMUDict.
    # Verifica download/cache, inferencia DeepPhonemizer, geracao adversarial e Piper.
    oov_phrase = 'hey ouh_lee'
    report['fonemizador_oov'] = helper.prepare_phonemizer(oov_phrase)
    if not report['fonemizador_oov']['necessario']:
        raise RuntimeError('A frase de regressao deixou de exercitar o fallback OOV.')
    adversarial = generate_adversarial_texts(oov_phrase, N=1,
                                           include_partial_phrase=0, include_input_words=0)
    if not adversarial or not adversarial[0].strip() or adversarial[0] == oov_phrase:
        raise RuntimeError('O gerador nao produziu o negativo adversarial OOV.')
    negative_dir = output / 'adversarial'
    negative_dir.mkdir()
    generate_samples(text=adversarial[0], model=model_path, output_dir=negative_dir,
                     max_samples=1, batch_size=1, file_names=['negativo.wav'],
                     length_scales=[1.1], noise_scales=[0.7], noise_scale_ws=[0.7],
                     auto_reduce_batch_size=False)
    _, info = check_wav(negative_dir / 'negativo.wav')
    report['fonemizador_oov'].update(frase=oov_phrase, texto_adversarial=adversarial[0],
                                     audio_adversarial=info)

    # O mesmo gerador usado pelo treino completo, com uma aumentacao leve de
    # ganho. Backgrounds/RIR externos e seus grandes downloads sao dispensados.
    probabilities = {name: 0.0 for name in ('SevenBandParametricEQ', 'TanhDistortion',
                     'PitchShift', 'BandStopFilter', 'AddColoredNoise',
                     'AddBackgroundNoise', 'Gain', 'RIR')}
    probabilities['Gain'] = 1.0
    length = max(32000, int(np.ceil((samples.size + 12000) / 1280)) * 1280)
    generated = augment_clips([str(clips[0])], total_length=length, batch_size=1,
                              augmentation_probabilities=probabilities,
                              background_clip_paths=[], RIR_paths=[])
    positive = next(generated)
    if next(generated, None) is not None:
        raise RuntimeError('O gerador de aumentacao produziu mais de um lote.')
    if positive.shape != (1, length) or positive.dtype != np.int16 or not np.any(positive):
        raise RuntimeError('A aumentacao nao preservou o sinal PCM16 esperado.')
    negative = np.zeros_like(positive)
    np.save(output / 'audio-aumentado.npy', positive, allow_pickle=False)
    np.save(output / 'silencio-negativo.npy', negative, allow_pickle=False)
    report['aumentacao'] = {'lotes': 1, 'amostras': 1, 'shape': list(positive.shape),
                            'dtype': str(positive.dtype), 'probabilidades': probabilities,
                            'fundos_externos': 0, 'respostas_de_ambiente': 0}

    features = AudioFeatures(inference_framework='onnx', device='cpu', ncpu=1)
    batch_audio = np.vstack((positive, negative))
    embeddings = features.embed_clips(batch_audio, batch_size=2, ncpu=1)
    if embeddings.ndim != 3 or embeddings.shape[0] != 2 or embeddings.shape[-1] != 96:
        raise RuntimeError(f'Formato de embeddings inesperado: {embeddings.shape}')
    if not np.isfinite(embeddings).all() or np.array_equal(embeddings[0], embeddings[1]):
        raise RuntimeError('Embeddings invalidos ou iguais para voz e silencio.')
    np.save(output / 'features.npy', embeddings, allow_pickle=False)
    report['features'] = {'shape': list(embeddings.shape), 'dtype': str(embeddings.dtype),
                          'finitos': True, 'voz_e_silencio_distintos': True,
                          'onnx_provedor': features.onnx_execution_provider}

    training = TrainingModel(n_classes=1, input_shape=tuple(embeddings.shape[1:]))
    training.model.to('cpu').train()
    inputs = torch.from_numpy(embeddings.astype(np.float32))
    labels = torch.tensor([[1.0], [0.0]], dtype=torch.float32)
    before = {name: value.detach().clone() for name, value in training.model.named_parameters()}
    training.optimizer.zero_grad()
    predictions_before = training.model(inputs)
    loss = training.loss(predictions_before, labels)
    if not torch.isfinite(loss):
        raise RuntimeError('A perda inicial nao e finita.')
    loss.backward()
    gradient_norm = float(torch.sqrt(sum(torch.sum(parameter.grad ** 2)
                          for parameter in training.model.parameters() if parameter.grad is not None)))
    if not np.isfinite(gradient_norm) or gradient_norm == 0:
        raise RuntimeError('Gradientes invalidos ou nulos antes da atualizacao.')
    # Usar train_model(max_steps=1) nao garante atualizacao: o upstream acumula
    # 128 exemplos. Aqui fazemos UMA atualizacao com seu modelo, perda e Adam.
    training.optimizer.step()
    with torch.no_grad():
        predictions_after = training.model(inputs)
        loss_after = training.loss(predictions_after, labels)
    changed = [name for name, parameter in training.model.named_parameters()
               if not torch.equal(before[name], parameter.detach())]
    steps = {int(state['step'].item()) for state in training.optimizer.state.values()}
    if not changed or steps != {1} or not torch.isfinite(loss_after):
        raise RuntimeError(f'Atualizacao Adam nao comprovada: parametros={changed}, passos={steps}')
    report['treino'] = {'classe_upstream': 'openwakeword.train.Model',
                        'metodo': 'model + loss + backward + optimizer.step do upstream',
                        'otimizador': type(training.optimizer).__name__,
                        'atualizacoes_reais': 1, 'passos_adam_por_parametro': sorted(steps),
                        'batch_shape': list(inputs.shape), 'rotulos': labels.tolist(),
                        'loss_antes': float(loss.detach()), 'loss_depois': float(loss_after),
                        'norma_gradientes': gradient_norm,
                        'parametros_alterados': changed,
                        'scores_antes': predictions_before.detach().tolist(),
                        'scores_depois': predictions_after.tolist()}

    training.model.eval()
    training.export_model(training.model, 'apenas_verificacao_hey_ollie', str(output))
    exported = output / 'apenas_verificacao_hey_ollie.onnx'
    onnx.checker.check_model(str(exported))
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(exported), sess_options=options,
                                   providers=['CPUExecutionProvider'])
    input_name = session.get_inputs()[0].name
    # Exportacao upstream fixa lote1; executar cada elemento separadamente.
    inference = np.vstack([session.run(None, {input_name: example[None].astype(np.float32)})[0]
                           for example in embeddings])
    expected = predictions_after.numpy()
    np.testing.assert_allclose(inference, expected, rtol=1e-4, atol=1e-5)
    report['exportacao'] = {'caminho': str(exported), 'sha256': sha256(exported),
                            'bytes': exported.stat().st_size, 'onnx_checker': 'ok',
                            'provedores': session.get_providers(),
                            'input_name': input_name, 'input_shape': session.get_inputs()[0].shape,
                            'output_shape': list(inference.shape), 'scores': inference.tolist(),
                            'erro_maximo_torch_onnx': float(np.max(np.abs(inference - expected)))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True,
                        help='Pasta preparada por colab_ollie.py (clones e modelos presentes).')
    args = parser.parse_args(argv)
    workspace = args.workspace.expanduser().resolve()
    output_root = workspace / 'verificacao-pipeline'
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output = output_root / stamp
    output.mkdir(parents=True)
    report = {'ok': False, 'inicio_utc': stamp, 'saida': str(output),
              'runtime': {'python': sys.version, 'plataforma': platform.platform()},
              'limites': ['Verificacao tecnica de uma unica atualizacao; modelo inutil para uso real.',
                          'Nao avalia a pronuncia do usuario, falsos positivos, Android ou CUDA.',
                          'Nao baixa bases de dados de treino ou capturas pessoais.']}
    started = time.monotonic()
    try:
        if sys.platform != 'linux' or sys.version_info[:2] != (3, 11):
            raise RuntimeError('Execute no Linux com Python 3.11 do ambiente preparado.')
        pipeline(workspace, output, report)
        report['ok'] = True
    except Exception as error:
        report.update(erro=f'{type(error).__name__}: {error}', traceback=traceback.format_exc())
        print(report['traceback'], file=sys.stderr, flush=True)
    finally:
        report['duracao_segundos'] = round(time.monotonic() - started, 3)
        encoded = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
        (output / 'relatorio.json').write_text(encoded, encoding='utf-8')
        (output_root / 'ultimo-relatorio.json').write_text(encoded, encoding='utf-8')
        print(f"Relatorio: {output / 'relatorio.json'}", flush=True)
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
