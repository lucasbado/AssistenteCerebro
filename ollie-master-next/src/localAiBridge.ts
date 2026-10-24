export type LocalAiRequest = { tipo_ws: 'IA_SOLICITACAO'; id: string; prompt: string; system: string; max_tokens: number };
export type LocalAiResult = { texto: string; modelo: string; entrada: number; saida: number };

export function createLocalAiBridge(generate: (request: LocalAiRequest) => Promise<LocalAiResult>) {
  let busy = false;
  const seen = new Set<string>();
  return async (request: unknown, send: (result: unknown) => void) => {
    if (!request || typeof request !== 'object') return;
    const r = request as LocalAiRequest;
    if (r.tipo_ws !== 'IA_SOLICITACAO' || typeof r.id !== 'string' || !/^[0-9a-f-]{36}$/.test(r.id) ||
        typeof r.prompt !== 'string' || typeof r.system !== 'string' || r.prompt.length + r.system.length > 30000 ||
        !Number.isInteger(r.max_tokens) || r.max_tokens < 1 || r.max_tokens > 1200 || seen.has(r.id)) return;
    seen.add(r.id);
    if (seen.size > 100) seen.delete(seen.values().next().value!);
    if (busy) { send({ tipo_ws: 'IA_RESULTADO', id: r.id, status: 'ocupado' }); return; }
    busy = true;
    try {
      const result = await generate(r);
      send({ ...result, tipo_ws: 'IA_RESULTADO', id: r.id, status: 'concluido' });
    } catch { send({ tipo_ws: 'IA_RESULTADO', id: r.id, status: 'erro' }); }
    finally { busy = false; }
  };
}
