export type WhatsAppDraft = { id: string; numero: string; texto: string };

function validDraft(numero: unknown, texto: unknown): boolean {
  return typeof numero === 'string' && /^[1-9][0-9]{7,14}$/.test(numero) &&
    typeof texto === 'string' && texto.length <= 2000 && Boolean(texto.trim());
}

export function readWhatsAppDraft(id: string, raw: string): WhatsAppDraft {
  const pedido = JSON.parse(raw);
  if (!id || !pedido || !validDraft(pedido.numero, pedido.texto)) {
    throw new Error('O rascunho precisa de um número internacional e de um texto.');
  }
  return { id, numero: pedido.numero, texto: pedido.texto };
}

export function whatsappDraftUrl(draft: WhatsAppDraft): string {
  if (!validDraft(draft.numero, draft.texto)) throw new Error('O rascunho está inválido.');
  return `https://wa.me/${draft.numero}?text=${encodeURIComponent(draft.texto)}`;
}
