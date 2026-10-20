import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DesktopReplies } from '../src/desktopReplies.ts';

test('speaks replies to desktop requests once, even after a WebSocket replay', () => {
  const replies = new DesktopReplies();
  replies.expect('pc-request', 100);
  const response = { tipo_ws: 'CHAT_RESPONSE', correlacao_id: 'pc-request', dispositivo_destino: 'PC', id: 'answer', texto: 'A luz está apagada.' };
  assert.equal(replies.consume(response, 200), 'A luz está apagada.');
  assert.equal(replies.consume(response, 201), null);
  assert.equal(replies.consume({ ...response, id: 'follow-up', texto: 'Mais um resultado.' }, 300), 'Mais um resultado.');
});

test('does not speak mobile conversations, proactive alerts or expired requests', () => {
  const replies = new DesktopReplies();
  replies.expect('pc-request', 100);
  const response = { tipo_ws: 'CHAT_RESPONSE', correlacao_id: 'pc-request', texto: 'Olá' };
  assert.equal(replies.consume({ ...response, correlacao_id: 'mobile-request' }, 200), null);
  assert.equal(replies.consume({ ...response, dispositivo_destino: 'MOBILE' }, 200), null);
  assert.equal(replies.consume({ ...response, tipo_ws: 'NOTIFICACAO' }, 200), null);
  assert.equal(replies.consume(response, 300101), null);
});

test('legacy responses without a device are accepted only with matching correlation', () => {
  const replies = new DesktopReplies();
  assert.equal(replies.consume({ tipo_ws: 'CHAT_RESPONSE', texto: 'Alerta' }), null);
  replies.expect('legacy');
  assert.equal(replies.consume({ tipo_ws: 'CHAT_RESPONSE', correlacao_id: 'legacy', texto: 'Resposta' }), 'Resposta');
});
