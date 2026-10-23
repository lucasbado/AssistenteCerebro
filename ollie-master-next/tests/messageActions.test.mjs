import { test } from 'node:test';
import assert from 'node:assert/strict';
import { decodeMessageActions } from '../src/messageActions.ts';
test('routine opens the inbox, while malformed message references are discarded', () => {
  const inbox = { id: 'pendentes', texto: 'Revisar mensagens' };
  const message = { id: 'e6533b8b-3f96-4e5e-94b1-b02be3a1efcb', texto: 'Contato' };
  assert.deepEqual(decodeMessageActions([inbox, message, { id: '../outro', texto: 'Abrir' }, null]), [inbox, message]);
});
