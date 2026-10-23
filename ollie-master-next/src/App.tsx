import { useState, useEffect, useRef } from 'react';
import DesktopInterface, { type DesktopPage, type DesktopMessage, type InterventionPolicy } from './components/DesktopInterface';
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { DesktopReplies } from './desktopReplies';
import { DesktopVoice } from './desktopVoice';
import { DesktopListening, type ListeningEvent, type ListeningPhase } from './desktopListening';

async function authenticatedFetch(url: string, options: RequestInit = {}) {
  const token = await invoke<string>("get_auth_token");
  const headers = new Headers(options.headers);
  headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(url, { ...options, headers });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response;
}

function requirePolicy(data: unknown): InterventionPolicy {
  const value = data as Partial<InterventionPolicy> | null;
  if (!value || typeof value.auto_open_enabled !== 'boolean' || typeof value.min_priority_score !== 'number' ||
      !Number.isFinite(value.min_priority_score) || value.min_priority_score < 0 || value.min_priority_score > 1 ||
      !Array.isArray(value.whitelist) || !value.whitelist.every(app => typeof app === 'string') ||
      !Array.isArray(value.blacklist) || !value.blacklist.every(app => typeof app === 'string')) {
    throw new Error('Permissões inválidas recebidas do servidor.');
  }
  return { auto_open_enabled: value.auto_open_enabled, min_priority_score: value.min_priority_score,
    whitelist: value.whitelist, blacklist: value.blacklist };
}

// --- Interfaces ---
interface HardwareUpdate {
  cpu: number;
  ram: number;
  processes: any[];
  audio_state: Record<string, unknown>;
  mic_mute: number;
}

interface WindowUpdate {
  title: string;
  process: string;
}

