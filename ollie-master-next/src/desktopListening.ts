export type ListeningPhase = 'off' | 'starting' | 'wake' | 'listening' | 'thinking' | 'speaking' | 'paused' | 'error';
export type ListeningEvent = { instance_id: string; type: string; state?: string; text?: string; message?: string; level?: number };
type Dependencies = {
  newId: () => string;
  start: (id: string, device: number | null) => Promise<unknown>;
  stop: (id: string) => Promise<unknown>;
  control: (id: string, action: 'pause' | 'resume' | 'listen') => Promise<unknown>;
  send: (text: string, signal: AbortSignal) => Promise<string>;
  speak: (text: string) => Promise<unknown>;
  stopSpeech: () => Promise<unknown>;
  phase: (phase: ListeningPhase) => void;
  partial: (text: string) => void;
  level: (value: number) => void;
  wake: () => void;
  error: (message: string) => void;
};

/** One microphone owner and one correlated voice turn; stale events cannot restart capture. */
export class DesktopListening {
  private deps: Dependencies;
  private instance = '';
  private epoch = 0;
  private turnNumber = 0;
  private abort: AbortController | null = null;
  private external = 0;
  private externalNumber = 0;
  enabled = false;
  constructor(deps: Dependencies) { this.deps = deps; }

  async start(device: number | null) {
    const epoch = ++this.epoch;
    const old = this.instance;
    const id = this.deps.newId();
    this.instance = id;
    this.enabled = true;
    this.abort?.abort(); this.abort = null;
    this.deps.phase('starting');
    await Promise.all([this.deps.stopSpeech().catch(() => {}), old ? this.deps.stop(old).catch(() => {}) : Promise.resolve()]);
    if (epoch !== this.epoch) return;
    try {
      await this.deps.start(id, device);
      if (epoch !== this.epoch) await this.deps.stop(id).catch(() => {});
    } catch (error) {
      if (epoch === this.epoch) this.fail(String(error));
    }
  }

  async stop() {
    ++this.epoch; ++this.turnNumber;
    this.enabled = false;
    this.external = 0;
    this.abort?.abort(); this.abort = null;
    const id = this.instance;
    this.instance = '';
    this.deps.phase('off'); this.deps.partial(''); this.deps.level(0);
    await Promise.all([this.deps.stopSpeech().catch(() => {}), id ? this.deps.stop(id).catch(() => {}) : Promise.resolve()]);
  }

  private fail(message: string) {
    const stopped = this.stop(), epoch = this.epoch;
    void stopped.then(() => { if (epoch === this.epoch) this.deps.phase('error'); });
    this.deps.error(message);
  }

  receive(event: ListeningEvent) {
    if (!this.enabled || event.instance_id !== this.instance) return;
    if (event.type === 'state' && !this.abort && !this.external) this.deps.phase(event.state as ListeningPhase);
    if (event.type === 'level') this.deps.level(event.level || 0);
    if (event.type === 'partial') this.deps.partial(event.text || '');
    if (event.type === 'wake' && !this.abort && !this.external) this.deps.wake();
    if (event.type === 'error') this.fail(event.message || 'Falha no microfone.');
    if (event.type === 'no_speech') { this.deps.error(event.message || 'Não ouvi o comando.'); void this.cancel(); }
    if (event.type === 'transcript' && event.text?.trim() && !this.abort && !this.external) void this.turn(event.text.trim());
  }

  async listenNow() {
    if (!this.enabled || this.abort || this.external) return;
    try { await this.deps.control(this.instance, 'listen'); this.deps.wake(); }
    catch (error) { this.fail(String(error)); }
  }

  async cancel() {
    ++this.turnNumber;
    this.abort?.abort(); this.abort = null;
    this.deps.partial('');
    await this.deps.stopSpeech().catch(() => {});
    if (this.enabled) {
      try { await this.deps.control(this.instance, 'resume'); }
      catch (error) { this.fail(String(error)); }
    }
  }

  private async turn(text: string) {
    const epoch = this.epoch, number = ++this.turnNumber, id = this.instance;
    const controller = new AbortController(); this.abort = controller;
    const active = () => this.enabled && this.epoch === epoch && this.turnNumber === number;
    this.deps.partial(text); this.deps.phase('thinking');
    try {
      await this.deps.control(id, 'pause'); // ACK confirma microfone liberado antes do TTS.
      if (!active()) return;
      const reply = await this.deps.send(text, controller.signal);
      if (!active()) return;
      this.deps.phase('speaking');
      await this.deps.speak(reply);
    } catch (error) {
      if (active() && !controller.signal.aborted) this.deps.error(String(error));
    } finally {
      if (active()) {
        this.abort = null;
        try { await this.deps.control(id, 'resume'); }
        catch (error) { this.fail(String(error)); }
      }
    }
  }

  async speakExternal(text: string) {
    if (this.abort) return;
    const epoch = this.epoch, id = this.instance, serial = ++this.externalNumber;
    this.external = serial;
    try {
      if (this.enabled) await this.deps.control(id, 'pause');
      if (epoch !== this.epoch) return;
      if (this.enabled) this.deps.phase('speaking');
      await this.deps.speak(text);
    } finally {
      if (this.external === serial) {
        this.external = 0;
        if (this.enabled && epoch === this.epoch && !this.abort) {
          try { await this.deps.control(id, 'resume'); }
          catch (error) { this.fail(String(error)); }
        }
      }
    }
  }
}
