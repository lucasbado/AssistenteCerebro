use std::io::Write;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;

static SPEECH: Mutex<Option<Child>> = Mutex::new(None);

// The response is JSON on stdin, never interpolated into PowerShell code.
const SPEAK: &str = r#"
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
$payload = [Console]::In.ReadToEnd() | ConvertFrom-Json
$voice = New-Object -ComObject SAPI.SpVoice
$portuguese = @($voice.GetVoices() | Where-Object { ($_.GetAttribute('Language') -split ';') -contains '416' }) | Select-Object -First 1
if ($portuguese) { $voice.Voice = $portuguese }
[void]$voice.Speak([string]$payload.text, 16)
"#;

fn stop_current(state: &mut Option<Child>) {
    if let Some(mut child) = state.take() {
        let _ = child.kill();
        let _ = child.wait();
    }
}

pub fn shutdown() {
    if let Ok(mut state) = SPEECH.lock() { stop_current(&mut state); }
}

#[tauri::command]
pub async fn stop_speech() -> Result<(), String> {
    let mut state = SPEECH.lock().map_err(|_| "Não consegui parar a voz")?;
    stop_current(&mut state);
    Ok(())
}

#[tauri::command]
pub async fn speak_response(text: String) -> Result<(), String> {
    if text.trim().is_empty() || text.chars().count() > 4000 {
        return Err("Resposta vazia ou longa demais para leitura".into());
    }
    tauri::async_runtime::spawn_blocking(move || speak(&text))
        .await.map_err(|e| e.to_string())?
}

fn speak(text: &str) -> Result<(), String> {
    let mut command = Command::new("powershell.exe");
    command.args(["-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", SPEAK])
        .stdin(Stdio::piped()).stdout(Stdio::null()).stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000); // CREATE_NO_WINDOW
    }
    let id;
    {
        let mut state = SPEECH.lock().map_err(|_| "Voz indisponível")?;
        stop_current(&mut state);
        let mut child = command.spawn().map_err(|_| "Não consegui iniciar a voz do Windows")?;
        let data = serde_json::json!({"text": text}).to_string();
        let input = child.stdin.take().ok_or("Entrada de voz indisponível")?;
        if let Err(error) = { let mut input = input; input.write_all(data.as_bytes()) } {
            let _ = child.kill();
            let _ = child.wait();
            return Err(error.to_string());
        }
        id = child.id();
        *state = Some(child);
    }
    loop {
        {
            let mut state = SPEECH.lock().map_err(|_| "Voz indisponível")?;
            let Some(child) = state.as_mut().filter(|c| c.id() == id) else { return Ok(()) };
            if let Some(status) = child.try_wait().map_err(|e| e.to_string())? {
                *state = None;
                return if status.success() { Ok(()) } else { Err("O Windows não conseguiu reproduzir a resposta".into()) };
            }
        }
        std::thread::sleep(Duration::from_millis(50));
    }
}
