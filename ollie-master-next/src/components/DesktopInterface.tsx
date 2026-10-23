import { useEffect, useRef, useState, type RefObject } from 'react';
import AgendaPanel, { type AgendaAction } from './AgendaPanel';
import { Activity, ArrowUpRight, Check, ChevronRight, CircleAlert, Cpu, Database, MessageCircle, Mic, MicOff, Monitor,
  Radio, RefreshCw, Send, Settings2, Shield, Sparkles, Terminal, Volume2, VolumeX, X, CalendarDays } from 'lucide-react';
import type { ListeningPhase } from '../desktopListening';
import './desktop-interface.css';

export type DesktopPage = 'chat' | 'computer' | 'activity' | 'automation' | 'agenda';
export type DesktopMessage = { id: string; role: 'user' | 'ollie'; text: string; time: string; agendaActions?: AgendaAction[] };
export type InterventionPolicy = { auto_open_enabled: boolean; min_priority_score: number; whitelist: string[]; blacklist: string[] };
type Props = {
  page: DesktopPage; onPage: (page: DesktopPage) => void; connected: boolean; thinking: boolean;
  cpu: number | null; ram: number | null; vision: { process: string; title: string };
  messages: DesktopMessage[]; logs: { t: string; m: string; c: string }[];
  draft: string; onDraft: (value: string) => void; onSend: () => void; inputRef: RefObject<HTMLInputElement | null>;
  voiceEnabled: boolean; onToggleVoice: () => void; onTestVoice: () => void;
  listeningEnabled: boolean; phase: ListeningPhase; level: number; heard: string;
  devices: { id: number; name: string; default: boolean }[]; device: number | null;
  onListening: (enabled: boolean) => void; onDevice: (id: number | null) => void; onListenNow: () => void; onCancel: () => void;
  onReconnect: () => void; onScan: () => void; onHardware: () => void;
  policy: InterventionPolicy; policyLoading: boolean; policyError: string; policyBusy: boolean;
  onPolicy: (value: InterventionPolicy) => void; onRefreshPolicy: () => void;
  routines: { nome: string; justificativa?: string; pode_ativar?: boolean; problemas?: string[] }[]; routinesLoading: boolean; routinesError: string; routineBusy: string | null;
  onRefreshRoutines: () => void; onApprove: (name: string) => void; onReject: (name: string) => void;
  notice: { text: string; kind: 'error' | 'success' } | null; onDismissNotice: () => void;
};

const pages = [
  { id: 'chat', label: 'Conversa', icon: MessageCircle, subtitle: 'Uma ideia, um pedido, uma conversa.' },
  { id: 'computer', label: 'Computador', icon: Monitor, subtitle: 'O que está acontecendo por aqui.' },
  { id: 'activity', label: 'Atividade', icon: Activity, subtitle: 'Conexões e execuções desta sessão.' },
  { id: 'automation', label: 'Autonomia', icon: Shield, subtitle: 'Você escolhe quando a Ollie pode agir.' },
  { id: 'agenda', label: 'Agenda', icon: CalendarDays, subtitle: 'Tempo para o que importa.' },
] as const;
const phases: Record<ListeningPhase, { title: string; hint: string }> = {
  off: { title: 'Ativação por voz desligada', hint: 'Você pode conversar por texto ou ativar a chamada.' },
  starting: { title: 'Preparando sua voz', hint: 'Carregando o detector e o microfone…' },
  wake: { title: 'Ouvindo “Ei Ollie”', hint: 'Faça a chamada, espere “Pode falar” e diga seu pedido.' },
  listening: { title: 'Pode falar', hint: 'Estou ouvindo seu pedido no microfone do PC.' },
  thinking: { title: 'Pensando no seu pedido', hint: 'Aguardando a resposta da Ollie.' },
  speaking: { title: 'Respondendo para você', hint: 'A chamada volta a ouvir depois da resposta.' },
  paused: { title: 'Microfone pausado', hint: 'A escuta retoma quando a interação terminar.' },
  error: { title: 'Não consegui iniciar a voz', hint: 'Confira a entrada de áudio e tente ativar novamente.' },
};

