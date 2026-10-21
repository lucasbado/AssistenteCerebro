import hashlib
import io
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from urllib.error import HTTPError

import pytest

from tools.wakeword import colab_ollie as tool


def fake_response(monkeypatch, content):
    calls = []
    def open_url(url, **kwargs):
        calls.append(url)
        return io.BytesIO(content)
    monkeypatch.setattr(tool.urllib.request, 'urlopen', open_url)
    return calls


def test_download_substitui_xml_por_checkpoint_verificado(tmp_path, monkeypatch):
    target = tmp_path / 'resources/model.pt'
    target.parent.mkdir()
    target.write_bytes(b'<Error><Code>AccessDenied</Code></Error>')
    payload = b'checkpoint valido do teste'
    calls = fake_response(monkeypatch, payload)
    tool.download('https://model.example/checkpoint', target,
                  expected_sha256=hashlib.sha256(payload).hexdigest())
    assert calls == ['https://model.example/checkpoint']
    assert target.read_bytes() == payload
    assert not list(target.parent.glob('*.parcial'))


def test_checkpoint_valido_no_cache_dispensa_rede(tmp_path, monkeypatch):
    target = tmp_path / 'model.pt'
    target.write_bytes(b'modelo ja aprovado')
    def forbidden(*args, **kwargs):
        pytest.fail('Cache valido nao precisa de rede')
    monkeypatch.setattr(tool.urllib.request, 'urlopen', forbidden)
    tool.download('https://model.example/checkpoint', target,
                  expected_sha256=tool.file_sha256(target))


def test_resposta_html_com_status200_nao_e_promovida_a_modelo(tmp_path, monkeypatch):
    target = tmp_path / 'model.pt'
    fake_response(monkeypatch, b'<html>erro do servidor</html>')
    with pytest.raises(ValueError, match='SHA256 inesperado'):
        tool.download('https://model.example/checkpoint', target, expected_sha256='0' * 64)
    assert not target.exists()
    assert not target.with_suffix('.pt.parcial').exists()


def test_403_nao_conserva_xml_antigo_nem_arquivo_parcial(tmp_path, monkeypatch):
    target = tmp_path / 'model.pt'
    target.write_bytes(b'<Error>AccessDenied</Error>')
    def forbidden(url, **kwargs):
        raise HTTPError(url, 403, 'Forbidden', {}, None)
    monkeypatch.setattr(tool.urllib.request, 'urlopen', forbidden)
    with pytest.raises(HTTPError):
        tool.download('https://model.example/checkpoint', target, expected_sha256='0' * 64)
    assert not target.exists()
    assert not target.with_suffix('.pt.parcial').exists()


def test_frase_no_dicionario_nao_exige_deepphonemizer(tmp_path, monkeypatch):
    monkeypatch.setattr(tool, 'WORK', tmp_path)
    monkeypatch.setitem(sys.modules, 'pronouncing', SimpleNamespace(phones_for_word=lambda word: ['HH EY1']))
    monkeypatch.setitem(sys.modules, 'dp.phonemizer', None)
    assert tool.prepare_phonemizer('hey ollie') == {
        'necessario': False, 'palavras_fora_do_dicionario': [],
    }
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('phones', ['[AW1][L][IY0]', ''])
def test_chamada_do_usuario_prepara_e_valida_oov(tmp_path, monkeypatch, phones):
    monkeypatch.setattr(tool, 'WORK', tmp_path)
    monkeypatch.setitem(sys.modules, 'pronouncing', SimpleNamespace(
        phones_for_word=lambda word: ['HH EY1'] if word == 'hey' else []))
    calls = []
    def download(url, target, **kwargs):
        calls.append((url, Path(target), kwargs))
        target.parent.mkdir(parents=True)
        target.write_bytes(b'checkpoint verificado pelo downloader')
    monkeypatch.setattr(tool, 'download', download)
    def from_checkpoint(path):
        assert path == str(tmp_path / 'openwakeword/openwakeword/resources/en_us_cmudict_forward.pt')
        def predict(word, *, lang):
            assert word == 'ouh_lee' and lang == 'en_us'
            return phones
        return predict
    dp = ModuleType('dp.phonemizer')
    dp.Phonemizer = SimpleNamespace(from_checkpoint=from_checkpoint)
    monkeypatch.setitem(sys.modules, 'dp.phonemizer', dp)
    if not phones:
        with pytest.raises(RuntimeError, match='nao gerou fonemas'):
            tool.prepare_phonemizer('hey ouh_lee')
    else:
        report = tool.prepare_phonemizer('hey ouh_lee')
        assert report['necessario']
        assert report['fonemas'] == {'ouh_lee': phones}
        assert report['palavras_fora_do_dicionario'] == ['ouh_lee']
    assert calls[0][0] == tool.PHONEMIZER_URL
    assert calls[0][2] == {'expected_sha256': tool.PHONEMIZER_SHA256}


def test_falha_do_fonemizador_interrompe_antes_de_sintetizar_positivos(tmp_path, monkeypatch):
    monkeypatch.setattr(tool, 'WORK', tmp_path)
    for name in ('yaml', 'onnxruntime', 'torch'):
        monkeypatch.setitem(sys.modules, name, SimpleNamespace())
    (tmp_path / 'previa.json').write_text(json.dumps({'frase': 'hey ouh_lee'}))
    (tmp_path / 'dados-prontos.json').write_text('{}')
    def failure(phrase):
        raise RuntimeError('Download do fonemizador falhou')
    def forbidden(*args, **kwargs):
        pytest.fail('Nao deve iniciar nenhum subprocesso de sintese')
    monkeypatch.setattr(tool, 'prepare_phonemizer', failure)
    monkeypatch.setattr(tool, 'run', forbidden)
    with pytest.raises(RuntimeError, match='Download do fonemizador falhou'):
        tool.train('hey ouh_lee', 1000, 10000)
