"""Todos os consumidores de rotinas usam a mesma pasta, independente do cwd."""
from pathlib import Path
import json
import os
import tempfile

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
ACTIVE_PATH = str(CONFIG_DIR / "routines.json")
DISCOVERED_PATH = str(CONFIG_DIR / "discovered_routines.json")
REJECTED_PATH = str(CONFIG_DIR / "rejected_routines.json")


def salvar_json(caminho, dados):
    """O executor só enxerga documentos completos durante uma atualização."""
    pasta = Path(caminho).parent
    pasta.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=pasta,
                                     suffix=".tmp", delete=False) as arquivo:
        temporario = arquivo.name
        try:
            json.dump(dados, arquivo, ensure_ascii=False, indent=2)
        except BaseException:
            arquivo.close()
            os.unlink(temporario)
            raise
    try:
        os.replace(temporario, caminho)
    finally:
        if os.path.exists(temporario):
            os.unlink(temporario)
