"""Instala os modelos locais do app de PC no workspace, fora do servidor."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / '.artifacts/wakeword'
MODELS = WORK / 'modelos'


def prepare(model, speech_model=None, enable=False):
    import onnxruntime as ort
    from vosk import Model, SetLogLevel
    MODELS.mkdir(parents=True, exist_ok=True)
    if not model.is_file():
        raise ValueError('Informe o arquivo ONNX treinado em --model.')
    session = ort.InferenceSession(str(model), providers=['CPUExecutionProvider'])
    if session.get_inputs()[0].shape[1:] != [16, 96] or session.get_outputs()[0].shape[-1] != 1:
        raise ValueError('O arquivo nao e um classificador de wake word [1,16,96] -> [1,1].')
    language = MODELS / 'vosk-model-small-pt-0.3'
    if not language.exists():
        if speech_model:
            shutil.copytree(speech_model, language)
        else:
            with tempfile.TemporaryDirectory(prefix='voz-pc-', dir=WORK) as temporary:
                staging = Path(temporary).resolve()
                assert staging.is_relative_to(WORK.resolve())
                archive = staging / 'portugues.zip'
                urllib.request.urlretrieve('https://alphacephei.com/vosk/models/vosk-model-small-pt-0.3.zip', archive)
                with zipfile.ZipFile(archive) as source:
                    if any(not (staging / member.filename).resolve().is_relative_to(staging) for member in source.infolist()):
                        raise ValueError('O pacote de portugues contem um caminho invalido.')
                    source.extractall(staging)
                SetLogLevel(-1)
                Model(str(staging / language.name))
                shutil.move(str(staging / language.name), str(language))
    SetLogLevel(-1)
    Model(str(language))
    target = MODELS / 'hey_ollie.onnx'
    temporary = target.with_suffix('.onnx.parcial')
    shutil.copyfile(model, temporary)
    temporary.replace(target)
    report = {'model': str(target), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
              'bytes': target.stat().st_size, 'speech_language': 'pt-BR', 'speech_model': str(language)}
    (WORK / 'desktop-model.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    settings = WORK / 'desktop-settings.json'
    if enable or not settings.exists():
        settings.write_text(json.dumps({'enabled': enable, 'device': None}), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--speech-model', type=Path)
    parser.add_argument('--enable', action='store_true')
    args = parser.parse_args()
    prepare(args.model, args.speech_model, args.enable)
