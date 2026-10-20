use tauri::{AppHandle, Emitter, Manager};
use sysinfo::System;
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
    audio_state: serde_json::Value,
    mic_mute: i32,
}

#[derive(serde::Serialize, Clone)]
struct WindowInfo {
    title: String,
    process: String,
}

fn backend_dir() -> std::path::PathBuf {
    std::env::var_os("OLLIE_BACKEND_DIR").map(std::path::PathBuf::from)
        .unwrap_or_else(|| std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap().parent().unwrap().to_path_buf())
}

fn load_config() {
    dotenvy::from_path(backend_dir().join(".env")).ok();
}

fn get_python_path() -> String {
    if let Ok(path) = std::env::var("OLLIE_PYTHON") { return path; }
    for name in [".venvs", ".venv", "venv"] {
        let path = backend_dir().join(name).join(if cfg!(windows) { "Scripts/python.exe" } else { "bin/python" });
        if path.exists() { return path.to_string_lossy().into_owned(); }
    }
    "python".to_string()
}

fn run_python(comando: &str, parametro: &str) -> Result<String, String> {
    let output = std::process::Command::new(get_python_path())
        .arg(backend_dir().join("scripts/pc_command.py"))
        .args([comando, parametro])
        .current_dir(backend_dir())
        .output().map_err(|e| e.to_string())?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).to_string());
    }
    Ok(String::from_utf8_lossy(&output.stdout).lines().last().unwrap_or("").to_string())
}

#[tauri::command]
async fn start_monitoring(app_handle: AppHandle) {
    if MONITORING_STARTED.swap(true, Ordering::SeqCst) {
        return;
    }

    // Hardware & Voicemeeter Monitoring Loop (syncs real PC audio state with cloud/mobile)
    let app_cpu = app_handle.clone();
    tauri::async_runtime::spawn(async move {
        let mut sys = System::new_all();
        loop {
            sys.refresh_all();

            let cpu = sys.global_cpu_info().cpu_usage() as u32;
            let ram = (sys.used_memory() as f64 / sys.total_memory() as f64 * 100.0) as u32;

            let audio_json = tauri::async_runtime::spawn_blocking(|| run_python("snapshot", ""))
                .await.ok().and_then(Result::ok).unwrap_or_default();

            let audio_data: serde_json::Value = serde_json::from_str(&audio_json).unwrap_or(serde_json::json!({}));

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

            let _ = app_cpu.emit("hardware-update", HardwareStats {
                cpu,
                ram,
                processes: top_procs,
                audio_state: audio_data.get("audio_state").cloned().unwrap_or(serde_json::json!({})),
                mic_mute: audio_data.get("mic_mute").and_then(|v| v.as_i64()).unwrap_or(0) as i32,
            });

            sleep(Duration::from_secs(3)).await;
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
            sleep(Duration::from_secs(3)).await;
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
async fn activate_window(app_handle: AppHandle) -> Result<(), String> {
    let window = app_handle.get_webview_window("main").ok_or("Janela principal indisponível")?;
    window.show().map_err(|e| e.to_string())?;
    window.unminimize().map_err(|e| e.to_string())?;
    window.set_focus().map_err(|e| e.to_string())
}

#[tauri::command]
fn get_cloud_url() -> String {
    load_config();
    let env = std::env::var("ENVIRONMENT").unwrap_or_else(|_| "production".to_string());
    if env == "development" {
        std::env::var("OLLIE_LOCAL_URL").unwrap_or_else(|_| "ws://localhost:8000/api/v1/ws/alertas".to_string())
    } else {
        std::env::var("OLLIE_CLOUD_URL").unwrap_or_else(|_| "wss://assistentecellfront.onrender.com/api/v1/ws/alertas".to_string())
    }
}

#[tauri::command]
fn get_api_url() -> String {
    load_config();
    let env = std::env::var("ENVIRONMENT").unwrap_or_else(|_| "production".to_string());
    if env == "development" {
        "http://127.0.0.1:8000".to_string()
    } else {
        "https://assistentecellfront.onrender.com".to_string()
    }
}

#[tauri::command]
fn get_auth_token() -> Result<String, String> {
    load_config();
    std::env::var("OLLIE_API_TOKEN").ok().filter(|v| !v.is_empty())
        .ok_or_else(|| "Configure OLLIE_API_TOKEN no servidor e neste desktop".to_string())
}

#[tauri::command]
async fn execute_pc_command(comando: String, parametro: Option<String>) -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(move || run_python(&comando, &parametro.unwrap_or_default()))
        .await.map_err(|e| e.to_string())?
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
            activate_window,
            get_cloud_url,
            get_api_url,
            get_auth_token,
            execute_pc_command
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
