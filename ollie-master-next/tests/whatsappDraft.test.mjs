import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readWhatsAppDraft, whatsappDraftUrl } from '../src/whatsappDraft.ts';

test('opens only the official WhatsApp origin and keeps the literal text in one parameter', () => {
  const texto = 'Oi, Ana!\nCafé às 18h? 🙂 &phone=outra';
  const draft = readWhatsAppDraft('pedido', JSON.stringify({ numero: '12025550142', texto }));
  const url = new URL(whatsappDraftUrl(draft));
  assert.equal(url.origin, 'https://wa.me');
  assert.equal(url.pathname, '/12025550142');
  assert.deepEqual([...url.searchParams], [['text', texto]]);
});

test('rejects missing identifiers, bad recipients and blank bodies', () => {
  const data = { numero: '12025550142', texto: 'Oi' };
  assert.throws(() => readWhatsAppDraft('', JSON.stringify(data)));
  assert.throws(() => readWhatsAppDraft('pedido', JSON.stringify({ ...data, numero: '../malicioso' })));
  assert.throws(() => readWhatsAppDraft('pedido', JSON.stringify({ ...data, texto: ' ' })));
});
