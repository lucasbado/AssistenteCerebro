import { useEffect, useState } from 'react';
import { invoke } from '@tauri-apps/api/core';

export type AgendaAction = { id: string; texto: string; quando: string; tipo: string };
type Item = { id: string; tipo: string; titulo: string; inicio: string; dia_inteiro: boolean;
  quando: string; estado: string; antecedencia_minutos: number };

async function request(path = '', options: RequestInit = {}) {
  const base = await invoke<string>('get_api_url');
  const token = await invoke<string>('get_auth_token');
  const response = await fetch(`${base.replace(/\/$/, '')}/api/v1/agenda${path}`, {
    ...options, headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    if (response.status === 404) throw new Error('Agenda indisponível. Confira se o servidor recebeu a atualização.');
    const data = await response.json().catch(() => null);
    throw new Error(typeof data?.detail === 'string' ? data.detail : 'Não consegui acessar a agenda. Confira a conexão e tente novamente.');
  }
  return response.json();
}

export default function AgendaPanel({ selected, onAll }: { selected: string | null; onAll: () => void }) {
  const [items, setItems] = useState<Item[]>([]), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [title, setTitle] = useState(''), [date, setDate] = useState(''), [time, setTime] = useState('');
  const [kind, setKind] = useState('compromisso'), [lead, setLead] = useState(0), [form, setForm] = useState(false);
  async function refresh() {
    const list = await request();
    if (!Array.isArray(list)) throw new Error('Resposta inválida recebida da agenda.');
    if (selected && !list.some((item: Item) => item.id === selected)) list.unshift(await request(`/${encodeURIComponent(selected)}`));
    setItems(list);
  }
  async function run(action: () => Promise<void>) {
    setBusy(true); setError('');
    try { await action(); } catch (err) { setError(err instanceof Error ? err.message : 'Não consegui concluir.'); }
    finally { setBusy(false); }
  }
  useEffect(() => { void run(refresh); }, [selected]);
  const visible = selected ? items.filter(item => item.id === selected) : items;
  return <section className="agenda-panel" aria-label="Sua agenda">
    <div className="agenda-toolbar"><div><h2>Uma coisa a menos pra lembrar.</h2><p>Compromissos, lembretes e datas que merecem ficar guardadas.</p></div>
      <button className="button" disabled={busy} onClick={() => void run(refresh)}>Atualizar</button>
      <button className="button button-primary" disabled={busy} onClick={() => setForm(!form)}>{form ? 'Fechar formulário' : 'Novo item'}</button></div>
    {error && <p className="agenda-error" role="alert">{error}</p>}
    {busy && <p role="status">Conferindo sua agenda…</p>}
    {form && <form className="agenda-form" onSubmit={event => { event.preventDefault(); void run(async () => {
      const start = new Date(`${date}T${time || '00:00'}:00`);
      if (!Number.isFinite(start.getTime())) throw new Error('Confira a data e o horário.');
      await request('', { method: 'POST', body: JSON.stringify({ tipo: kind, titulo: title.trim(), inicio: start.toISOString(),
        dia_inteiro: !time, antecedencia_minutos: kind === 'alarme' ? 0 : lead }) });
      setForm(false); setTitle(''); await refresh(); onAll();
    }); }}>
      <label>O que é?<input required maxLength={255} value={title} onChange={e => setTitle(e.target.value)} /></label>
      <label>Tipo<select value={kind} onChange={e => setKind(e.target.value)}><option value="compromisso">Compromisso</option><option value="lembrete">Lembrete</option><option value="alarme">Despertador no celular</option></select></label>
      <label>Data<input type="date" required value={date} onChange={e => setDate(e.target.value)} /></label>
      <label>Horário deste PC<input type="time" required={kind !== 'compromisso'} value={time} onChange={e => setTime(e.target.value)} /></label>
      {kind !== 'alarme' && <label>Avisar minutos antes<input type="number" min={0} max={10080} value={lead} onChange={e => setLead(Number(e.target.value))} /></label>}
      <p>Compromissos sem horário ficam como dia inteiro. Despertadores precisam ser revisados no Relógio do celular.</p>
      <button className="button button-primary" disabled={busy}>Guardar na Ollie</button>
    </form>}
    {selected && <button className="button" onClick={onAll}>Ver toda a agenda</button>}
    {!busy && !error && !visible.length && <p className="agenda-empty">Sua agenda está livre. Você pode guardar uma data aqui ou pedir na conversa.</p>}
    <div className="agenda-items">{visible.map(item => <article className="agenda-card" key={item.id}>
      <span className="eyebrow">{item.tipo === 'alarme' ? 'DESPERTADOR NO CELULAR' : item.tipo.toUpperCase()}</span>
      <h3>{item.titulo}</h3><p className="agenda-date">{item.quando}</p>
      <p>{item.estado === 'sugestao' ? 'Sugestão • revise antes de salvar.' : item.estado === 'preparado' ? 'Preparado • abra a agenda no celular para revisar no Relógio. A ativação ainda não foi confirmada.' : item.estado === 'agendado' ? 'Guardado na sua agenda.' : 'Item encerrado.'}</p>
      {item.tipo !== 'alarme' && <p>{item.dia_inteiro ? 'Dia inteiro, sem aviso em horário específico.' : `Aviso ${item.antecedencia_minutos} min antes. A entrega depende do servidor e da conexão.`}</p>}
      {!['cancelado', 'concluido'].includes(item.estado) && <div className="agenda-actions">
        {item.estado === 'sugestao' && <button disabled={busy} className="button button-primary" onClick={() => void run(async () => { await request(`/${item.id}`, { method: 'PATCH', body: JSON.stringify({ estado: 'agendado' }) }); await refresh(); })}>Salvar na agenda</button>}
        <button disabled={busy} className="button" onClick={() => void run(async () => { await request(`/${item.id}`, { method: 'PATCH', body: JSON.stringify({ estado: 'cancelado' }) }); await refresh(); })}>{item.estado === 'sugestao' ? 'Descartar sugestão' : 'Retirar da Ollie'}</button>
      </div>}
      {item.tipo === 'alarme' && <small>Retirar da Ollie não desativa um despertador já salvo no Relógio.</small>}
    </article>)}</div>
  </section>;
}
