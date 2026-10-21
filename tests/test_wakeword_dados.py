"""Dados reais pequenos, sem rede nem dependencias de audio opcionais."""
import io
import json
import os
from pathlib import Path
import sys
import tarfile
from types import ModuleType, SimpleNamespace
import wave

import numpy as np
import pytest

from tools.wakeword import colab_ollie as tool


@pytest.fixture
def dataset(tmp_path, monkeypatch):
    monkeypatch.setattr(tool, 'WORK', tmp_path)
    source = tmp_path / 'fontes'
    source.mkdir()
    rir = source / 'mit/16khz'
    rir.mkdir(parents=True)
    (rir / 'sala.wav').write_bytes(b'RIR controlado pelo teste')
    archive = source / 'bal_train09.tar'
    with tarfile.open(archive, 'w') as output:
        # Nomes iguais em pastas diferentes nao podem sobrescrever o WAV final.
        for name in ['audio/bal_train/a/amostra.flac', 'audio/bal_train/b/amostra.flac']:
            payload = b'fLaC audio sintetico do teste'
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            output.addfile(member, io.BytesIO(payload))
    original_stat = Path.stat
    archive_size = {'value': 968540160}

    def stat(path, *args, **kwargs):
        result = original_stat(path, *args, **kwargs)
        if path == archive:
            values = list(result)
            values[6] = archive_size['value']
            return os.stat_result(values)
        return result

    # Simula so o tamanho do TAR remoto; extracao le um TAR pequeno verdadeiro.
    monkeypatch.setattr(Path, 'stat', stat)
    originals = dict(tool.FEATURE_FILES)
    features = {}
    for index, (name, (_, _, dtype)) in enumerate(originals.items()):
        path = source / name
        values = np.zeros((2, 16, 96) if index == 0 else (3, 96), dtype=dtype)
        np.save(path, values)
        features[name] = (path.stat().st_size, values.shape, str(values.dtype))
    monkeypatch.setattr(tool, 'FEATURE_FILES', features)
    calls = []

    def snapshot_download(**kwargs):
        calls.append(('snapshot', kwargs))
        return str(rir.parent)

    def hf_hub_download(**kwargs):
        calls.append(('file', kwargs))
        if kwargs['repo_id'] == 'agkphysics/AudioSet':
            return str(archive)
        return str(source / kwargs['filename'])

    hub = ModuleType('huggingface_hub')
    hub.snapshot_download = snapshot_download
    hub.hf_hub_download = hf_hub_download
    monkeypatch.setitem(sys.modules, 'huggingface_hub', hub)
    reads, writes, resamples = [], [], []
    soundfile = ModuleType('soundfile')

    def read(path, **kwargs):
        reads.append((path, kwargs))
        return np.array([[2, 0], [-2, 0], [.5, 1.5], [-1.5, -.5]], dtype=np.float32), 8000

    def write(path, samples, rate, **kwargs):
        writes.append((path, samples.copy(), rate, kwargs))
        with wave.open(str(path), 'wb') as output:
            output.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
            output.writeframes((samples * 32767).astype('<i2').tobytes())

    soundfile.read, soundfile.write = read, write
    monkeypatch.setitem(sys.modules, 'soundfile', soundfile)
    scipy, signal = ModuleType('scipy'), ModuleType('scipy.signal')

    def resample_poly(samples, up, down):
        resamples.append((samples.copy(), up, down))
        assert (up, down) == (2, 1)
        return np.repeat(samples, 2)

    signal.resample_poly = resample_poly
    scipy.signal = signal
    monkeypatch.setitem(sys.modules, 'scipy', scipy)
    monkeypatch.setitem(sys.modules, 'scipy.signal', signal)
    return SimpleNamespace(root=tmp_path, source=source, rir=rir, archive=archive,
                           archive_size=archive_size, calls=calls, reads=reads,
                           writes=writes, resamples=resamples, originals=originals)


