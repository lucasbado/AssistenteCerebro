/** Only correlated replies to requests made on this desktop can be spoken. */
export class DesktopReplies {
  private pending = new Map<string, number>();
  private seen = new Set<string>();
  expect(id: string, now = Date.now()) {
    this.pending.set(id, now);
    if (this.pending.size > 100) this.pending.delete(this.pending.keys().next().value!);
  }
  consume(data: { tipo_ws?: string; correlacao_id?: string; dispositivo_destino?: string; texto?: unknown; id?: string }, now = Date.now()): string | null {
    for (const [id, at] of this.pending) if (now - at > 300000) this.pending.delete(id);
    if (data.tipo_ws !== 'CHAT_RESPONSE' || data.dispositivo_destino === 'MOBILE' ||
        !this.pending.has(data.correlacao_id || '') || typeof data.texto !== 'string' || !data.texto.trim()) return null;
    const key = data.id || JSON.stringify([data.correlacao_id, data.texto]);
    if (this.seen.has(key)) return null;
    this.seen.add(key);
    if (this.seen.size > 200) this.seen.delete(this.seen.values().next().value!);
    return data.texto.trim();
  }
}
