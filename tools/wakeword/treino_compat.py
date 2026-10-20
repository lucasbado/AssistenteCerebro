"""Adaptacao localizada do CLI fixado do openWakeWord para memoria limitada.

O clone original permanece intacto. A validacao mantem todas as janelas e a
duracao original; somente a leitura e a inferencia passam a ocorrer em lotes.
"""

TRAIN_LOADER = '''        X_train = torch.utils.data.DataLoader(IterDataset(batch_generator),
                                              batch_size=None, num_workers=n_cpus, prefetch_factor=16)'''

TRAIN_LOADER_SAFE = '''        # Um unico leitor mantem a posicao do gerador entre as tres sequencias.
        # Evita replicar o mmap/gerador e pre-carregar dezenas de lotes por worker.
        X_train = torch.utils.data.DataLoader(IterDataset(batch_generator),
                                              batch_size=None, num_workers=0)'''

VALIDATION_LOADER = '''        X_val_fp = np.load(config["false_positive_validation_data_path"])
        X_val_fp = np.array([X_val_fp[i:i+input_shape[0]] for i in range(0, X_val_fp.shape[0]-input_shape[0], 1)])  # reshape to match model
        X_val_fp_labels = np.zeros(X_val_fp.shape[0]).astype(np.float32)
        X_val_fp = torch.utils.data.DataLoader(
            torch.utils.data.TensorDataset(torch.from_numpy(X_val_fp), torch.from_numpy(X_val_fp_labels)),
            batch_size=len(X_val_fp_labels)
        )'''

VALIDATION_LOADER_SAFE = '''        class FalsePositiveWindows(torch.utils.data.Dataset):
            """Todas as janelas originais, sem materializar copias de todo o corpus."""
            def __init__(self, path, width):
                self.features = np.load(path, mmap_mode="r", allow_pickle=False)
                self.width = width
                if self.features.ndim != 2 or self.features.shape[0] <= width:
                    raise ValueError("Corpus de validacao precisa ser uma matriz maior que a janela.")

            def __len__(self):
                # Mantem exatamente range(0, n_frames - width, 1) do CLI original.
                return self.features.shape[0] - self.width

            def __getitem__(self, index):
                if index < 0 or index >= len(self):
                    raise IndexError(index)
                window = np.array(self.features[index:index+self.width], dtype=np.float32, copy=True)
                return torch.from_numpy(window), torch.tensor(0.0, dtype=torch.float32)

        X_val_fp = torch.utils.data.DataLoader(
            FalsePositiveWindows(config["false_positive_validation_data_path"], input_shape[0]),
            batch_size=2048, num_workers=0, shuffle=False
        )'''


def improve_training_source(source):
    """Falha explicitamente se a revisao externa nao tiver os trechos esperados."""
    for original, replacement in (
        (TRAIN_LOADER, TRAIN_LOADER_SAFE),
        (VALIDATION_LOADER, VALIDATION_LOADER_SAFE),
    ):
        if source.count(original) != 1:
            raise RuntimeError('O CLI de treino mudou. Revise os carregadores antes de continuar.')
        source = source.replace(original, replacement, 1)
    return source
