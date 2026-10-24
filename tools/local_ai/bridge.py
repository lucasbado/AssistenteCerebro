"""Helper do desktop: JSON no stdin/stdout, Ollama fixo em loopback."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / '.artifacts/local_ai'
URL = 'http://127.0.0.1:11434'


def requisitar(path, payload=None, timeout=2):
    # Ignora proxies de ambiente: a inferência nunca sai da interface loopback.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(URL + path, data=None if payload is None else json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json'})
    with opener.open(req, timeout=timeout) as resp: return json.load(resp)


def modelo_configurado():
    config = json.loads((LOCAL / 'config.json').read_text(encoding='utf-8'))
    modelo = config.get('model')
    if config.get('enabled') is not True or not isinstance(modelo, str) or not modelo or len(modelo) > 100:
        raise ValueError('IA local não habilitada.')
    return modelo


def garantir_servidor():
    try:
        requisitar('/api/version')
        return
    except Exception: pass
    executable = LOCAL / 'runtime/ollama.exe'
    if os.name != 'nt' or not executable.is_file(): raise ValueError('Ollama local não está iniciado.')
    env = dict(os.environ, OLLAMA_HOST='127.0.0.1:11434', OLLAMA_MODELS=str(LOCAL / 'models'),
        OLLAMA_NO_CLOUD='1', OLLAMA_NUM_PARALLEL='1', OLLAMA_MAX_LOADED_MODELS='1', OLLAMA_KEEP_ALIVE='2m')
    with (LOCAL / 'server.log').open('ab') as log:
        subprocess.Popen([str(executable), 'serve'], cwd=LOCAL, env=env, stdin=subprocess.DEVNULL,
            stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
    for _ in range(10):
        try:
            requisitar('/api/version', timeout=.3)
            return
        except Exception: time.sleep(.2)
    raise ValueError('Ollama ainda não está pronto.')


def processar(dados):
    modelo = modelo_configurado()
    garantir_servidor()
    if dados.get('modo') == 'probe':
        nomes = {m['name'] for m in requisitar('/api/tags').get('models', [])}
        return {'disponivel': modelo in nomes, 'modelo': modelo}
    if dados.get('modo') != 'generate': raise ValueError('Operação inválida.')
    prompt, system = dados.get('prompt'), dados.get('system')
    if not isinstance(prompt, str) or not isinstance(system, str) or len(prompt) + len(system) > 30000:
        raise ValueError('Contexto inválido para IA local.')
    tokens = dados.get('max_tokens', 900)
    if not isinstance(tokens, int) or not 1 <= tokens <= 1200: raise ValueError('Limite de resposta inválido.')
    resultado = requisitar('/api/generate', dict(model=modelo, prompt=prompt, system=system,
        stream=False, format='json', keep_alive='2m', options=dict(temperature=.1, num_ctx=8192, num_predict=tokens)), timeout=45)
    texto = resultado.get('response')
    if not isinstance(texto, str) or not texto or len(texto) > 24000 or not isinstance(json.loads(texto), dict):
        raise ValueError('Modelo não devolveu um objeto JSON válido.')
    return dict(texto=texto, modelo=modelo, entrada=resultado.get('prompt_eval_count', 0), saida=resultado.get('eval_count', 0))


if __name__ == '__main__':
    try:
        dados = sys.stdin.buffer.read(200001)
        if len(dados) > 200000: raise ValueError('Pedido muito grande.')
        print(json.dumps(processar(json.loads(dados)), ensure_ascii=True))
    except Exception as erro:
        # Erro curto e sem prompts, credenciais ou conteúdo da resposta.
        print(json.dumps({'erro': type(erro).__name__}))
        sys.exit(1)
