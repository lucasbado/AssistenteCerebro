type VoiceAudio = Pick<HTMLAudioElement, 'play' | 'pause' | 'src' | 'onended' | 'onerror'>;
type VoiceDependencies = {
  fetchAudio: (text: string, signal: AbortSignal) => Promise<Blob>;
  createAudio: (url: string) => VoiceAudio;
  createUrl: (blob: Blob) => string;
  revokeUrl: (url: string) => void;
  speakLocal: (text: string) => Promise<unknown>;
  stopLocal: () => Promise<unknown>;
};

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
    try {
      const blob = await this.deps.fetchAudio(text, controller.signal);
      clearTimeout(timeout);
      if (generation !== this.generation) return 'cancelled';
      if (!blob.size || !blob.type.startsWith('audio/')) throw new Error('Resposta sem áudio');
      this.url = this.deps.createUrl(blob);
      const audio = this.deps.createAudio(this.url);
      this.audio = audio;
      await new Promise<void>((resolve, reject) => {
        this.finish = resolve;
        audio.onended = () => resolve();
        audio.onerror = () => reject(new Error('Falha na reprodução'));
        void audio.play().catch(reject);
      });
      return generation === this.generation ? 'neural' : 'cancelled';
    } catch (error) {
      if (generation !== this.generation) return 'cancelled';
      this.clearMedia();
      await this.deps.speakLocal(text);
      return generation === this.generation ? 'local' : 'cancelled';
    } finally {
      clearTimeout(timeout);
      if (generation === this.generation) this.clearMedia();
    }
  }
}
