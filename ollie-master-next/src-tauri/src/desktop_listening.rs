use serde::{Deserialize, Serialize};
use std::{collections::HashMap, io::{BufRead, BufReader, Write}, process::{Child, Command, Stdio},
    sync::{Arc, Mutex, atomic::{AtomicU64, Ordering}, mpsc}, time::Duration};
use tauri::{AppHandle, Emitter, Manager};

struct Worker {
    child: Child,
    instance_id: String,
    pending: Arc<Mutex<HashMap<u64, mpsc::Sender<()>>>>,
}
static WORKER: Mutex<Option<Worker>> = Mutex::new(None);
static REQUEST: AtomicU64 = AtomicU64::new(1);

#[derive(Serialize, Deserialize, Default)]
pub struct Preferences { pub enabled: bool, pub device: Option<i32> }

fn preferences_path() -> std::path::PathBuf {
    super::backend_dir().join(".artifacts/wakeword/desktop-settings.json")
}

fn command() -> Result<Command, String> {
    let root = super::backend_dir();
    let python = root.join(".artifacts/wakeword/venv").join(if cfg!(windows) { "Scripts/python.exe" } else { "bin/python" });
    if !python.is_file() { return Err("A voz local do computador ainda nao foi preparada.".into()); }
    let mut command = Command::new(python);
    command.arg("-u").arg(root.join("tools/wakeword/desktop_worker.py"))
        .current_dir(root).env("PYTHONUTF8", "1");
    #[cfg(windows)] {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    Ok(command)
}

pub fn shutdown() {
    if let Ok(mut state) = WORKER.lock() {
        if let Some(mut worker) = state.take() {
            let _ = worker.child.kill();
            let _ = worker.child.wait();
            if let Ok(mut pending) = worker.pending.lock() { pending.clear(); }
        }
    }
}

