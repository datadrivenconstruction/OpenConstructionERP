// OpenConstructionERP Desktop, Tauri v2 application.
//
// Manages the FastAPI backend as a sidecar process.
// The React frontend loads in a native webview window.
// Backend communicates via http://localhost:{port}/api/
//
// Robustness contract (why this file is defensive):
//   In release builds the process has no console (windows_subsystem = "windows"),
//   so any panic dies silently and, if it happens inside setup(), the window
//   never appears. That is exactly the "I click the icon and nothing happens"
//   failure. So setup() must NEVER panic: every fallible step is handled, the
//   splash window is kept open, a human-readable error is shown via setError(),
//   and a full diagnostic log is always written to
//   ~/.openestimate/desktop-launcher.log (alongside the backend's own data).

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use tauri::{
    menu::{MenuBuilder, MenuItemBuilder, PredefinedMenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager, RunEvent,
};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

struct AppState {
    /// Handle to the spawned backend process so it survives past setup() and
    /// can be killed when the app exits.
    backend_child: Mutex<Option<CommandChild>>,
    /// The local URL the app is served on (e.g. http://127.0.0.1:8732/).
    ///
    /// Resolved once the backend is healthy and the webview is pointed at it.
    /// Stored here so the tray menu and the "open in your browser" command can
    /// hand the user the exact same address the app window is showing, even
    /// though the port is chosen dynamically at startup.
    app_url: Mutex<Option<String>>,
}

/// Open a URL or file path in the operating system's default handler.
///
/// Uses the platform opener directly (`cmd /c start` on Windows, `open` on
/// macOS, `xdg-open` on Linux) for the same reason `open_log_file` does: it is
/// fully cross-platform, adds no dependency, and avoids the tauri shell
/// plugin's deprecated `open`. For a URL this lands the user in their normal
/// web browser at the local address.
fn open_with_os_default(target: &str) -> std::io::Result<std::process::Child> {
    if cfg!(target_os = "windows") {
        // The empty "" is start's title argument; without it a quoted target is
        // mis-parsed as the window title and nothing opens.
        std::process::Command::new("cmd")
            .args(["/c", "start", "", target])
            .spawn()
    } else if cfg!(target_os = "macos") {
        std::process::Command::new("open").arg(target).spawn()
    } else {
        std::process::Command::new("xdg-open").arg(target).spawn()
    }
}

/// Open the running app in the user's default web browser.
///
/// Exposed to the splash first-run card and to any in-app control (via
/// `withGlobalTauri`). Reads the resolved local URL from `AppState`; if startup
/// has not gotten that far yet it returns a friendly error the caller can show.
///
/// `path` lets the in-app toolbar open the EXACT page the user is on rather
/// than just the home page. It is treated as a path within the app (for example
/// "/boq" or "/projects/123/finance"); anything that is not a clean local path
/// is ignored and the home page is opened, so a caller can never be redirected
/// somewhere off the local origin.
#[tauri::command]
fn open_app_in_browser(app: tauri::AppHandle, path: Option<String>) -> Result<(), String> {
    let base = {
        let state = app.state::<AppState>();
        let guard = state.app_url.lock().unwrap();
        guard.clone()
    };
    let base = base.ok_or_else(|| {
        "The app is still starting. Please try again in a moment.".to_string()
    })?;
    let url = build_local_url(&base, path.as_deref());
    open_with_os_default(&url)
        .map(|_| ())
        .map_err(|e| format!("Could not open your browser: {e}"))
}

/// Combine the resolved local base URL with a caller-supplied app path.
///
/// Only same-origin paths are honoured: the path must start with a single "/"
/// (not "//", which a browser reads as a protocol-relative host) and must not
/// contain a scheme. Anything else falls back to the bare base URL. This keeps
/// the "open in browser" action firmly on the local app and never lets a path
/// argument send the user to an arbitrary site.
fn build_local_url(base: &str, path: Option<&str>) -> String {
    let trimmed = base.trim_end_matches('/');
    match path {
        Some(p)
            if p.starts_with('/')
                && !p.starts_with("//")
                && !p.contains("://")
                && !p.contains('\\') =>
        {
            format!("{trimmed}{p}")
        }
        _ => format!("{trimmed}/"),
    }
}

/// Return the resolved local URL the app is served on, for the UI to display or
/// open. Empty string until the backend is healthy and the URL is known.
#[tauri::command]
fn get_app_url(app: tauri::AppHandle) -> String {
    let state = app.state::<AppState>();
    let guard = state.app_url.lock().unwrap();
    guard.clone().unwrap_or_default()
}

/// Open the launcher diagnostic log in the OS default handler.
///
/// Exposed to the splash screen (via `withGlobalTauri`) so the failure UI can
/// offer a one-click "Open log" button. Returns an error string the splash can
/// show if the log path cannot be resolved or opened. Shells out to the
/// platform's default opener (`cmd /c start` on Windows, `open` on macOS,
/// `xdg-open` on Linux) rather than the tauri shell plugin's `open`, which is
/// deprecated; this keeps the dependency surface unchanged and avoids the
/// deprecation while still being fully cross-platform.
#[tauri::command]
fn open_log_file(_app: tauri::AppHandle) -> Result<(), String> {
    let path = log_path().ok_or_else(|| "Could not resolve the log file path".to_string())?;
    let path_str = path.to_string_lossy().to_string();

    let result = if cfg!(target_os = "windows") {
        // The empty "" is start's title argument; without it a quoted path is
        // mis-parsed as the window title and the file never opens.
        std::process::Command::new("cmd")
            .args(["/c", "start", "", &path_str])
            .spawn()
    } else if cfg!(target_os = "macos") {
        std::process::Command::new("open").arg(&path_str).spawn()
    } else {
        std::process::Command::new("xdg-open").arg(&path_str).spawn()
    };

    result
        .map(|_| ())
        .map_err(|e| format!("Could not open the log file: {e}"))
}

/// Resolve the user's home directory without pulling in extra crates.
fn home_dir() -> Option<PathBuf> {
    for var in ["USERPROFILE", "HOME"] {
        if let Ok(p) = std::env::var(var) {
            if !p.is_empty() {
                return Some(PathBuf::from(p));
            }
        }
    }
    None
}

/// Path of the launcher diagnostic log (same folder the backend uses for data).
fn log_path() -> Option<PathBuf> {
    home_dir().map(|h| h.join(".openestimate").join("desktop-launcher.log"))
}

/// Append one line to the diagnostic log (best effort) and to stderr.
///
/// This is the single most important diagnostic when a user reports "nothing
/// happens": even if the window never paints, the log records how far startup
/// got and the exact error.
fn log_line(msg: &str) {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let line = format!("[{secs}] {msg}\n");

    if let Some(path) = log_path() {
        if let Some(parent) = path.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        use std::io::Write;
        if let Ok(mut f) = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&path)
        {
            let _ = f.write_all(line.as_bytes());
        }
    }
    eprintln!("{}", line.trim_end());
}

