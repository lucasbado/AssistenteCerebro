"""Gera o notebook guiado; hashes impedem executar helpers diferentes dos revisados."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def cell(kind, source):
    result = {'cell_type': kind, 'metadata': {}, 'source': source.splitlines(keepends=True)}
    if kind == 'code':
        result.update(execution_count=None, outputs=[])
    return result


def generate():
    hashes = {name: hashlib.sha256((HERE / name).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
              for name in ['colab_ollie.py', 'requirements-treino.txt']}
    setup = '''# @title 1. Preparar ambiente compatível (Python 3.11 separado)
import hashlib, json, subprocess, sys, urllib.request
from pathlib import Path
ROOT = Path('/content/ollie-wakeword')
ROOT.mkdir(exist_ok=True)
EXPECTED = HASHES
BASE = 'https://raw.githubusercontent.com/lucasbado/AssistenteCerebro/main/tools/wakeword/'
for name, expected in EXPECTED.items():
    with urllib.request.urlopen(BASE + name, timeout=60) as response:
        content = response.read()
    if hashlib.sha256(content).hexdigest() != expected:
        raise RuntimeError('O código mudou. Reabra a versão atual do notebook antes de continuar.')
    (ROOT / name).write_bytes(content)
subprocess.run([sys.executable, '-m', 'pip', 'install', 'uv==0.8.22'], check=True)
PY = ROOT / 'env/bin/python'
if not PY.exists():
    subprocess.run([sys.executable, '-m', 'uv', 'venv', '--seed', '--python', '3.11', str(ROOT / 'env')], check=True)
def etapa(nome, *argumentos):
    subprocess.run([str(PY), str(ROOT / 'colab_ollie.py'), nome, *map(str, argumentos)], check=True)
etapa('preparar')
'''.replace('HASHES', repr(hashes))
    preview = '''# @title 2. Ouvir a chamada antes de treinar
frase = "hey ollie" # @param {type:"string"}
etapa('previa', '--frase', frase)
from IPython.display import Audio, display
previa = json.loads((ROOT / 'previa.json').read_text())
display(Audio(filename=previa['audio']))
print('Ouça o player. Se o nome sair diferente, experimente hey_oh_lee e execute esta célula novamente.')
'''
    data = '''# @title 3. Baixar dados de ambiente e exemplos negativos
etapa('dados')
'''
    train = '''# @title 4. Treinar Hey Ollie (só depois de ouvir a prévia)
ouvi_e_aprovei_a_pronuncia = False # @param {type:"boolean"}
exemplos = 1000 # @param {type:"integer"}
passos = 10000 # @param {type:"integer"}
if not ouvi_e_aprovei_a_pronuncia:
    raise RuntimeError('Ouça o áudio da etapa 2 e marque a caixa antes de iniciar o treino.')
etapa('treinar', '--frase', frase, '--exemplos', exemplos, '--passos', passos)
'''
    export = '''# @title 5. Baixar modelo ONNX e informações do treino
from google.colab import files
resultado = json.loads((ROOT / 'ultimo_modelo.json').read_text())
print(resultado['validacao'])
files.download(resultado['modelo'])
files.download(str(ROOT / 'ultimo_modelo.json'))
'''
    notebook = {
        'nbformat': 4, 'nbformat_minor': 5,
        'metadata': {'colab': {'name': 'Treinar Hey Ollie', 'provenance': []},
                     'kernelspec': {'name': 'python3', 'display_name': 'Python 3'}, 'accelerator': 'GPU'},
        'cells': [cell('markdown', '''# Treinar “Hey Ollie” — Ollie

Execute os botões ▶ em ordem. Este notebook evita o erro de dependências no Python 3.13,
usando Python 3.11 separado. O ambiente padrão do Colab não é substituído.

Selecione **Ambiente de execução → Alterar tipo → GPU T4**, se disponível gratuitamente.
Não contrate créditos para este experimento. Se uma etapa falhar, pare nela e envie o erro.

O treino usa vozes sintéticas e dados públicos, sem tokens ou gravações pessoais.
Os dados podem ocupar dezenas de GB. O resultado é um primeiro modelo experimental
para uso pessoal não comercial; não comprova o reconhecimento da sua pronúncia.
Baseado no [treinamento oficial openWakeWord](https://github.com/dscripka/openWakeWord#training-new-models)
e no gerador [Piper](https://github.com/rhasspy/piper-sample-generator).
'''), cell('code', setup), cell('code', preview),
                  cell('markdown', 'Antes de continuar, ouça a prévia. A grafia é apenas uma forma de gerar o som desejado.\n'),
                  cell('code', data), cell('code', train), cell('code', export),
                  cell('markdown', '''## Depois do download

No PC, abra PowerShell na pasta `D:\\Programacao\\AssistenteCell` e execute:

```powershell
.\\tools\\wakeword\\ouvir.ps1 -Modelo "$env:USERPROFILE\\Downloads\\hey_ollie.onnx"
```

Esse teste somente mostra as chamadas detectadas. Ctrl+C encerra.
Depois validaremos pronúncia, falsos disparos e integração com o Android em português.
''')],
    }
    for index, item in enumerate(notebook['cells']):
        item['id'] = f'ollie-{index}'
        if item['cell_type'] == 'code':
            item['metadata']['cellView'] = 'form'
    target = HERE / 'treinar_ollie.ipynb'
    target.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(target)


if __name__ == '__main__':
    generate()
