"""Executa uma etapa mostrando a saída e inclui a causa no erro final do Colab."""
from collections import deque
from pathlib import Path
import os
import subprocess


class StageError(RuntimeError):
    """Falha com o final do log anexado, em vez de só um código de saída."""


def run_logged(command, *, log_path, cwd=None, tail_lines=40):
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    tail = deque(maxlen=tail_lines)
    # O kernel do Colab usa matplotlib_inline; o Python isolado não usa interface gráfica.
    environment = dict(os.environ, PYTHONUNBUFFERED='1', PYTHONIOENCODING='utf-8', MPLBACKEND='Agg')
    with log_path.open('w', encoding='utf-8') as log:
        with subprocess.Popen(list(map(str, command)), cwd=cwd, env=environment,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding='utf-8', errors='replace', bufsize=1) as process:
            try:
                for line in process.stdout:
                    print(line, end='', flush=True)
                    log.write(line)
                    log.flush()
                    tail.append(line)
                code = process.wait()
            except BaseException:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                raise
    if code:
        detail = ''.join(tail).strip() or '(O processo não produziu saída.)'
        raise StageError(f'Etapa falhou (código {code}). Log completo: {log_path}\n'
                         f'Últimas linhas da causa:\n{detail}')
