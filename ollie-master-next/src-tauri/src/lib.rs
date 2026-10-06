use tauri::{AppHandle, Emitter, Manager};
use sysinfo::{System, ProcessRefreshKind, CpuRefreshKind};
use active_win_pos_rs::get_active_window;
use std::time::Duration;
use tokio::time::sleep;
use std::sync::atomic::{AtomicBool, Ordering};

static MONITORING_STARTED: AtomicBool = AtomicBool::new(false);

#[derive(serde::Serialize, Clone)]
struct HardwareStats {
    cpu: u32,
    ram: u32,
    processes: Vec<serde_json::Value>,
}

#[derive(serde::Serialize, Clone)]
struct WindowInfo {
    title: String,
    process: String,
}

#[tauri::command]
async fn start_monitoring(app_handle: AppHandle) {
    // Evita iniciar múltiplos loops se o comando for chamado várias vezes (ex: React StrictMode)
    if MONITORING_STARTED.swap(true, Ordering::SeqCst) {
        return;
    }

    // CPU/RAM Monitoring Loop
    let app_cpu = app_handle.clone();
    tauri::async_runtime::spawn(async move {
        let mut sys = System::new_all();
        loop {
            sys.refresh_all();

            let cpu = sys.global_cpu_info().cpu_usage() as u32;
            let ram = (sys.used_memory() as f64 / sys.total_memory() as f64 * 100.0) as u32;

            // Get top 5 processes by CPU
            let mut processes = sys
                .processes()
                .values()
                .filter(|p| p.cpu_usage() > 0.1)
                .collect::<Vec<_>>();

            processes.sort_by(|a, b| b.cpu_usage().partial_cmp(&a.cpu_usage()).unwrap());

            let top_procs = processes
                .iter()
                .take(5)
                .map(|p| serde_json::json!({ "n": p.name(), "c": format!("{:.1}", p.cpu_usage()) }))
                .collect::<Vec<_>>();

            let _ = app_cpu.emit("hardware-update", HardwareStats { cpu, ram, processes: top_procs });
            sleep(Duration::from_secs(15)).await; // Aumentado para 15s para reduzir carga e rede
        }
    });

    // Active Window Monitoring Loop
    let app_win = app_handle.clone();
    tauri::async_runtime::spawn(async move {
        let mut last_title = String::new();
        loop {
            if let Ok(active_window) = get_active_window() {
                if active_window.title != last_title {
                    last_title = active_window.title.clone();
                    let _ = app_win.emit("window-update", WindowInfo {
                        title: active_window.title,
                        process: active_window.app_name,
                    });
                }
            }
            sleep(Duration::from_secs(3)).await; // Aumentado para 3s
        }
    });
}

#[tauri::command]
async fn close_window(app_handle: AppHandle) {
    let _ = app_handle.get_webview_window("main").unwrap().close();
}

#[tauri::command]
async fn minimize_window(app_handle: AppHandle) {
    let _ = app_handle.get_webview_window("main").unwrap().minimize();
}

#[tauri::command]
async fn maximize_window(app_handle: AppHandle) {
    if let Some(window) = app_handle.get_webview_window("main") {
        if window.is_maximized().unwrap_or(false) {
            let _ = window.unmaximize();
        } else {
            let _ = window.maximize();
        }
    }
}

#[tauri::command]
fn get_cloud_url() -> String {
    dotenvy::from_path("../../../.env").ok();
    let env = std::env::var("ENVIRONMENT").unwrap_or_else(|_| "production".to_string());
    if env == "development" {
        std::env::var("OLLIE_LOCAL_URL").unwrap_or_else(|_| "ws://localhost:8000/api/v1/ws/alertas".to_string())
    } else {
        std::env::var("OLLIE_CLOUD_URL").unwrap_or_else(|_| "wss://assistentecellfront.onrender.com/api/v1/ws/alertas".to_string())
    }
}

#[tauri::command]
fn get_api_url() -> String {
    dotenvy::from_path("../../../.env").ok();
    let env = std::env::var("ENVIRONMENT").unwrap_or_else(|_| "production".to_string());
    if env == "development" {
        "http://127.0.0.1:8000".to_string()
    } else {
        "https://assistentecellfront.onrender.com".to_string()
    }
}

