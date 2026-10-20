"""Contratos leves do verificador; integracao real roda em Linux separado."""
import json
from pathlib import Path
import struct
from types import SimpleNamespace
import wave

import pytest

from tools.wakeword import validar_pipeline as tool


def wav(path, *, rate=16000, channels=1, width=2, values=(0, 32767, -32768)):
    with wave.open(str(path), 'wb') as output:
        output.setnchannels(channels)
        output.setsampwidth(width)
        output.setframerate(rate)
        output.writeframes(struct.pack('<' + 'h' * len(values), *values))


def test_wav_real_contabiliza_sinal_sem_overflow_int16(tmp_path):
    path = tmp_path / 'voz.wav'
    wav(path)
    samples, info = tool.check_wav(path)
    assert samples.tolist() == [0, 32767, -32768]
    assert info['pico_absoluto'] == 32768
    assert info['rms'] > 0
    assert info['sha256'] == tool.sha256(path)


@pytest.mark.parametrize('values', [(), (0, 0, 0)])
def test_audio_vazio_ou_silencio_nao_valida_geracao_piper(tmp_path, values):
    path = tmp_path / 'voz.wav'
    wav(path, values=values)
    with pytest.raises(ValueError, match='vazio ou somente silencio'):
        tool.check_wav(path)


def test_taxa_de_audio_errada_falha_antes_dos_modelos(tmp_path):
    path = tmp_path / 'voz.wav'
    wav(path, rate=22050)
    with pytest.raises(ValueError, match='16000'):
        tool.check_wav(path)


def test_auditoria_continua_e_expoe_todos_os_imports_que_falharam(monkeypatch):
    monkeypatch.setattr(tool, 'IMPORTS', (('broken_a', None), ('ok', None), ('broken_b', None)))
    called = []
    def importer(name):
        called.append(name)
        if name.startswith('broken'):
            raise ImportError('dependencia ausente: ' + name)
        return SimpleNamespace(__file__='/fonte/ok.py')
    monkeypatch.setattr(tool.importlib, 'import_module', importer)
    rows = tool.import_audit()
    assert called == ['broken_a', 'ok', 'broken_b']
    assert [row['ok'] for row in rows] == [False, True, False]
    assert 'ImportError: dependencia ausente: broken_b' in rows[2]['traceback']
    assert rows[1]['origem'] == '/fonte/ok.py'


def test_falha_real_do_pipeline_ainda_salva_relatorio_e_codigo1(tmp_path, monkeypatch):
    monkeypatch.setattr(tool.sys, 'platform', 'linux')
    monkeypatch.setattr(tool.sys, 'version_info', (3, 11, 9))
    def failure(workspace, output, report):
        report['imports'] = [{'modulo': 'x', 'ok': False}]
        raise ImportError('falha concreta no pipeline')
    monkeypatch.setattr(tool, 'pipeline', failure)
    result = tool.main(['--workspace', str(tmp_path)])
    assert result == 1
    report = json.loads((tmp_path / 'verificacao-pipeline/ultimo-relatorio.json').read_text(encoding='utf-8'))
    assert report['ok'] is False
    assert report['imports'] == [{'modulo': 'x', 'ok': False}]
    assert 'ImportError: falha concreta no pipeline' in report['traceback']
    assert Path(report['saida']).parent == tmp_path / 'verificacao-pipeline'
    assert (Path(report['saida']) / 'relatorio.json').is_file()
