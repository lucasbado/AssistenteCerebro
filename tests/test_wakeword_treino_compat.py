import ast
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from tools.wakeword.treino_compat import (
    TRAIN_LOADER,
    VALIDATION_LOADER,
    improve_training_source,
)


def source_fixture():
    return 'if True:\n' + TRAIN_LOADER + '\n' + VALIDATION_LOADER + '\n'


def window_dataset_class():
    """Executa a classe emitida, sem exigir PyTorch no backend da Ollie."""
    tree = ast.parse(improve_training_source(source_fixture()))
    definition = next(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef))
    namespace = {
        'np': np,
        'torch': SimpleNamespace(
            utils=SimpleNamespace(data=SimpleNamespace(Dataset=object)),
            from_numpy=lambda value: value,
            tensor=lambda value, dtype: np.float32(value),
            float32='float32',
        ),
    }
    exec(compile(ast.Module(body=[definition], type_ignores=[]), '<windows>', 'exec'), namespace)
    return namespace['FalsePositiveWindows']


def test_all_validation_windows_and_labels_match_original(tmp_path):
    original = np.arange(65 * 96, dtype=np.float32).reshape(65, 96)
    path = tmp_path / 'validation.npy'
    np.save(path, original)
    dataset = window_dataset_class()(path, 16)
    expected = np.array([original[index:index+16] for index in range(65-16)])
    assert len(dataset) == len(expected)
    assert isinstance(dataset.features, np.memmap)
    for index, window in enumerate(expected):
        actual, label = dataset[index]
        np.testing.assert_array_equal(actual, window)
        assert actual.dtype == np.float32
        assert label == 0
        assert actual.flags.writeable
        assert not np.shares_memory(actual, dataset.features)
    for index in (-1, len(dataset)):
        with pytest.raises(IndexError):
            dataset[index]


@pytest.mark.parametrize('shape', [(16, 96), (15, 96), (3, 16, 96)])
def test_validation_rejects_invalid_dimensions(tmp_path, shape):
    path = tmp_path / 'invalid.npy'
    np.save(path, np.zeros(shape, dtype=np.float32))
    with pytest.raises(ValueError):
        window_dataset_class()(path, 16)


def test_loaders_are_bounded_without_changing_training_steps_or_duration():
    source = source_fixture() + '\n# steps remain 10000; val_set_hrs remains 11.3\n'
    revised = improve_training_source(source)
    ast.parse(revised)
    assert revised.count('num_workers=0') == 2
    assert 'prefetch_factor' not in revised
    assert 'batch_size=2048' in revised
    assert 'shuffle=False' in revised
    assert 'steps remain 10000; val_set_hrs remains 11.3' in revised


@pytest.mark.parametrize('source', ['', source_fixture().replace('prefetch_factor=16', 'prefetch_factor=8'),
                                    source_fixture() + '\n' + VALIDATION_LOADER])
def test_changed_upstream_fails_clearly(source):
    with pytest.raises(RuntimeError, match='CLI de treino mudou'):
        improve_training_source(source)


def test_pinned_source_is_compatible_when_available():
    upstream = Path('.artifacts/wakeword/repro-import/openwakeword/openwakeword/train.py')
    if not upstream.is_file():
        pytest.skip('O clone de reproducao local nao faz parte do repositorio.')
    original = upstream.read_text(encoding='utf-8')
    revised = improve_training_source(original)
    ast.parse(revised)
    assert original.count('val_set_hrs = 11.3') == revised.count('val_set_hrs = 11.3')
    assert original.count('steps=config["steps"]') == revised.count('steps=config["steps"]')