#[tauri::command]
pub fn desktop_listening_preferences() -> Result<Preferences, String> {
    let path = preferences_path();
    if !path.is_file() { return Ok(Preferences::default()); }
    serde_json::from_slice(&std::fs::read(path).map_err(|e| e.to_string())?).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn save_desktop_listening_preferences(enabled: bool, device: Option<i32>) -> Result<(), String> {
    let path = preferences_path();
    std::fs::create_dir_all(path.parent().unwrap()).map_err(|e| e.to_string())?;
    std::fs::write(path, serde_json::to_vec(&Preferences { enabled, device }).unwrap()).map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn desktop_input_devices() -> Result<serde_json::Value, String> {
    tauri::async_runtime::spawn_blocking(|| {
        let output = command()?.arg("--devices").output().map_err(|e| e.to_string())?;
        if !output.status.success() { return Err("Nao consegui listar os microfones.".into()); }
        serde_json::from_slice(&output.stdout).map_err(|e| e.to_string())
    }).await.map_err(|e| e.to_string())?
}

#[tauri::command]
pub fn stop_desktop_listening(instance_id: String) {
    if let Ok(mut state) = WORKER.lock() {
        if state.as_ref().is_some_and(|worker| worker.instance_id == instance_id) {
            if let Some(mut worker) = state.take() {
                let _ = worker.child.kill();
                let _ = worker.child.wait();
                if let Ok(mut map) = worker.pending.lock() { map.clear(); }
            }
        }
    }
}

#[tauri::command]
pub fn start_desktop_listening(app: AppHandle, instance_id: String, device: Option<i32>) -> Result<(), String> {
    let mut command = command()?;
    if let Some(device) = device { command.args(["--device", &device.to_string()]); }
    let diagnostic_dir = super::backend_dir().join(".artifacts/wakeword");
    let _ = std::fs::create_dir_all(&diagnostic_dir);
    let stderr = std::fs::OpenOptions::new().create(true).append(true)
        .open(diagnostic_dir.join("desktop-worker.log")).map_err(|e| e.to_string())?;
    let mut state = WORKER.lock().map_err(|e| e.to_string())?;
    if let Some(mut old) = state.take() {
        let _ = old.child.kill();
        let _ = old.child.wait();
        if let Ok(mut map) = old.pending.lock() { map.clear(); }
    }
    let mut child = command.stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(stderr).spawn().map_err(|e| e.to_string())?;
    let stdout = child.stdout.take().ok_or("Saida do detector indisponivel")?;
    let pid = child.id();
    let pending = Arc::new(Mutex::new(HashMap::<u64, mpsc::Sender<()>>::new()));
    *state = Some(Worker { child, instance_id: instance_id.clone(), pending: pending.clone() });
    drop(state);
    std::thread::spawn(move || {
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            let Ok(mut event) = serde_json::from_str::<serde_json::Value>(&line) else { continue };
            if let Some(ack) = event.get("ack").and_then(|v| v.as_u64()) {
                if let Ok(mut pending) = pending.lock() { if let Some(sender) = pending.remove(&ack) { let _ = sender.send(()); } }
                continue;
            }
            let active = WORKER.lock().map(|s| s.as_ref().is_some_and(|w| w.child.id() == pid)).unwrap_or(false);
            if !active { break; }
            event["instance_id"] = serde_json::json!(instance_id);
            if event["type"] == "wake" {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.show();
                    let _ = window.unminimize();
                    let _ = window.set_focus();
                }
            }
            // Diagnostico de estado sem audio nem texto reconhecido.
            if event["type"] != "partial" && event["type"] != "level" {
                let summary = serde_json::json!({"type":event["type"], "state":event["state"],
                    "at_ms":std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap_or_default().as_millis(),
                    "score":event["score"], "instance_id":instance_id, "pid":pid});
                if let Ok(mut file) = std::fs::OpenOptions::new().create(true).append(true).open(diagnostic_dir.join("desktop-events.jsonl")) {
                    let _ = writeln!(file, "{}", summary);
                }
            }
            let _ = app.emit("desktop-listening", event);
        }
        if let Ok(mut map) = pending.lock() { map.clear(); }
        let mut state = WORKER.lock().unwrap();
        if state.as_ref().is_some_and(|w| w.child.id() == pid) {
            if let Some(mut worker) = state.take() { let _ = worker.child.wait(); }
            let _ = app.emit("desktop-listening", serde_json::json!({"type":"error", "instance_id":instance_id,
                "message":"A escuta foi encerrada. Confira o microfone e ative novamente."}));
        }
    });
    Ok(())
}

#[tauri::command]
pub async fn control_desktop_listening(action: String, instance_id: String) -> Result<(), String> {
    if !["pause", "resume", "listen"].contains(&action.as_str()) { return Err("Acao de voz invalida".into()); }
    tauri::async_runtime::spawn_blocking(move || {
        let id = REQUEST.fetch_add(1, Ordering::Relaxed);
        let (sender, receiver) = mpsc::channel();
        let pending;
        {
            let mut state = WORKER.lock().map_err(|e| e.to_string())?;
            let worker = state.as_mut().ok_or("Escuta nao esta ativa")?;
            if worker.instance_id != instance_id { return Err("Sessao de escuta substituida".into()); }
            pending = worker.pending.clone();
            pending.lock().map_err(|e| e.to_string())?.insert(id, sender);
            let input = worker.child.stdin.as_mut().ok_or("Controle da escuta indisponivel")?;
            let payload = serde_json::json!({"action":action,"request_id":id,"instance_id":instance_id});
            if writeln!(input, "{}", payload).and_then(|_| input.flush()).is_err() {
                pending.lock().unwrap().remove(&id);
                return Err("Nao consegui controlar o microfone".into());
            }
        }
        let result = receiver.recv_timeout(Duration::from_secs(4)).map_err(|_| "O microfone nao confirmou a pausa/retomada".to_string());
        if let Ok(mut map) = pending.lock() { map.remove(&id); }
        result
    }).await.map_err(|e| e.to_string())?
}
