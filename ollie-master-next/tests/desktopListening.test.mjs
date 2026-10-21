import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DesktopListening } from '../src/desktopListening.ts';

const tick = () => new Promise(resolve => setImmediate(resolve));
function fixture(overrides = {}) {
  const events = [], calls = [], phases = [];
  let count = 0, reply;
  const control = new DesktopListening({
    newId: () => String(++count),
    start: async (id, device) => calls.push(['start', id, device]),
    stop: async id => calls.push(['stop', id]),
    control: async (id, action) => calls.push([action, id]),
    send: (text, signal) => {
      calls.push(['send', text]);
      return new Promise(resolve => { reply = resolve; });
    },
    speak: async text => calls.push(['speak', text]),
    stopSpeech: async () => calls.push(['stopSpeech']),
    phase: phase => phases.push(phase), partial: text => events.push(text), level() {},
    wake: () => events.push('wake'), error: message => events.push(message),
    ...overrides,
  });
  return { control, calls, events, phases, reply: text => reply(text), event: (type, extra = {}, id = String(count)) => control.receive({instance_id:id, type, ...extra}) };
}

test('voz faz pausa confirmada, envia uma vez e retoma depois da resposta falada', async () => {
  const f = fixture();
  await f.control.start(null);
  f.event('wake'); f.event('state', {state:'listening'});
  f.event('transcript', {text:'como esta a luz'});
  f.event('transcript', {text:'como esta a luz'});
  await tick();
  assert.equal(f.calls.filter(c => c[0] === 'send').length, 1);
  assert.ok(f.calls.findIndex(c => c[0] === 'pause') < f.calls.findIndex(c => c[0] === 'send'));
  assert.ok(!f.calls.some(c => c[0] === 'speak' || c[0] === 'resume'));
  f.reply('A luz esta ligada.'); await tick();
  assert.ok(f.calls.findIndex(c => c[0] === 'speak') < f.calls.findIndex(c => c[0] === 'resume'));
});

test('desativar durante espera impede fala e reativacao tardia', async () => {
  const f = fixture();
  await f.control.start(null);
  f.event('transcript', {text:'teste'}); await tick();
  await f.control.stop();
  f.reply('Resposta atrasada'); await tick();
  assert.ok(!f.calls.some(c => c[0] === 'speak' || c[0] === 'resume'));
  assert.equal(f.control.enabled, false);
});

test('eventos e respostas de instancia substituida nao controlam o novo microfone', async () => {
  const f = fixture();
  await f.control.start(1);
  f.event('transcript', {text:'antigo'}); await tick();
  await f.control.start(7);
  f.event('wake', {}, '1');
  f.reply('antiga'); await tick();
  assert.ok(!f.events.includes('wake'));
  assert.ok(!f.calls.some(c => c[0] === 'speak' || c[0] === 'resume'));
  assert.equal(f.control.enabled, true);
});

test('reproducao externa so comeca depois do ACK de pausa e termina antes da retomada', async () => {
  let releasePause, finishSpeech;
  const f = fixture({
    control: async (id, action) => {
      f.calls.push([action]);
      if (action === 'pause') await new Promise(resolve => { releasePause = resolve; });
    },
    speak: async text => { f.calls.push(['speak']); await new Promise(resolve => { finishSpeech = resolve; }); },
  });
  await f.control.start(null);
  const spoken = f.control.speakExternal('Ola'); await tick();
  assert.ok(!f.calls.some(c => c[0] === 'speak'));
  releasePause(); await tick();
  assert.ok(f.calls.some(c => c[0] === 'speak'));
  assert.ok(!f.calls.some(c => c[0] === 'resume'));
  finishSpeech(); await spoken;
  assert.ok(f.calls.some(c => c[0] === 'resume'));
});

test('ausencia de fala e falha de rede retomam escuta sem inventar comandos', async () => {
  const f = fixture({send: async () => { throw new Error('Sem rede'); }});
  await f.control.start(null);
  f.event('no_speech', {message:'Nao ouvi'}); await tick();
  assert.ok(!f.calls.some(c => c[0] === 'send'));
  f.event('transcript', {text:'teste'}); await tick();
  assert.ok(f.events.some(e => String(e).includes('Sem rede')));
  assert.equal(f.calls.filter(c => c[0] === 'resume').length, 2);
});

test('cancelar a conversa impede a resposta antiga de falar ou retomar novamente', async () => {
  const f = fixture();
  await f.control.start(null);
  f.event('transcript', {text:'antigo'}); await tick();
  await f.control.cancel();
  f.reply('atrasado'); await tick();
  assert.ok(!f.calls.some(c => c[0] === 'speak'));
  assert.equal(f.calls.filter(c => c[0] === 'resume').length, 1);
});
