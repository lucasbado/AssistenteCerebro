export type TaskAction = { id: string; texto: string; quando: string };
export function decodeTaskActions(value: unknown): TaskAction[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is TaskAction => !!item && typeof item.id === 'string' &&
    /^[0-9a-f-]{36}$/i.test(item.id) && typeof item.texto === 'string' && !!item.texto.trim() &&
    typeof item.quando === 'string').slice(0, 15);
}

export function taskDeadline(date: string, time: string) {
  if (!date) {
    if (time) throw new Error('Escolha a data desse horário.');
    return { prazo: null, dia_inteiro: false };
  }
  const start = new Date(`${date}T${time || '00:00'}:00`);
  const local = `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, '0')}-${String(start.getDate()).padStart(2, '0')}`;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !Number.isFinite(start.getTime()) || local !== date)
    throw new Error('Confira a data e o horário do prazo.');
  return { prazo: start.toISOString(), dia_inteiro: !time };
}
