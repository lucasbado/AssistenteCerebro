import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Zap,
  Cpu,
  Database,
  Activity,
  Terminal,
  Send,
  X,
  Minus,
  RefreshCw,
  Search,
  Shield,
  Maximize2
} from 'lucide-react';
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// --- Interfaces ---
interface HardwareUpdate {
  cpu: number;
  ram: number;
  processes: any[];
}

interface WindowUpdate {
  title: string;
  process: string;
}

// --- Components ---

const NeonStat = ({ label, value, segments, color }: { label: string, value: string, segments: number, color: string }) => (
  <div className="space-y-2">
    <div className="flex justify-between items-center text-[11px] font-medium">
      <span className="text-gray-500 uppercase tracking-widest">{label}</span>
      <span className="text-white font-bold">{value}</span>
    </div>
    <div className="flex gap-1">
      {Array.from({ length: 10 }).map((_, i) => (
        <div
          key={i}
          className={cn(
            "h-1.5 flex-1 rounded-sm transition-all duration-500",
            i < segments ? color : "bg-white/5"
          )}
          style={i < segments ? { boxShadow: `0 0 8px var(--color-${color.replace('bg-', '')})` } : {}}
        />
      ))}
    </div>
  </div>
);

const LogEntry = ({ timestamp, text, color }: { timestamp: string, text: string, color: string }) => (
  <div className="flex gap-3 text-[11px] font-mono py-1 group">
    <span className="text-gray-600 shrink-0">[{timestamp}]</span>
    <span className={cn("break-all leading-relaxed", color)}>{text}</span>
  </div>
);