/// Escape a string for embedding inside a single-quoted JavaScript literal.
fn js_escape(s: &str) -> String {
    s.replace('\\', "\\\\")
        .replace('\'', "\\'")
        .replace('\n', " ")
        .replace('\r', " ")
}

/// Run a snippet of JavaScript in the splash window, retried a few times.
///
/// setup() may run before the splash page has finished loading its inline
/// script, so we retry the eval over ~2 seconds. The splash boot functions are
/// idempotent (they just set DOM state), so repeated calls are harmless.
fn eval_in_splash(handle: &tauri::AppHandle, js: String) {
    let handle = handle.clone();
    tauri::async_runtime::spawn(async move {
        for _ in 0..8 {
            if let Some(window) = handle.get_webview_window("main") {
                let _ = window.show();
                let _ = window.eval(&js);
            }
            tokio::time::sleep(std::time::Duration::from_millis(250)).await;
        }
    });
}

/// Tell the splash where the diagnostic log lives so a failure message can point
/// the user straight at it.
fn report_log_path(handle: &tauri::AppHandle) {
    if let Some(path) = log_path() {
        let p = js_escape(&path.to_string_lossy());
        eval_in_splash(
            handle,
            format!("(function(){{if(typeof setLogPath==='function'){{setLogPath('{p}');}}}})()"),
        );
    }
}

/// Advance one step of the visible boot checklist on the splash screen.
///
/// `status` is one of "pending" | "active" | "done" | "failed". Never panics;
/// if the splash is not ready yet the retrying eval picks it up shortly.
fn boot_stage(handle: &tauri::AppHandle, id: &str, status: &str, detail: &str) {
    let id = js_escape(id);
    let status = js_escape(status);
    let detail = js_escape(detail);
    eval_in_splash(
        handle,
        format!(
            "(function(){{if(typeof bootStage==='function'){{bootStage('{id}','{status}','{detail}');}}}})()"
        ),
    );
}