#[tauri::command]
async fn execute_pc_command(comando: String, parametro: Option<String>) -> Result<String, String> {
    let param = parametro.unwrap_or_default();
    println!("⚡ Executing PC Command: {} with param: {}", comando, param);

    let target_macro = if !param.is_empty() { param.as_str() } else { comando.as_str() };

    match comando.as_str() {
        "executar_macro" | "macro" | "alt_tab" | "win_d" | "print_screen" | "task_mgr" | "alt_f4" | "win_tab" | "media_play_pause" | "media_next" | "media_prev" => {
            let py_code = format!(
                "import sys; sys.path.append(r'D:\\Programacao\\AssistenteCell'); from servicos.pc_control_service import pc_control_service; pc_control_service.executar_macro('{}')",
                target_macro
            );
            std::process::Command::new("python").args(["-c", &py_code]).spawn().map_err(|e| e.to_string())?;
            Ok(format!("Macro executed: {}", target_macro))
        }
        "bloquear_pc" => {
            let py_code = "import sys; sys.path.append(r'D:\\Programacao\\AssistenteCell'); from servicos.pc_control_service import pc_control_service; pc_control_service.bloquear_pc()";
            std::process::Command::new("python").args(["-c", py_code]).spawn().map_err(|e| e.to_string())?;
            Ok("PC locked".to_string())
        }
        "dormir_pc" | "suspender_pc" | "hibernar_pc" => {
            let py_code = "import sys; sys.path.append(r'D:\\Programacao\\AssistenteCell'); from servicos.pc_control_service import pc_control_service; pc_control_service.dormir_pc()";
            std::process::Command::new("python").args(["-c", py_code]).spawn().map_err(|e| e.to_string())?;
            Ok("PC suspended".to_string())
        }
        "desligar_pc" => {
            let py_code = "import sys; sys.path.append(r'D:\\Programacao\\AssistenteCell'); from servicos.pc_control_service import pc_control_service; pc_control_service.desligar_pc()";
            std::process::Command::new("python").args(["-c", py_code]).spawn().map_err(|e| e.to_string())?;
            Ok("PC shutdown initiated".to_string())
        }
        "reiniciar_pc" => {
            let py_code = "import sys; sys.path.append(r'D:\\Programacao\\AssistenteCell'); from servicos.pc_control_service import pc_control_service; pc_control_service.reiniciar_pc()";
            std::process::Command::new("python").args(["-c", py_code]).spawn().map_err(|e| e.to_string())?;
            Ok("PC restart initiated".to_string())
        }
        "abrir_app" | "abrir_programa" => {
            let target_app = if !param.is_empty() { &param } else { &comando };
            let py_code = format!(
                "import sys; sys.path.append(r'D:\\Programacao\\AssistenteCell'); from servicos.pc_control_service import pc_control_service; pc_control_service.abrir_app('{}')",
                target_app
            );
            std::process::Command::new("python").args(["-c", &py_code]).spawn().map_err(|e| e.to_string())?;
            Ok(format!("Opened app: {}", target_app))
        }
        "abrir_url" => {
            #[cfg(target_os = "windows")]
            {
                std::process::Command::new("cmd")
                    .args(["/C", "start", &param])
                    .spawn()
                    .map_err(|e| e.to_string())?;
            }
            Ok(format!("Opened URL: {}", param))
        }
        "mutar_mic" => {
            let py_code = "import sys; sys.path.append(r'D:\\Programacao\\AssistenteCell'); from servicos.pc_control_service import pc_control_service; pc_control_service.mutar_mic()";
            std::process::Command::new("python").args(["-c", py_code]).spawn().map_err(|e| e.to_string())?;
            Ok("Mic muted".to_string())
        }
        "spotify_play" => {
            let py_code = format!("import sys; sys.path.append(r'D:\\Programacao\\AssistenteCell'); from servicos.pc_control_service import pc_control_service; pc_control_service.tocar_spotify('{}')", param);
            std::process::Command::new("python").args(["-c", &py_code]).spawn().map_err(|e| e.to_string())?;
            Ok(format!("Spotify play: {}", param))
        }
        "volume_sistema" => {
            let val = param.parse::<i32>().unwrap_or(50);
            let py_code = format!("import sys; sys.path.append(r'D:\\Programacao\\AssistenteCell'); from servicos.pc_control_service import pc_control_service; pc_control_service.set_system_volume({})", val);
            std::process::Command::new("python").args(["-c", &py_code]).spawn().map_err(|e| e.to_string())?;
            Ok(format!("Volume set: {}", val))
        }
        "voicemeeter" => {
            if param.contains('=') {
                let parts: Vec<&str> = param.splitn(2, '=').collect();
                let py_code = format!("import sys; sys.path.append(r'D:\\Programacao\\AssistenteCell'); from servicos.pc_control_service import pc_control_service; pc_control_service.set_vm_param('{}', '{}')", parts[0].trim(), parts[1].trim());
                std::process::Command::new("python").args(["-c", &py_code]).spawn().map_err(|e| e.to_string())?;
            }
            Ok(format!("Voicemeeter param: {}", param))
        }
        "volume_canal" => {
            let val = param.parse::<i32>().unwrap_or(50);
            let py_code = format!(
                "import sys; sys.path.append(r'D:\\Programacao\\AssistenteCell'); from servicos.pc_control_service import pc_control_service; pc_control_service.set_gain(3, {})",
                val
            );
            std::process::Command::new("python").args(["-c", &py_code]).spawn().map_err(|e| e.to_string())?;
            Ok(format!("Volume canal set: {}", val))
        }
        "ciclar_saida" => {
            let py_code = "import sys; sys.path.append(r'D:\\Programacao\\AssistenteCell'); from servicos.pc_control_service import pc_control_service; pc_control_service.ciclar_saida(3)";
            std::process::Command::new("python").args(["-c", py_code]).spawn().map_err(|e| e.to_string())?;
            Ok("Ciclar saída executed".to_string())
        }
        _ => {
            #[cfg(target_os = "windows")]
            {
                std::process::Command::new("cmd")
                    .args(["/C", &comando])
                    .spawn()
                    .map_err(|e| e.to_string())?;
            }
            Ok(format!("Command executed: {}", comando))
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            start_monitoring,
            close_window,
            minimize_window,
            maximize_window,
            get_cloud_url,
            get_api_url,
            execute_pc_command
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
