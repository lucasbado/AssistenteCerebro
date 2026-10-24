import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createLocalAiBridge } from '../src/localAiBridge.ts';

const request = { tipo_ws: 'IA_SOLICITACAO', id: '00000000-0000-4000-8000-000000000001', prompt: 'Uma pergunta', system: 'JSON', max_tokens: 500 };
test('IA local responde com a correlação recebida e não repete uma inferência', async () => {
  let calls = 0;
  const bridge = createLocalAiBridge(async () => { calls++; return { texto: '{"resposta":"Olá"}', modelo: 'teste', entrada: 10, saida: 5 }; });
  const sent = [];
  await bridge(request, r => sent.push(r)); await bridge(request, r => sent.push(r));
  assert.equal(calls, 1); assert.equal(sent.length, 1);
  assert.equal(sent[0].id, request.id); assert.equal(sent[0].tipo_ws, 'IA_RESULTADO');
  assert.equal(sent[0].status, 'concluido');
});
test('pedidos inválidos não chegam ao modelo e ocupação não acumula fila', async () => {
  let finish;
  const bridge = createLocalAiBridge(() => new Promise(r => { finish = r; }));
  const sent = [];
  await bridge({ ...request, max_tokens: 90000 }, r => sent.push(r));
  const first = bridge(request, r => sent.push(r));
  await bridge({ ...request, id: '00000000-0000-4000-8000-000000000002' }, r => sent.push(r));
  assert.equal(sent[0].status, 'ocupado');
  finish({ texto: '{}', modelo: 'teste', entrada: 0, saida: 0 }); await first;
});
test('falha do modelo é devolvida como erro, sem executar comando ou fabricar resposta', async () => {
  const bridge = createLocalAiBridge(async () => { throw Error('falha'); });
  const sent = []; await bridge(request, r => sent.push(r));
  assert.equal(sent[0].status, 'erro'); assert.equal(sent[0].texto, undefined);
});
