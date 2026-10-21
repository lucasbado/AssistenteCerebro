"""Baixa e valida a transcricao multilingue antes de ativa-la no PC."""
import json
import os
from pathlib import Path

if __package__:
    from .transcricao import MODEL_NAME, MODEL_REPO, MODEL_REVISION, LocalTranscriber
else:
    from transcricao import MODEL_NAME, MODEL_REPO, MODEL_REVISION, LocalTranscriber

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / '.artifacts/wakeword'


def prepare():
    os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN'] = '1'
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    from huggingface_hub import snapshot_download
    folder = WORK / 'modelos' / MODEL_NAME
    snapshot_download(MODEL_REPO, revision=MODEL_REVISION, token=False, local_dir=folder,
                      cache_dir=WORK / 'hf-cache',
                      allow_patterns=['config.json', 'model.bin', 'tokenizer.json', 'preprocessor_config.json', 'vocabulary.*'])
    decoder = LocalTranscriber(folder)
    if decoder(bytes(16000 * 2)):
        raise RuntimeError('A verificacao de silencio produziu texto. O modelo nao foi ativado.')
    settings = WORK / 'desktop-speech.json'
    temporary = settings.with_suffix('.json.parcial')
    temporary.write_text(json.dumps({'engine': 'faster-whisper', 'repo': MODEL_REPO,
                                    'revision': MODEL_REVISION, 'device': 'cpu', 'compute_type': 'int8'}), encoding='utf-8')
    temporary.replace(settings)
    print('Transcricao multilingue local preparada. Reabra a Ollie no PC.')


if __name__ == '__main__':
    prepare()
