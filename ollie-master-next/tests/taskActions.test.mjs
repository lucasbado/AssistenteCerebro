import { test } from 'node:test';
import assert from 'node:assert/strict';
import { decodeTaskActions, taskDeadline } from '../src/taskActions.ts';

test('chat accepts actionable task IDs and ignores malformed server data', () => {
  const valid = { id: '3e4a7322-0201-49f7-82e2-224e81c0595a', texto: 'Comprar pão', quando: 'Sem prazo' };
  assert.deepEqual(decodeTaskActions([null, valid, { ...valid, id: '../outro' }, { ...valid, texto: '' }]), [valid]);
  assert.deepEqual(decodeTaskActions({}), []);
});

test('task with no deadline stays undated, and a clock time requires its date', () => {
  assert.deepEqual(taskDeadline('', ''), { prazo: null, dia_inteiro: false });
  assert.throws(() => taskDeadline('', '15:00'));
});

test('manual deadlines do not silently roll impossible dates into another month', () => {
  assert.throws(() => taskDeadline('2030-02-30', '15:00'));
  const date = taskDeadline('2030-10-23', '15:00');
  assert.equal(new Date(date.prazo).getHours(), 15);
  assert.equal(date.dia_inteiro, false);
  assert.equal(taskDeadline('2030-10-23', '').dia_inteiro, true);
});
