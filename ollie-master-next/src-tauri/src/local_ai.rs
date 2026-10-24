use std::io::Write;
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};
use serde_json::{json, Value};

static BUSY: AtomicBool = AtomicBool::new(false);
struct BusyGuard;
impl Drop for BusyGuard { fn drop(&mut self) { BUSY.store(false, Ordering::SeqCst); } }

fn helper(data: Value) -> Result<Value, String> {
    let mut cmd = Command::new(super::get_python_path());
    cmd.arg(super::backend_dir().join("tools/local_ai/bridge.py"))
        .current_dir(super::backend_dir()).env("PYTHONDONTWRITEBYTECODE", "1")
        .stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::null());
    #[cfg(windows)] {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x08000000);
    }
    let mut child = cmd.spawn().map_err(|_| "Não consegui iniciar a IA local.")?;
    let mut input = child.stdin.take().ok_or("Entrada indisponível.")?;
    input.write_all(data.to_string().as_bytes()).map_err(|_| "Falha ao enviar contexto.")?;
    drop(input);
    // Lê em paralelo para evitar bloquear o pipe com respostas UTF-8 maiores.
    let mut stdout = child.stdout.take().ok_or("Saída indisponível.")?;
    let reader = std::thread::spawn(move || {
        use std::io::Read;
        let mut output = Vec::new();
        stdout.read_to_end(&mut output).map(|_| output)
    });
    let start = Instant::now();
    loop {
        if let Some(status) = child.try_wait().map_err(|_| "Falha na IA local.")? {
            let bytes = reader.join().map_err(|_| "Falha na resposta local.")?
                .map_err(|_| "Falha na leitura local.")?;
            if !status.success() { return Err("A IA local não conseguiu responder.".into()); }
            return serde_json::from_slice(&bytes).map_err(|_| "Resposta local inválida.".into());
        }
        if start.elapsed() > Duration::from_secs(48) {
            let _ = child.kill(); let _ = child.wait();
            return Err("A IA local excedeu o tempo de resposta.".into());
        }
        std::thread::sleep(Duration::from_millis(50));
    }
}

#[tauri::command]
pub async fn probe_local_ai() -> Value {
    tauri::async_runtime::spawn_blocking(|| helper(json!({"modo": "probe"}))).await
        .ok().and_then(Result::ok).unwrap_or(json!({"disponivel": false}))
}

#[tauri::command]
pub async fn generate_local_ai(prompt: String, system: String, max_tokens: u32) -> Result<Value, String> {
    if prompt.chars().count() + system.chars().count() > 30000 || max_tokens == 0 || max_tokens > 1200 {
        return Err("Pedido de IA inválido.".into());
    }
    if BUSY.swap(true, Ordering::SeqCst) { return Err("A IA local está ocupada.".into()); }
    tauri::async_runtime::spawn_blocking(move || {
        let _guard = BusyGuard;
        helper(json!({"modo": "generate", "prompt": prompt, "system": system, "max_tokens": max_tokens}))
    }).await.map_err(|_| "A IA local foi interrompida.".to_string())?
}