def test_dados_fixam_revisoes_convertem_mono_16k_e_registram_manifesto(dataset):
    tool.data()
    calls = [kwargs for _, kwargs in dataset.calls]
    assert [(c['repo_id'], c['revision']) for c in calls] == [
        ('davidscripka/MIT_environmental_impulse_responses', 'b824a1ef2821f112fda0b9cb26e4278c62b425bb'),
        ('agkphysics/AudioSet', '5a2fa42a1506470d275a47ff8e1fdac5b364e6ef'),
        ('davidscripka/openwakeword_features', '985bf1b47e7f19c07741af82bfe32d5a9dc56096'),
        ('davidscripka/openwakeword_features', '985bf1b47e7f19c07741af82bfe32d5a9dc56096'),
    ]
    assert all(c['token'] is False and c['repo_type'] == 'dataset' for c in calls)
    assert calls[1]['filename'] == 'data/bal_train09.tar'
    assert len(dataset.reads) == len(dataset.writes) == len(dataset.resamples) == 2
    for _, values, rate, options in dataset.writes:
        assert rate == 16000 and values.ndim == 1 and len(values) == 8
        assert np.max(np.abs(values)) <= 1
        assert options == {'subtype': 'PCM_16', 'format': 'WAV'}
    wavs = list((dataset.root / 'dados/fundos_16k').glob('*.wav'))
    assert len(wavs) == 2 and wavs[0].name != wavs[1].name
    assert not list((dataset.root / 'dados/fundos_16k').glob('*.parcial'))
    report = json.loads((dataset.root / 'dados-prontos.json').read_text())
    assert report['fundos'] == 2 and report['rir'] == 1
    assert report['audioset_revision'] == tool.AUDIOSET_REV
    assert set(report['features']) == set(tool.FEATURE_FILES)


def test_tar_incompleto_falha_antes_da_extracao_e_nao_declara_dados_prontos(dataset):
    dataset.archive_size['value'] = 123
    with pytest.raises(RuntimeError, match='Tamanho inesperado'):
        tool.data()
    assert not (dataset.root / 'dados/audioset/.extraido').exists()
    assert not (dataset.root / 'dados-prontos.json').exists()
    assert not dataset.reads


def test_nova_falha_remove_manifesto_anterior_para_impedir_treino_com_dados_invalidos(dataset):
    manifest = dataset.root / 'dados-prontos.json'
    manifest.write_text(json.dumps({'fundos': 500, 'execucao': 'anterior'}))
    dataset.archive_size['value'] = 123
    with pytest.raises(RuntimeError, match='Tamanho inesperado'):
        tool.data()
    assert not manifest.exists()


@pytest.mark.parametrize('corruption', ['tamanho', 'shape', 'dtype', 'cabecalho'])
def test_feature_corrompida_nao_e_aceita_pelo_manifesto(dataset, corruption):
    name = next(iter(tool.FEATURE_FILES))
    path = dataset.source / name
    if corruption == 'tamanho':
        path.write_bytes(b'download incompleto')
    elif corruption == 'shape':
        np.save(path, np.zeros((4, 8, 96), dtype='float16'))
    elif corruption == 'dtype':
        # Mantem bytes totais iguais para atingir a validacao do cabecalho.
        np.save(path, np.zeros((1, 16, 96), dtype='float32'))
    else:
        path.write_bytes(b'x' * path.stat().st_size)
    with pytest.raises((RuntimeError, ValueError)) as error:
        tool.data()
    if corruption == 'tamanho':
        assert 'Download incompleto' in str(error.value)
    elif corruption in {'shape', 'dtype'}:
        assert 'Formato inesperado' in str(error.value)
    assert not (dataset.root / 'dados-prontos.json').exists()


@pytest.mark.parametrize('method, arguments, dependency, manifest', [
    ('data', (), 'huggingface_hub', 'dados-prontos.json'),
    ('train', ('hey ollie', 1000, 10000), 'yaml', 'ultimo_modelo.json'),
])
def test_import_ausente_tambem_invalida_resultado_antigo(tmp_path, monkeypatch, method, arguments, dependency, manifest):
    monkeypatch.setattr(tool, 'WORK', tmp_path)
    stale = tmp_path / manifest
    stale.write_text('{"resultado": "antigo"}')
    monkeypatch.setitem(sys.modules, dependency, None)
    with pytest.raises(ModuleNotFoundError):
        getattr(tool, method)(*arguments)
    assert not stale.exists()


def test_sem_respostas_de_ambiente_interrompe_antes_do_corpus_grande(dataset):
    (dataset.rir / 'sala.wav').unlink()
    with pytest.raises(RuntimeError, match='Nenhuma resposta'):
        tool.data()
    assert len(dataset.calls) == 1
    assert not (dataset.root / 'dados-prontos.json').exists()


def test_conjuntos_publicados_preservam_tamanho_formato_e_dtype(dataset):
    # Impede aceitar o tamanho certo de um artefato diferente do treino aprovado.
    assert dataset.originals == {
        'openwakeword_features_ACAV100M_2000_hrs_16bit.npy':
            (17280000128, (5625000, 16, 96), 'float16'),
        'validation_set_features.npy': (184836608, (481345, 96), 'float32'),
    }
