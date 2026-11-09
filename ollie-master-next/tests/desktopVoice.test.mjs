import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DesktopVoice } from '../src/desktopVoice.ts';

function player(fetchAudio, extra = {}) {
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
    ...extra,
  });
  return { voice, local, revoked, audios, stops: () => stops };
}
const audio = () => new Response('mp3', { headers: { 'Content-Type': 'audio/mpeg' } });
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
  for (const fetch of [async () => { throw new Error('offline'); }, async () => new Response('error')]) {
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

function streamPlayer() {
  let stream;
  const body = new ReadableStream({ start: controller => { stream = controller; } });
  const buffer = new EventTarget();
  const appended = [];
  buffer.buffered = { length: 0 };
  let begin;
  const firstAudio = new Promise(resolve => { begin = resolve; });
  buffer.appendBuffer = bytes => {
    appended.push(...bytes);
    buffer.buffered.length = 1;
    buffer.dispatchEvent(new Event('updateend'));
    begin();
  };
  let finished = false;
  const p = player(async (_, _signal, streaming) => {
    assert.equal(streaming, true);
    return new Response(body, { headers: { 'Content-Type': 'audio/mpeg' } });
  }, {
    createMediaSource: () => ({
      readyState: 'open', addSourceBuffer: () => buffer, endOfStream: () => { finished = true; },
    }),
    createAudio: src => {
      const audio = { src, onended: null, onerror: null, pause() {},
        async play() { await firstAudio; this.started = true; } };
      p.audios.push(audio);
      return audio;
    },
  });
  return { ...p, stream, appended, finished: () => finished };
}

test('plays the first neural block while the response is still downloading', async () => {
  const p = streamPlayer();
  const spoken = p.voice.speak('Resposta');
  p.stream.enqueue(Uint8Array.of(1));
  await tick();
  assert.deepEqual(p.appended, [1]);
  assert.equal(p.audios[0].started, true);
  assert.equal(p.finished(), false);
  p.stream.enqueue(Uint8Array.of(2));
  p.stream.close();
  await tick();
  assert.equal(p.finished(), true);
  p.audios[0].onended();
  assert.equal(await spoken, 'neural');
});

test('a broken stream does not repeat speech that has already started', async () => {
  const p = streamPlayer();
  const spoken = p.voice.speak('Resposta');
  p.stream.enqueue(Uint8Array.of(1));
  await tick();
  p.stream.error(new Error('Conexão interrompida'));
  await assert.rejects(spoken, /Conexão interrompida/);
  assert.deepEqual(p.local, []);
});