function Usage({ label, value, purple = false }: { label: string; value: number | null; purple?: boolean }) {
  return <div className={`usage${purple ? ' usage-purple' : ''}`}>
    <div><span>{label}</span><strong>{value === null ? '—' : `${Math.round(value)}%`}</strong></div>
    <meter min={0} max={100} value={value ?? 0} aria-label={label} />
  </div>;
}

function AgendaMessage({ message, onOpen }: { message: DesktopMessage; onOpen: (id: string) => void }) {
  const action = message.agendaActions?.[0];
  const start = action?.quando ? message.text.indexOf(action.quando) : -1;
  return <><p>{action && start >= 0 ? <>{message.text.slice(0, start)}<button className="agenda-date-link" onClick={() => onOpen(action.id)}>{action.quando}</button>{message.text.slice(start + action.quando.length)}</> : message.text}</p>
    {message.agendaActions?.map(item => <button className="button button-subtle" key={item.id} onClick={() => onOpen(item.id)}>{item.texto}</button>)}</>;
}

export default function DesktopInterface(p: Props) {
  const [agendaSelection, setAgendaSelection] = useState<string | null>(null);
  const openAgenda = (id: string) => { setAgendaSelection(id); p.onPage('agenda'); };
  const chatScroll = useRef<HTMLDivElement>(null), logScroll = useRef<HTMLDivElement>(null);
  const stickChat = useRef(true), stickLog = useRef(true);
  useEffect(() => { if (stickChat.current && chatScroll.current) chatScroll.current.scrollTop = chatScroll.current.scrollHeight; }, [p.messages, p.thinking, p.page]);
  useEffect(() => { if (stickLog.current && logScroll.current) logScroll.current.scrollTop = logScroll.current.scrollHeight; }, [p.logs, p.page]);
  const page = pages.find(item => item.id === p.page)!;
  const status = phases[p.phase];
  const talking = ['listening', 'thinking', 'speaking'].includes(p.phase);
  const policyDisabled = p.policyBusy || p.policyLoading || !!p.policyError;
  return <main className="desktop-shell">
    <a className="skip-link" href="#desktop-content">Ir para o conteúdo</a>
    <aside className="desktop-sidebar" aria-label="Navegação principal">
      <div className="desktop-brand"><span className="brand-symbol"><Sparkles size={22} /></span><div><strong>ollie<span>.</span></strong><small>presente no seu PC</small></div></div>
      <nav>{pages.map(item => <button key={item.id} className={p.page === item.id ? 'nav-item selected' : 'nav-item'}
        aria-current={p.page === item.id ? 'page' : undefined} aria-label={item.label} title={item.label} onClick={() => p.onPage(item.id)}>
        <item.icon size={19} /><span>{item.label}</span>{p.page === item.id && <ChevronRight size={14} className="nav-chevron" />}
      </button>)}</nav>
      <div className="sidebar-presence"><div className={`presence-orb ${talking ? 'orb-active' : ''}`} aria-hidden="true"><span /></div>
        <strong>{p.phase === 'listening' ? 'Estou ouvindo.' : p.phase === 'speaking' ? 'Vamos conversar.' : 'Por aqui, com você.'}</strong>
        <p>{p.connected ? 'Seu computador conectado à Ollie.' : 'Aguardando conexão com a Ollie.'}</p>
      </div>
      <div className="sidebar-footer"><Monitor size={15} /><span>Este computador</span><span className={`status-dot ${p.connected ? 'connected' : ''}`} /></div>
    </aside>

    <div className="desktop-workspace">
      <header className="desktop-header"><div><p className="eyebrow">OLLIE / SEU ESPAÇO</p><h1>{page.label}</h1><p className="page-subtitle">{page.subtitle}</p></div>
        <div className="header-connection"><span className={`connection-label ${p.connected ? '' : 'is-offline'}`} role="status"><span className={`status-dot ${p.connected ? 'connected' : ''}`} />{p.connected ? 'Conectada' : 'Sem conexão'}</span>
          <button className="icon-button" onClick={p.onReconnect} aria-label="Reconectar à Ollie" title="Reconectar à Ollie"><RefreshCw size={17} /></button></div>
      </header>
      {p.notice && <div className={`desktop-notice ${p.notice.kind}`} role={p.notice.kind === 'error' ? 'alert' : 'status'}>
        {p.notice.kind === 'error' ? <CircleAlert size={18} /> : <Check size={18} />}<span>{p.notice.text}</span>
        <button className="icon-button" onClick={p.onDismissNotice} aria-label="Dispensar aviso"><X size={16} /></button>
      </div>}
      <div id="desktop-content" className="desktop-content">
        {p.page === 'agenda' && <AgendaPanel selected={agendaSelection} onAll={() => setAgendaSelection(null)} />}
        {p.page === 'chat' && <section className="conversation" aria-label="Conversa com a Ollie">
          <div className={`voice-strip phase-${p.phase}`}><span className="voice-strip-icon">{p.listeningEnabled ? <Mic size={20} /> : <MicOff size={20} />}</span>
            <div className="voice-strip-copy" role="status" aria-live="polite"><strong>{status.title}</strong><span>{status.hint}</span></div>
            {p.phase === 'wake' && <button className="button button-subtle" onClick={p.onListenNow} disabled={!p.connected}>Falar agora</button>}
            {talking && <button className="button button-subtle" onClick={p.onCancel}>Cancelar</button>}
            {!p.listeningEnabled && <button className="button button-subtle" onClick={() => p.onListening(true)}>Ativar chamada</button>}
            <button className="icon-button" onClick={() => p.onPage('computer')} aria-label="Configurar microfone" title="Configurar microfone"><Settings2 size={18} /></button>
          </div>
          <div className="conversation-history" ref={chatScroll} onScroll={e => { const el = e.currentTarget; stickChat.current = el.scrollHeight - el.scrollTop - el.clientHeight < 70; }}>
            {p.messages.length === 0 && <div className="conversation-empty"><div className="empty-emblem" aria-hidden="true"><Sparkles size={29} /></div>
              <p className="eyebrow">UMA CONVERSA COMEÇA AQUI</p><h2>O que vamos fazer?</h2><p>Peça ajuda, dê um comando ou traga uma ideia.<br />A Ollie está aqui para acompanhar você.</p>
              <div className="conversation-suggestions">{['Como está a luz do quarto?', 'Abra o YouTube no PC', 'Vamos organizar uma rotina?'].map(text =>
                <button key={text} onClick={() => { p.onDraft(text); p.inputRef.current?.focus(); }}>{text}<ArrowUpRight size={14} /></button>)}</div>
            </div>}
            <div className="message-list" role="log" aria-label="Mensagens da conversa" aria-live="polite" aria-relevant="additions">
              {p.messages.map(message => <article key={message.id} className={`chat-message ${message.role}`}><div className="message-meta"><strong>{message.role === 'user' ? 'Você' : 'Ollie'}</strong><time>{message.time}</time></div>
                <AgendaMessage message={message} onOpen={openAgenda} />
              </article>)}
              {p.thinking && <div className="thinking-indicator" role="status"><span /><span /><span />Ollie está pensando…</div>}
            </div>
          </div>
          {p.heard && <div className="heard-preview"><Mic size={14} /><span>{p.heard}</span></div>}
          {!p.connected && <div className="offline-hint">Reconecte para enviar. Seu rascunho continua aqui.</div>}
          <form className="conversation-composer" onSubmit={event => { event.preventDefault(); stickChat.current = true; p.onSend(); }}>
            <label className="sr-only" htmlFor="ollie-message">Mensagem para a Ollie</label>
            <input id="ollie-message" ref={p.inputRef} value={p.draft} onChange={e => p.onDraft(e.target.value)} autoComplete="off" placeholder="Converse com a Ollie…" />
            <button className="icon-button" type="button" onClick={p.onToggleVoice} aria-label={p.voiceEnabled ? 'Silenciar respostas faladas' : 'Ouvir respostas faladas'} aria-pressed={p.voiceEnabled} title={p.voiceEnabled ? 'Respostas faladas ligadas' : 'Respostas faladas desligadas'}>{p.voiceEnabled ? <Volume2 size={19} /> : <VolumeX size={19} />}</button>
            <button type="submit" className="send-button" disabled={!p.draft.trim() || !p.connected} aria-label="Enviar mensagem"><Send size={18} /></button>
          </form>
          <div className="composer-caption"><span>Enter para enviar</span><span>{p.voiceEnabled ? 'Respostas com voz' : 'Respostas em texto'}</span></div>
        </section>}

        {p.page === 'computer' && <div className="page-scroll"><div className="computer-grid">
          <section className="desktop-panel window-panel"><div className="panel-heading"><Monitor size={18} /><h2>Janela em uso</h2></div><div className="window-preview"><span className="eyebrow">ATIVIDADE ATUAL</span><h3>{p.vision.process || 'Aguardando atividade'}</h3><p>{p.vision.title || 'A janela atual aparecerá aqui.'}</p></div><p className="help-text">Última janela detectada pela Ollie neste computador.</p></section>
          <section className="desktop-panel"><div className="panel-heading"><Cpu size={18} /><h2>Desempenho</h2></div><Usage label="Processador" value={p.cpu} /><Usage label="Memória RAM" value={p.ram} purple /><p className="help-text">{p.cpu === null ? 'Aguardando os dados do computador.' : 'Leituras recebidas do monitor local.'}</p></section>
          <section className="desktop-panel microphone-panel"><div className="panel-heading"><Mic size={18} /><h2>Voz e microfone</h2><span className="setting-badge">{p.listeningEnabled ? 'Ativada' : 'Desligada'}</span></div>
            <div className="setting-row"><div><strong>Chamar com “Ei Ollie”</strong><p>O PC escuta a chamada pelo microfone selecionado.</p></div><input type="checkbox" role="switch" aria-label="Ativação por voz no PC" checked={p.listeningEnabled} onChange={e => p.onListening(e.target.checked)} /></div>
            <label className="field-label" htmlFor="ollie-input-device">Entrada de áudio</label><select id="ollie-input-device" value={p.device ?? ''} onChange={e => p.onDevice(e.target.value === '' ? null : Number(e.target.value))}>
              <option value="">Padrão do Windows{p.devices.find(d => d.default) ? ` · ${p.devices.find(d => d.default)!.name}` : ''}</option>{p.devices.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select><div className="microphone-meter"><span>Nível de entrada</span><meter min={0} max={1} value={Math.min(1, p.level * 8)} aria-label="Nível do microfone" /></div><p className="help-text">No Voicemeeter, escolha a saída de captura que recebe seu microfone, como Out B1.</p>
            <div className="panel-actions"><button className="button" onClick={p.onTestVoice}><Volume2 size={16} />Testar voz da Ollie</button><button className="button button-subtle" disabled={!p.listeningEnabled || p.phase !== 'wake' || !p.connected} onClick={p.onListenNow}><Mic size={16} />Falar agora</button></div>
          </section>
          <section className="desktop-panel quick-actions"><div className="panel-heading"><Settings2 size={18} /><h2>Conexões do PC</h2></div><button className="action-row" onClick={p.onScan}><span><Monitor size={18} />Analisar aplicativos do PC</span><ChevronRight size={16} /></button><button className="action-row" onClick={p.onHardware}><span><Database size={18} />Reconectar controles de hardware</span><ChevronRight size={16} /></button><button className="action-row" onClick={p.onReconnect}><span><RefreshCw size={18} />Reconectar ao servidor</span><ChevronRight size={16} /></button></section>
        </div></div>}

        {p.page === 'activity' && <section className="activity-panel"><div className="activity-heading"><div><Terminal size={18} /><strong>Registros desta sessão</strong></div><span>Últimos {p.logs.length} eventos</span></div>
          <div className="activity-log" ref={logScroll} onScroll={e => { const el = e.currentTarget; stickLog.current = el.scrollHeight - el.scrollTop - el.clientHeight < 70; }}>
            {p.logs.length === 0 && <p className="help-text">Os eventos de conexão e execução aparecerão aqui.</p>}{p.logs.map((log, i) => <div className={`activity-entry ${/red|orange/.test(log.c) ? 'entry-warning' : ''}`} key={`${log.t}-${i}`}><time>{log.t}</time><p>{log.m}</p></div>)}
          </div><p className="help-text activity-caption">Os registros técnicos ficam aqui. Suas mensagens estão em Conversa.</p></section>}

        {p.page === 'automation' && <div className="page-scroll automation-page"><section className="desktop-panel"><div className="panel-heading"><Shield size={19} /><h2>Abertura automática de aplicativos</h2>{p.policyBusy && <span role="status" className="setting-badge">Salvando…</span>}</div>
          <p className="section-description">Defina quando a Ollie pode abrir aplicativos por conta própria. Seus pedidos explícitos por voz ou texto continuam funcionando.</p>
          {p.policyLoading && <p role="status" className="help-text">Buscando as permissões no servidor…</p>}{p.policyError && <div className="inline-error" role="alert"><p>{p.policyError}</p><button className="button" onClick={p.onRefreshPolicy}>Tentar novamente</button></div>}
          <div className="setting-row"><div><strong>Permitir abertura automática</strong><p>{p.policy.auto_open_enabled ? 'Apenas os apps permitidos seguem as regras abaixo.' : 'A Ollie espera seu pedido para abrir aplicativos.'}</p></div><input type="checkbox" role="switch" aria-label="Permitir abertura automática de aplicativos" checked={p.policy.auto_open_enabled} disabled={policyDisabled} onChange={e => p.onPolicy({ ...p.policy, auto_open_enabled: e.target.checked })} /></div>
          <div className="priority-setting"><label htmlFor="ollie-priority">Importância mínima para abrir um app</label><select id="ollie-priority" disabled={policyDisabled} value={p.policy.min_priority_score} onChange={e => p.onPolicy({ ...p.policy, min_priority_score: Number(e.target.value) })}>
            {Array.from(new Set([.5,.55,.6,.65,.7,.75,.8,.85,.9,.95,1,p.policy.min_priority_score])).sort((a,b) => a-b).map(n => <option key={n} value={n}>{Math.round(n * 100)}%{n === .85 ? ' · padrão' : ''}</option>)}
          </select><p className="help-text">Uma importância maior exige um motivo mais forte para interromper você.</p></div>
          <div className="app-permissions"><div><h3>Apps permitidos</h3><div className="app-tags">{p.policy.whitelist?.length ? p.policy.whitelist.map(app => <span key={app}>{app}</span>) : <p className="help-text">Nenhum app permitido.</p>}</div></div><div><h3>Nunca abrir sozinhos</h3><div className="app-tags blocked">{p.policy.blacklist?.length ? p.policy.blacklist.map(app => <span key={app}>{app}</span>) : <p className="help-text">Nenhum bloqueio adicional.</p>}</div></div></div>
        </section><section className="desktop-panel"><div className="panel-heading"><Sparkles size={18} /><h2>Rotinas sugeridas</h2><button className="icon-button" onClick={p.onRefreshRoutines} disabled={p.routinesLoading} aria-label="Atualizar rotinas" title="Atualizar rotinas"><RefreshCw size={16} /></button></div>
          <p className="section-description">Revise o que a Ollie aprendeu antes de ativar uma rotina.</p>{p.routinesLoading ? <p role="status" className="help-text">Buscando sugestões…</p> : p.routinesError ? <div className="inline-error" role="alert"><p>{p.routinesError}</p><button className="button" onClick={p.onRefreshRoutines}>Tentar novamente</button></div> : p.routines.length === 0 ? <div className="routines-empty"><Check size={22} /><div><strong>Nada pendente por aqui.</strong><p>Novas sugestões aparecem conforme a Ollie observa padrões.</p></div></div> : p.routines.map((r, index) => <article className="routine-row" key={`${r.nome}-${index}`}><div><h3>{r.nome}</h3><p>{r.justificativa || 'Revise esta sugestão antes de ativar.'}</p>{r.pode_ativar === false && <p className="routine-issue">{r.problemas?.length ? r.problemas.join(' ') : 'Esta sugestão precisa de ajustes antes de ser ativada.'}</p>}</div><div><button className="button button-primary" disabled={p.routineBusy !== null || r.pode_ativar === false} onClick={() => p.onApprove(r.nome)}>{p.routineBusy === r.nome ? 'Aguarde…' : 'Ativar'}</button><button className="button button-subtle" disabled={p.routineBusy !== null} onClick={() => p.onReject(r.nome)}>Descartar</button></div></article>)}
        </section></div>}
      </div>
      <footer className="desktop-statusbar"><span><Radio size={13} />{p.connected ? 'Servidor conectado' : 'Aguardando servidor'}</span><span>{status.title}</span></footer>
    </div>
  </main>;
}