/// Show a fatal error on the splash screen and mark a checklist step as failed,
/// without ever panicking. Always pairs the message with the log path so the
/// user can find the full diagnostics.
fn report_fatal_stage(handle: &tauri::AppHandle, stage: &str, message: &str) {
    log_line(&format!("FATAL [{stage}]: {message}"));
    report_log_path(handle);
    let stage_js = js_escape(stage);
    let msg = js_escape(message);
    eval_in_splash(
        handle,
        format!(
            "(function(){{\
                if(typeof failStage==='function'){{failStage('{stage_js}','{msg}');}}\
                else if(typeof setError==='function'){{setError('{msg}');}}\
            }})()"
        ),
    );
}

/// Parse a backend ``STAGE:<id>:<status>[:<detail>]`` marker line.
///
/// Returns ``Some((id, splash_status, detail))`` where splash_status is mapped
/// to the values the splash checklist understands. Returns ``None`` for lines
/// that are not stage markers.
fn parse_stage_marker(line: &str) -> Option<(String, String, String)> {
    let rest = line.trim().strip_prefix("STAGE:")?;
    let mut parts = rest.splitn(3, ':');
    let id = parts.next()?.trim().to_string();
    let raw_status = parts.next()?.trim().to_string();
    let detail = parts.next().unwrap_or("").trim().to_string();
    if id.is_empty() || raw_status.is_empty() {
        return None;
    }
    let splash_status = match raw_status.as_str() {
        "start" | "progress" => "active",
        "done" => "done",
        "fail" => "failed",
        _ => "active",
    }
    .to_string();
    Some((id, splash_status, detail))
}

/// Find an available port for the backend server, with a fixed fallback so a
/// picker failure never aborts startup.
fn find_available_port() -> u16 {
    portpicker::pick_unused_port().unwrap_or(8732)
}

/// Resolve the bundled read-only converters directory shipped as an app
/// resource, if present.
///
/// The Windows installer ships the small (~30 MB) DDC IFC converter under
/// `resources/converters/ifc_windows/` so a fresh install can convert .ifc
/// offline with zero first-use download. We resolve the Tauri resource dir and
/// return the `converters` subfolder only when it actually exists on disk.
/// Returns `None` on platforms or builds that did not ship the converter (every
/// non-Windows build, and any Windows build where the workflow download step was
/// skipped), so the backend silently falls back to its normal install path.
fn bundled_converters_dir(app: &tauri::App) -> Option<PathBuf> {
    let resource_dir = app.path().resource_dir().ok()?;
    let converters = resource_dir.join("converters");
    if converters.is_dir() {
        Some(converters)
    } else {
        None
    }
}

/// Record the resolved local URL so the tray menu and the "open in your
/// browser" command can hand the user the same address the window is showing.
///
/// Also tells the webview the URL (via `setAppUrl`) so the splash first-run
/// card and any in-app control can offer the browser option without having to
/// re-derive the dynamic port.
fn set_app_url(handle: &tauri::AppHandle, url: &str) {
    {
        let state = handle.state::<AppState>();
        *state.app_url.lock().unwrap() = Some(url.to_string());
    }
    let url_js = js_escape(url);
    eval_in_splash(
        handle,
        format!("(function(){{if(typeof setAppUrl==='function'){{setAppUrl('{url_js}');}}}})()"),
    );
}

