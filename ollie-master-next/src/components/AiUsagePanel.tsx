import { useEffect, useState } from 'react';
import { invoke } from '@tauri-apps/api/core';

type Usage = { tokens_groq: number; tokens_automaticos: number; restante_groq: number;
  limites: { total_24h: number; automatico_24h: number }; pc_disponivel: boolean; cloudflare_configurada: boolean;
  por_funcao: { provider: string; funcao: string; solicitado: boolean; tokens: number; estimativas: number }[] };
const number = (n: number) => n.toLocaleString('pt-BR');

export default function AiUsagePanel() {
  const [data, setData] = useState<Usage | null>(null), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  async function refresh() {
    setBusy(true); setError('');
    try {
      const base = await invoke<string>('get_api_url'), token = await invoke<string>('get_auth_token');
      const response = await fetch(`${base.replace(/\/$/, '')}/api/v1/ia/consumo`, { headers: { Authorization: `Bearer ${token}` } });
      if (!response.ok) throw Error(response.status === 404 ? 'Atualize o servidor para acompanhar o consumo.' : 'Não consegui consultar o consumo agora.');
      const value = await response.json();
      if (typeof value.tokens_groq !== 'number' || !value.limites || !Array.isArray(value.por_funcao)) throw Error('Resposta de consumo inválida.');
      setData(value);
    } catch (e) { setError(e instanceof Error ? e.message : 'Consumo indisponível.'); }
    finally { setBusy(false); }
  }
  useEffect(() => { void refresh(); }, []);
  return <section className="desktop-panel ai-usage-panel" aria-label="Consumo de inteligência artificial">
    <div className="panel-heading"><h2>Uso da IA</h2><button className="button button-subtle" disabled={busy} onClick={() => void refresh()}>{busy ? 'Conferindo…' : 'Atualizar'}</button></div>
    <p className="help-text">Últimas 24 horas. O limite da Ollie reserva espaço para seus pedidos.</p>
    {error && <p className="help-text" role="alert">{error}</p>}
    {data && <>
      <div className="setting-row"><div><strong>{number(data.tokens_groq)} / {number(data.limites.total_24h)} tokens no Groq</strong><p>Análises automáticas: {number(data.tokens_automaticos)} / {number(data.limites.automatico_24h)}</p></div></div>
      <p className="help-text">Cloudflare: {data.cloudflare_configurada ? 'configurada' : 'aguardando configuração'} · IA deste PC: {data.pc_disponivel ? 'disponível ao servidor' : 'sem conexão com o servidor'}</p>
      <details><summary>De onde veio o consumo?</summary>{data.por_funcao.length ? data.por_funcao.map((g, i) => <p className="help-text" key={i}>{g.provider} · {g.funcao} · {g.solicitado ? 'seu pedido' : 'automático'}: {number(g.tokens)} tokens{g.estimativas > 0 ? ' (inclui estimativas)' : ''}</p>) : <p className="help-text">Nenhuma chamada registrada nesta janela.</p>}</details>
      <p className="help-text">Este é o orçamento do app. O saldo oficial de cada provedor pode ser diferente.</p>
    </>}
  </section>;
}
