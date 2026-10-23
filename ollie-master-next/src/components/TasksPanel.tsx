import { useEffect, useState } from 'react';
import { invoke } from '@tauri-apps/api/core';
import { taskDeadline } from '../taskActions';

type Task = { id: string; titulo: string; prazo: string | null; quando: string; dia_inteiro: boolean;
  estado: string; atrasada: boolean; contexto: string; versao: number; aviso: string };

async function request(path = '', options: RequestInit = {}) {
  const base = await invoke<string>('get_api_url'), token = await invoke<string>('get_auth_token');
  const response = await fetch(`${base.replace(/\/$/, '')}/api/v1/tarefas${path}`, {
    ...options, headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(response.status === 404 ? 'Tarefas indisponíveis. Confira a atualização do servidor.' :
      typeof data?.detail === 'string' ? data.detail : 'Não consegui acessar suas tarefas. Tente novamente.');
  }
  return response.json();
}

export default function TasksPanel({ selected, onAll }: { selected: string | null; onAll: () => void }) {
  const [items, setItems] = useState<Task[]>([]), [filter, setFilter] = useState('abertas');
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const [form, setForm] = useState(false), [title, setTitle] = useState('');
  const [date, setDate] = useState(''), [time, setTime] = useState('');
  const [postpone, setPostpone] = useState<string | null>(null), [nextDate, setNextDate] = useState(''), [nextTime, setNextTime] = useState('');
  async function refresh() {
    const list = await request(`?estado=${filter}`);
    if (!Array.isArray(list)) throw new Error('Resposta inválida recebida das tarefas.');
    if (selected && !list.some((item: Task) => item.id === selected)) list.unshift(await request(`/${encodeURIComponent(selected)}`));
    setItems(list);
  }
  async function run(action: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('');
    try { await action(); } catch (err) { setError(err instanceof Error ? err.message : 'Não consegui concluir.'); }
    finally { setBusy(false); }
  }
  async function change(item: Task, action: string, deadline = {}) {
    await request(`/${item.id}`, { method: 'PATCH', body: JSON.stringify({ acao: action, versao: item.versao, ...deadline }) });
    await refresh(); setPostpone(null);
    setNotice(action === 'concluir' ? 'Tarefa concluída.' : action === 'adiar' ? 'Prazo atualizado.' : action === 'aceitar' ? 'Guardado nas suas tarefas.' : 'Tarefa descartada.');
  }
  useEffect(() => { void run(refresh); }, [selected, filter]);
  const visible = selected ? items.filter(item => item.id === selected) : items;
  return <section className="agenda-panel" aria-label="Suas tarefas">
    <div className="agenda-toolbar"><div><h2>O que falta resolver?</h2><p>Suas pendências ficam aqui até você concluir ou descartar.</p></div>
      <button className="button" disabled={busy} onClick={() => void run(refresh)}>Atualizar</button>
      <button className="button button-primary" onClick={() => setForm(!form)}>{form ? 'Fechar formulário' : 'Nova tarefa'}</button></div>
    <label className="task-filter">Mostrar <select disabled={busy} value={filter} onChange={e => { setFilter(e.target.value); onAll(); }}>
      <option value="abertas">Em aberto e sugestões</option><option value="pendente">Pendentes</option><option value="sugestao">Sugestões de mensagens</option><option value="concluida">Concluídas</option><option value="descartada">Descartadas</option></select></label>
    {error && <p className="agenda-error" role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}{busy && <p role="status">Conferindo suas tarefas…</p>}
    {form && <form className="agenda-form" onSubmit={e => { e.preventDefault(); void run(async () => {
      await request('', { method: 'POST', body: JSON.stringify({ titulo: title.trim(), ...taskDeadline(date, time) }) });
      setForm(false); setTitle(''); setDate(''); setTime(''); await refresh(); onAll(); setNotice('Anotado nas suas tarefas.');
    }); }}>
      <label>O que precisa fazer?<input required maxLength={255} value={title} onChange={e => setTitle(e.target.value)} /></label>
      <label>Data do prazo (opcional)<input type="date" value={date} onChange={e => setDate(e.target.value)} /></label>
      <label>Horário (opcional)<input type="time" value={time} onChange={e => setTime(e.target.value)} /></label>
      <p>Sem horário, a data vale até o fim do dia e não gera aviso em horário inventado. Prazos com horário recebem um aviso, dependendo do servidor e da conexão.</p>
      <button className="button button-primary" disabled={busy}>Guardar tarefa</button>
    </form>}
    {selected && <button className="button" onClick={onAll}>Ver todas as tarefas</button>}
    {!busy && !error && !visible.length && <p className="agenda-empty">Nenhuma tarefa nessa lista por enquanto.</p>}
    <div className="agenda-items">{visible.map(item => <article className="agenda-card" key={item.id}>
      <span className={`eyebrow ${item.atrasada ? 'task-overdue' : ''}`}>{item.atrasada ? 'PRAZO VENCIDO' : item.estado === 'sugestao' ? 'SUGESTÃO DE MENSAGEM' : item.estado.toUpperCase()}</span>
      <h3>{item.titulo}</h3><p className="agenda-date">{item.quando}</p><p>{item.aviso}</p>
      {item.contexto && <details><summary>Mensagem de origem</summary><p>{item.contexto}</p></details>}
      {['pendente', 'sugestao'].includes(item.estado) && <div className="agenda-actions">
        {item.estado === 'sugestao' ? <button className="button button-primary" disabled={busy} onClick={() => void run(() => change(item, 'aceitar'))}>Colocar nas tarefas</button> : <>
          <button className="button button-primary" disabled={busy} onClick={() => void run(() => change(item, 'concluir'))}>Concluir</button>
          <button className="button" disabled={busy} onClick={() => { setPostpone(item.id); setNextDate(''); setNextTime(''); }}>Adiar</button></>}
        <button className="button" disabled={busy} onClick={() => void run(() => change(item, 'descartar'))}>Descartar</button>
      </div>}
      {postpone === item.id && <form className="agenda-form task-postpone" onSubmit={e => { e.preventDefault(); void run(() => change(item, 'adiar', taskDeadline(nextDate, nextTime))); }}>
        <label>Nova data<input type="date" required value={nextDate} onChange={e => setNextDate(e.target.value)} /></label>
        <label>Horário<input type="time" value={nextTime} onChange={e => setNextTime(e.target.value)} /></label>
        <button className="button button-primary" disabled={busy}>Salvar prazo</button>
        <button className="button" type="button" onClick={() => setPostpone(null)}>Cancelar</button>
      </form>}
    </article>)}</div>
  </section>;
}
