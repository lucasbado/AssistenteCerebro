import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createAudioQueue } from '../src/audioControl.ts';

test('gestos de audio conservam ordem mesmo com helpers demorados', async () => {
  const order = []; let release;
  const q = createAudioQueue(async param => {
    order.push(param);
    if (param === 'modo') await new Promise(r => { release = r; });
    return JSON.stringify({ status: 'concluido', codigo: param });
  });
  const first = q('modo'), second = q('volume');
  await new Promise(r => setImmediate(r));
  assert.deepEqual(order, ['modo']);
  release();
  assert.equal((await first).codigo, 'modo');
  assert.equal((await second).codigo, 'volume');
  assert.deepEqual(order, ['modo', 'volume']);
});

test('falha nao trava a fila e resultado parcial permanece explicito', async () => {
  const q = createAudioQueue(async p => p === 'invalid' ? '{}' : '{"status":"parcial","codigo":"alteracao_nao_confirmada"}');
  await assert.rejects(q('invalid'), /inválido/);
  assert.equal((await q('next')).status, 'parcial');
});
