// OpenEstimate Desktop — Tauri v2 Application
//
// Manages the FastAPI backend as a sidecar process.
// The React frontend loads in a native webview window.
// Backend communicates via http://localhost:{port}/api/

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::Mutex;
use tauri::{
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager, RunEvent,
};
use tauri_plugin_shell::ShellExt;

struct AppState {
    backend_port: u16,
    backend_running: Mutex<bool>,
}

/// Find an available port for the backend server.
fn find_available_port() -> u16 {
    portpicker::pick_unused_port().expect("No available port found")
}

/// Wait for the backend health endpoint to respond.
async fn wait_for_backend(port: u16, timeout_secs: u64) -> bool {
    let client = reqwest::Client::new();
    let url = format!("http://127.0.0.1:{}/api/health", port);
    let start = std::time::Instant::now();

    while start.elapsed().as_secs() < timeout_secs {
        if let Ok(resp) = client.get(&url).send().await {
            if resp.status().is_success() {
                return true;
            }
        }
        tokio::time::sleep(std::time::Duration::from_millis(500)).await;
    }
    false
}

fn main() {
    let port = find_available_port();

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .manage(AppState {
            backend_port: port,
            backend_running: Mutex::new(false),
        })
        .setup(move |app| {
            let handle = app.handle().clone();

            // Build tray icon
            let _tray = TrayIconBuilder::new()
                .tooltip("OpenEstimate")
                .on_tray_icon_event(move |tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        // Show/focus main window on tray click
                        if let Some(window) = tray.app_handle().get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                })
                .build(app)?;

            // Start the backend sidecar
            let shell = handle.shell();
            let sidecar_cmd = shell
                .sidecar("openestimate-server")
                .expect("Failed to create sidecar command")
                .args(["--host", "127.0.0.1", "--port", &port.to_string()]);

            let (mut _rx, _child) = sidecar_cmd
                .spawn()
                .expect("Failed to spawn backend sidecar");

            // Mark backend as running
            let state = handle.state::<AppState>();
            *state.backend_running.lock().unwrap() = true;

            // Wait for backend to be ready, then navigate the webview
            let handle_clone = handle.clone();
            tauri::async_runtime::spawn(async move {
                if wait_for_backend(port, 60).await {
                    if let Some(window) = handle_clone.get_webview_window("main") {
                        let url = format!("http://127.0.0.1:{}", port);
                        let _ = window.eval(&format!("window.location.replace('{}')", url));
                    }
                } else {
                    eprintln!("Backend failed to start within 60 seconds");
                }
            });

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("Error building Tauri application")
        .run(|_app, event| {
            if let RunEvent::ExitRequested { .. } = event {
                // Backend sidecar is automatically killed when the app exits
            }
        });
}
