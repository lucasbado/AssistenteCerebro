import { useEffect, useState } from 'react';
import { invoke } from '@tauri-apps/api/core';

type Message = { id: string; remetente: string; texto: string; sinais: string[]; estado: string; quando: string;
  rascunho: string; versao: number; agenda_id: string | null; tarefa_id: string | null; pacote: string;
  prioridade?: number; motivo?: string };
async function request(path = '', options: RequestInit = {}) {
  const base = await invoke<string>('get_api_url'), token = await invoke<string>('get_auth_token');
  const response = await fetch(`${base.replace(/\/$/, '')}/api/v1/mensagens${path}`, {
    ...options, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
  });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(response.status === 404 ? 'Mensagens indisponíveis. Confira a atualização do servidor.' :
      typeof data?.detail === 'string' ? data.detail : 'Não consegui atualizar as mensagens. Tente novamente.');
  }
  return response.json();
}

export default function MessagesPanel({ selected, onAll }: { selected: string | null; onAll: () => void }) {
  const [items, setItems] = useState<Message[]>([]), [filter, setFilter] = useState('revisar');
  const [error, setError] = useState(''), [busy, setBusy] = useState(false);
  async function load(register = false) {
    const list = register ? await request('/revisao', { method: 'POST', body: JSON.stringify({ dispositivo: 'PC' }) }) : await request(`?estado=${filter}`);
    if (!Array.isArray(list)) throw new Error('Resposta de mensagens inválida.');
    if (selected && !list.some((i: Message) => i.id === selected)) list.unshift(await request(`/${encodeURIComponent(selected)}`));
    setItems(list);
  }
  async function run(fn: () => Promise<void>) {
    setBusy(true); setError('');
    try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : 'Não consegui concluir.'); }
    finally { setBusy(false); }
  }
  useEffect(() => { void run(() => load(filter === 'revisar')); }, [selected, filter]);
  async function action(item: Message, kind: string, text = '') {
    setBusy(true); setError('');
    try {
      const updated: Message = await request(`/${item.id}/acao`, { method: 'POST', body: JSON.stringify({ acao: kind, versao: item.versao, texto: text }) });
      setItems(prev => prev.map(i => i.id === updated.id ? updated : i));
      return updated;
    } catch (e) { setError(e instanceof Error ? e.message : 'Não consegui concluir.'); throw e; }
    finally { setBusy(false); }
  }
  const visible = items.filter(i => (selected ? i.id === selected : i.estado === filter));
  return <section className="agenda-panel" aria-label="Mensagens para revisar">
    <div className="agenda-toolbar"><div><h2>O que merece sua atenção.</h2><p>Pedidos, prazos e decisões selecionados pelo contexto recebido. Os mais importantes aparecem primeiro; você pode já ter respondido no aplicativo.</p></div>
      <button className="button" disabled={busy} onClick={() => void run(() => load())}>Atualizar</button></div>
    <label className="task-filter">Mostrar <select disabled={busy} value={filter} onChange={e => { setFilter(e.target.value); onAll(); }}><option value="revisar">Para revisar</option><option value="resolvida">Resolvidas</option><option value="ignorada">Ignoradas</option></select></label>
    {error && <p className="agenda-error" role="alert">{error}</p>}{busy && <p role="status">Conferindo suas mensagens…</p>}
    {selected && <button className="button" onClick={onAll}>Ver todas</button>}
    {!busy && !error && !visible.length && <p>Nenhuma mensagem nessa lista por enquanto.</p>}
    <div className="message-review-list">{visible.map(item => <MessageCard key={item.id} item={item} busy={busy} action={action} />)}</div>
  </section>;
}

function MessageCard({ item, busy, action }: { item: Message; busy: boolean; action: (i: Message, a: string, t?: string) => Promise<Message> }) {
  const [draft, setDraft] = useState(item.rascunho), [instruction, setInstruction] = useState(''), [feedback, setFeedback] = useState('');
  async function act(kind: string, text = '') {
    setFeedback('');
    try { const updated = await action(item, kind, text); if (['preparar_resposta', 'salvar_rascunho'].includes(kind)) setDraft(updated.rascunho);
      setFeedback(kind === 'preparar_resposta' ? 'Rascunho pronto para conferir.' : kind === 'salvar_rascunho' ? 'Rascunho guardado.' : 'Atualizado.');
    } catch { /* Parent keeps error visible and local edits stay intact. */ }
  }
  return <article className="agenda-card message-review-card"><span className="eyebrow">{item.sinais.join(' · ')}</span><h3>{item.remetente}</h3>
    <p>{item.quando} · {item.estado === 'revisar' ? 'Para revisar' : item.estado}</p><blockquote>{item.texto}</blockquote>
    {item.motivo && <p>{item.motivo}</p>}
    {item.estado === 'revisar' && <>
      <div className="agenda-actions"><button className="button" disabled={busy || !!item.agenda_id} onClick={() => void act('guardar_agenda')}>{item.agenda_id ? 'Guardado na agenda' : 'Guardar compromisso'}</button>
        <button className="button" disabled={busy || !!item.tarefa_id} onClick={() => void act('criar_tarefa')}>{item.tarefa_id ? 'Tarefa guardada' : 'Criar tarefa'}</button></div>
      <label>O que você quer responder?<textarea maxLength={2000} value={instruction} onChange={e => setInstruction(e.target.value)} placeholder="Ex.: diga que vou conferir o horário e aviso depois." /></label>
      <button className="button button-primary" disabled={busy} onClick={() => void act('preparar_resposta', instruction)}>Preparar resposta</button>
      <label>Rascunho para você conferir<textarea maxLength={2000} value={draft} onChange={e => setDraft(e.target.value)} /></label>
      <div className="agenda-actions"><button className="button" disabled={busy || !draft.trim()} onClick={() => void act('salvar_rascunho', draft)}>Guardar rascunho</button>
        <button className="button" disabled={!draft.trim()} onClick={() => {
          if (!navigator.clipboard?.writeText) { setFeedback('Selecione e copie o texto do rascunho.'); return; }
          void navigator.clipboard.writeText(draft).then(() => setFeedback('Copiado. Confira o destinatário ao colar na conversa.')).catch(() => setFeedback('Não consegui copiar. Você pode selecionar o texto do rascunho.'));
        }}>Copiar rascunho</button>
        <button className="button" disabled={busy} onClick={() => void act('resolver')}>Marcar resolvida</button><button className="button" disabled={busy} onClick={() => void act('ignorar')}>Ignorar</button></div>
    </>}
    <p role="status">{feedback}</p><small>O rascunho fica para revisão. O envio é feito por você na conversa do aplicativo.</small>
  </article>;
}