/// Bring the main app window to the front (used by the tray).
fn show_main_window(handle: &tauri::AppHandle) {
    if let Some(window) = handle.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

/// Ports an already-running OpenConstructionERP backend is likely to be on.
///
/// Checked in order before we spawn our own sidecar. This is what lets the
/// desktop app coexist with a developer backend or a CLI ``openconstructionerp
/// serve`` already running on the same machine: rather than booting a SECOND
/// backend that fights the first one over the shared embedded-PostgreSQL cluster
/// at ``~/.openestimate/pgdata`` (a real founder-machine failure mode), we
/// simply attach to the healthy instance that is already there.
const ATTACH_CANDIDATE_PORTS: [u16; 4] = [8000, 8080, 8732, 8765];

/// Probe ``127.0.0.1:<port>/api/health`` and decide whether we may attach to it.
///
/// Returns ``true`` only when the responder is unambiguously a HEALTHY backend
/// of EXACTLY OUR version. Attaching to anything less is dangerous: a stale dev
/// backend of a different version (the founder-machine case is a degraded
/// v6.10.0 on :8000) would serve the desktop app the wrong frontend/schema, and
/// a merely "degraded" instance may not actually work. So all of the following
/// must hold, and every rejected candidate is logged with its port, version and
/// status so attach decisions are auditable from the launcher log:
///   * HTTP 2xx
///   * ``status`` is "ok" or "healthy" (NOT "degraded"/"unhealthy")
///   * ``version`` equals our own ``CARGO_PKG_VERSION`` exactly
///   * ``alembic_head_matches`` is not ``false`` (migrations not known-stale)
async fn is_our_backend_healthy(client: &reqwest::Client, port: u16) -> bool {
    let url = format!("http://127.0.0.1:{port}/api/health");
    let resp = match client
        .get(&url)
        .timeout(std::time::Duration::from_millis(1500))
        .send()
        .await
    {
        Ok(resp) => resp,
        // No listener / connection refused / timeout: nothing to log, this is
        // the normal "port is free" case.
        Err(_) => return false,
    };

    let http_status = resp.status();
    if !http_status.is_success() {
        log_line(&format!(
            "attach: rejected candidate on port {port}: HTTP {}",
            http_status.as_u16()
        ));
        return false;
    }

    let body = match resp.text().await {
        Ok(body) => body,
        Err(e) => {
            log_line(&format!(
                "attach: rejected candidate on port {port}: could not read health body ({e})"
            ));
            return false;
        }
    };

    // Parse the health JSON properly so the decision is on real fields, not
    // substring guesses. serde_json is already a dependency.
    let json: serde_json::Value = match serde_json::from_str(&body) {
        Ok(v) => v,
        Err(_) => {
            log_line(&format!(
                "attach: rejected candidate on port {port}: health body is not JSON"
            ));
            return false;
        }
    };

    let status = json.get("status").and_then(|v| v.as_str()).unwrap_or("");
    let version = json.get("version").and_then(|v| v.as_str()).unwrap_or("");
    // Missing key is treated as "not known false" (acceptable); only an explicit
    // false rejects.
    let alembic_ok = json
        .get("alembic_head_matches")
        .and_then(|v| v.as_bool())
        .unwrap_or(true);
    let our_version = env!("CARGO_PKG_VERSION");

    let status_ok = matches!(status, "ok" | "healthy");
    let version_ok = version == our_version;

    if status_ok && version_ok && alembic_ok {
        log_line(&format!(
            "attach: accepted candidate on port {port}: status={status} version={version}"
        ));
        return true;
    }

    log_line(&format!(
        "attach: rejected candidate on port {port}: status={status:?} version={version:?} \
(ours={our_version}) alembic_head_matches={alembic_ok}"
    ));
    false
}

/// Scan the candidate ports for an existing healthy backend to attach to.
///
/// Returns the first port that responds as our backend, or ``None`` if none do
/// (the normal cold-start case, where we then spawn our own sidecar).
async fn find_existing_backend(client: &reqwest::Client) -> Option<u16> {
    for port in ATTACH_CANDIDATE_PORTS {
        if is_our_backend_healthy(client, port).await {
            return Some(port);
        }
    }
    None
}

/// Wait for the backend health endpoint to respond.
///
/// Polls `/api/health` every ~500ms until it succeeds or the timeout elapses.
/// While waiting, updates the splash screen so the user sees progress; first-run
/// embedded-PostgreSQL setup can be slow.
async fn wait_for_backend(handle: &tauri::AppHandle, port: u16, timeout_secs: u64) -> bool {
    let client = reqwest::Client::new();
    let url = format!("http://127.0.0.1:{port}/api/health");
    let start = std::time::Instant::now();
    let mut progress_shown = false;

    while start.elapsed().as_secs() < timeout_secs {
        if let Ok(resp) = client.get(&url).send().await {
            if resp.status().is_success() {
                return true;
            }
        }

        if !progress_shown && start.elapsed().as_secs() >= 8 {
            progress_shown = true;
            if let Some(window) = handle.get_webview_window("main") {
                let _ = window.eval("setStatus('Setting up the local database, almost there')");
            }
        }

        tokio::time::sleep(std::time::Duration::from_millis(500)).await;
    }
    false
}

fn main() {
    // Write the diagnostic log at the VERY FIRST instruction, before anything
    // else in startup can fail. If the user reports "I click the icon and
    // nothing happens", this line guarantees the log file at least exists and
    // records that the process launched -- so the failure is never invisible,
    // even if building the Tauri app itself (WebView2 missing, etc.) blows up
    // before any window appears.
    log_line(&format!(
        "=== OpenConstructionERP desktop launcher starting (v{}) ===",
        env!("CARGO_PKG_VERSION")
    ));

    let port = find_available_port();
    log_line(&format!("selected backend port {port}"));

    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_process::init())
        .manage(AppState {
            backend_child: Mutex::new(None),
            app_url: Mutex::new(None),
        })
        .invoke_handler(tauri::generate_handler![
            open_log_file,
            open_app_in_browser,
            get_app_url
        ])
        .setup(move |app| {
            let handle = app.handle().clone();
            log_line(&format!("setup() running; backend port = {port}"));

            // Resolve the bundled read-only converters dir (Windows ships the
            // DDC IFC converter as an app resource) BEFORE the attach/spawn
            // branches so we can hand its path to whichever sidecar we start.
            // None on builds that did not ship it, in which case the backend
            // keeps its normal auto-download behaviour.
            let bundled_converters = bundled_converters_dir(app);
            if let Some(ref dir) = bundled_converters {
                log_line(&format!("bundled converters dir: {}", dir.display()));
            }

            // Surface the log path and the first two checklist steps right away
            // so the user sees a live boot screen the instant the window paints.
            report_log_path(&handle);
            boot_stage(&handle, "launcher", "done", "");
            boot_stage(&handle, "sidecar", "active", "Locating the backend");

            // Tray icon with a right-click menu. The menu is the always-present
            // home for the "open in your browser" choice the founder asked for:
            // however the app was started, the user can right-click the tray
            // icon and pick whether to keep using the app window or hand the
            // local address to their normal web browser. Building the tray is a
            // nice-to-have, so its failure must never abort startup.
            let tray_menu_result = (|| {
                let show_item = MenuItemBuilder::with_id("tray_show", "Show app window")
                    .build(app)?;
                let browser_item =
                    MenuItemBuilder::with_id("tray_open_browser", "Open in your browser")
                        .build(app)?;
                let quit_item = MenuItemBuilder::with_id("tray_quit", "Quit").build(app)?;
                let sep = PredefinedMenuItem::separator(app)?;
                MenuBuilder::new(app)
                    .item(&show_item)
                    .item(&browser_item)
                    .item(&sep)
                    .item(&quit_item)
                    .build()
            })();

            let tray_build = match tray_menu_result {
                Ok(menu) => TrayIconBuilder::new()
                    .icon(app.default_window_icon().cloned().unwrap_or_else(|| {
                        // Should never happen (the bundle always ships an icon),
                        // but fall back to a 1x1 transparent pixel rather than
                        // panic, keeping the no-panic startup contract.
                        tauri::image::Image::new_owned(vec![0, 0, 0, 0], 1, 1)
                    }))
                    .tooltip("OpenConstructionERP")
                    .menu(&menu)
                    // Keep the existing left-click-to-show behaviour. The menu
                    // shows on right-click; suppressing menu-on-left-click means
                    // a single left click still just raises the window.
                    .show_menu_on_left_click(false)
                    .on_menu_event(|app, event| match event.id().as_ref() {
                        "tray_show" => show_main_window(app),
                        "tray_open_browser" => {
                            if let Err(e) = open_app_in_browser(app.clone(), None) {
                                log_line(&format!("tray: open in browser failed: {e}"));
                            }
                        }
                        "tray_quit" => app.exit(0),
                        _ => {}
                    })
                    .on_tray_icon_event(|tray, event| {
                        if let TrayIconEvent::Click {
                            button: MouseButton::Left,
                            button_state: MouseButtonState::Up,
                            ..
                        } = event
                        {
                            show_main_window(tray.app_handle());
                        }
                    })
                    .build(app),
                Err(e) => {
                    log_line(&format!("warning: tray menu build failed (non-fatal): {e}"));
                    // Fall back to the plain icon-only tray (left-click shows).
                    TrayIconBuilder::new()
                        .tooltip("OpenConstructionERP")
                        .on_tray_icon_event(|tray, event| {
                            if let TrayIconEvent::Click {
                                button: MouseButton::Left,
                                button_state: MouseButtonState::Up,
                                ..
                            } = event
                            {
                                show_main_window(tray.app_handle());
                            }
                        })
                        .build(app)
                }
            };
            if let Err(e) = tray_build {
                log_line(&format!("warning: tray icon build failed (non-fatal): {e}"));
            }

            // Attach to an existing healthy backend instead of booting a second
            // one.
            //
            // If a developer backend or a CLI `openconstructionerp serve` is
            // already running on this machine, it already owns the embedded
            // PostgreSQL cluster at ~/.openestimate/pgdata. Spawning our own
            // sidecar against the SAME default data dir makes two processes
            // share one cluster; when the desktop app later exits it tells
            // pixeltable-pgserver to clean up, which can stop the postmaster out
            // from under the still-running developer backend. Attaching instead
            // is both safer and faster (no second boot, no second cluster
            // handle). We only attach to a server that self-identifies as ours.
            //
            // The probe is short (four ports, 1.5s each at worst, only while
            // they are actually open) and is run to completion here so the
            // decision to spawn is made BEFORE we start a sidecar -- otherwise a
            // concurrent probe would race the spawn and we could end up with two
            // backends anyway. block_on is safe: setup() already runs on the
            // Tauri async runtime's worker, and the probe never blocks
            // indefinitely.
            let attached_port = tauri::async_runtime::block_on(async {
                let client = reqwest::Client::new();
                find_existing_backend(&client).await
            });

            if let Some(existing) = attached_port {
                log_line(&format!(
                    "found an existing OpenConstructionERP backend on port {existing}; attaching instead of starting a second one"
                ));
                boot_stage(&handle, "sidecar", "done", "Found a running backend");
                boot_stage(&handle, "pg", "done", "");
                boot_stage(&handle, "migrate", "done", "");
                boot_stage(&handle, "server", "done", "");
                boot_stage(&handle, "open", "done", "Ready");
                let url = format!("http://127.0.0.1:{existing}/");
                set_app_url(&handle, &url);
                let handle_nav = handle.clone();
                tauri::async_runtime::spawn(async move {
                    // Give the splash script a moment to finish loading, then
                    // let it offer the one-time "app window or browser" choice
                    // before navigating the webview to the running app.
                    tokio::time::sleep(std::time::Duration::from_millis(400)).await;
                    if let Some(window) = handle_nav.get_webview_window("main") {
                        let _ = window.show();
                        let _ = window.set_focus();
                        let url_js = js_escape(&url);
                        let _ = window.eval(&format!(
                            "(function(){{if(typeof offerLaunchChoice==='function'){{\
                                offerLaunchChoice('{url_js}');}}\
                                else{{window.location.replace('{url_js}');}}}})()"
                        ));
                    }
                });
                // We did not spawn a sidecar, so there is no child to manage and
                // nothing more for setup() to do.
                return Ok(());
            }

            log_line("no existing backend found; starting our own sidecar");

            // Start the backend sidecar.
            //
            // The "serve" subcommand is required: the CLI only accepts --host /
            // --port under a subcommand. Invoked bare it would ignore them,
            // fall back to defaults, and on first run block on an interactive
            // "open in browser?" stdin prompt that a sidecar has no terminal
            // for. With --data-dir left unset the sidecar uses its default
            // (~/.openestimate), which stays writable even for a per-machine
            // install under Program Files.
            let shell = handle.shell();
            let sidecar_cmd = match shell.sidecar("openestimate-server") {
                Ok(cmd) => {
                    // OE_DESKTOP=1 marks this backend as one we spawned from the
                    // desktop shell (so the backend can run desktop-only
                    // bootstrapping). We deliberately do NOT set it on the attach
                    // path above, because an already-running dev backend must not
                    // be treated as a desktop-bootstrapped one.
                    let mut cmd = cmd.env("OE_DESKTOP", "1").args([
                        "serve",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        &port.to_string(),
                    ]);
                    // Point the backend at the bundled read-only converters so
                    // an .ifc upload converts offline with no first-use download.
                    // Only set when we actually shipped a converters dir; absent
                    // env keeps the normal auto-download path intact.
                    if let Some(ref dir) = bundled_converters {
                        cmd = cmd.env("OE_BUNDLED_CONVERTERS_DIR", dir.as_os_str());
                    }
                    cmd
                }
                Err(e) => {
                    report_fatal_stage(
                        &handle,
                        "sidecar",
                        &format!(
                            "Could not locate the backend component ({e}). Please reinstall \
the application."
                        ),
                    );
                    // Keep the window open so the user sees the error.
                    return Ok(());
                }
            };

            let (mut rx, child) = match sidecar_cmd.spawn() {
                Ok(pair) => pair,
                Err(e) => {
                    report_fatal_stage(
                        &handle,
                        "sidecar",
                        &format!(
                            "The backend component could not be started ({e}). Some antivirus \
tools block newly installed programs; allow OpenConstructionERP and try again."
                        ),
                    );
                    return Ok(());
                }
            };
            log_line("sidecar spawned");
            boot_stage(&handle, "sidecar", "done", "");
            boot_stage(&handle, "pg", "active", "Starting the local database");

            // Keep the child handle alive (and killable on exit).
            {
                let state = handle.state::<AppState>();
                *state.backend_child.lock().unwrap() = Some(child);
            }

            let backend_ready = Arc::new(AtomicBool::new(false));
            let last_stderr = Arc::new(Mutex::new(String::new()));

            // Pump the sidecar's output into the log file and remember recent
            // stderr so a startup crash can be shown to the user verbatim.
            {
                let ready = backend_ready.clone();
                let stderr_buf = last_stderr.clone();
                let handle_evt = handle.clone();
                tauri::async_runtime::spawn(async move {
                    while let Some(event) = rx.recv().await {
                        match event {
                            CommandEvent::Stdout(bytes) => {
                                let line = String::from_utf8_lossy(&bytes);
                                log_line(&format!("[backend] {}", line.trim_end()));
                                // Drive the visible boot checklist from the
                                // backend's machine-readable progress markers.
                                for raw in line.split('\n') {
                                    if let Some((id, status, detail)) = parse_stage_marker(raw) {
                                        boot_stage(&handle_evt, &id, &status, &detail);
                                    }
                                }
                            }
                            CommandEvent::Stderr(bytes) => {
                                let line = String::from_utf8_lossy(&bytes);
                                log_line(&format!("[backend:err] {}", line.trim_end()));
                                // Some launchers/loggers route progress markers
                                // to stderr; honour them there too.
                                for raw in line.split('\n') {
                                    if let Some((id, status, detail)) = parse_stage_marker(raw) {
                                        boot_stage(&handle_evt, &id, &status, &detail);
                                    }
                                }
                                let mut buf = stderr_buf.lock().unwrap();
                                buf.push_str(&line);
                                if buf.len() > 4000 {
                                    let cut = buf.len() - 4000;
                                    *buf = buf[cut..].to_string();
                                }
                            }
                            CommandEvent::Error(err) => {
                                log_line(&format!("[backend:error] {err}"));
                            }
                            CommandEvent::Terminated(payload) => {
                                log_line(&format!(
                                    "[backend] terminated: code={:?} signal={:?}",
                                    payload.code, payload.signal
                                ));
                                // If the backend died before ever becoming
                                // healthy, surface it now instead of leaving the
                                // user staring at the spinner for the full timeout.
                                if !ready.load(Ordering::SeqCst) {
                                    let tail = stderr_buf.lock().unwrap().clone();
                                    let detail = if tail.trim().is_empty() {
                                        format!(
                                            "The backend stopped unexpectedly (exit code {:?}) \
before it finished starting.",
                                            payload.code
                                        )
                                    } else {
                                        // Keep the message readable: show the
                                        // last chunk of stderr, which usually
                                        // carries the actual cause.
                                        let trimmed = tail.trim();
                                        let shown = if trimmed.len() > 600 {
                                            &trimmed[trimmed.len() - 600..]
                                        } else {
                                            trimmed
                                        };
                                        format!(
                                            "The backend stopped unexpectedly during startup: {shown}"
                                        )
                                    };
                                    // Attribute the failure to whichever step was
                                    // last in progress so the checklist shows a
                                    // clear red mark, defaulting to the server step.
                                    report_fatal_stage(&handle_evt, "server", &detail);
                                }
                                break;
                            }
                            _ => {}
                        }
                    }
                });
            }

            // Wait for the backend to be ready, then navigate the webview from
            // the splash screen to the live application. First-run embedded
            // PostgreSQL setup (initdb, migrations, module load, demo seed) can
            // be slow on a cold machine, so allow up to 240 seconds.
            let handle_clone = handle.clone();
            let ready_flag = backend_ready.clone();
            tauri::async_runtime::spawn(async move {
                // A first run that has to recover a large local database (WAL
                // replay + fsync) can take several minutes, so allow a generous
                // window. The backend retries embedded-PG bring-up internally
                // for up to ~10 minutes; keep the health wait comfortably above
                // its own previous 240s so we never abandon a backend that is
                // still legitimately recovering.
                if wait_for_backend(&handle_clone, port, 600).await {
                    ready_flag.store(true, Ordering::SeqCst);
                    log_line("backend healthy; navigating to app");
                    boot_stage(&handle_clone, "server", "done", "");
                    boot_stage(&handle_clone, "open", "done", "Ready");
                    let url = format!("http://127.0.0.1:{port}/");
                    set_app_url(&handle_clone, &url);
                    if let Some(window) = handle_clone.get_webview_window("main") {
                        let _ = window.show();
                        let _ = window.set_focus();
                        // Let the splash offer the one-time "app window or
                        // browser" choice; if that helper is missing for any
                        // reason, fall straight through to the app window so the
                        // user is never left on the splash.
                        let url_js = js_escape(&url);
                        let _ = window.eval(&format!(
                            "(function(){{if(typeof offerLaunchChoice==='function'){{\
                                offerLaunchChoice('{url_js}');}}\
                                else{{window.location.replace('{url_js}');}}}})()"
                        ));
                    }
                } else {
                    log_line("backend did not become healthy within the startup window");
                    // If the sidecar already reported termination, that handler
                    // showed a precise error; only show the generic timeout if
                    // startup is genuinely still pending.
                    if !ready_flag.load(Ordering::SeqCst) {
                        report_fatal_stage(
                            &handle_clone,
                            "server",
                            "The application backend did not start in time. Please close this \
window and try again. If the problem persists, please send the log file to \
info@datadrivenconstruction.io.",
                        );
                    }
                }
            });

            Ok(())
        })
        .build(tauri::generate_context!());

    match app {
        Ok(app) => app.run(|app_handle, event| {
            if let RunEvent::ExitRequested { .. } = event {
                // Stop the backend sidecar so it does not linger after close.
                // Take the child out in its own statement so the MutexGuard
                // temporary is dropped at the semicolon, before `state` (the
                // State borrow it is taken from) goes out of scope. Holding the
                // guard across the `if let` body borrowed `state` too long and
                // failed to compile (E0597) in the release build.
                let state = app_handle.state::<AppState>();
                let child = state.backend_child.lock().unwrap().take();
                if let Some(child) = child {
                    let _ = child.kill();
                }
            }
        }),
        Err(e) => {
            // Building the Tauri app itself failed. There is no Tauri window to
            // show an error in, so at least leave a breadcrumb in the log...
            let message = format!("FATAL: error building Tauri application: {e}");
            log_line(&message);
            // ...and, on Windows, pop a NATIVE message box so the failure is
            // never silent again (the v7.0.0 updater-plugin crash exited within
            // 2s with nothing on screen). MessageBoxW is a bare Win32 call via
            // windows-sys, so it works even though no Tauri/WebView2 window
            // exists.
            show_startup_failure_dialog(&message);
        }
    }
}

