type VoiceAudio = Pick<HTMLAudioElement, 'play' | 'pause' | 'src' | 'onended' | 'onerror'>;
type VoiceDependencies = {
  fetchAudio: (text: string, signal: AbortSignal, streaming: boolean) => Promise<Response>;
  createAudio: (url: string) => VoiceAudio;
  createMediaSource?: () => MediaSource;
  createUrl: (media: Blob | MediaSource) => string;
  revokeUrl: (url: string) => void;
  speakLocal: (text: string) => Promise<unknown>;
  stopLocal: () => Promise<unknown>;
  onStarted?: (streaming: boolean) => void;
};

const MP3 = 'audio/mpeg';

function waitForMedia(target: EventTarget, event: string, signal: AbortSignal, start?: () => void) {
  return new Promise<void>((resolve, reject) => {
    const clear = () => {
      target.removeEventListener(event, done);
      target.removeEventListener('error', failed);
      signal.removeEventListener('abort', cancelled);
    };
    const done = () => { clear(); resolve(); };
    const failed = () => { clear(); reject(new Error('Falha no fluxo de áudio')); };
    const cancelled = () => { clear(); reject(signal.reason); };
    if (signal.aborted) return cancelled();
    target.addEventListener(event, done, { once: true });
    target.addEventListener('error', failed, { once: true });
    signal.addEventListener('abort', cancelled, { once: true });
    try { start?.(); } catch (error) { clear(); reject(error); }
  });
}

async function fillMediaSource(media: MediaSource, body: ReadableStream<Uint8Array>, signal: AbortSignal) {
  if (media.readyState !== 'open') await waitForMedia(media, 'sourceopen', signal);
  const buffer = media.addSourceBuffer(MP3);
  const reader = body.getReader();
  try {
    while (true) {
      signal.throwIfAborted();
      const chunk = await reader.read();
      if (chunk.done) break;
      await waitForMedia(buffer, 'updateend', signal, () => buffer.appendBuffer(new Uint8Array(chunk.value)));
    }
    if (!buffer.buffered.length) throw new Error('Resposta sem áudio');
    media.endOfStream();
  } finally {
    reader.releaseLock();
  }
}

/** Neural audio first, with cancellation shared by playback, download and local fallback. */
export class DesktopVoice {
  private generation = 0;
  private controller: AbortController | null = null;
  private audio: VoiceAudio | null = null;
  private url: string | null = null;
  private finish: (() => void) | null = null;
  private deps: VoiceDependencies;

  constructor(deps: VoiceDependencies) { this.deps = deps; }

  private clearMedia() {
    this.controller?.abort();
    this.controller = null;
    if (this.audio) {
      this.audio.onended = null;
      this.audio.onerror = null;
      this.audio.pause();
      this.audio.src = '';
      this.audio = null;
    }
    if (this.url) this.deps.revokeUrl(this.url);
    this.url = null;
    this.finish?.();
    this.finish = null;
  }

  async stop() {
    ++this.generation;
    this.clearMedia();
    await this.deps.stopLocal();
  }

  async speak(text: string): Promise<'neural' | 'local' | 'cancelled'> {
    const generation = ++this.generation;
    this.clearMedia();
    await this.deps.stopLocal().catch(() => {});
    if (generation !== this.generation) return 'cancelled';
    const controller = new AbortController();
    this.controller = controller;
    const timeout = setTimeout(() => controller.abort(), 15000);
    let started = false;
    try {
      const response = await this.deps.fetchAudio(text, controller.signal, Boolean(this.deps.createMediaSource));
      if (generation !== this.generation) return 'cancelled';
      const mime = response.headers.get('Content-Type')?.split(';')[0];
      if (!response.ok || !mime?.startsWith('audio/')) throw new Error('Resposta sem áudio');
      const source = mime === MP3 && response.body ? this.deps.createMediaSource?.() : undefined;
      const media = source ?? await response.blob();
      if (generation !== this.generation) return 'cancelled';
      if (media instanceof Blob && !media.size) throw new Error('Resposta sem áudio');
      this.url = this.deps.createUrl(media);
      const audio = this.deps.createAudio(this.url);
      this.audio = audio;
      const ended = new Promise<void>((resolve, reject) => {
        audio.onended = () => resolve();
        audio.onerror = () => reject(new Error('Falha na reprodução'));
      });
      const cancelled = new Promise<void>(resolve => { this.finish = resolve; });
      const pumping = source ? fillMediaSource(source, response.body!, controller.signal) : Promise.resolve();
      const playing = Promise.resolve().then(() => audio.play())
        .then(() => {
          started = true;
          clearTimeout(timeout);
          if (generation === this.generation) this.deps.onStarted?.(Boolean(source));
        });
      await Promise.race([cancelled, Promise.all([playing, pumping, ended])]);
      return generation === this.generation ? 'neural' : 'cancelled';
    } catch (error) {
      if (generation !== this.generation) return 'cancelled';
      this.clearMedia();
      if (started) throw error;
      await this.deps.speakLocal(text);
      return generation === this.generation ? 'local' : 'cancelled';
    } finally {
      clearTimeout(timeout);
      if (generation === this.generation) this.clearMedia();
    }
  }
}
