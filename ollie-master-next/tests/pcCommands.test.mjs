import { test } from 'node:test';
import assert from 'node:assert/strict';
import { pcCommandParam, readFileResult, readSystemResult } from '../src/pcCommands.ts';

test('preserves structured input from Wear and legacy PC clients', () => {
  assert.equal(pcCommandParam('mouse_move', { dx: 0, dy: -12, parametro: '' }), '0,-12');
  assert.equal(pcCommandParam('mouse_scroll', { quantidade: 0 }), '0');
  assert.equal(pcCommandParam('mouse_click', { botao: 'right', parametro: '' }), 'right');
  assert.equal(pcCommandParam('volume_canal', { canal: 0, valor: 0 }), '0,0');
});

test('returns structured file confirmation and rejects older helpers without it', () => {
  const result = { arquivo: { estado: 'janela_confirmada', itens: ['Downloads/teste.pdf'] } };
  assert.deepEqual(readFileResult(JSON.stringify(result)), result);
  assert.throws(() => readFileResult('{"status":"ok"}'));
});

test('forwards only valid CPU, memory and disk percentages', () => {
  assert.deepEqual(readSystemResult('{"sistema":{"cpu":0,"ram":55,"disco":75}}'),
    { sistema: { cpu: 0, ram: 55, disco: 75 } });
  assert.throws(() => readSystemResult('{"sistema":{"cpu":101,"ram":55,"disco":75}}'));
});
