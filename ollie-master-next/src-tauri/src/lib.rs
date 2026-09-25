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
fn get_cloud_url() -> String {
    // Tenta ler do .env na raiz do ecossistema (3 níveis acima: src-tauri/src -> src-tauri -> ollie-master-next -> raiz)
    dotenvy::from_path("../../../.env").ok();
    std::env::var("OLLIE_CLOUD_URL").unwrap_or_else(|_| "wss://assistentecellfront.onrender.com/api/v1/ws/alertas".to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![start_monitoring, close_window, minimize_window, get_cloud_url])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