/// Show a native, blocking failure dialog when the app cannot even be built.
///
/// On Windows this calls `MessageBoxW` directly (no Tauri window is available at
/// this point), pairing the error text with the launcher log path so the user
/// can find full diagnostics. On every other platform it is a no-op beyond the
/// log line and stderr that the caller already emitted.
#[cfg(windows)]
fn show_startup_failure_dialog(message: &str) {
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        MessageBoxW, MB_ICONERROR, MB_OK, MB_SETFOREGROUND, MB_TOPMOST,
    };

    let log_hint = log_path()
        .map(|p| format!("\n\nA full diagnostic log was written to:\n{}", p.display()))
        .unwrap_or_default();
    let body = format!(
        "OpenConstructionERP could not start.\n\n{message}{log_hint}\n\n\
If this keeps happening, please send the log file to info@datadrivenconstruction.io."
    );

    let to_wide = |s: &str| -> Vec<u16> {
        s.encode_utf16().chain(std::iter::once(0)).collect::<Vec<u16>>()
    };
    let body_w = to_wide(&body);
    let title_w = to_wide("OpenConstructionERP failed to start");

    // SAFETY: both buffers are valid, NUL-terminated UTF-16; a null HWND is the
    // documented way to show an owner-less message box.
    unsafe {
        MessageBoxW(
            std::ptr::null_mut(),
            body_w.as_ptr(),
            title_w.as_ptr(),
            MB_OK | MB_ICONERROR | MB_SETFOREGROUND | MB_TOPMOST,
        );
    }
}

/// Non-Windows fallback: the log line and stderr from the caller are the whole
/// story, so there is nothing extra to do here.
#[cfg(not(windows))]
fn show_startup_failure_dialog(_message: &str) {}
