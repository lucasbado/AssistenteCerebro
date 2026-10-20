import argparse
import ast
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import wave

import pytest

from tools.wakeword.testar import ActivationGate, read_wav, threshold


def test_score_sustentado_gera_uma_ativacao_e_exige_queda():
    gate = ActivationGate()
    assert not gate.accept(.8, 0)
    assert gate.accept(.8, .08)
    assert not gate.accept(.9, 8)
    assert not gate.accept(.1, 9)
    assert not gate.accept(.9, 9.08)
    assert gate.accept(.9, 9.16)


def test_intervalo_e_picos_isolados_nao_ativam():
    gate = ActivationGate()
    assert not gate.accept(.8, 0)
    assert not gate.accept(.1, .08)
    assert not gate.accept(.8, .16)
    assert gate.accept(.8, .24)
    assert not gate.accept(.1, .32)
    assert not gate.accept(.9, 1)
    assert not gate.accept(.9, 1.08)
    assert gate.accept(.9, 5.24)


@pytest.mark.parametrize('score', [math.nan, math.inf, -math.inf])
def test_score_invalido_nao_ativa(score):
    gate = ActivationGate(consecutive=1)
    assert not gate.accept(score, 10)


@pytest.mark.parametrize('value', ['0', '-0.5', '1.1', 'nan', 'inf'])
def test_limiar_invalido(value):
    with pytest.raises(argparse.ArgumentTypeError):
        threshold(value)


@pytest.mark.parametrize('channels,width,rate', [(2, 2, 16000), (1, 1, 16000), (1, 2, 44100)])
def test_formato_incompativel_nao_vira_audio_valido(tmp_path, channels, width, rate):
    path = tmp_path / 'sample.wav'
    with wave.open(str(path), 'wb') as output:
        output.setnchannels(channels)
        output.setsampwidth(width)
        output.setframerate(rate)
        output.writeframes(bytes(16 * channels * width))
    with pytest.raises(ValueError, match='16000'):
        read_wav(path)


def test_le_pcm_com_sinal_e_rejeita_vazio(tmp_path):
    path = tmp_path / 'sample.wav'
    for values in [[], [-32768, 0, 32767]]:
        with wave.open(str(path), 'wb') as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            output.writeframes(struct.pack('<' + 'h' * len(values), *values))
        if values:
            assert read_wav(path).tolist() == values
        else:
            with pytest.raises(ValueError, match='vazia'):
                read_wav(path)


def test_notebook_tem_codigo_python_valido_sem_execucoes_salvas():
    root = Path(__file__).resolve().parents[1]
    nb = json.loads((root / 'tools/wakeword/treinar_ollie.ipynb').read_text(encoding='utf-8'))
    code = [cell for cell in nb['cells'] if cell['cell_type'] == 'code']
    assert len(code) == 5
    for cell in code:
        assert cell['outputs'] == []
        assert cell['execution_count'] is None
        compile(''.join(cell['source']), cell['id'], 'exec')


def test_notebook_so_executa_helpers_com_os_hashes_atuais():
    root = Path(__file__).resolve().parents[1] / 'tools/wakeword'
    nb = json.loads((root / 'treinar_ollie.ipynb').read_text(encoding='utf-8'))
    setup = next(cell for cell in nb['cells'] if cell['cell_type'] == 'code')
    tree = ast.parse(''.join(setup['source']))
    hashes = next(ast.literal_eval(node.value) for node in tree.body
                  if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'EXPECTED' for t in node.targets))
    assert hashes == {name: hashlib.sha256((root / name).read_bytes().replace(b'\r\n', b'\n')).hexdigest() for name in hashes}


def test_avaliacao_reinicia_modelo_por_arquivo_e_conta_chamadas(tmp_path, monkeypatch):
    import tools.wakeword.testar as tool
    class Detector:
        resets = 0
        def reset(self):
            self.resets += 1
            self.frames = 0
        def predict(self, audio):
            assert len(audio) == 1280
            self.frames += 1
            return {'hey_ollie': .9 if self.frames <= 2 else .1}
    detector = Detector()
    for name in ['a.wav', 'b.wav']:
        with wave.open(str(tmp_path / name), 'wb') as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(16000)
            output.writeframes(bytes(16000 * 2))
    model = tmp_path / 'hey_ollie.onnx'
    model.write_bytes(b'modelo apenas para teste')
    monkeypatch.setattr(tool, 'WORK', tmp_path)
    monkeypatch.setattr(tool, 'load_model', lambda path: detector)
    tool.evaluate(SimpleNamespace(modelo=model, pasta=tmp_path, tipo='positivo', limiar=.5))
    report = json.loads(next(tmp_path.glob('relatorio-*.json')).read_text(encoding='utf-8'))
    assert detector.resets == 2
    assert report['fracao_de_arquivos_detectados'] == 1
    assert all(len(row['ativacoes']) == 1 for row in report['resultados'])


def test_erro_de_subprocesso_inclui_causa_de_stderr_e_log_inteiro(tmp_path):
    from tools.wakeword.execucao import run_logged, StageError
    log = tmp_path / 'etapa.log'
    script = "import sys; print('iniciando'); print('ModuleNotFoundError: exemplo', file=sys.stderr); sys.exit(7)"
    with pytest.raises(StageError) as error:
        run_logged([sys.executable, '-c', script], log_path=log)
    assert 'ModuleNotFoundError: exemplo' in str(error.value)
    assert 'código 7' in str(error.value)
    assert 'iniciando' in log.read_text(encoding='utf-8')
    assert 'ModuleNotFoundError: exemplo' in log.read_text(encoding='utf-8')


def test_saida_extensa_limita_erro_final_e_preserva_log(tmp_path):
    from tools.wakeword.execucao import run_logged, StageError
    log = tmp_path / 'etapa.log'
    script = "import sys; [print('linha', i) for i in range(100)]; sys.exit(1)"
    with pytest.raises(StageError) as error:
        run_logged([sys.executable, '-c', script], log_path=log, tail_lines=3)
    assert 'linha 0\n' not in str(error.value)
    assert 'linha 99' in str(error.value)
    assert len(log.read_text(encoding='utf-8').splitlines()) == 100


def test_subprocesso_sucesso_nao_gera_falso_erro(tmp_path):
    from tools.wakeword.execucao import run_logged
    log = tmp_path / 'etapa.log'
    run_logged([sys.executable, '-c', "print('pronto')"], log_path=log)
    assert log.read_text(encoding='utf-8').strip() == 'pronto'