export default function App() {
  const [page, setPage] = useState<DesktopPage>('chat');
  const [messages, setMessages] = useState<DesktopMessage[]>([]);
  const [notice, setNotice] = useState<{ text: string; kind: 'error' | 'success' } | null>(null);
  const [hardwareReady, setHardwareReady] = useState(false);
  const [mood, setMood] = useState<'idle' | 'thinking' | 'alert'>('idle');
  const [isConnected, setIsConnected] = useState(false);
  const [logs, setLogs] = useState<{t: string, m: string, c: string}[]>([]);
  const [cpu, setCpu] = useState(0);
  const [ram, setRam] = useState(0);
  const [vision, setVision] = useState({ process: "", title: "" });
  const [chatText, setChatInput] = useState("");
  const [voiceEnabled, setVoiceEnabled] = useState(() => localStorage.getItem('ollie.desktopVoice') !== 'false');
  const voiceEnabledRef = useRef(voiceEnabled);
  voiceEnabledRef.current = voiceEnabled;
  const desktopReplies = useRef(new DesktopReplies());
  const desktopVoice = useRef<DesktopVoice | null>(null);
  if (!desktopVoice.current) desktopVoice.current = new DesktopVoice({
    fetchAudio: async (text, signal) => {
      const api = await invoke<string>('get_api_url');
      const url = new URL(`${api}/api/v1/voice/speak`);
      url.searchParams.set('text', text);
      url.searchParams.set('voice', 'pt-BR-ThalitaNeural');
      const response = await authenticatedFetch(url.toString(), { signal });
      return response.blob();
    },
    createAudio: url => new Audio(url),
    createUrl: blob => URL.createObjectURL(blob),
    revokeUrl: url => URL.revokeObjectURL(url),
    speakLocal: text => invoke('speak_response', { text }),
    stopLocal: () => invoke('stop_speech'),
  });
  const socketRef = useRef<WebSocket | null>(null);
  const [listeningPhase, setListeningPhase] = useState<ListeningPhase>('off');
  const [microphoneLevel, setMicrophoneLevel] = useState(0);
  const [heardText, setHeardText] = useState('');
  const [inputDevices, setInputDevices] = useState<{id: number; name: string; default: boolean}[]>([]);
  const [inputDevice, setInputDevice] = useState<number | null>(null);
  const inputDeviceRef = useRef<number | null>(null);
  const pendingVoice = useRef(new Map<string, { resolve: (text: string) => void; reject: (error: Error) => void }>());
  const listening = useRef<DesktopListening | null>(null);
  if (!listening.current) listening.current = new DesktopListening({
    newId: () => crypto.randomUUID(),
    start: (instanceId, device) => invoke('start_desktop_listening', { instanceId, device }),
    stop: instanceId => invoke('stop_desktop_listening', { instanceId }),
    control: (instanceId, action) => invoke('control_desktop_listening', { instanceId, action }),
    send: (text, signal) => sendVoiceChat(text, signal),
    speak: text => voiceEnabledRef.current ? desktopVoice.current!.speak(text) : Promise.resolve(),
    stopSpeech: () => desktopVoice.current!.stop(),
    phase: phase => setListeningPhase(phase),
    partial: setHeardText,
    level: setMicrophoneLevel,
    wake: () => { setPage('chat'); void invoke('activate_window'); addLog('Pode falar seu comando.', 'text-neon-cyan'); },
    error: message => { addLog(`Voz: ${message}`, 'text-neon-orange'); setNotice({ text: message, kind: 'error' }); },
  });

  const sendVoiceChat = (text: string, signal: AbortSignal): Promise<string> => {
    const socket = socketRef.current;
    if (socket?.readyState !== WebSocket.OPEN) return Promise.reject(new Error('Sem conexão com a Ollie.'));
    return new Promise((resolve, reject) => {
      const id = crypto.randomUUID();
      const cleanup = () => {
        clearTimeout(timeout); signal.removeEventListener('abort', cancel);
        pendingVoice.current.delete(id); desktopReplies.current.forget(id);
      };
      const cancel = () => { cleanup(); reject(new Error('Conversa cancelada.')); };
      const timeout = window.setTimeout(() => { cleanup(); reject(new Error('A resposta demorou. Chame a Ollie novamente.')); }, 45000);
      pendingVoice.current.set(id, {
        resolve: reply => { cleanup(); resolve(reply); },
        reject: error => { cleanup(); reject(error); },
      });
      signal.addEventListener('abort', cancel, { once: true });
      if (signal.aborted) { cancel(); return; }
      desktopReplies.current.expect(id);
      addLog(`Você: ${text}`, 'text-white');
      appendMessage('user', text, `user-${id}`);
      setMood('thinking');
      try {
        socket.send(JSON.stringify({ tipo_ws: 'CHAT_MESSAGE', texto: text, pacote: 'pc.chat', correlacao_id: id, canal: 'voz' }));
      } catch (error) { cleanup(); reject(error); }
    });
  };

  const changeListening = async (enabled: boolean, device = inputDeviceRef.current) => {
    try {
      await invoke('save_desktop_listening_preferences', { enabled, device });
      if (enabled) await listening.current!.start(device);
      else await listening.current!.stop();
    } catch (error) { addLog(`Não consegui ativar a voz: ${error}`, 'text-neon-orange'); setNotice({ text: 'Não consegui ativar a voz. Confira o microfone e tente novamente.', kind: 'error' }); }
  };
  const [policy, setPolicy] = useState<InterventionPolicy>({
    auto_open_enabled: false,
    min_priority_score: 0.85,
    whitelist: [],
    blacklist: []
  });

  const policyRef = useRef(policy);
  policyRef.current = policy;
  const reconnectRef = useRef<() => void>(() => {});
  const chatInputRef = useRef<HTMLInputElement>(null);
  const commandResultsRef = useRef(new Map<string, 'executando' | 'concluido' | 'erro'>());
  const scenarioBusyRef = useRef(false);
  const lastCommandRef = useRef<{ id: string; comando: string; status: string } | null>(null);
  const houseResultsRef = useRef(new Map<string, { entity_id: string; state: string }>());
  const openingResultsRef = useRef(new Map<string, { primeiro_plano: boolean }>());

  const [policyLoading, setPolicyLoading] = useState(true);
  const [policyError, setPolicyError] = useState('');
  const [policyBusy, setPolicyBusy] = useState(false);
  const [routinesLoading, setRoutinesLoading] = useState(true);
  const [routinesError, setRoutinesError] = useState('');
  const [routineBusy, setRoutineBusy] = useState<string | null>(null);
  const [discoveredRoutines, setDiscoveredRoutines] = useState<any[]>([]);

  const fetchDiscovered = async () => {
    setRoutinesLoading(true); setRoutinesError('');
    try {
      const apiUrl = await invoke<string>("get_api_url");
      const res = await authenticatedFetch(`${apiUrl}/api/v1/capabilities/discovered`);
      const data = await res.json();
      if (!Array.isArray(data) || !data.every(item => item && typeof item.nome === 'string' &&
          (item.justificativa == null || typeof item.justificativa === 'string') &&
          (item.pode_ativar == null || typeof item.pode_ativar === 'boolean') &&
          (item.problemas == null || (Array.isArray(item.problemas) && item.problemas.every((problem: unknown) => typeof problem === 'string'))))) {
        throw new Error('Resposta de rotinas inválida.');
      }
      setDiscoveredRoutines(data);
    } catch {
      setRoutinesError('Não consegui buscar as rotinas. Confira a conexão e tente novamente.');
    } finally { setRoutinesLoading(false); }
  };

  const approveRoutine = async (nome: string) => {
    if (routineBusy !== null) return;
    setRoutineBusy(nome);
    try {
      const apiUrl = await invoke<string>("get_api_url");
      const res = await authenticatedFetch(`${apiUrl}/api/v1/capabilities/approve`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ nome })
      });
      const data = await res.json();
      addLog(data.message || 'Rotina ativada.', 'text-neon-cyan');
      setNotice({ text: data.message || 'Rotina ativada.', kind: 'success' });
      await fetchDiscovered();
    } catch (error) {
      addLog(`Não consegui ativar a rotina: ${error}`, 'text-red-400');
      setNotice({ text: 'Não consegui ativar a rotina. Tente novamente.', kind: 'error' });
    } finally { setRoutineBusy(null); }
  };

  const rejectRoutine = async (nome: string) => {
    if (routineBusy !== null) return;
    setRoutineBusy(nome);
    try {
      const apiUrl = await invoke<string>("get_api_url");
      const res = await authenticatedFetch(`${apiUrl}/api/v1/capabilities/discovered/${encodeURIComponent(nome)}`, { method: 'DELETE' });
      const data = await res.json();
      addLog(data.message || 'Sugestão descartada.', 'text-neon-orange');
      setNotice({ text: data.message || 'Sugestão descartada.', kind: 'success' });
      await fetchDiscovered();
    } catch (error) {
      addLog(`Não consegui descartar a sugestão: ${error}`, 'text-red-400');
      setNotice({ text: 'Não consegui descartar a sugestão. Tente novamente.', kind: 'error' });
    } finally { setRoutineBusy(null); }
  };

  const fetchPolicy = async () => {
    setPolicyLoading(true); setPolicyError('');
    try {
      const apiUrl = await invoke<string>("get_api_url");
      const res = await authenticatedFetch(`${apiUrl}/api/v1/pc/intervention/policy`);
      const data = await res.json();
      setPolicy(requirePolicy(data));
    } catch {
      setPolicyError('Não consegui consultar as permissões atuais. Os controles ficam indisponíveis até reconectar.');
    } finally { setPolicyLoading(false); }
  };

  const updatePolicy = async (newPolicy: InterventionPolicy) => {
    if (policyBusy || policyLoading || policyError) return;
    setPolicyBusy(true);
    try {
      const apiUrl = await invoke<string>("get_api_url");
      const res = await authenticatedFetch(`${apiUrl}/api/v1/pc/intervention/policy`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(newPolicy)
      });
      const data = await res.json();
      setPolicy(requirePolicy(data.policy));
      setNotice({ text: 'Permissões atualizadas.', kind: 'success' });
      addLog('Permissões de autonomia atualizadas.', 'text-neon-cyan');
    } catch (error) {
      addLog(`Não consegui salvar as permissões: ${error}`, 'text-red-400');
      setNotice({ text: 'Não consegui salvar. As permissões anteriores continuam em uso.', kind: 'error' });
    } finally { setPolicyBusy(false); }
  };

  useEffect(() => {
    fetchPolicy();
    fetchDiscovered();
  }, []);

  const appendMessage = (role: DesktopMessage['role'], text: string, id: string, agendaActions?: DesktopMessage['agendaActions']) => {
    setMessages(previous => previous.some(message => message.id === id) ? previous : [...previous.slice(-99), {
      id, role, text, agendaActions, time: new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
    }]);
  };

  const addLog = (m: string, c: string = "text-gray-400") => {
    setLogs(prev => [...prev.slice(-99), { t: new Date().toLocaleTimeString(), m, c }]);
  };

  const handleCommand = async (data: any, socket?: WebSocket | null) => {
    const id = String(data.id_comando || '');
    const previous = id ? commandResultsRef.current.get(id) : undefined;
    const finish = (status: 'concluido' | 'erro') => {
      if (id) {
        lastCommandRef.current = { id, comando: String(data.comando || data.acao || ''), status };
        commandResultsRef.current.set(id, status);
        if (commandResultsRef.current.size > 200) {
          commandResultsRef.current.delete(commandResultsRef.current.keys().next().value!);
        }
        if (socket?.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ tipo_ws: 'COMANDO_RESULTADO', id_comando: id, status,
            resultado: houseResultsRef.current.get(id) ?? openingResultsRef.current.get(id) }));
        }
      }
    };
    if (previous) {
      if (previous !== 'executando') finish(previous);
      return;
    }
    if (id) commandResultsRef.current.set(id, 'executando');
    try {
      const cmd = data.comando || data.acao || 'CUSTOM';
      let param = String(data.url ?? data.parametro ?? data.app ?? data.query ?? data.macro ?? data.valor ?? "");
      if (cmd === 'volume_canal' && data.canal != null) {
        param = `${data.canal},${data.valor ?? data.parametro ?? ''}`;
      }

      // 🛡️ CHECK INTERVENTION POLICY (Super Poderes / Auto-Open)
      if (data.origem === "IA" && !(data.abertura_modo === "pedido" && data.abertura_autorizada === true) && !policyRef.current.auto_open_enabled && (cmd === "open_url" || cmd === "abrir_url" || cmd === "abrir_app" || cmd === "abrir_programa")) {
        addLog(`🛡️ Intervention blocked by policy (Auto-Open OFF): ${cmd} (${param})`, "text-neon-orange");
        finish('erro');
        return;
      }

      addLog(`⚡ Executing local PC command: ${cmd} (${param})`, "text-neon-cyan");

      if (cmd === 'wake_ollie') {
        setPage('chat');
        await invoke('activate_window');
        if (listening.current!.enabled) await listening.current!.listenNow();
        requestAnimationFrame(() => chatInputRef.current?.focus());
        setMood('idle');
        if (!listening.current!.enabled) addLog('Ollie pronta. Digite seu comando.', 'text-neon-cyan');
      } else if (cmd === 'executar_cenario') {
        if (scenarioBusyRef.current) throw new Error('Já há um cenário em execução.');
        scenarioBusyRef.current = true;
        try {
          await invoke('execute_pc_command', { comando: cmd, parametro: param });
        } finally {
          scenarioBusyRef.current = false;
        }
      } else {
        const raw = await invoke<string>("execute_pc_command", { comando: cmd, parametro: param });
        if (['abrir_app', 'abrir_programa', 'abrir_url', 'open_url', 'pesquisa_google', 'web_search', 'pesquisar'].includes(cmd)) {
          try {
            const result = JSON.parse(raw);
            if (typeof result.primeiro_plano === 'boolean') {
              if (openingResultsRef.current.size >= 200) openingResultsRef.current.clear();
              openingResultsRef.current.set(id, { primeiro_plano: result.primeiro_plano });
              if (!result.primeiro_plano) setNotice({ text: 'A abertura foi encaminhada, mas o Windows não confirmou a janela em primeiro plano.', kind: 'error' });
            }
          } catch { /* Older helpers return only a success status. */ }
        }
        if (cmd === 'casa_acao') {
          const result = JSON.parse(raw);
          if (typeof result.entity_id !== 'string' || !['on', 'off'].includes(result.state)) {
            throw new Error('O Home Assistant não confirmou o estado da luz.');
          }
          if (houseResultsRef.current.size >= 200) houseResultsRef.current.clear();
          houseResultsRef.current.set(id, { entity_id: result.entity_id, state: result.state });
        }
      }
      addLog(`✅ Executed successfully: ${cmd}`, "text-neon-cyan");
      finish('concluido');
    } catch (err) {
      addLog(`Erro ao executar: ${err}`, "text-red-400");
      setNotice({ text: `Não consegui concluir a ação: ${err}`, kind: 'error' });
      finish('erro');
    }
  };

  const sendChat = () => {
    const text = chatText.trim(), socket = socketRef.current;
    if (!text || socket?.readyState !== WebSocket.OPEN) return;
    const correlation = crypto.randomUUID();
    desktopReplies.current.expect(correlation);
    try {
      socket.send(JSON.stringify({ tipo_ws: 'CHAT_MESSAGE', texto: text, pacote: 'pc.chat', correlacao_id: correlation, canal: 'texto' }));
      appendMessage('user', text, `user-${correlation}`);
      addLog(`Você: ${text}`, 'text-white');
      setChatInput(''); setNotice(null); setMood('thinking');
    } catch {
      desktopReplies.current.forget(correlation);
      setNotice({ text: 'Não consegui enviar. Sua mensagem continua no campo para tentar novamente.', kind: 'error' });
    }
  };

  // --- Effects ---

  useEffect(() => {
    let mounted = true;
    let unlisten: (() => void) | undefined;
    void (async () => {
      const dispose = await listen<ListeningEvent>('desktop-listening', event => listening.current!.receive(event.payload));
      if (!mounted) { dispose(); return; }
      unlisten = dispose;
      const [preferences, devices] = await Promise.all([
        invoke<{enabled: boolean; device: number | null}>('desktop_listening_preferences'),
        invoke<{id: number; name: string; default: boolean}[]>('desktop_input_devices'),
      ]);
      if (!mounted) return;
      setInputDevices(devices);
      setInputDevice(preferences.device); inputDeviceRef.current = preferences.device;
      if (preferences.enabled) await listening.current!.start(preferences.device);
    })().catch(error => { if (mounted) addLog(`Voz local indisponível: ${error}`, 'text-neon-orange'); });
    return () => {
      mounted = false; unlisten?.();
      for (const request of pendingVoice.current.values()) request.reject(new Error('Conversa encerrada.'));
      void listening.current?.stop();
    };
  }, []);

  useEffect(() => {
    console.log("🚀 Ollie Master Next starting...");
    addLog("OLLIE Master Next // Neural Interface Initialized", "text-neon-cyan");

    let activeSocket: WebSocket | null = null;
    let isComponentMounted = true;
    let reconnectTimeout: number;
    let isConnecting = false;
    let unlistenHardware: Promise<any> | null = null;
    let unlistenWindow: Promise<any> | null = null;

    // Start Monitoring in Rust
    invoke("start_monitoring").catch(err => {
      addLog(`Failed to start Rust monitor: ${err}`, "text-red-400");
    });

    // Listen to Hardware Updates
    unlistenHardware = listen<HardwareUpdate>("hardware-update", (event) => {
      setHardwareReady(true);
      setCpu(event.payload.cpu);
      setRam(event.payload.ram);

      // Notify Cloud about hardware status including processes
      if (activeSocket && activeSocket.readyState === WebSocket.OPEN) {
        activeSocket.send(JSON.stringify({
          tipo_ws: "STATUS_PC",
          id: "PC_MASTER",
          stats: {
            cpu: event.payload.cpu,
            ram: event.payload.ram,
            online: true,
            processes: event.payload.processes,
            audio_state: event.payload.audio_state,
            mic_mute: event.payload.mic_mute,
            ultimo_comando: lastCommandRef.current
          }
        }));
      }
    });

    // Listen to Window Updates
    let lastLogProcess = "";
    unlistenWindow = listen<WindowUpdate>("window-update", (event) => {
      setVision({ process: event.payload.process, title: event.payload.title });

      // Deduplicação de logs
      if (event.payload.process !== lastLogProcess) {
        addLog(`Activity Detected: ${event.payload.process}`, "text-neon-cyan");
        lastLogProcess = event.payload.process;
      }

      // Notify Cloud about activity
      if (activeSocket && activeSocket.readyState === WebSocket.OPEN) {
        activeSocket.send(JSON.stringify({
          tipo_ws: "PC_ACTIVITY",
          payload: { processo: event.payload.process, titulo: event.payload.title }
        }));
      }
    });

    const setupWS = async () => {
      if (!isComponentMounted || isConnecting) return;
      isConnecting = true;

      try {
        const cloudUrl = await invoke<string>("get_cloud_url");
        addLog(`Connecting to: ${cloudUrl}`, "text-gray-500 text-[10px]");

        const token = await invoke<string>("get_auth_token");
        if (!isComponentMounted) return;
        const ws = new WebSocket(cloudUrl, ["ollie", `bearer.${token}`]);
        activeSocket = ws;
        socketRef.current = ws;

        ws.onopen = () => {
          isConnecting = false;
          if (!isComponentMounted) { ws.close(); return; }
          setIsConnected(true);
          addLog("📡 Sincronização com Cloud concluída.", "text-neon-cyan");
          ws.send(JSON.stringify({ tipo_ws: "REGISTRO", id: "PC_MASTER", capacidades: ["CASA"] }));
        };

        ws.onmessage = (event) => {
          if (!isComponentMounted) return;
          let data;
          try { data = JSON.parse(event.data); } catch { return; }

          if (data.tipo_ws === "CHAT_RESPONSE") {
            addLog(`🤖 OLLIE: ${data.texto}`, "text-neon-purple text-[13px] font-bold");
            setMood("idle");
            const reply = desktopReplies.current.consume(data);
            if (reply) appendMessage('ollie', reply, String(data.id || `${data.correlacao_id}:${reply}`),
              Array.isArray(data.acoes_agenda) ? data.acoes_agenda.filter((a: any) => a && typeof a.id === 'string' && typeof a.quando === 'string' && typeof a.texto === 'string') : []);
            const voiceRequest = pendingVoice.current.get(data.correlacao_id);
            if (reply && voiceRequest) {
              voiceRequest.resolve(reply);
              return;
            }
            if (reply && voiceEnabledRef.current) {
              void listening.current!.speakExternal(reply).catch(() =>
                addLog('Não consegui reproduzir a voz. A resposta continua no chat.', 'text-neon-orange'));
            }
          }

          if (data.tipo_ws === 'NOTIFICACAO' && data.acao_tipo === 'AGENDA_REVISAR' && typeof data.texto === 'string') {
            appendMessage('ollie', data.texto, String(data.id || `agenda-${data.acao_parametro}`),
              [{ id: String(data.acao_parametro), texto: 'Ver na agenda', quando: '', tipo: 'compromisso' }]);
            setNotice({ text: data.texto, kind: 'success' });
          }

          if (data.comando && data.tipo_ws === 'COMANDO_PC') {
            addLog(`⚡ EXEC_CMD: ${data.comando.toUpperCase()}`, "text-neon-cyan");
            void handleCommand(data, ws);
          }

          if (data.mood) setMood(data.mood);

          if (data.tipo_ws === "REGISTRO_OK") {
            addLog("✅ Autenticação confirmada pelo cérebro.", "text-neon-cyan");
            setIsConnected(true);
          }

          if (data.tipo_ws === "STATUS_PC" && data.id === "PC_MASTER") {
             setIsConnected(true);
          }
        };

        ws.onclose = () => {
          for (const request of pendingVoice.current.values()) request.reject(new Error('A conexão com a Ollie foi interrompida.'));
          isConnecting = false;
          if (!isComponentMounted) return;
          setIsConnected(false); setMood('idle');
          addLog("❌ Falha de link: Cloud connection lost.", "text-red-400");
          clearTimeout(reconnectTimeout);
          reconnectTimeout = window.setTimeout(setupWS, 10000); // Aumentado para 10s para evitar spam
        };

        ws.onerror = (err) => {
          isConnecting = false;
          if (!isComponentMounted) return;
          console.error("WS Error:", err);
          addLog(`WS Error: Connection issues detected.`, "text-red-500");
        };

      } catch (err) {
        isConnecting = false;
        if (isComponentMounted) addLog(`Setup Error: ${err}`, "text-red-400");
      }
    };

    reconnectRef.current = () => {
      for (const request of pendingVoice.current.values()) request.reject(new Error('Conexão reiniciada.'));
      if (reconnectTimeout) window.clearTimeout(reconnectTimeout);
      void desktopVoice.current?.stop().catch(() => {});
      if (activeSocket) {
        activeSocket.onclose = null;
        activeSocket.close();
      }
      isConnecting = false;
      void setupWS();
    };
    void setupWS();

    return () => {
      isComponentMounted = false;
      if (unlistenHardware) unlistenHardware.then(u => u());
      if (unlistenWindow) unlistenWindow.then(u => u());
      if (activeSocket) activeSocket.close();
      if (reconnectTimeout) window.clearTimeout(reconnectTimeout);
    };
  }, []);

  return <DesktopInterface
    page={page} onPage={setPage} connected={isConnected} thinking={mood === 'thinking'}
    cpu={hardwareReady ? cpu : null} ram={hardwareReady ? ram : null} vision={vision} messages={messages} logs={logs}
    draft={chatText} onDraft={setChatInput} onSend={sendChat} inputRef={chatInputRef}
    voiceEnabled={voiceEnabled} onToggleVoice={() => {
      const enabled = !voiceEnabled;
      setVoiceEnabled(enabled); localStorage.setItem('ollie.desktopVoice', String(enabled));
      if (!enabled) void desktopVoice.current!.stop().catch(() => {});
    }} onTestVoice={() => {
      if (!voiceEnabledRef.current) { setVoiceEnabled(true); localStorage.setItem('ollie.desktopVoice', 'true'); }
      void listening.current!.speakExternal('Oi! Sou a Ollie. Essa é minha voz mais natural no computador.')
        .catch(() => setNotice({ text: 'Não consegui reproduzir o teste de voz.', kind: 'error' }));
    }}
    listeningEnabled={listening.current.enabled} phase={listeningPhase} level={microphoneLevel} heard={heardText}
    devices={inputDevices} device={inputDevice} onListening={enabled => void changeListening(enabled)}
    onDevice={device => { setInputDevice(device); inputDeviceRef.current = device; void changeListening(listening.current!.enabled, device); }}
    onListenNow={() => { setPage('chat'); void listening.current!.listenNow(); }} onCancel={() => void listening.current!.cancel()}
    onReconnect={() => reconnectRef.current()} onScan={() => void handleCommand({ comando: 'estudar_pc' })}
    onHardware={() => void handleCommand({ comando: 'inicializar_hardware' })}
    policy={policy} policyLoading={policyLoading} policyError={policyError} policyBusy={policyBusy}
    onPolicy={value => void updatePolicy(value)} onRefreshPolicy={() => void fetchPolicy()}
    routines={discoveredRoutines} routinesLoading={routinesLoading} routinesError={routinesError} routineBusy={routineBusy}
    onRefreshRoutines={() => void fetchDiscovered()} onApprove={name => void approveRoutine(name)} onReject={name => void rejectRoutine(name)}
    notice={notice} onDismissNotice={() => setNotice(null)}
  />;
}
