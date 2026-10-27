"""Backup somente de leitura no HA. Não altera nem recarrega automações/scripts."""
import argparse
import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


async def backup(pasta, env=None):
    env = env or dotenv_values(ROOT / '.env')
    if not env.get('HA_URL') or not env.get('HA_TOKEN'):
        raise ValueError('Configure HA_URL e HA_TOKEN sem passá-los na linha de comando')
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=False)  # Nunca substitui um backup anterior.
    async with httpx.AsyncClient(timeout=10, headers={'Authorization': 'Bearer ' + env['HA_TOKEN']}) as client:
        base = env['HA_URL'].rstrip('/')
        response = await client.get(base + '/api/states/automation.controle_de_midia_mesa_touch_esp32')
        response.raise_for_status()
        ident = response.json()['attributes']['id']
        if not str(ident).replace('_', '').replace('-', '').isalnum():
            raise ValueError('ID de automação inválido')
        arquivos = {}
        for nome, caminho in [('mesa-touch.json', '/api/config/automation/config/' + str(ident)),
                              ('feedback-visual.json', '/api/config/script/config/ollie_feedback_visual')]:
            response = await client.get(base + caminho)
            response.raise_for_status()
            content = (json.dumps(response.json(), ensure_ascii=False, indent=2) + '\n').encode('utf-8')
            with (pasta / nome).open('xb') as file:
                file.write(content)
            arquivos[nome] = {'sha256': hashlib.sha256(content).hexdigest(), 'origem': caminho}
        with (pasta / 'manifesto.json').open('x', encoding='utf-8') as file:
            json.dump({'criado_utc': datetime.now(timezone.utc).isoformat(), 'arquivos': arquivos}, file, indent=2)
    return pasta


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pasta', type=Path, default=ROOT / '.artifacts' / ('backup-audio-ha-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')))
    args = parser.parse_args()
    print(asyncio.run(backup(args.pasta)))
