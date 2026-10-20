"""Etapas explícitas de treino pessoal no Colab, em Python 3.11 isolado.

Usa o treino original do openWakeWord e o gerador Piper oficial, com revisões fixas.
Não acessa credenciais, servidor Ollie ou gravações pessoais.
"""
import argparse
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tarfile
import time
import urllib.request

if __package__:
    from .execucao import run_logged
else:
    from execucao import run_logged

WORK = Path('/content/ollie-wakeword')
OWW_REV = '368c03716d1e92591906a84949bc477f3a834455'
PIPER_REV = '213d4d5'
DATA_BASE = 'https://huggingface.co/datasets/davidscripka/openwakeword_features/resolve/main/'


def configure_runtime():
    # Definido antes de torchmetrics/speechbrain importarem Matplotlib.
    os.environ['MPLBACKEND'] = 'Agg'


def run(*command, cwd=None):
    print('Executando:', ' '.join(map(str, command)), flush=True)
    run_logged(command, cwd=cwd, log_path=WORK / 'logs' / f'comando-{time.time_ns()}.log')


def download(url, target):
    target = Path(target)
    if target.is_file() and target.stat().st_size:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + '.parcial')
    print(f'Baixando {target.name}...', flush=True)
    try:
        with urllib.request.urlopen(url, timeout=180) as response, temporary.open('wb') as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
        if not temporary.stat().st_size:
            raise ValueError(f'Download vazio: {target.name}')
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def checkout(url, path, revision):
    if not path.exists():
        run('git', 'clone', url, path)
    run('git', 'checkout', revision, cwd=path)


def configure_sources():
    """Prioriza o pacote interno; o diretório externo do clone é um namespace homônimo."""
    repository = (WORK / 'openwakeword').resolve()
    package = repository / 'openwakeword'
    if not (package / '__init__.py').is_file() or not (package / 'train.py').is_file():
        raise RuntimeError('O clone não contém openwakeword/train.py. Execute a preparação novamente.')
    source = str(repository)
    sys.path[:] = [source, *(path for path in sys.path if path != source)]
    # train.py roda em outro processo e também precisa encontrar o pacote interno.
    inherited = os.environ.get('PYTHONPATH', '').split(os.pathsep)
    os.environ['PYTHONPATH'] = os.pathsep.join([source, *(path for path in inherited if path and path != source)])
    importlib.invalidate_caches()
    spec = importlib.util.find_spec('openwakeword')
    expected = package / '__init__.py'
    if spec is None or not spec.origin or Path(spec.origin).resolve() != expected:
        raise RuntimeError('Outro módulo openwakeword está ocultando o código do treino.')
    print(f'Pacote de treinamento: {spec.origin}', flush=True)


def setup(*, cpu=False):
    configure_runtime()
    if sys.version_info[:2] != (3, 11) or sys.platform != 'linux':
        raise RuntimeError('Use o Python 3.11 isolado criado pela primeira célula.')
    WORK.mkdir(exist_ok=True)
    # A validação em CPU usa as mesmas versões e evita baixar bibliotecas CUDA.
    index = 'https://download.pytorch.org/whl/cpu' if cpu else 'https://download.pytorch.org/whl/cu121'
    run(sys.executable, '-m', 'pip', 'install', 'torch==2.5.0', 'torchvision==0.20.0',
        'torchaudio==2.5.0', '--index-url', index)
    run(sys.executable, '-m', 'pip', 'install', '-r', WORK / 'requirements-treino.txt')
    checkout('https://github.com/dscripka/openWakeWord', WORK / 'openwakeword', OWW_REV)
    checkout('https://github.com/rhasspy/piper-sample-generator', WORK / 'piper-sample-generator', PIPER_REV)
    # Só ONNX: dispensa TensorFlow, conversores e o runtime de TFLite.
    run(sys.executable, '-m', 'pip', 'install', '--no-deps', '-e', WORK / 'openwakeword')
    configure_sources()
    download('https://github.com/rhasspy/piper-sample-generator/releases/download/v2.0.0/en_US-libritts_r-medium.pt',
             WORK / 'piper-sample-generator/models/en_US-libritts_r-medium.pt')
    for name in ('melspectrogram', 'embedding_model'):
        download(f'https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/{name}.onnx',
                 WORK / f'openwakeword/openwakeword/resources/models/{name}.onnx')
    verify_runtime()


def onnx_training_source(source):
    # O parser original usa a string "False", que é verdadeira em `if valor:`.
    old = 'if args.convert_to_tflite:'
    if source.count(old) != 1:
        raise RuntimeError('O script de treino mudou. Revise a opção de conversão antes de continuar.')
    return source.replace(old, 'if args.convert_to_tflite is True:', 1)


