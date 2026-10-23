export type MessageAction = { id: string; texto: string };
export function decodeMessageActions(value: unknown): MessageAction[] {
  if (!Array.isArray(value)) return [];
  return value.filter((v): v is MessageAction => !!v && typeof v.id === 'string' &&
    (v.id === 'pendentes' || /^[0-9a-f-]{36}$/i.test(v.id)) && typeof v.texto === 'string' && !!v.texto.trim()).slice(0, 10);
}
