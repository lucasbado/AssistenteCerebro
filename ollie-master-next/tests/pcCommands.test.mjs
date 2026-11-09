import { test } from 'node:test';
import assert from 'node:assert/strict';
import { pcCommandParam, readFileResult, readSystemResult, readWindowResult, readInterfaceResult } from '../src/pcCommands.ts';

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

test('forwards only window labels and checks the count matches the request', () => {
  const window = { titulo: 'Nota de teste', processo: 'notepad.exe' };
  const raw = JSON.stringify({ janelas: [{ ...window, id: 42 }], total: 1 });
  assert.deepEqual(readWindowResult(raw, 'janela_ativa'), { janelas: [window], total: 1 });
  assert.throws(() => readWindowResult('{"janelas":[],"total":2}', 'listar_janelas'));
  assert.throws(() => readWindowResult(JSON.stringify({ janelas: [window], total: 2 }), 'janela_ativa'));
});

test('forwards control labels and states without values or coordinates', () => {
  const control = { tipo: 'menu', nome: 'Arquivo', habilitado: true };
  const result = { estado: 'lida', janela: 'Teste', itens: [control], parcial: false };
  const raw = JSON.stringify({ ...result, itens: [{ ...control, x: 42, valor: 'privado' }] });
  assert.deepEqual(readInterfaceResult(raw), result);
  assert.throws(() => readInterfaceResult(JSON.stringify({ ...result, itens: [{ ...control, habilitado: 1 }] })));
});
