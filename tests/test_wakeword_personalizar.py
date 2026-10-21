from types import SimpleNamespace

import numpy as np
import pytest

from tools.wakeword.personalizar import Clip, training_data, cross_validate, speech_end, sustained


def clip(value, positive):
    variants = [(np.full((4, 2), value + offset), np.full(4, int(positive)), np.ones(4, bool), speed)
                for offset, speed in enumerate([90, 100, 110])]
    return Clip(str(value), positive, variants)


def test_validacao_exclui_todas_as_variacoes_da_gravacao():
    clips = [clip(10, True), clip(20, False), clip(30, True)]
    x, y = training_data(clips, [np.full((2, 2), -1)], excluded=[0])
    assert not np.isin(x, [10, 11, 12]).any()
    assert set(x[:, 0]) == {20, 21, 22, 30, 31, 32, -1}
    assert sum(y) == 12
    assert (y[-2:] == 0).all()


def test_cada_gravacao_e_avaliada_uma_vez_sem_participar_do_treino(monkeypatch):
    import tools.wakeword.personalizar as module
    clips = [clip(10, True), clip(20, True), clip(30, False), clip(40, False)]
    exclusions = []
    def fake_fit(data, backgrounds, excluded):
        exclusions.append(set(excluded))
        x, _ = training_data(data, backgrounds, excluded)
        for i in excluded:
            assert not np.isin(x, [int(data[i].name) + j for j in range(3)]).any()
        return SimpleNamespace(predict_proba=lambda x: np.tile([.9, .1], (len(x), 1)))
    monkeypatch.setattr(module, 'fit', fake_fit)
    rows = cross_validate(clips, [])
    assert exclusions == [{0, 2}, {1, 3}]
    assert sorted(r['arquivo'] for r in rows) == ['10', '20', '30', '40']
    assert all(not r['detectado'] for r in rows)


def test_delimitacao_rejeita_silencio_e_ruido_constante():
    for audio in [np.zeros(64000, dtype=np.int16), np.full(64000, 1200, dtype=np.int16)]:
        with pytest.raises(ValueError, match='ruido'):
            speech_end(audio)
    audio = np.zeros(64000, dtype=np.int16)
    audio[16000:24000] = 3000
    assert speech_end(audio) == 1.5


def test_pico_isolado_nao_e_pontuacao_sustentada():
    assert sustained([.1, .9, .1]) == .1
    assert sustained([.1, .8, .9, .1]) == .8
    assert sustained([]) == 0


@pytest.mark.parametrize('duplicate_recording', [False, True])
def test_gravacoes_renomeadas_nao_podem_vazar_na_validacao(tmp_path, monkeypatch, duplicate_recording):
    import tools.wakeword.personalizar as module
    source = tmp_path / 'coleta'
    backgrounds = tmp_path / 'fundos'
    backgrounds.mkdir()
    for kind in ['positivo', 'negativo']:
        (source / kind).mkdir(parents=True)
        for i in range(6):
            (source / kind / f'{i}.wav').write_bytes(f'{kind}:{i}'.encode())
    (backgrounds / 'renomeado.wav').write_bytes((source / 'negativo/0.wav').read_bytes())
    if duplicate_recording:
        (source / 'positivo/1.wav').write_bytes((source / 'positivo/0.wav').read_bytes())
    monkeypatch.setattr(module, 'load_model', lambda _: None)
    monkeypatch.setattr(module, 'prepare_clip', lambda path, positive, _: clip(10, positive))
    with pytest.raises(ValueError, match='duplicadas' if duplicate_recording else 'renomeadas'):
        module.train(source, tmp_path / 'base.onnx', tmp_path / 'saida', backgrounds)
    assert not (tmp_path / 'saida').exists()


@pytest.mark.parametrize('raw_threshold', [.5, .99])
def test_exportacao_onnx_preserva_classificador_e_corte_calibrado(tmp_path, raw_threshold):
    pytest.importorskip('onnx')
    ort = pytest.importorskip('onnxruntime')
    from tools.wakeword.personalizar import export
    rng = np.random.default_rng(42)
    classifier = SimpleNamespace(coef_=rng.normal(0, .01, (1, 1536)), intercept_=np.array([.2]))
    path = tmp_path / 'candidato.onnx'
    export(classifier, path, raw_threshold)
    session = ort.InferenceSession(str(path), providers=['CPUExecutionProvider'])
    audio_features = rng.normal(size=(1, 16, 96)).astype(np.float32)
    result = session.run(None, {'input': audio_features})[0]
    offset = np.log(raw_threshold / (1 - raw_threshold))
    expected = 1 / (1 + np.exp(-(audio_features.reshape(1, -1) @ classifier.coef_.T + classifier.intercept_ - offset)))
    np.testing.assert_allclose(result, expected, atol=1e-6)


def test_calibracao_aperta_corte_sem_aceitar_classes_sobrepostas():
    from tools.wakeword.personalizar import calibration_threshold
    rows = [{'positivo': True, 'pico_dois_frames': .997}, {'positivo': False, 'pico_dois_frames': .98}]
    assert .98 < calibration_threshold(rows) < .997
    rows[0]['pico_dois_frames'] = .97
    with pytest.raises(ValueError, match='sobrepoem'):
        calibration_threshold(rows)