def prepare_training_script():
    source = WORK / 'openwakeword/openwakeword/train.py'
    script = WORK / 'train_onnx.py'
    script.write_text(onnx_training_source(source.read_text(encoding='utf-8')), encoding='utf-8')
    return script


def verify_runtime():
    print('Verificando imports, gerador de voz e modelos de áudio...', flush=True)
    import torch
    import matplotlib
    import numpy as np
    from piper_phonemize import phonemize_espeak
    from openwakeword.train import Model
    from openwakeword.utils import AudioFeatures
    sys.path.insert(0, str(WORK / 'piper-sample-generator'))
    from generate_samples import generate_samples
    assert phonemize_espeak and generate_samples
    features = AudioFeatures(inference_framework='onnx', device='cpu')
    features(np.zeros(1280, dtype=np.int16))
    # Uma inferência pequena verifica o modelo de treino, sem iniciar o treinamento.
    training_model = Model()
    with torch.no_grad():
        prediction = training_model.model(torch.zeros(1, 16, 96))
    if prediction.shape != (1, 1):
        raise RuntimeError('Formato inesperado na verificação do modelo de treino.')
    script = prepare_training_script()
    report = {'python': sys.version.split()[0], 'matplotlib_backend': matplotlib.get_backend(),
              'gpu_disponivel': torch.cuda.is_available(), 'modelo_audio_carregado': True,
              'inferencia_de_treino': 'ok', 'script_sha256': hashlib.sha256(script.read_bytes()).hexdigest()}
    (WORK / 'verificacao-ambiente.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f'Ambiente pronto: Python {sys.version.split()[0]}, GPU disponível: {torch.cuda.is_available()}')


def phrase_id(phrase):
    return hashlib.sha256(phrase.encode('utf-8')).hexdigest()[:12]


def preview(phrase):
    sys.path.insert(0, str(WORK / 'piper-sample-generator'))
    from generate_samples import generate_samples
    out = WORK / 'previas' / phrase_id(phrase)
    out.mkdir(parents=True, exist_ok=True)
    generate_samples(text=phrase, max_samples=1, length_scales=[1.1],
                     noise_scales=[0.7], noise_scale_ws=[0.7], output_dir=str(out),
                     batch_size=1, auto_reduce_batch_size=True, file_names=['chamada.wav'])
    audio = out / 'chamada.wav'
    if not audio.is_file():
        raise RuntimeError('A prévia não foi gerada. Confira o erro acima.')
    (WORK / 'previa.json').write_text(json.dumps({'frase': phrase, 'audio': str(audio)}))
    print('Prévia pronta. Ouça antes de continuar.')


def data():
    from huggingface_hub import snapshot_download
    import soundfile as sf
    from scipy.signal import resample_poly
    from math import gcd
    import numpy as np
    assets = WORK / 'dados'
    assets.mkdir(exist_ok=True)
    rir = snapshot_download(repo_id='davidscripka/MIT_environmental_impulse_responses',
                            repo_type='dataset', allow_patterns=['16khz/*.wav'],
                            local_dir=str(assets / 'mit'))
    if not list((Path(rir) / '16khz').glob('*.wav')):
        raise RuntimeError('Nenhuma resposta de ambiente foi baixada.')
    archive = assets / 'bal_train09.tar'
    download('https://huggingface.co/datasets/agkphysics/AudioSet/resolve/main/data/bal_train09.tar', archive)
    extracted = assets / 'audioset'
    marker = extracted / '.extraido'
    if not marker.exists():
        extracted.mkdir(exist_ok=True)
        with tarfile.open(archive) as source:
            # Impede arquivos escapando da pasta de dados.
            source.extractall(extracted, filter='data')
        marker.touch()
    converted = assets / 'fundos_16k'
    converted.mkdir(exist_ok=True)
    paths = sorted(extracted.rglob('*.flac'))
    if not paths:
        raise RuntimeError('O pacote AudioSet não contém os áudios esperados.')
    for index, path in enumerate(paths):
        # Identificador pelo caminho impede colisão de nomes de subpastas.
        target = converted / (hashlib.sha256(str(path.relative_to(extracted)).encode()).hexdigest() + '.wav')
        if not target.exists():
            samples, rate = sf.read(path, dtype='float32', always_2d=True)
            samples = samples.mean(axis=1)
            if rate != 16000:
                factor = gcd(rate, 16000)
                samples = resample_poly(samples, 16000 // factor, rate // factor)
            sf.write(target, np.clip(samples, -1, 1), 16000, subtype='PCM_16')
        if index % 100 == 0:
            print(f'Áudios de ambiente: {index + 1}/{len(paths)}', flush=True)
    for name in ('openwakeword_features_ACAV100M_2000_hrs_16bit.npy', 'validation_set_features.npy'):
        download(DATA_BASE + name, assets / name)
        # Checa o cabeçalho, sem carregar os dados inteiros em RAM.
        np.load(assets / name, mmap_mode='r', allow_pickle=False)
    (WORK / 'dados-prontos.json').write_text(json.dumps({'fundos': len(paths)}))
    print('Dados prontos para o treinamento.')


def train(phrase, examples, steps):
    import yaml
    import onnxruntime as ort
    preview_state = json.loads((WORK / 'previa.json').read_text())
    if preview_state['frase'] != phrase:
        raise RuntimeError('A frase mudou. Gere e ouça a nova prévia primeiro.')
    if not (WORK / 'dados-prontos.json').is_file():
        raise RuntimeError('Execute a etapa de dados antes do treinamento.')
    config = yaml.safe_load((WORK / 'openwakeword/examples/custom_model.yml').read_text())
    # Configurações diferentes usam pastas próprias para não reutilizar exemplos de outra frase.
    output = WORK / 'treinos' / f'{phrase_id(phrase)}-{examples}-{steps}'
    output.mkdir(parents=True, exist_ok=True)
    config.update(target_phrase=[phrase], model_name='hey_ollie', n_samples=examples,
                  n_samples_val=max(500, examples // 10), steps=steps,
                  output_dir=str(output), piper_sample_generator_path=str(WORK / 'piper-sample-generator'),
                  rir_paths=[str(WORK / 'dados/mit/16khz')],
                  background_paths=[str(WORK / 'dados/fundos_16k')], background_paths_duplication_rate=[1],
                  false_positive_validation_data_path=str(WORK / 'dados/validation_set_features.npy'),
                  feature_data_files={'ACAV100M_sample': str(WORK / 'dados/openwakeword_features_ACAV100M_2000_hrs_16bit.npy')})
    config_path = output / 'config.yml'
    config_path.write_text(yaml.safe_dump(config), encoding='utf-8')
    training_script = prepare_training_script()
    for phase in ('generate_clips', 'augment_clips', 'train_model'):
        print(f'Etapa: {phase}', flush=True)
        run(sys.executable, training_script,
            '--training_config', config_path, '--' + phase, cwd=WORK)
    model = output / 'hey_ollie.onnx'
    ort.InferenceSession(str(model), providers=['CPUExecutionProvider'])
    manifest = {'modelo': str(model), 'frase': phrase, 'exemplos': examples, 'passos': steps,
                'sha256': hashlib.sha256(model.read_bytes()).hexdigest(), 'openwakeword_commit': OWW_REV,
                'script_treino_sha256': hashlib.sha256(training_script.read_bytes()).hexdigest(),
                'validacao': 'Exportação técnica. Reconhecimento da voz real ainda não avaliado.'}
    (WORK / 'ultimo_modelo.json').write_text(json.dumps(manifest, indent=2))
    print(f'Modelo exportado: {model}. Agora teste sua pronúncia no PC.')


def main():
    global WORK
    configure_runtime()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('etapa', choices=['preparar', 'previa', 'dados', 'treinar', 'verificar'])
    parser.add_argument('--frase', default='hey ollie')
    parser.add_argument('--exemplos', type=int, choices=range(100, 50001), default=1000)
    parser.add_argument('--passos', type=int, choices=range(1000, 50001), default=10000)
    parser.add_argument('--workspace', type=Path, default=WORK)
    parser.add_argument('--cpu', action='store_true', help='Preparar PyTorch CPU para a verificação Linux.')
    args = parser.parse_args()
    WORK = args.workspace.expanduser().resolve()
    WORK.mkdir(parents=True, exist_ok=True)
    os.chdir(WORK)
    if not args.frase.strip() or len(args.frase) > 100:
        parser.error('Use uma chamada curta e não vazia.')
    if args.etapa == 'preparar': setup(cpu=args.cpu)
    else:
        configure_sources()
        if args.etapa == 'previa': preview(args.frase)
        elif args.etapa == 'dados': data()
        elif args.etapa == 'verificar':
            run(sys.executable, Path(__file__).with_name('validar_pipeline.py'), '--workspace', WORK)
        else: train(args.frase, args.exemplos, args.passos)


if __name__ == '__main__':
    main()