export default function App() {
  const [mood, setMood] = useState<'idle' | 'thinking' | 'alert'>('idle');
  const [isConnected, setIsConnected] = useState(false);
  const [logs, setLogs] = useState<{t: string, m: string, c: string}[]>([]);
  const [cpu, setCpu] = useState(0);
  const [ram, setRam] = useState(0);
  const [vision, setVision] = useState({ process: "IDLE", title: "Scanning neural activity..." });
  const [chatText, setChatInput] = useState("");
  const [wsInstance, setWs] = useState<WebSocket | null>(null);
  const [showInterventionModal, setShowInterventionModal] = useState(false);
  const [policy, setPolicy] = useState({
    auto_open_enabled: false,
    min_priority_score: 0.85,
    whitelist: ["whatsapp", "telegram", "vscode"],
    blacklist: ["jogo", "netflix", "youtube"]
  });

  const fetchPolicy = async () => {
    try {
      const apiUrl = await invoke<string>("get_api_url");
      const res = await fetch(`${apiUrl}/api/v1/pc/intervention/policy`);
      const data = await res.json();
      setPolicy(data);
    } catch (e) {
      console.error("Failed to fetch policy", e);
    }
  };

  const updatePolicy = async (newPolicy: any) => {
    try {
      const apiUrl = await invoke<string>("get_api_url");
      const res = await fetch(`${apiUrl}/api/v1/pc/intervention/policy`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(newPolicy)
      });
      const data = await res.json();
      setPolicy(data.policy);
      addLog("🛡️ Intervention policy updated successfully.", "text-neon-cyan");
    } catch (e) {
      addLog(`Failed to update policy: ${e}`, "text-red-400");
    }
  };

  useEffect(() => {
    fetchPolicy();
  }, []);

  // Mood Colors
  const accentColor = mood === 'thinking' ? '#bc13fe' : mood === 'alert' ? '#ff9800' : '#05ffa1';
  const accentTailwind = mood === 'thinking' ? 'bg-neon-purple' : mood === 'alert' ? 'bg-neon-orange' : 'bg-neon-cyan';

  const addLog = (m: string, c: string = "text-gray-400") => {
    setLogs(prev => [...prev.slice(-99), { t: new Date().toLocaleTimeString(), m, c }]);
  };

  const handleCommand = async (data: any) => {
    try {
      addLog(`⚡ Sending Command: ${data.comando || data.acao || 'CUSTOM'}`, "text-neon-cyan");
      const apiUrl = await invoke<string>("get_api_url");
      await fetch(`${apiUrl}/api/v1/pc/comando`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data)
      });
    } catch (err) {
      addLog(`Bridge Error: ${err}`, "text-red-400");
    }
  };

  const sendChat = async () => {
    if (!chatText.trim() || !wsInstance) return;
    addLog(`👤 USER >> ${chatText}`, "text-white");

    wsInstance.send(JSON.stringify({
      categoria: "SISTEMA_COMANDO_USUARIO",
      payload: { texto: chatText },
      origem: "PC"
    }));

    setChatInput("");
    setMood("thinking");
  };

  const setupWS = async () => {
    try {
      const cloudUrl = await invoke<string>("get_cloud_url");
      addLog(`Connecting to: ${cloudUrl}`, "text-gray-500 text-[10px]");

      const ws = new WebSocket(cloudUrl);
      setWs(ws);

      ws.onopen = () => {
        setIsConnected(true);
        addLog("📡 Sincronização com Cloud concluída.", "text-neon-cyan");
        ws.send(JSON.stringify({ tipo_ws: "REGISTRO", id: "PC_MASTER" }));
      };

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);

        if (data.tipo_ws === "CHAT_RESPONSE") {
          addLog(`🤖 OLLIE: ${data.texto}`, "text-neon-purple text-[13px] font-bold");
          setMood("thinking");
        }

        if (data.comando) {
          addLog(`⚡ EXEC_CMD: ${data.comando.toUpperCase()}`, "text-neon-cyan");
          handleCommand(data);
        }

        if (data.mood) setMood(data.mood);

        // Se recebermos status do Render, marcamos como conectado
        if (data.tipo_ws === "STATUS_PC" && data.id === "PC_MASTER") {
           setIsConnected(true);
        }
      };

      ws.onclose = () => {
        setIsConnected(false);
        addLog("❌ Falha de link: Cloud connection lost.", "text-red-400");
        // Re-setup after 5s if still active
        setTimeout(() => {
           if (document.visibilityState === 'visible') setupWS();
        }, 5000);
      };

      ws.onerror = (err) => {
        console.error("WS Error:", err);
        addLog(`WS Error: Connection issues detected.`, "text-red-500");
      };

    } catch (err) {
      addLog(`Setup Error: ${err}`, "text-red-400");
    }
  };

  // --- Effects ---

  useEffect(() => {
    const logContainer = document.querySelector('.custom-scrollbar');
    if (logContainer) logContainer.scrollTop = logContainer.scrollHeight;
  }, [logs]);

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
            processes: event.payload.processes
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

        const ws = new WebSocket(cloudUrl);
        activeSocket = ws;
        setWs(ws);

        ws.onopen = () => {
          isConnecting = false;
          if (!isComponentMounted) { ws.close(); return; }
          setIsConnected(true);
          addLog("📡 Sincronização com Cloud concluída.", "text-neon-cyan");
          ws.send(JSON.stringify({ tipo_ws: "REGISTRO", id: "PC_MASTER" }));
        };

        ws.onmessage = (event) => {
          if (!isComponentMounted) return;
          const data = JSON.parse(event.data);

          if (data.tipo_ws === "CHAT_RESPONSE") {
            addLog(`🤖 OLLIE: ${data.texto}`, "text-neon-purple text-[13px] font-bold");
            setMood("thinking");
          }

          if (data.comando) {
            addLog(`⚡ EXEC_CMD: ${data.comando.toUpperCase()}`, "text-neon-cyan");
            handleCommand(data);
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
          isConnecting = false;
          if (!isComponentMounted) return;
          setIsConnected(false);
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

    setupWS();

    return () => {
      isComponentMounted = false;
      if (unlistenHardware) unlistenHardware.then(u => u());
      if (unlistenWindow) unlistenWindow.then(u => u());
      if (activeSocket) activeSocket.close();
      if (reconnectTimeout) window.clearTimeout(reconnectTimeout);
    };
  }, []);

  return (
    <main className="relative w-screen h-screen overflow-hidden p-6 text-white font-sans selection:bg-neon-purple/30 bg-black/10">
      {/* --- AURA BACKGROUNDS --- */}
      <motion.div
        animate={{
          scale: [1, 1.2, 1],
          opacity: [0.25, 0.4, 0.25],
          x: [-200, -150, -200],
          y: [-200, -150, -200]
        }}
        transition={{ duration: 8, repeat: Infinity, ease: "easeInOut" }}
        className="absolute w-[600px] h-[600px] rounded-full blur-[100px]"
        style={{
          background: `radial-gradient(circle, ${accentColor} 0%, transparent 70%)`,
          left: -200, top: -200
        }}
      />
      <motion.div
        animate={{
          scale: [1, 1.1, 1],
          opacity: [0.1, 0.2, 0.1],
          x: [150, 100, 150],
          y: [150, 100, 150]
        }}
        transition={{ duration: 10, repeat: Infinity, ease: "easeInOut" }}
        className="absolute w-[500px] h-[500px] rounded-full blur-[80px]"
        style={{
          background: `radial-gradient(circle, #bc13fe 0%, transparent 70%)`,
          right: -150, bottom: -150
        }}
      />

      {/* --- MAIN INTERFACE --- */}
      <div className="relative z-10 w-full h-full flex flex-col gap-6">

        {/* HEADER */}
        <header className="flex justify-between items-center px-4">
          <div className="flex items-center gap-4">
            <Activity className="w-8 h-8 text-neon-cyan" />
            <h1 className="text-xl font-black tracking-[4px] uppercase">Ollie Master</h1>
          </div>

          <div className="flex items-center gap-6">
            <div className="glass px-6 py-3 rounded-3xl flex items-center gap-3">
              <div className={cn("w-2.5 h-2.5 rounded-full", isConnected ? accentTailwind : "bg-red-500 animate-pulse")} />
              <span className={cn("text-[11px] font-bold tracking-widest", isConnected ? "text-white" : "text-red-400")}>
                {isConnected ? "ONLINE // NEURAL LINK ACTIVE" : "OFFLINE // LINK BROKEN"}
              </span>
            </div>

            <div className="flex items-center">
              <button
                onClick={() => invoke("minimize_window")}
                className="p-2 text-gray-500 hover:text-white transition-colors"
                title="Minimize"
              >
                <Minus className="w-4 h-4" />
              </button>
              <button
                onClick={() => invoke("maximize_window")}
                className="p-2 text-gray-500 hover:text-white transition-colors"
                title="Maximize / Fullscreen"
              >
                <Maximize2 className="w-4 h-4" />
              </button>
              <button
                onClick={() => invoke("close_window")}
                className="p-2 text-gray-500 hover:text-red-400 transition-colors"
                title="Close"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>
        </header>

        <div className="flex-1 flex gap-6 overflow-hidden">
          {/* LEFT PANEL */}
          <aside className="w-[340px] flex flex-col gap-6 overflow-y-auto custom-scrollbar pr-2">

            {/* OLLIE'S VISION */}
            <section className="glass rounded-3xl p-6 flex flex-col gap-4">
              <h2 className="text-[11px] font-bold text-gray-500 tracking-[2px] uppercase">Ollie's Vision</h2>
              <div className="relative h-40 bg-black/30 rounded-2xl border border-white/5 overflow-hidden p-6 flex flex-col justify-center gap-2">
                {/* Grid Background */}
                <div className="absolute inset-0 flex">
                  {Array.from({ length: 5 }).map((_, i) => <div key={i} className="flex-1 border-r border-white/[0.03]" />)}
                </div>
                <div className="absolute inset-0 flex flex-col">
                  {Array.from({ length: 4 }).map((_, i) => <div key={i} className="flex-1 border-b border-white/[0.03]" />)}
                </div>

                <div className="relative z-10 space-y-1">
                  <h3 className="text-xl font-black text-neon-cyan truncate uppercase">{vision.process}</h3>
                  <p className="text-xs text-gray-400 italic truncate">{vision.title}</p>
                </div>

                {/* Scan Line */}
                <motion.div
                  animate={{ y: [0, 160, 0] }}
                  transition={{ duration: 4, repeat: Infinity, ease: "linear" }}
                  className="absolute left-0 right-0 h-[2px] bg-neon-cyan/30 shadow-[0_0_15px_rgba(5,255,161,0.5)]"
                />

                {/* REC Indicator */}
                <div className="absolute top-4 right-4 flex items-center gap-2">
                  <motion.div
                    animate={{ opacity: [1, 0, 1] }}
                    transition={{ duration: 1, repeat: Infinity }}
                    className="w-2 h-2 rounded-full bg-red-500"
                  />
                  <span className="text-[9px] font-black tracking-tighter text-red-400">REC</span>
                </div>
              </div>
            </section>

            {/* HARDWARE NEURONS */}
            <section className="glass rounded-3xl p-6 flex flex-col gap-6">
              <h2 className="text-[11px] font-bold text-gray-500 tracking-[2px] uppercase">Hardware Neurons</h2>
              <div className="space-y-4">
                <NeonStat label="CPU LOAD" value={`${cpu}%`} segments={Math.floor(cpu/10)} color="bg-neon-cyan" />
                <NeonStat label="RAM STACK" value={`${ram}%`} segments={Math.floor(ram/10)} color="bg-neon-purple" />
              </div>
            </section>

            {/* SUPER PODERES & INTERVENÇÃO */}
            <section className="glass rounded-3xl p-6 flex flex-col gap-4">
              <div className="flex justify-between items-center">
                <h2 className="text-[11px] font-bold text-gray-500 tracking-[2px] uppercase flex items-center gap-1.5">
                  <Shield className="w-3.5 h-3.5 text-neon-cyan" /> Super Poderes
                </h2>
                <button
                  onClick={() => setShowInterventionModal(true)}
                  className="text-[10px] text-neon-cyan hover:underline font-mono"
                >
                  Configurar
                </button>
              </div>
              <div className="glass p-3 rounded-2xl flex items-center justify-between">
                <span className="text-xs font-bold text-white">Auto-Open Notificações</span>
                <input
                  type="checkbox"
                  checked={policy.auto_open_enabled}
                  onChange={(e) => updatePolicy({ ...policy, auto_open_enabled: e.target.checked })}
                  className="w-4 h-4 accent-neon-cyan cursor-pointer"
                />
              </div>
            </section>

            {/* QUICK ACTIONS */}
            <section className="glass rounded-3xl p-4 flex justify-around text-neon-cyan">
              {[
                { icon: Search, label: "Neural Scan", action: () => handleCommand({ comando: "estudar_pc" }) },
                { icon: RefreshCw, label: "Reset Link", action: () => setupWS() },
                { icon: Database, label: "Hardware Init", action: () => handleCommand({ comando: "inicializar_hardware" }) },
                { icon: Shield, label: "Intervention Governor", action: () => setShowInterventionModal(true) }
              ].map((item, i) => (
                <button
                  key={i}
                  onClick={item.action}
                  className="p-3 rounded-xl hover:bg-white/5 transition-all group relative active:scale-90"
                  title={item.label}
                >
                  <item.icon className="w-5 h-5" />
                </button>
              ))}
            </section>
          </aside>

          {/* MAIN CONSOLE PANEL */}
          <section className="flex-1 glass rounded-3xl p-6 flex flex-col gap-5">
            <div className="flex justify-between items-center">
              <h2 className="text-[11px] font-bold text-gray-500 tracking-[2px] uppercase">Neural Stream Log</h2>
              <Terminal className="w-5 h-5 text-neon-cyan" />
            </div>

            <div className="flex-1 glass-dark rounded-2xl p-4 overflow-y-auto custom-scrollbar">
              <AnimatePresence initial={false}>
                {logs.map((log, i) => (
                  <motion.div
                    key={i}
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                    className={i === logs.length - 1 ? "shadow-[0_0_10px_rgba(162,249,210,0.1)] rounded" : ""}
                  >
                    <LogEntry timestamp={log.t} text={log.m} color={log.c} />
                  </motion.div>
                ))}
              </AnimatePresence>
            </div>

            <div className="flex gap-4 items-center bg-white/[0.02] rounded-2xl p-2 border border-neon-purple/30">
              <input
                className="flex-1 bg-transparent border-none outline-none px-4 py-2 text-sm font-mono placeholder:text-gray-600"
                placeholder="Neural Interface: Type command..."
                value={chatText}
                onChange={(e) => setChatInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && sendChat()}
              />
              <button
                onClick={sendChat}
                className="bg-white/5 p-3 rounded-xl hover:bg-neon-purple/20 transition-all"
              >
                <Send className="w-5 h-5 text-neon-cyan" />
              </button>
            </div>
          </section>
        </div>
      </div>

      {/* --- INTERVENTION GOVERNOR MODAL --- */}
      {showInterventionModal && (
        <div className="absolute inset-0 z-50 bg-black/95 flex items-center justify-center p-6">
          <div className="glass w-full max-w-lg rounded-3xl p-6 flex flex-col gap-6 border border-white/10">
            <div className="flex justify-between items-center">
              <h3 className="text-lg font-black tracking-wider uppercase text-neon-cyan flex items-center gap-2">
                <Shield className="w-5 h-5" /> Intervention Governor
              </h3>
              <button onClick={() => setShowInterventionModal(false)} className="text-gray-400 hover:text-white">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-4 text-xs">
              <div className="flex justify-between items-center glass p-4 rounded-2xl">
                <div>
                  <h4 className="font-bold text-white">Auto-Open Apps on Notification</h4>
                  <p className="text-gray-400 text-[10px]">Permitir que a Ollie abra apps automaticamente</p>
                </div>
                <input
                  type="checkbox"
                  checked={policy.auto_open_enabled}
                  onChange={(e) => updatePolicy({ ...policy, auto_open_enabled: e.target.checked })}
                  className="w-5 h-5 accent-neon-cyan cursor-pointer"
                />
              </div>

              <div className="glass p-4 rounded-2xl space-y-2">
                <div className="flex justify-between">
                  <span className="font-bold text-white">Min Priority Score Threshold</span>
                  <span className="text-neon-cyan font-mono">{policy.min_priority_score}</span>
                </div>
                <input
                  type="range"
                  min="0.5"
                  max="1.0"
                  step="0.05"
                  value={policy.min_priority_score}
                  onChange={(e) => updatePolicy({ ...policy, min_priority_score: parseFloat(e.target.value) })}
                  className="w-full accent-neon-purple cursor-pointer"
                />
              </div>

              <div className="glass p-4 rounded-2xl space-y-2">
                <span className="font-bold text-white block">Whitelist (Apps permitidos)</span>
                <div className="flex flex-wrap gap-2">
                  {(policy.whitelist || []).map((app: string, idx: number) => (
                    <span key={idx} className="bg-neon-cyan/10 text-neon-cyan px-2.5 py-1 rounded-full text-[10px] font-mono border border-neon-cyan/20">
                      {app}
                    </span>
                  ))}
                </div>
              </div>

              <div className="glass p-4 rounded-2xl space-y-2">
                <span className="font-bold text-white block">Blacklist (Nunca abrir sozinhos)</span>
                <div className="flex flex-wrap gap-2">
                  {(policy.blacklist || []).map((app: string, idx: number) => (
                    <span key={idx} className="bg-red-500/10 text-red-400 px-2.5 py-1 rounded-full text-[10px] font-mono border border-red-500/20">
                      {app}
                    </span>
                  ))}
                </div>
              </div>
            </div>

            <button
              onClick={() => setShowInterventionModal(false)}
              className="bg-neon-cyan/25 hover:bg-neon-cyan/40 text-neon-cyan font-bold py-3 rounded-2xl transition-all tracking-widest uppercase text-xs border border-neon-cyan/40 shadow-[0_0_15px_rgba(5,255,161,0.2)]"
            >
              Close Governor
            </button>
          </div>
        </div>
      )}
    </main>
  );
}
