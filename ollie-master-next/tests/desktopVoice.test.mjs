import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DesktopVoice } from '../src/desktopVoice.ts';

function player(fetchAudio) {
  const local = [], revoked = [], audios = [];
  let stops = 0;
  const voice = new DesktopVoice({
    fetchAudio,
    createAudio: src => {
      const audio = { src, onended: null, onerror: null, pause() { this.paused = true; },
        async play() { this.started = true; } };
      audios.push(audio);
      return audio;
    },
    createUrl: () => 'blob:voice', revokeUrl: url => revoked.push(url),
    speakLocal: async text => { local.push(text); }, stopLocal: async () => { ++stops; },
  });
  return { voice, local, revoked, audios, stops: () => stops };
}
const audio = () => new Blob(['mp3'], { type: 'audio/mpeg' });
const tick = () => new Promise(resolve => setImmediate(resolve));

test('uses neural audio and releases media when playback ends', async () => {
  const p = player(async () => audio());
  const spoken = p.voice.speak('Olá');
  await tick();
  assert.equal(p.audios[0].started, true);
  p.audios[0].onended();
  assert.equal(await spoken, 'neural');
  assert.deepEqual(p.local, []);
  assert.deepEqual(p.revoked, ['blob:voice']);
});

test('uses Windows voice when the server fails or returns non-audio', async () => {
  for (const fetch of [async () => { throw new Error('offline'); }, async () => new Blob(['error'], { type: 'text/html' })]) {
    const p = player(fetch);
    assert.equal(await p.voice.speak('Resposta'), 'local');
    assert.deepEqual(p.local, ['Resposta']);
  }
});

test('muting while downloading prevents late audio and fallback speech', async () => {
  let finish;
  const p = player(() => new Promise(resolve => { finish = resolve; }));
  const spoken = p.voice.speak('Resposta');
  await tick();
  await p.voice.stop();
  finish(audio());
  assert.equal(await spoken, 'cancelled');
  assert.equal(p.audios.length, 0);
  assert.deepEqual(p.local, []);
});

test('muting during playback pauses, releases the URL and finishes the request', async () => {
  const p = player(async () => audio());
  const spoken = p.voice.speak('Resposta');
  await tick();
  await p.voice.stop();
  assert.equal(await spoken, 'cancelled');
  assert.equal(p.audios[0].paused, true);
  assert.deepEqual(p.local, []);
  assert.deepEqual(p.revoked, ['blob:voice']);
});

test('a newer response cancels the old download without speaking it', async () => {
  let finish;
  const p = player(text => text === 'antiga' ? new Promise(resolve => { finish = resolve; }) : Promise.resolve(audio()));
  const old = p.voice.speak('antiga');
  await tick();
  const current = p.voice.speak('nova');
  await tick();
  finish(audio());
  assert.equal(await old, 'cancelled');
  assert.equal(p.audios.length, 1);
  p.audios[0].onended();
  assert.equal(await current, 'neural');
  assert.deepEqual(p.local, []);
});
