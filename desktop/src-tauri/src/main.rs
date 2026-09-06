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
use std::time::{Duration, Instant};

use tauri::{
    menu::{MenuBuilder, MenuItemBuilder, PredefinedMenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager, RunEvent,
};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

/// Asks GitHub, once per start, whether a newer release exists, and offers it in
/// the failure window. Kept in its own file because it must be able to speak
/// when nothing else in this one worked.
mod update_check;

/// Decides which application server this window talks to: the one this launcher
/// starts, as always, or one somewhere else that an administrator or the user
/// pointed it at. Kept in its own file because it reads three inputs and returns
/// an answer without touching a network, a process or Tauri, which is what lets
/// the precedence order be tested as a function rather than as a startup.
mod server_config;

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
    /// Set the moment the app decides to exit, before the sidecar is stopped.
    ///
    /// Everything that watches the backend has to be able to tell a crash from
    /// a shutdown we asked for. Without this flag the watchers below would see
    /// the very kill we just issued and announce to a user who is closing the
    /// app that their backend has died.
    shutting_down: Arc<AtomicBool>,
    /// Set by the output pump when the sidecar process is observed to exit, so
    /// the exit path can wait for the process to really be gone rather than
    /// assume it.
    backend_exited: Arc<AtomicBool>,
    /// Set by whichever watcher first told the user the backend was lost, so
    /// the same failure is never reported twice through two channels.
    backend_lost_reported: Arc<AtomicBool>,
    /// The loopback port of the sidecar THIS launcher started.
    ///
    /// Set only on the spawn path. On the attach path the backend belongs to
    /// somebody else - a developer running `serve` in a terminal - and asking
    /// it to shut down would stop a server we were only borrowing.
    backend_port: Mutex<Option<u16>>,
    /// Secret the backend requires before it will stop itself, one per run.
    ///
    /// Generated here, handed to the sidecar in its environment, and sent back
    /// in a header on the way out. It never touches the disk. See
    /// `backend/app/core/desktop_shutdown.py` for the guards it satisfies.
    shutdown_token: String,
}

/// How long to give the platform opener a chance to report failure.
///
/// `ShellExecuteW` and `open` hand the target to the OS and answer within a few
/// milliseconds, so a real failure lands well inside this window. `xdg-open` may
/// exec the browser in place instead and stay alive for the whole desktop
/// session, which is why the opener is never simply waited on: that would block
/// the caller until the user closed their browser. Waiting only this long for an
/// answer catches the failures the OS does report and returns immediately on the
/// normal path.
const OPENER_FAILURE_WINDOW: Duration = Duration::from_millis(400);

/// Only the spawning arms poll; the Windows arm waits on a channel instead.
#[cfg(not(target_os = "windows"))]
const OPENER_POLL_INTERVAL: Duration = Duration::from_millis(20);

/// The NUL-terminated wide string the Windows shell is handed, or a refusal.
///
/// This is the whole of the argument the opener receives. There is no command
/// line, so nothing here is quoted, escaped or otherwise adjusted: the caller's
/// string is converted to UTF-16 and a terminator is appended, and that is all.
/// Keeping it a separate function is what lets a test assert that the bytes
/// leaving us are the bytes that arrived.
///
/// An interior NUL is the one thing that must be refused. It is the string
/// terminator, so the shell would silently see a prefix of the target and open
/// something the user never asked for, which is the failure mode this whole
/// change exists to remove. Rust strings may legally contain one; a URL that
/// reached us honestly cannot.
///
/// Args:
///     target: The URL or path about to be opened.
///
/// Returns:
///     The wide string to pass as `lpFile`, or an error naming the refusal.
#[cfg(target_os = "windows")]
fn shell_target(target: &str) -> Result<Vec<u16>, String> {
    use std::os::windows::ffi::OsStrExt;

    if target.contains('\0') {
        return Err("the link contains a null character".to_string());
    }
    Ok(std::ffi::OsStr::new(target)
        .encode_wide()
        .chain(std::iter::once(0))
        .collect())
}

/// Ask the Windows shell to open one target, and report what it said.
///
/// Runs on its own thread with COM initialised, because the shell may hand the
/// open to a shell extension that requires an apartment, and a Tauri command
/// runs on whatever thread Tauri chose. A dedicated thread makes the pairing
/// with `CoUninitialize` exact: it is taken and released around one call and the
/// thread then ends, so there is no apartment left behind on a worker that
/// something else will reuse.
///
/// The return value is an `HINSTANCE` for historical reasons and is not a
/// handle. Anything above 32 means the request was accepted; at or below 32 it
/// is an error code, and the few worth naming are named.
///
/// Args:
///     file: The wide string from `shell_target`.
///
/// Returns:
///     Ok when the shell accepted the request, otherwise what it refused with.
#[cfg(target_os = "windows")]
fn shell_execute(file: &[u16]) -> Result<(), String> {
    use windows_sys::Win32::System::Com::{
        CoInitializeEx, CoUninitialize, COINIT_APARTMENTTHREADED, COINIT_DISABLE_OLE1DDE,
    };
    use windows_sys::Win32::UI::Shell::ShellExecuteW;
    use windows_sys::Win32::UI::WindowsAndMessaging::SW_SHOWNORMAL;

    let verb: Vec<u16> = "open".encode_utf16().chain(std::iter::once(0)).collect();

    // S_OK and S_FALSE both mean this thread now holds an initialisation to
    // release. Anything else, RPC_E_CHANGED_MODE in particular, means somebody
    // else's apartment is already here and releasing it would not be ours to do.
    let hr = unsafe {
        CoInitializeEx(
            std::ptr::null(),
            (COINIT_APARTMENTTHREADED | COINIT_DISABLE_OLE1DDE) as u32,
        )
    };
    let owns_com = hr == 0 || hr == 1;

    let outcome = unsafe {
        ShellExecuteW(
            std::ptr::null_mut(),
            verb.as_ptr(),
            file.as_ptr(),
            std::ptr::null(),
            std::ptr::null(),
            SW_SHOWNORMAL,
        )
    } as isize;

    if owns_com {
        unsafe { CoUninitialize() };
    }

    if outcome > 32 {
        return Ok(());
    }
    Err(match outcome {
        2 | 3 => "the system could not find an application to open it".to_string(),
        5 => "the system refused access to the application that opens it".to_string(),
        31 => "no application is associated with this kind of link".to_string(),
        code => format!("the system opener refused it with code {code}"),
    })
}

/// Start the platform opener for a URL or file path.
///
/// Uses the platform opener directly (`open` on macOS, `xdg-open` on Linux)
/// rather than the tauri shell plugin's deprecated `open`, and adds no
/// dependency. Windows does not come through here at all; see
/// `open_with_os_default`.
#[cfg(target_os = "macos")]
fn spawn_os_opener(target: &str) -> std::io::Result<std::process::Child> {
    std::process::Command::new("open").arg(target).spawn()
}

#[cfg(not(any(target_os = "windows", target_os = "macos")))]
fn spawn_os_opener(target: &str) -> std::io::Result<std::process::Child> {
    std::process::Command::new("xdg-open").arg(target).spawn()
}

/// Open a URL or file path in the operating system's default handler, and say
/// so honestly when the operating system refuses.
///
/// For a URL this lands the user in their normal web browser at the local
/// address. Spawning alone proves nothing: it succeeds the moment the launcher
/// process starts, so a machine with no registered browser, a broken file
/// association or no `xdg-open` handler used to be reported back as a success
/// and the user was told nothing at all.
///
/// This is not a complete detector, and callers should not present it as one.
/// `Ok` means the OS accepted the request, not that a browser window appeared:
/// the shell answers before the browser has drawn anything, and a "How do you
/// want to open this file?" chooser is an acceptance too.
///
/// Windows takes an entirely different route from the other two, and that is
/// the point of it. It used to run `cmd /c start "" "<target>"`, which meant the
/// target became part of a command line that cmd.exe then re-parsed. Quoting
/// held off the separators, but cmd expands `%NAME%` inside quotes as well as
/// outside, so a link could carry a variable reference that cmd substituted on
/// the way past. Measured on Windows 11: `%USERNAME%` in a link became the
/// account name and `%CD%` became the full path of the working directory, both
/// sent to whatever host the link named. Once the application page could invoke
/// the link command, that link no longer had to come from one of our own string
/// literals, and a value read out of a project could reach it.
///
/// No enumeration of what cmd does to a string was going to close that. The
/// obvious rule of refusing two hex digits after a percent does not, because
/// `%CD%` is a real variable and C and D are both hex digits. Refusing names
/// that `std::env::var` resolves does not either, because cmd expands dynamic
/// pseudo-variables that are not in the environment block at all: `CD`, `DATE`,
/// `TIME`, `RANDOM` and `ERRORLEVEL` all expand while `std::env::var` reports
/// them absent, and an undefined name survives literally, so testing such a rule
/// with an obvious name produces a green that means nothing.
///
/// So the command line is gone. `ShellExecuteW` takes the target as one
/// argument, and no shell parses it: percent signs, ampersands, quotes and line
/// breaks are all just characters in a string. The JavaScript layer above never
/// helped with this and should not be credited for it. `new URL` leaves invalid
/// percent sequences exactly as written, so the browser hands the string through
/// unchanged; it does encode a double quote and strip carriage returns and
/// newlines, which is why those three were never the hole. Percent was the one
/// thing that passed both layers.
#[cfg(target_os = "windows")]
fn open_with_os_default(target: &str) -> Result<(), String> {
    let file = shell_target(target)?;

    // The call is given the same grace the child process used to get. Opening a
    // link is meant to feel instant, and a shell that has not answered inside
    // the window has taken the request rather than refused it, so the caller is
    // told the truth it has: nothing has gone wrong. A refusal arrives in
    // microseconds, well inside this, because it is a lookup and not a launch.
    //
    // THIS TIMEOUT IS NOT GUARDING A RACE OF OURS AND MUST NOT BE READ AS ONE.
    // Nothing here is shared, and the thread cannot be beaten to anything. What
    // it bounds is somebody else's code: the shell may hand the open to a shell
    // extension from any installed application, and such an extension is free to
    // be slow or to block outright. Without the timeout that third party decides
    // how long the window stays frozen. Remove it and links stay correct while
    // the application occasionally stops responding on a machine whose shell
    // extensions we have never seen.
    let (tx, rx) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        let _ = tx.send(shell_execute(&file));
    });
    match rx.recv_timeout(OPENER_FAILURE_WINDOW) {
        Ok(outcome) => outcome,
        Err(_) => Ok(()),
    }
}

#[cfg(not(target_os = "windows"))]
fn open_with_os_default(target: &str) -> Result<(), String> {
    let mut child = spawn_os_opener(target).map_err(|e| e.to_string())?;
    let deadline = Instant::now() + OPENER_FAILURE_WINDOW;
    loop {
        match child.try_wait() {
            Ok(Some(status)) if status.success() => return Ok(()),
            Ok(Some(status)) => {
                return Err(match status.code() {
                    Some(code) => format!("the system opener exited with code {code}"),
                    None => "the system opener was terminated".to_string(),
                })
            }
            Ok(None) => {
                if Instant::now() >= deadline {
                    // Still running past the window: it has taken ownership of
                    // the target (the normal xdg-open case) and there is
                    // nothing left to report.
                    return Ok(());
                }
                std::thread::sleep(OPENER_POLL_INTERVAL);
            }
            Err(e) => return Err(e.to_string()),
        }
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
    open_with_os_default(&url).map_err(|e| format!("Could not open your browser: {e}"))
}

/// Open an arbitrary external link (http/https/mailto) in the OS default handler.
///
/// The in-app UI carries many outbound links - the docs, the GitHub repo, the
/// marketing site, contact mail. Inside the webview a `target="_blank"` anchor is
/// swallowed and nothing opens, so the frontend routes every external-link click
/// here. Only web and mail schemes are honoured, so a stray or crafted href
/// cannot name a local program for the opener to launch.
///
/// That scheme test is not on its own what makes this safe, and it used to be
/// described as though it were. It bounds what the opener is asked to open; it
/// says nothing about what happens to the string on the way there. When this
/// went through `cmd /c start`, https://example.invalid/&calc passed this check
/// in full and the tail ran as a second command until quoting was added, and a
/// link carrying %USERNAME% still had the account name substituted into it and
/// sent to the host in the link. Neither was a scheme problem and neither could
/// be fixed here.
///
/// It is now safe because there is no shell. `open_with_os_default` hands the
/// target to `ShellExecuteW` as one argument, so this check does only the job
/// it can actually do: deciding which schemes we are willing to open at all.
///
/// This command takes a caller-supplied destination, which `open_app_in_browser`
/// does not, so it is the one to think hardest about before anything is added
/// beside it.
#[tauri::command]
fn open_external_url(url: String) -> Result<(), String> {
    let target = url.trim();
    let lower = target.to_ascii_lowercase();
    let allowed = lower.starts_with("http://")
        || lower.starts_with("https://")
        || lower.starts_with("mailto:");
    if !allowed {
        return Err("Only http, https and mailto links can be opened".to_string());
    }
    open_with_os_default(target).map_err(|e| format!("Could not open the link: {e}"))
}

/// Decide which folder, if any, a reveal request may open.
///
/// Separated from the command so the rule can be tested without a webview, an
/// app handle or a real click. It takes the two paths already resolved by the
/// caller and answers with the directory to hand the opener, or with the reason
/// it will not.
///
/// Two bounds, and both are about what a page may reach rather than what a user
/// may see. The target has to sit inside this workspace, so a page cannot ask
/// the operating system to open `C:\\Windows` or a network share by naming it.
/// And what comes back is always a DIRECTORY: a file is answered with its
/// parent, so the file manager shows the file in place instead of the shell
/// launching it with whatever program claims its extension. That second rule is
/// why an executable dropped into the workspace is not a way for a page to run
/// code.
///
/// `starts_with` here is `Path::starts_with`, which compares whole components
/// rather than characters, so a sibling folder whose name merely begins with
/// the workspace's name is outside and is refused.
fn folder_to_reveal(root: &std::path::Path, target: &std::path::Path) -> Result<PathBuf, String> {
    if !target.starts_with(root) {
        return Err("Only files inside this workspace can be shown".to_string());
    }
    if target.is_dir() {
        return Ok(target.to_path_buf());
    }
    match target.parent() {
        Some(parent) if parent.starts_with(root) => Ok(parent.to_path_buf()),
        _ => Err("That file has no folder inside this workspace".to_string()),
    }
}

/// Show a file from this workspace in the operating system's file manager.
///
/// The file manager's "Open in OS" button used to reach for the shell plugin's
/// own `open` command. The application window is a remote origin governed by
/// `capabilities/app-window.json`, which grants no shell plugin permission at
/// all, so every click was refused by the access control list before it ran.
/// The frontend caught the rejection, wrote it to the console and returned
/// false, and the button did nothing with nothing on screen to say why; the
/// refusal text is what a user's bug report carried instead.
///
/// Granting `shell:allow-open` to the application window would have made the
/// click work by handing page content an opener whose destination the page
/// chooses, which the capability's own description names as the thing to think
/// hardest about before adding. This is the narrow command instead. The caller
/// names a path and this decides whether it is one we will show, by the rule in
/// `folder_to_reveal`.
///
/// Both paths are canonicalised first, which is what makes the rule mean
/// anything: `..` segments, symbolic links and the short names Windows still
/// hands out all collapse before the comparison, so a path that spells its way
/// out of the workspace is judged on what it resolves to rather than on how it
/// is written.
#[tauri::command]
fn reveal_path_in_os(path: String) -> Result<(), String> {
    let raw = path.trim();
    if raw.is_empty() {
        return Err("There is no path to show".to_string());
    }

    let root = workspace_data_dir().ok_or("This installation has no data folder")?;
    let root = std::fs::canonicalize(&root)
        .map_err(|_| "This installation's data folder could not be found".to_string())?;
    let target = std::fs::canonicalize(PathBuf::from(raw))
        .map_err(|_| "That file is not on this computer".to_string())?;

    let folder = folder_to_reveal(&root, &target)?;
    open_with_os_default(&folder.to_string_lossy())
        .map_err(|e| format!("Could not open the folder: {e}"))
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
/// show if the log path cannot be resolved or opened. Shares `open_with_os_default`
/// with the browser and link commands rather than repeating the platform block:
/// this is the surface a user reaches for when something has already gone
/// wrong, so it is the last place that should quietly claim success.
#[tauri::command]
fn open_log_file(_app: tauri::AppHandle) -> Result<(), String> {
    let path = log_path().ok_or_else(|| "Could not resolve the log file path".to_string())?;
    let path_str = path.to_string_lossy().to_string();
    open_with_os_default(&path_str).map_err(|e| format!("Could not open the log file: {e}"))
}

/// Tell the caller which server this window is talking to, and who decided.
///
/// Answers from the same resolver startup used, rather than from a note taken
/// at startup, so the answer is about the machine's current configuration and
/// not about a decision that may since have been changed in another window.
///
/// The address for a local start comes from the running app URL rather than
/// from the resolver, because the resolver only knows that a local server was
/// wanted; the port it actually ended up on is a runtime fact.
#[tauri::command]
fn get_server_choice(app: tauri::AppHandle) -> serde_json::Value {
    let running = {
        let state = app.state::<AppState>();
        let guard = state.app_url.lock().unwrap();
        guard.clone().unwrap_or_default()
    };

    let (mode, url, source) = match server_config::resolve() {
        server_config::Resolution::Local { source } => ("local", running, source),
        server_config::Resolution::Remote { url, source } => ("remote", url, source),
        // Reachable only if the configuration changed under a window that had
        // already started. Reported as what it is rather than smoothed over.
        server_config::Resolution::Refused { source, raw, .. } => ("remote", raw, source),
    };

    serde_json::json!({
        "mode": mode,
        "url": url,
        "source": source.describe(),
        "fromUserSetting": source == server_config::ChoiceSource::Setting,
    })
}

/// Save, or clear, this user's own choice of server.
///
/// `mode` of `None` clears the choice and hands the decision back to the
/// environment variable and the file an administrator deployed. That is the
/// only route back to being centrally managed once somebody has chosen, so it
/// is a supported argument and not an accident of the signature.
///
/// Never changes the running window. The setting is read while starting, and
/// repointing a live session at a different database would leave every open
/// form and every cached query belonging to the server it came from.
///
/// EVERY OUTCOME IS LOGGED, AND WHY THAT IS NOT DECORATION.
///
/// This command is granted to the application page, which means anything that
/// can run script on our own origin can call it, and what it writes decides
/// where the NEXT start sends this user's password. That is a step up from what
/// script on that origin can otherwise do, because it survives a restart, and
/// the argument written in capabilities/app-window.json does not cover it: that
/// argument is about a hostile process already running as this user, and script
/// on a page is not one.
///
/// The log line is a record, not a defence, and it is written down as a record
/// so that nobody later mistakes it for one. It cannot stop the write. What it
/// does is make a write that nobody performed visible afterwards to the one
/// person who would go looking, next to the log the failure screen already
/// tells people to send us. A change of server also announces itself at the
/// next start, where the splash names the host it is contacting. Neither of
/// those is consent, and a control that asks for consent is a separate change.
#[tauri::command]
fn set_server_choice(mode: Option<String>, url: Option<String>) -> Result<(), String> {
    let Some(mode) = mode else {
        log_line("the server choice was cleared from the application page");
        return server_config::write_setting(None);
    };
    match mode.as_str() {
        "local" => {
            log_line("a server on this computer was chosen from the application page");
            server_config::write_setting(Some(&server_config::ServerChoice::Local))
        }
        "remote" => {
            let raw = url.unwrap_or_default();
            // Validated here, in the launcher, and nowhere else. A second
            // validator in the web page would be a second opinion about what is
            // acceptable, and the day the two disagree is the day the settings
            // page accepts an address the launcher then refuses, which is the
            // blank window this whole path exists to prevent.
            let canonical =
                server_config::validate_server_url(&raw).map_err(|problem| problem.message())?;
            // The canonical form, not the typed one. This line is read to find
            // out where the machine was actually pointed, and the typed text is
            // not necessarily that.
            log_line(&format!(
                "the server for the next start was set to {canonical} from the application page"
            ));
            server_config::write_setting(Some(&server_config::ServerChoice::Remote {
                url: canonical,
            }))
        }
        other => Err(format!("Unknown server mode \"{other}\".")),
    }
}

/// Record a choice of local server and restart into it.
///
/// The recovery action, reached from the tray when a configured server is the
/// wrong one and from the startup failure screen when it cannot be reached. It
/// writes the choice before restarting rather than after, because a restart
/// that lost the choice would come straight back to the screen it was started
/// from, and a loop is a worse experience than the failure it was trying to
/// leave.
///
/// A write that fails is logged and the restart happens anyway. The user asked
/// to get out of here, and an unwritable home folder is not a reason to keep
/// them in it; they land on the same screen and can try again, which is exactly
/// where they already were.
fn switch_to_local_and_restart(app: &tauri::AppHandle) {
    if let Err(e) = server_config::write_setting(Some(&server_config::ServerChoice::Local)) {
        log_line(&format!(
            "could not save the choice of a local server, restarting anyway: {e}"
        ));
    } else {
        log_line("switching to a server on this computer, restarting");
    }
    app.restart();
}

/// The startup failure screen's button for the same thing.
#[tauri::command]
fn use_local_server(app: tauri::AppHandle) {
    switch_to_local_and_restart(&app);
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

/// Run a snippet of JavaScript in the main window, retried a few times.
///
/// setup() may run before the page has finished loading its inline script, so
/// we retry the eval over ~2 seconds. Every snippet sent through here must
/// therefore be idempotent, because it will run up to eight times.
///
/// `raise_window` brings the window to the front on each attempt. That is right
/// while the splash is up and the window is what the user just asked for, and
/// wrong afterwards: an app sitting in the tray would be yanked onto the screen
/// by a message that could have waited.
fn eval_retrying(handle: &tauri::AppHandle, js: String, raise_window: bool) {
    let handle = handle.clone();
    tauri::async_runtime::spawn(async move {
        for _ in 0..8 {
            if let Some(window) = handle.get_webview_window("main") {
                if raise_window {
                    let _ = window.show();
                }
                let _ = window.eval(&js);
            }
            tokio::time::sleep(std::time::Duration::from_millis(250)).await;
        }
    });
}

/// Run a snippet in the splash window. The splash boot functions are idempotent
/// (they just set DOM state), so repeated calls are harmless.
fn eval_in_splash(handle: &tauri::AppHandle, js: String) {
    eval_retrying(handle, js, true);
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

/// Tell the splash which build it is, so a startup failure carries its version.
///
/// This is the one screen a user with a backend that will not start can still
/// read, and the version is the first thing anyone answering their report has to
/// know: the same message is produced by faults that were fixed releases ago and
/// by faults that are still open. Without it a report cannot be triaged at all.
/// Every other place that names the version lives behind a running application,
/// which is precisely what these users do not have.
fn report_app_version(handle: &tauri::AppHandle) {
    let v = js_escape(env!("CARGO_PKG_VERSION"));
    eval_in_splash(
        handle,
        format!("(function(){{if(typeof setAppVersion==='function'){{setAppVersion('{v}');}}}})()"),
    );
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
    report_app_version(handle);
    // Every way startup can fail comes through here, so this is the one place
    // that has to carry the offer of a newer version. For a user whose
    // installed build cannot start at all, that sentence is the entire fix, and
    // the application's own update notice can never reach them: it is served by
    // the backend that just failed. Adds nothing to the failure path but a flag
    // read, and shows nothing unless an answer has already come back.
    update_check::note_startup_failed(handle, env!("CARGO_PKG_VERSION"));
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

/// A pre-ready sidecar death the launcher can name more precisely than "the
/// backend stopped unexpectedly".
struct StartupFailure {
    /// Checklist step to mark failed.
    stage: &'static str,
    /// What to show in place of the raw stderr tail.
    message: String,
}

/// Name the onefile entry a bootloader extraction failure stopped on.
///
/// The bootloader reports the same failure twice and in two shapes, "Failed to
/// extract <name>: decompression resulted in return code -1!" and then "Failed
/// to extract entry: <name>". Only the first carries the name before the colon,
/// so the literal word "entry" is skipped rather than reported as a filename.
fn bootloader_failed_entry(tail: &str) -> Option<String> {
    const MARKER: &str = "Failed to extract ";
    for (idx, _) in tail.match_indices(MARKER) {
        let rest = &tail[idx + MARKER.len()..];
        let name = rest
            .split(|c: char| c == ':' || c == '\n' || c == '\r' || c == '!')
            .next()
            .unwrap_or("")
            .trim();
        if name.is_empty() || name == "entry" {
            continue;
        }
        return Some(name.to_string());
    }
    None
}

/// Recognise a PyInstaller onefile bootloader failure in the sidecar's stderr.
///
/// The sidecar is a onefile build (desktop/pyinstaller.spec), which means the
/// bootloader unpacks the entire payload into a temporary folder on every
/// single launch (on Windows the one named by `EXTRACTION_ROOT_SPEC_LITERAL`),
/// before the bundled Python interpreter is started and therefore before one
/// line of this project's code runs. When that unpacking
/// fails the process dies with no traceback, no "STAGE:" line and nothing the
/// rest of this file knows how to read, so the launcher fell through to its last
/// resort and showed the raw tail:
///
///   [PYI-16964:ERROR] Failed to extract cv2\cv2.pyd: decompression resulted in
///   return code -1! [PYI-16964:ERROR] Failed to extract entry: cv2\cv2.pyd
///
/// which reads as an internal crash rather than as the environmental problem it
/// is. Worse, that path attributed the death to the "server" step, so the one
/// screen the user can send us said the application server had failed on a run
/// where no server was ever reached - pointing the reader at startup code that
/// had not executed. Reported against 16.5.0 on Windows 11 (issue 462).
///
/// Returns None for anything that is not a bootloader failure, which leaves
/// every existing cause reported exactly as before.
fn classify_bootloader_failure(tail: &str) -> Option<StartupFailure> {
    if !tail.contains("[PYI-") {
        return None;
    }
    let unpack_failed = tail.contains("Failed to extract")
        || tail.contains("decompression resulted in return code")
        || tail.contains("Failed to create temporary directory")
        || tail.contains("Could not create temporary directory");
    if !unpack_failed {
        return None;
    }
    let on_entry = match bootloader_failed_entry(tail) {
        Some(name) => format!(" It stopped while writing {name}."),
        None => String::new(),
    };
    Some(StartupFailure {
        // Not "server": the backend executable never got as far as running a
        // server. This step is the one that owns having a working backend.
        stage: "sidecar",
        message: format!(
            "The application could not unpack itself into the temporary folder it \
uses.{on_entry} The whole program is unpacked there every time it starts, so this is \
normally either antivirus software removing or locking the files while they are being \
written, or too little free space on the drive that holds that temporary folder."
        ),
    })
}

/// Tell the user the backend is gone, in whatever page the window is showing.
///
/// The splash reporting above is unusable once startup has succeeded. The
/// moment the webview navigates to the application the splash document is torn
/// down with every function the launcher talks to it through, so `failStage`
/// and `setError` are no longer defined and the `typeof` guards turn every
/// later report into a silent no-op. A backend that died an hour into the
/// session therefore had no way at all to reach the person using it: the window
/// kept showing the last screen it had rendered while every action on it failed.
///
/// So this builds its own overlay out of plain DOM instead of calling into the
/// page, which works on the splash and on the application alike, and needs
/// nothing from the frontend bundle. It is idempotent by element id because
/// `eval_retrying` will run it up to eight times.
fn report_backend_lost(
    handle: &tauri::AppHandle,
    reported: &AtomicBool,
    headline: &str,
    detail: &str,
) {
    // First reporter wins. The process pump and the liveness watch can both
    // see the same death, and the user should hear about it once.
    if reported
        .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
        .is_err()
    {
        return;
    }

    log_line(&format!("BACKEND LOST: {headline} {detail}"));
    let log_hint = log_path()
        .map(|p| format!(" The launcher log is at {}.", p.display()))
        .unwrap_or_default();
    let head_js = js_escape(headline);
    let body_js = js_escape(&format!("{detail}{log_hint}"));

    eval_retrying(
        handle,
        format!(
            "(function(){{\
                var d=document;\
                if(!d||d.getElementById('oe-backend-lost')){{return;}}\
                var host=d.body||d.documentElement;\
                if(!host){{return;}}\
                var o=d.createElement('div');\
                o.id='oe-backend-lost';\
                o.setAttribute('style','position:fixed;top:0;left:0;right:0;bottom:0;\
z-index:2147483647;background:rgba(15,17,21,0.94);color:#f5f7fa;display:flex;\
align-items:center;justify-content:center;padding:32px;text-align:left;\
font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:15px;\
line-height:1.55');\
                var c=d.createElement('div');\
                c.setAttribute('style','max-width:620px');\
                var h=d.createElement('div');\
                h.setAttribute('style','font-size:20px;font-weight:600;margin-bottom:12px');\
                h.textContent='{head_js}';\
                var p=d.createElement('div');\
                p.textContent='{body_js}';\
                c.appendChild(h);c.appendChild(p);o.appendChild(c);host.appendChild(o);\
            }})()"
        ),
        false,
    );
}

/// Show or clear the notice that says the backend has gone quiet.
///
/// Deliberately not the modal above. Silence is a symptom that can end: a long
/// import holding the database pool keeps the health check waiting on a backend
/// that is working perfectly well, and telling that person their app is dead,
/// behind a sheet they cannot dismiss, would cost them the very work that
/// caused the delay. So this is a strip along the bottom that takes no clicks
/// (`pointer-events:none`) and is removed again the moment the backend answers.
fn set_backend_silent_notice(handle: &tauri::AppHandle, shown: bool) {
    let js = if shown {
        let text = js_escape(
            "The application backend has not answered for about two minutes. It may be working \
through a long operation, such as a large import, and this notice will disappear as soon as it \
responds. If the window stays unusable, close it and start OpenConstructionERP again.",
        );
        format!(
            "(function(){{\
                var d=document;\
                if(!d||d.getElementById('oe-backend-silent')){{return;}}\
                var host=d.body||d.documentElement;\
                if(!host){{return;}}\
                var o=d.createElement('div');\
                o.id='oe-backend-silent';\
                o.setAttribute('style','position:fixed;left:0;right:0;bottom:0;\
z-index:2147483646;pointer-events:none;background:rgba(15,17,21,0.94);color:#f5f7fa;\
padding:14px 20px;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;\
font-size:14px;line-height:1.5');\
                o.textContent='{text}';\
                host.appendChild(o);\
            }})()"
        )
    } else {
        "(function(){\
            var d=document;if(!d){return;}\
            var e=d.getElementById('oe-backend-silent');\
            if(e&&e.parentNode){e.parentNode.removeChild(e);}\
        })()"
            .to_string()
    };
    eval_retrying(handle, js, false);
}

/// How often the liveness watch asks the backend whether it is still there.
const LIVENESS_POLL_INTERVAL: Duration = Duration::from_secs(10);
/// How long one liveness probe may take before it counts as unanswered.
const LIVENESS_PROBE_TIMEOUT: Duration = Duration::from_secs(5);
/// Consecutive refused connections before the backend is called dead. A refusal
/// is an immediate and unambiguous answer from the operating system: nothing is
/// listening on that port any more.
const LIVENESS_REFUSED_STRIKES: u32 = 2;
/// Consecutive unanswered probes before the user is told the backend has gone
/// quiet. Silence is much weaker evidence than a refusal, because a machine
/// waking from sleep, a heavy import or a long migration can all keep a request
/// waiting, so this threshold is deliberately several times longer and what it
/// triggers is a reversible notice rather than a verdict. Two minutes is not
/// generous by accident: the health check takes a database connection, and a
/// large import holding the pool keeps every probe waiting on a backend that is
/// working perfectly well.
const LIVENESS_SILENT_STRIKES: u32 = 12;

/// What to say when a server this machine was running has gone.
const LOCAL_BACKEND_LOST_DETAIL: &str =
    "Nothing is listening on the local address any more, so this window can no longer load or \
save anything. Please close it and start OpenConstructionERP again. If this keeps happening, \
send the log file to info@datadrivenconstruction.io.";

/// What to say when a server somewhere else has gone.
///
/// A separate sentence rather than the local one with the address swapped in,
/// because the action is different: nobody can restart a server on another
/// machine by reopening this window, and telling them to try would send them
/// round a loop that cannot end.
fn remote_backend_lost_detail(url: &str) -> String {
    format!(
        "The server at {url} is no longer answering, so this window can no longer load or save \
anything. Check that the server is running and that this computer can still reach it, then \
start OpenConstructionERP again. You can also switch back to a server on this computer from \
the tray icon menu."
    )
}

/// Keep watching the backend AFTER it has answered its first health check.
///
/// Readiness was the end of the launcher's attention: past that point nothing
/// asked whether the backend was still alive. When it went away the window
/// stayed exactly as it was, so a user went on clicking a screen whose every
/// request was failing, with no message anywhere saying why.
///
/// This is also the only cover for the attach path, where the backend belongs
/// to another process entirely: there is no child to wait on and no output to
/// pump, so its death is invisible by construction.
///
/// Takes the health address rather than a port because the backend is no longer
/// always on loopback. `lost_detail` travels with it for the same reason: what
/// a user should do about a dead server is different depending on whose server
/// it is, and "nothing is listening on the local address" is actively
/// misleading about one that lives on the network.
async fn watch_backend_liveness(
    handle: tauri::AppHandle,
    health_url: String,
    lost_detail: String,
    shutting_down: Arc<AtomicBool>,
    reported: Arc<AtomicBool>,
) {
    let client = reqwest::Client::new();
    let url = health_url;
    let mut refused: u32 = 0;
    let mut silent: u32 = 0;
    let mut silent_notice = false;

    loop {
        tokio::time::sleep(LIVENESS_POLL_INTERVAL).await;
        // A shutdown we asked for is not a failure, and a death already
        // reported by the process pump does not need saying twice.
        if shutting_down.load(Ordering::SeqCst) || reported.load(Ordering::SeqCst) {
            return;
        }

        match client.get(&url).timeout(LIVENESS_PROBE_TIMEOUT).send().await {
            // Any answer at all, including an error status, proves the process
            // is alive and serving. Only absence is evidence of death here.
            Ok(_) => {
                refused = 0;
                silent = 0;
                if silent_notice {
                    silent_notice = false;
                    log_line("liveness: the backend is answering again");
                    set_backend_silent_notice(&handle, false);
                }
            }
            Err(e) if e.is_connect() => {
                refused += 1;
                silent = 0;
                log_line(&format!(
                    "liveness: connection to the backend refused ({}/{})",
                    refused, LIVENESS_REFUSED_STRIKES
                ));
            }
            Err(e) => {
                silent += 1;
                log_line(&format!(
                    "liveness: backend did not answer ({}/{}): {e}",
                    silent, LIVENESS_SILENT_STRIKES
                ));
            }
        }

        if refused >= LIVENESS_REFUSED_STRIKES {
            if silent_notice {
                set_backend_silent_notice(&handle, false);
            }
            report_backend_lost(
                &handle,
                &reported,
                "The application backend has stopped",
                &lost_detail,
            );
            return;
        }
        // Silence is not a verdict, so the watch does not end here. It says
        // what it sees, keeps polling, and takes the notice down again if the
        // backend comes back. Only a refusal, above, is final.
        if silent >= LIVENESS_SILENT_STRIKES && !silent_notice {
            silent_notice = true;
            log_line("liveness: the backend has gone quiet, telling the user");
            set_backend_silent_notice(&handle, true);
        }
    }
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

/// Accumulates a Python traceback seen on the sidecar's stderr so the launcher
/// can report the real exception line as the failure cause when the backend
/// crashed too early to emit a `STAGE:server:fail` marker. Only the exception
/// summary line is kept (chained tracebacks overwrite it, which is what Python
/// prints last and what the user needs to see), so the database-shutdown noise
/// that follows a crash can never become the reported cause.
#[derive(Default)]
struct TracebackCapture {
    capturing: bool,
    cause: Option<String>,
}

impl TracebackCapture {
    /// Feed one stderr line (the caller has already split on `\n`).
    fn feed_line(&mut self, raw: &str) {
        let line = raw.trim_end();
        if line.contains("Traceback (most recent call last)") {
            self.capturing = true;
            return;
        }
        if !self.capturing {
            return;
        }
        let body = line.trim();
        if body.is_empty() {
            return;
        }
        // Stack-frame lines are indented; keep reading until the summary line.
        if line.starts_with(' ') || line.starts_with('\t') {
            return;
        }
        // Chained-exception connectors are not the cause; the traceback that
        // follows them re-triggers capture and overwrites with the later cause.
        if body.starts_with("During handling of the above exception")
            || body.starts_with("The above exception was the direct cause")
        {
            return;
        }
        // A non-indented, non-connector line is the exception summary
        // (`ExceptionType: message`): record it (bounded, on a char boundary)
        // and stop until another traceback re-triggers capture.
        let mut summary = body.to_string();
        if summary.len() > 300 {
            let mut end = 300;
            while end > 0 && !summary.is_char_boundary(end) {
                end -= 1;
            }
            summary.truncate(end);
        }
        self.cause = Some(summary);
        self.capturing = false;
    }
}

/// The port the desktop app serves on whenever it can have it.
///
/// It is also one of the ports the attach probe below looks at, so a backend
/// left over from a previous run is found and reused instead of becoming a
/// second owner of the same PostgreSQL cluster.
const DEFAULT_BACKEND_PORT: u16 = 8732;

/// Find a port for the backend server, preferring a STABLE one.
///
/// The webview loads the application from `http://127.0.0.1:<port>/`, so the
/// port is the browser origin, and everything the app stores per origin lives
/// and dies with it: the saved session, the chosen interface language, the
/// user's own translation overrides. Picking a fresh random port on every run
/// therefore signed the user out and reset their language on every restart,
/// with nothing on screen to connect the two. Take the default port whenever it
/// is free and only fall back to a picked one when something else holds it.
///
/// Binding and dropping a listener is the only honest way to ask: the bind
/// releases the port at the end of the expression, which leaves the usual tiny
/// race between the check and the sidecar's own bind. That race is what the
/// picker has always had, so this is no weaker than what it replaces.
fn find_available_port() -> u16 {
    if std::net::TcpListener::bind(("127.0.0.1", DEFAULT_BACKEND_PORT)).is_ok() {
        return DEFAULT_BACKEND_PORT;
    }
    portpicker::pick_unused_port().unwrap_or(DEFAULT_BACKEND_PORT)
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

/// File inside the data directory that carries that directory's identity.
///
/// The backend writes and reads the same name from the same directory
/// (`_WORKSPACE_ID_FILENAME` in `backend/app/main.py`). Neither side can import
/// anything from the other, so the name is the whole of the agreement between
/// them and a rename here is a rename there.
const WORKSPACE_ID_FILENAME: &str = "workspace_id.json";

/// The data directory this launcher's backend works in.
///
/// Resolved the way the backend resolves it, because the point of resolving it
/// is to arrive at the same folder. The sidecar is spawned without `--data-dir`
/// and inherits this process's environment, so the CLI's `_default_data_dir`
/// runs there with these same variables and the same precedence:
/// `OE_DATA_DIR`, then `DATA_DIR`, then `OE_CLI_DATA_DIR`, then
/// `~/.openestimate`. Reading only the last of those would be wrong on any
/// machine that sets one of the first three: this launcher would compute one
/// folder, its own backend another, and the two would refuse to recognise each
/// other and start a second server on the first one's database.
fn workspace_data_dir() -> Option<PathBuf> {
    for var in ["OE_DATA_DIR", "DATA_DIR", "OE_CLI_DATA_DIR"] {
        if let Ok(value) = std::env::var(var) {
            if !value.trim().is_empty() {
                return Some(PathBuf::from(value.trim()));
            }
        }
    }
    home_dir().map(|h| h.join(".openestimate"))
}

/// Pull a usable workspace id out of a health body, if it carries one.
///
/// Separate from the probe so the rule can be tested as a function. An empty
/// string is not an identity: two installations that both published one would
/// compare equal, which is the exact confusion this field exists to end.
fn workspace_id_of(json: &serde_json::Value) -> Option<&str> {
    json.get("workspace_id")
        .and_then(|v| v.as_str())
        .map(str::trim)
        .filter(|s| !s.is_empty())
}

/// Read the identity of our own data directory, writing one if there is none.
///
/// The launcher creates this file rather than waiting for a backend to, because
/// it needs the answer before it probes and on a cold start no backend has run
/// yet. That is safe rather than a hazard: both sides resolve the same
/// directory, so whichever runs first writes the file and the other reads that
/// same value back. Two ids can only differ when two directories differ, which
/// is precisely the case that must not attach.
///
/// `create_new` is what makes concurrent starts agree. Writing a temporary file
/// and renaming it over the target is the usual idiom and is the wrong one
/// here: `std::fs::rename` replaces what it finds (`MOVEFILE_REPLACE_EXISTING`
/// on Windows), so two launchers started together would each write an id and
/// the loser would go on holding one that is no longer on disk, then refuse to
/// attach to a backend that is in fact its own. `create_new` fails instead of
/// replacing, and the loser re-reads the winner's value.
///
/// `None` means this launcher has no identity to compare with - no home
/// directory, an unwritable data directory - and the caller must then attach to
/// nothing at all. That is the safe direction: the cost of not attaching is a
/// second backend, and the cost of attaching wrongly is one user reading
/// another user's data.
fn our_workspace_id() -> Option<String> {
    let dir = workspace_data_dir()?;
    let path = dir.join(WORKSPACE_ID_FILENAME);

    if let Some(existing) = read_workspace_id_file(&path) {
        return Some(existing);
    }

    let candidate = uuid::Uuid::new_v4().simple().to_string();
    let body = format!("{{\n  \"workspace_id\": \"{candidate}\"\n}}\n");

    if std::fs::create_dir_all(&dir).is_err() {
        log_line("attach: this installation's data directory could not be created; will not attach to anything");
        return None;
    }

    use std::io::Write;
    match std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&path)
    {
        Ok(mut file) => match file.write_all(body.as_bytes()) {
            Ok(()) => Some(candidate),
            Err(e) => {
                log_line(&format!(
                    "attach: could not record this installation's identity ({e}); will not attach to anything"
                ));
                None
            }
        },
        // Somebody wrote it between the read above and this create. Theirs is
        // the identity of this directory; the candidate above was never used.
        Err(ref e) if e.kind() == std::io::ErrorKind::AlreadyExists => read_workspace_id_file(&path),
        Err(e) => {
            log_line(&format!(
                "attach: could not record this installation's identity ({e}); will not attach to anything"
            ));
            None
        }
    }
}

/// Read one workspace id off disk. Anything unreadable or malformed is absent.
fn read_workspace_id_file(path: &std::path::Path) -> Option<String> {
    let text = std::fs::read_to_string(path).ok()?;
    let json: serde_json::Value = serde_json::from_str(&text).ok()?;
    workspace_id_of(&json).map(str::to_string)
}

/// The first few characters of an id, for a log line that must not print it all.
///
/// Enough to tell two workspaces apart when reading the log, and not the value
/// itself. The log lives in one user's home directory and the ids of other
/// accounts on the machine have no business being written out there in full.
fn id_prefix(id: &str) -> String {
    id.chars().take(8).collect()
}

/// The faults that make a backend unusable, asked once for both callers.
///
/// Two decisions in this launcher rest on one health body, and they used to
/// answer it differently. `judge_health` let a backend reporting stale
/// migrations open the application, which is right: the schema being behind is
/// a real problem the user can see and act on from inside the app.
/// `is_our_backend_healthy` refused to attach to that same backend, which sent
/// the launcher off to start a SECOND backend against the same
/// `~/.openestimate/pgdata` - the precise accident the attach path exists to
/// avoid. One running backend was simultaneously fit to be used and unfit to be
/// used, on one field, because the two judgements were written apart.
///
/// So there is one question now, and both ask it. `None` means nothing here
/// stops a user working. `Some(reason)` names a fault that leaves nothing
/// working at all, in words fit to show someone: no database, or an
/// installation with no application files, which answers every route in the app
/// with a 404.
///
/// Everything else stays open on purpose, including a stale migration head and
/// a failed schema heal. This decides whether anyone may use the application at
/// all, so a missing field, a renamed field or a status word we do not know all
/// mean no fault. Only something the backend positively reports may hold a user
/// out of their own installation.
///
/// Takes the parsed body, not the text. What an unreadable body means differs
/// between the two callers and must keep differing: for one it is a stranger to
/// be refused, for the other it is the user's own backend to be trusted. That
/// asymmetry is deliberate, lives at each call site, and is not a bug to tidy.
fn blocking_fault(json: &serde_json::Value) -> Option<String> {
    let status = json.get("status").and_then(|v| v.as_str()).unwrap_or("");
    if status != "degraded" {
        return None;
    }

    let database_down = json
        .get("database")
        .and_then(|v| v.as_str())
        .map(|s| s != "ok")
        .unwrap_or(false);
    if database_down {
        return Some("the local database is not answering".to_string());
    }

    let frontend_missing = json
        .get("frontend_dist_present")
        .and_then(|v| v.as_bool())
        .map(|present| !present)
        .unwrap_or(false);
    if frontend_missing {
        return Some("this installation is missing the application files it serves".to_string());
    }

    None
}

/// Probe ``127.0.0.1:<port>/api/health`` and decide whether we may attach to it.
///
/// Returns ``true`` only when the responder is a backend of EXACTLY OUR version
/// with no fault that would stop us using it. Attaching to anything less is
/// dangerous: a stale dev backend of a different version (the founder-machine
/// case is a degraded v6.10.0 on :8000) would serve the desktop app the wrong
/// frontend and schema. So all of the following must hold, and every rejected
/// candidate is logged with its port, version and status so attach decisions
/// are auditable from the launcher log:
///   * HTTP 2xx, and a body that parses as JSON
///   * ``version`` equals our own ``CARGO_PKG_VERSION`` exactly
///   * ``blocking_fault`` names nothing
///
/// What is deliberately NOT checked here any more is bare ``status ==
/// "degraded"`` and ``alembic_head_matches``. Both rejected a backend that was
/// serving its users perfectly well, and the cost of rejecting was not "we look
/// elsewhere", it was "we start a second backend on the running one's data
/// directory". The founder-machine case that motivated the status check is
/// still rejected, on the check that actually described it: a v6.10.0 responder
/// is not our version. Version equality is what made the status test redundant.
///
/// One of those two has since been fixed at the source, and this note is here so
/// nobody reads the paragraph above as a permanent statement about the backend.
/// A head that trails the tree no longer degrades anything: the backend
/// publishes ``alembic_head_matches`` as a fact and degrades on the condition
/// that actually is a fault, a live schema that has drifted from the models,
/// which it reports separately as ``schema_matches_models``. So the shape that
/// made dropping the head test necessary is not one a current backend produces.
///
/// Neither test goes back in regardless. The launcher attaches to whatever is
/// already listening, and that can be an older build than the launcher itself,
/// so the old shape stays reachable for as long as any such install survives.
/// More to the point, the reason for dropping them was never only that the
/// backend was wrong: rejecting a healthy backend costs a second server on the
/// running one's data directory, and that price is paid whether the field that
/// triggered it was right or not. The fix upstream removes the occasion, not
/// the argument.
async fn is_our_backend_healthy(
    client: &reqwest::Client,
    port: u16,
    our_workspace: &str,
) -> bool {
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
    let our_version = env!("CARGO_PKG_VERSION");

    // Whose installation is this? Asked before anything else and answered with
    // its own return, because a backend belonging to another workspace is not a
    // candidate we found something wrong with, it is not a candidate at all.
    //
    // The Windows installer is per-machine and loopback there is not per
    // session, so every backend any account on this computer is running answers
    // on 127.0.0.1 to every other account. Each of those is our exact version -
    // it is the same installed program - so the version test below passes, we
    // attach, and the frontend bootstraps a desktop session against a backend
    // holding somebody else's database. That was the whole of the defect: not a
    // permissive endpoint, but a launcher pointing the window at a stranger.
    //
    // A candidate with no such field is an older build and is refused too. That
    // adds no occasion of two servers on one data directory, because a build old
    // enough to lack the field is old enough to fail the version test anyway.
    match workspace_id_of(&json) {
        Some(theirs) if theirs == our_workspace => {}
        Some(theirs) => {
            log_line(&format!(
                "attach: rejected candidate on port {port}: the backend there belongs to a different \
workspace (theirs {}..., ours {}...)",
                id_prefix(theirs),
                id_prefix(our_workspace)
            ));
            return false;
        }
        None => {
            log_line(&format!(
                "attach: rejected candidate on port {port}: the backend there does not say which \
workspace it belongs to"
            ));
            return false;
        }
    }

    let version_ok = version == our_version;
    let fault = blocking_fault(&json);

    if version_ok && fault.is_none() {
        log_line(&format!(
            "attach: accepted candidate on port {port}: status={status} version={version}"
        ));
        return true;
    }

    // Name the reason we actually consulted, and name both when both applied. A
    // log that reports a field the decision no longer reads is the same kind of
    // dishonesty as a health flag that reports false when it means unknown.
    let reason = match (version_ok, fault) {
        (false, Some(fault)) => format!("version mismatch, and {fault}"),
        (false, None) => "version mismatch".to_string(),
        (true, Some(fault)) => fault,
        // Not reachable today: this arm is the accepted case, which returned
        // above. It is written out rather than left as a panic because the only
        // thing downstream of it is a log line, and a launcher that aborts while
        // deciding which port to attach to is a worse outcome than a vague one.
        (true, None) => "no fault found".to_string(),
    };
    log_line(&format!(
        "attach: rejected candidate on port {port}: status={status:?} version={version:?} \
(ours={our_version}) reason={reason}"
    ));
    false
}

/// Scan the candidate ports for an existing healthy backend to attach to.
///
/// Returns the first port that responds as our backend, or ``None`` if none do
/// (the normal cold-start case, where we then spawn our own sidecar).
///
/// `our_workspace` is the identity of the data directory this launcher works
/// in, resolved once by the caller. It is passed in rather than read here so
/// that a launcher which cannot establish an identity at all never reaches this
/// function: with nothing to compare against there is no port it may attach to.
async fn find_existing_backend(client: &reqwest::Client, our_workspace: &str) -> Option<u16> {
    for port in ATTACH_CANDIDATE_PORTS {
        if is_our_backend_healthy(client, port, our_workspace).await {
            return Some(port);
        }
    }
    None
}

/// Where the application server this window will use is going to come from.
///
/// Startup used to answer that question without ever asking it. The loopback
/// probe and the sidecar spawn were one straight line inside `setup`: probe,
/// and if nothing answered, fall through and start a server. Deciding and
/// starting were the same code, so there was no point at which a different
/// answer could have been given, and no name for the thing being decided.
///
/// This type is that point. `resolve_backend_source` decides and returns; the
/// caller carries the decision out. A source that is neither of these is a
/// third variant and a third arm at the call site, and nothing else in `setup`
/// changes shape to admit it.
///
/// Every variant carries the base URL the webview will be sent to, so the
/// address is built once, where the decision is made, instead of being
/// re-derived by whoever acts on it. `port` rides alongside because a loopback
/// server is addressed by port everywhere else in this file: `wait_for_backend`,
/// `watch_backend_liveness` and the clean-shutdown request are all port-typed.
/// A source that is not on loopback would carry no port and would not use them.
enum BackendSource {
    /// A server is already running and needs nothing started; use it as it is.
    AlreadyRunning { base_url: String, port: u16 },
    /// Nothing suitable is running, so this launcher starts one itself.
    StartLocally { base_url: String, port: u16 },
    /// A server somewhere else, named by a setting, an environment variable or
    /// a file an administrator deployed.
    ///
    /// The third answer this type was shaped to admit. It carries no port,
    /// exactly as the doc comment above predicted a non-loopback source would:
    /// the port-typed helpers cannot describe it, and everything that touches
    /// it works from the base URL instead.
    Remote {
        base_url: String,
        source: server_config::ChoiceSource,
    },
    /// Somebody named a server address that cannot be used, so nothing is
    /// started and nothing is contacted.
    ///
    /// Not an error state that the resolver stumbled into; it is an answer, and
    /// the point of returning it as one is that the failure screen can then say
    /// which of the four places the bad address came from. Falling back to a
    /// local start here would be worse than failing: it would open a working
    /// window onto the wrong, empty database and say nothing.
    Refused {
        source: server_config::ChoiceSource,
        raw: String,
        problem: server_config::UrlProblem,
    },
}

/// Decide where this launcher's application server comes from. Starts nothing.
///
/// `local_port` is the port a locally started server would bind, chosen before
/// the Tauri builder ran so that the choice is logged on every run whether or
/// not it ends up being used.
///
/// Attach to an existing healthy backend instead of booting a second one.
///
/// If a developer backend or a CLI `openconstructionerp serve` is already
/// running on this machine, it already owns the embedded PostgreSQL cluster at
/// ~/.openestimate/pgdata. Spawning our own sidecar against the SAME default
/// data dir makes two processes share one cluster; when the desktop app later
/// exits it tells pixeltable-pgserver to clean up, which can stop the postmaster
/// out from under the still-running developer backend. Attaching instead is both
/// safer and faster (no second boot, no second cluster handle). We only attach
/// to a server that self-identifies as ours.
///
/// The probe is short (four ports, 1.5s each at worst, only while they are
/// actually open) and is run to completion here so the decision is made BEFORE
/// anything is started -- otherwise a concurrent probe would race the spawn and
/// we could end up with two backends anyway. block_on is safe: `setup()` already
/// runs on the Tauri async runtime's worker, and the probe never blocks
/// indefinitely.
fn resolve_backend_source(local_port: u16) -> BackendSource {
    // Ask first whether anybody has said where the server should come from.
    // This runs before the loopback probe on purpose: a machine pointed at the
    // office server has no business attaching to whatever happens to be
    // listening on 127.0.0.1, and probing first would let a stray developer
    // backend quietly win against an administrator's deployed configuration.
    match server_config::resolve() {
        server_config::Resolution::Remote { url, source } => {
            log_line(&format!(
                "using the server at {url}, configured in {}",
                source.describe()
            ));
            return BackendSource::Remote {
                base_url: url,
                source,
            };
        }
        server_config::Resolution::Refused {
            source,
            raw,
            problem,
        } => {
            log_line(&format!(
                "refusing to start: the server address \"{raw}\" from {} cannot be used: {}",
                source.describe(),
                problem.message()
            ));
            return BackendSource::Refused {
                source,
                raw,
                problem,
            };
        }
        server_config::Resolution::Local { source } => {
            // The default path, and the one almost every install takes. Only
            // logged when somebody actually chose it, so an ordinary start
            // keeps the log it has always had.
            if source != server_config::ChoiceSource::Default {
                log_line(&format!(
                    "starting a server on this computer, as configured in {}",
                    source.describe()
                ));
            }
        }
    }

    // Establish who we are before asking who is listening. A launcher with no
    // identity of its own has nothing to compare a candidate against, so it
    // probes nothing and starts its own server, which is the answer it would
    // have reached anyway on a machine with no backend running.
    let attached_port = match our_workspace_id() {
        Some(our_workspace) => tauri::async_runtime::block_on(async {
            let client = reqwest::Client::new();
            find_existing_backend(&client, &our_workspace).await
        }),
        None => {
            log_line(
                "attach: this installation has no workspace identity, so no running backend can be \
recognised as its own; starting a server instead",
            );
            None
        }
    };

    match attached_port {
        Some(existing) => {
            log_line(&format!(
                "found an existing OpenConstructionERP backend on port {existing}; attaching instead of starting a second one"
            ));
            BackendSource::AlreadyRunning {
                base_url: format!("http://127.0.0.1:{existing}/"),
                port: existing,
            }
        }
        None => {
            log_line("no existing backend found; starting our own sidecar");
            BackendSource::StartLocally {
                base_url: format!("http://127.0.0.1:{local_port}/"),
                port: local_port,
            }
        }
    }
}

/// What one health answer said about the backend.
enum HealthProbe {
    /// No usable answer: nothing listening yet, no reply in time, or a non-2xx.
    Unreachable,
    /// Fit to open the application against.
    Ready,
    /// Answered, and named a fault that makes the application unusable.
    Broken(String),
}

/// The outcome of waiting for the backend to become ready.
enum StartupOutcome {
    Ready,
    /// The backend is up and says it cannot do its job; carries the reason.
    Broken(String),
    /// The wait gave up; carries which of the two limits ran out.
    TimedOut(TimeoutKind),
}

/// Why the startup wait gave up.
enum TimeoutKind {
    /// The backend went quiet: nothing on stdout or stderr for a long time,
    /// which means the step it was on is not progressing.
    WentQuiet(Duration),
    /// The backend kept talking and still never became ready, so the absolute
    /// ceiling ran out.
    TookTooLong,
}

/// What the sidecar's output pump knows about the backend's progress.
///
/// Two different facts, deliberately kept apart:
///
/// * `last_output` moves on ANY line the sidecar writes. It answers "is this
///   backend still doing something", which is the question a timeout should
///   actually ask. Reading only STAGE markers would not answer it - migrations,
///   the module load and first-run seeding emit no markers at all, and a
///   recovering database emits one and then works in silence.
/// * `last_stage` remembers WHICH step the backend last named, so that when the
///   wait does give up it can say what the backend was busy with instead of
///   only that it was slow.
#[derive(Clone)]
struct BootProgress {
    last_output: Arc<Mutex<Instant>>,
    last_stage: Arc<Mutex<Option<(String, String)>>>,
}

impl BootProgress {
    fn new() -> Self {
        Self {
            last_output: Arc::new(Mutex::new(Instant::now())),
            last_stage: Arc::new(Mutex::new(None)),
        }
    }

    /// Record that the sidecar wrote something, whatever it was.
    fn saw_output(&self) {
        if let Ok(mut slot) = self.last_output.lock() {
            *slot = Instant::now();
        }
    }

    /// Record the boot step the sidecar just named, with its detail text.
    fn saw_stage(&self, id: &str, detail: &str) {
        if let Ok(mut slot) = self.last_stage.lock() {
            *slot = Some((id.to_string(), detail.to_string()));
        }
    }

    /// How long the sidecar has said nothing at all.
    ///
    /// A poisoned lock reports zero rather than a huge silence: the timeout
    /// this feeds must never fire because a mutex broke.
    fn quiet_for(&self) -> Duration {
        self.last_output
            .lock()
            .map(|slot| slot.elapsed())
            .unwrap_or_else(|_| Duration::from_secs(0))
    }

    /// The last step the sidecar named, if it named one.
    fn stage(&self) -> Option<(String, String)> {
        self.last_stage.lock().ok().and_then(|slot| slot.clone())
    }
}

/// How long one health probe may take before it counts as no answer.
///
/// Without a per-request bound a backend that accepts the connection and then
/// never answers holds the poll open forever. The deadline below is only tested
/// between polls, so that single hung request outlived the entire startup
/// window: the user waited on the spinner with no timeout message ever shown,
/// because the code that would have shown it never got another turn.
///
/// Generous on purpose. The bound exists to stop one request holding the loop,
/// not to judge how quick the backend is, and this endpoint does real work: a
/// database round trip, a walk of the whole Alembic version tree and a process
/// memory reading. A tight bound would turn a slow first answer on a cold disk
/// into a startup timeout, which is the same lie in the other direction. At
/// twelve seconds there are still dozens of polls inside the startup window.
const HEALTH_PROBE_TIMEOUT: Duration = Duration::from_secs(12);

/// How long the backend may keep reporting a fault that makes it unusable
/// before we stop waiting for it to sort itself out and say so. Startup states
/// clear in seconds; a fault still standing after this is the real state.
const DEGRADED_GRACE: Duration = Duration::from_secs(30);

/// Judge one health body, and fail OPEN.
///
/// The health endpoint answers 200 whether it is healthy or degraded, and the
/// old check read only the status code. So a backend that had answered
/// "degraded, database: error" was treated as ready, the webview was pointed at
/// it, and the user got the application shell with every request inside it
/// failing and nothing to say why. The two faults tested here are the ones that
/// leave nothing working: no database, and an installation with no application
/// files to serve, which answers every route in the app with a 404.
///
/// Everything else stays open on purpose. This function decides whether anyone
/// can start the app at all, so an unreadable body, a missing field, a renamed
/// field or a status word we do not know all mean ready. Only a fault the
/// backend positively reports may hold a user out of their own installation,
/// and stale migrations do not qualify: that is a real problem, and it is one
/// the user can still see and act on from inside the app.
///
/// The fault test itself is `blocking_fault`, shared with the attach probe so
/// the two cannot drift apart again. Only the unreadable-body case is decided
/// here, and it stays decided here: this is the user's own backend, so a body
/// we cannot parse means open the app. The attach probe reaches the opposite
/// conclusion on the same input, because there the responder is a stranger.
fn judge_health(body: &str) -> HealthProbe {
    let json: serde_json::Value = match serde_json::from_str(body) {
        Ok(v) => v,
        Err(_) => return HealthProbe::Ready,
    };

    match blocking_fault(&json) {
        Some(reason) => HealthProbe::Broken(reason),
        None => HealthProbe::Ready,
    }
}

/// How long the backend may say nothing at all before the wait gives up.
///
/// The wait used to decide on elapsed time alone, so a backend that had
/// reported progress one second ago was still abandoned the moment the window
/// closed - and the window has to be long enough for the slowest legitimate
/// start, which is why it was twenty minutes. Silence is the better signal: a
/// sidecar that is working writes to its log, and one that is wedged does not.
///
/// Four minutes, and not less, because some legitimate steps are quiet for a
/// while: a single long migration, or first-run demo seeding on a slow disk.
/// Crash recovery, the longest quiet step there was, now reports itself every
/// fifteen seconds (`_RECOVERY_HEARTBEAT_SECONDS` in `app/core/embedded_pg.py`),
/// so the backend that this limit abandons is one that really has stopped.
/// Abandoning a working backend is strictly worse than waiting longer for a
/// broken one, so when in doubt this number goes up, not down.
const STARTUP_QUIET_TIMEOUT: Duration = Duration::from_secs(240);

/// Wait for the backend to become fit to open.
///
/// Polls `/api/health` every ~500ms until it is ready, reports a standing fault,
/// runs out of patience with a backend that has gone quiet, or reaches the
/// absolute ceiling. While waiting, updates the splash screen so the user sees
/// progress; first-run embedded-PostgreSQL setup can be slow.
async fn wait_for_backend(
    handle: &tauri::AppHandle,
    port: u16,
    timeout_secs: u64,
    progress: &BootProgress,
) -> StartupOutcome {
    let client = reqwest::Client::new();
    let url = format!("http://127.0.0.1:{port}/api/health");
    let start = Instant::now();
    let mut progress_shown = false;
    let mut broken_since: Option<Instant> = None;
    let mut broken_logged = false;

    while start.elapsed().as_secs() < timeout_secs {
        // Checked before the probe, so a backend that has gone quiet is given
        // up on at the quiet limit rather than one poll later.
        let quiet_for = progress.quiet_for();
        if quiet_for >= STARTUP_QUIET_TIMEOUT {
            return StartupOutcome::TimedOut(TimeoutKind::WentQuiet(quiet_for));
        }

        let probe = match client.get(&url).timeout(HEALTH_PROBE_TIMEOUT).send().await {
            Ok(resp) if resp.status().is_success() => match resp.text().await {
                Ok(body) => judge_health(&body),
                // The status line arrived and the body did not. Something is
                // serving; do not hold the user out over a lost read.
                Err(_) => HealthProbe::Ready,
            },
            _ => HealthProbe::Unreachable,
        };

        match probe {
            HealthProbe::Ready => return StartupOutcome::Ready,
            HealthProbe::Broken(reason) => {
                if !broken_logged {
                    broken_logged = true;
                    log_line(&format!("backend answered but reports a fatal fault: {reason}"));
                }
                let since = *broken_since.get_or_insert_with(Instant::now);
                if since.elapsed() >= DEGRADED_GRACE {
                    return StartupOutcome::Broken(reason);
                }
            }
            HealthProbe::Unreachable => {
                // A backend that has stopped answering is starting or dying,
                // not degraded, so an earlier degraded reading must not be held
                // against the next one.
                broken_since = None;
                broken_logged = false;
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
    StartupOutcome::TimedOut(TimeoutKind::TookTooLong)
}

/// A fresh secret for the backend's shutdown endpoint, one per run of the app.
///
/// Two v4 UUIDs, because one is 122 bits of randomness and two are cheap. The
/// value only ever travels between this process and the backend it starts, so
/// there is nothing to rotate and nothing to store: a new run gets a new token,
/// and the backend from the previous run - if one somehow outlived us - will
/// not accept it, which is the correct answer, because that backend is not ours
/// to stop.
fn new_shutdown_token() -> String {
    format!(
        "{}{}",
        uuid::Uuid::new_v4().simple(),
        uuid::Uuid::new_v4().simple()
    )
}

/// The message shown when the backend never became ready.
///
/// Names the step it was on. "The application backend did not start in time"
/// told a user only that they had waited, which is the one thing they already
/// knew; the launcher has always known which step the backend last reported and
/// simply did not say it.
fn startup_timeout_message(stage: Option<&(String, String)>, kind: &TimeoutKind) -> String {
    let tail = "Please close this window and try again. If the problem persists, please send the \
log file to info@datadrivenconstruction.io.";

    let Some((id, detail)) = stage else {
        // Nothing was ever reported, so there is no step to name and the old
        // wording is still the honest one.
        return format!("The application backend did not start in time. {tail}");
    };

    let step = describe_stage(id);
    let note = if detail.is_empty() {
        String::new()
    } else {
        format!(" The last thing it reported was: {detail}.")
    };

    match kind {
        TimeoutKind::WentQuiet(quiet_for) => format!(
            "The application backend stopped responding while {step}. It has reported nothing \
for {} minutes.{note} {tail}",
            quiet_for.as_secs() / 60
        ),
        TimeoutKind::TookTooLong => format!(
            "The application backend is still {step} and did not finish in time.{note} {tail}"
        ),
    }
}

/// Turn a boot-stage id into something a person can read.
///
/// Only ids the sidecar itself reports can reach this, so the launcher's own
/// checklist ids are not listed: an id with no words of its own would be
/// indistinguishable from the fallback, which is the very failure this exists
/// to fix.
fn describe_stage(id: &str) -> &'static str {
    match id {
        "sidecar" => "starting its backend component",
        "pg" => "preparing the local database",
        "migrate" => "updating the local database",
        "model" => "installing the semantic search model",
        "server" => "starting the application server",
        "open" => "opening the application",
        _ => "starting up",
    }
}

/// Use a server that is already running: mark the checklist complete and open
/// the app against it.
///
/// Nothing is started here. This is one of the two things `setup` can do with
/// a `BackendSource`, and it is the arm that does the least: the server exists,
/// so all that is left is to say so and navigate to it.
fn attach_to_running_backend(
    handle: tauri::AppHandle,
    base_url: String,
    port: u16,
    shutting_down: Arc<AtomicBool>,
    backend_lost: Arc<AtomicBool>,
) {
    boot_stage(&handle, "sidecar", "done", "Found a running backend");
    boot_stage(&handle, "pg", "done", "");
    boot_stage(&handle, "migrate", "done", "");
    boot_stage(&handle, "server", "done", "");
    boot_stage(&handle, "open", "done", "Ready");
    let url = base_url;
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
        update_check::note_app_started(&handle_nav, env!("CARGO_PKG_VERSION"));
    });
    // We did not spawn a sidecar, so there is no child to manage.
    // That is exactly why the liveness watch matters most here: the
    // backend belongs to another process, nothing reports its exit
    // to us, and without this its death would leave the window
    // showing an application that no longer has a server.
    tauri::async_runtime::spawn(watch_backend_liveness(
        handle.clone(),
        format!("http://127.0.0.1:{port}/api/health"),
        LOCAL_BACKEND_LOST_DETAIL.to_string(),
        shutting_down.clone(),
        backend_lost.clone(),
    ));
}

/// How long to give a configured remote server to answer before saying it did
/// not.
///
/// Longer than the loopback attach probe's 1.5 seconds, because this one is
/// crossing a network that may be a site office on a slow uplink, and shorter
/// than the local startup budget, because there is nothing to wait for here: a
/// server that is up answers a health check immediately, and one that is not is
/// not going to become up while we hold a blank window in front of somebody.
const REMOTE_PROBE_TIMEOUT: Duration = Duration::from_secs(10);

/// Ask a configured remote server whether it is there and ready.
///
/// Returns the reason it is not, in a sentence, rather than a bool. The whole
/// point of this path is that the user is told which server was tried and why
/// it did not work, and a bool would throw away the half of that which they
/// cannot guess.
///
/// Deliberately more forgiving than `is_our_backend_healthy`, which is the
/// probe used to decide whether to ATTACH to something nobody asked about. That
/// one may reject on a doubt, because the cost of being wrong is starting a
/// second server. Here a person has named this server on purpose, so the only
/// question is whether it answers; refusing it over an unrecognised health
/// field would be overruling an explicit instruction on a technicality.
async fn probe_remote_backend(base_url: &str) -> Result<Option<String>, String> {
    let url = format!("{base_url}api/health");
    let client = reqwest::Client::new();
    let resp = match client.get(&url).timeout(REMOTE_PROBE_TIMEOUT).send().await {
        Ok(resp) => resp,
        Err(e) if e.is_timeout() => {
            return Err(format!(
                "It did not answer within {} seconds. The server may be switched off, or a \
firewall may be blocking the connection.",
                REMOTE_PROBE_TIMEOUT.as_secs()
            ))
        }
        Err(e) if e.is_connect() => {
            return Err(
                "This computer could not connect to it. Check the address, and check that the \
server is running and reachable from here."
                    .to_string(),
            )
        }
        Err(e) => return Err(format!("The connection failed: {e}.")),
    };

    let status = resp.status();
    if status.is_success() {
        // Read the version out of the body, and never fail on it. The question
        // this probe answers is whether the server is there; a health body that
        // will not parse, or one from a build too old to publish a version, is
        // not a reason to refuse an address a person typed in on purpose.
        let version = resp
            .text()
            .await
            .ok()
            .and_then(|body| serde_json::from_str::<serde_json::Value>(&body).ok())
            .and_then(|json| {
                json.get("version")
                    .and_then(|v| v.as_str())
                    .map(|v| v.to_string())
            });
        return Ok(version);
    }
    if status.as_u16() == 404 {
        // Something is listening and it is not us. Worth its own sentence,
        // because the address is almost right and the user is about to stare at
        // it looking for a typo that is not there.
        return Err(
            "Something answered at that address, but it is not an OpenConstructionERP server. \
Check that the address is complete, including any folder the server is published under."
                .to_string(),
        );
    }
    Err(format!(
        "It answered with HTTP {}. The server is reachable but is not ready to serve the \
application.",
        status.as_u16()
    ))
}

/// The sentence to show when a named server and this build are far enough
/// apart to matter, or `None` when they are not.
///
/// Deliberately NOT the equality test `is_our_backend_healthy` uses, and the
/// difference is a decision rather than an omission. That test decides whether
/// to attach to something NOBODY ASKED ABOUT, where the cost of being wrong is
/// a second server started on the running one's data directory, so it may
/// reject on a doubt. Here a person named this server on purpose, and the
/// deployment this whole mode exists for is an office whose desks update on
/// their own schedule: an equality gate would lock a fleet out of its own ERP
/// on the morning after the server was upgraded, which is a worse outage than
/// anything it would prevent.
///
/// There is still something real to warn about, which is why this is not simply
/// dropped. In remote mode the webview loads the FRONTEND from the server, and
/// that frontend talks to THIS shell over Tauri IPC. Across a major version the
/// two are not promised to offer the same commands, so a feature can fail with
/// nothing on screen to say why. A major difference is worth a sentence. A
/// minor or a patch difference is the normal state of a fleet and gets none.
///
/// A server that reports no version at all gets none either. That is an older
/// build, not a mismatched one, and guessing would put a warning on the one
/// case where there is no evidence.
fn remote_version_note(ours: &str, theirs: Option<&str>) -> Option<String> {
    let theirs = theirs?;
    let major = |v: &str| v.split('.').next()?.parse::<u32>().ok();
    let (ours_major, theirs_major) = (major(ours)?, major(theirs)?);
    if ours_major == theirs_major {
        return None;
    }
    Some(format!(
        "This desktop application is version {ours} and the server is version {theirs}. \
They are a major version apart, so anything that needs the desktop application itself may \
not work until the older of the two is updated."
    ))
}

/// Use a server somewhere else: check it is there, then open the app against
/// it.
///
/// The third arm of `BackendSource`, and the only one that can fail before
/// anything is on screen. What it must never do is navigate to an address it
/// has not checked: a webview pointed at an unreachable host shows a blank
/// window with no way back, and a blank window is worse than never having had
/// the feature.
fn attach_to_remote_backend(
    handle: tauri::AppHandle,
    base_url: String,
    source: server_config::ChoiceSource,
    shutting_down: Arc<AtomicBool>,
    backend_lost: Arc<AtomicBool>,
) {
    boot_stage(&handle, "sidecar", "done", "Using a server on the network");
    boot_stage(&handle, "pg", "done", "");
    boot_stage(&handle, "migrate", "done", "");
    boot_stage(
        &handle,
        "server",
        "active",
        &format!("Contacting {base_url}"),
    );

    tauri::async_runtime::spawn(async move {
        let their_version = match probe_remote_backend(&base_url).await {
            Ok(version) => version,
            Err(reason) => {
                report_remote_unreachable(&handle, &base_url, source, &reason);
                return;
            }
        };

        // Logged whether or not it is a problem. Both versions are the first
        // two facts anybody answering a support report has to establish, and
        // in remote mode neither is visible from the machine that failed.
        let ours = env!("CARGO_PKG_VERSION");
        log_line(&format!(
            "remote: {base_url} answered, server version {}, desktop version {ours}",
            their_version.as_deref().unwrap_or("not reported")
        ));
        let note = remote_version_note(ours, their_version.as_deref());
        if let Some(note) = note.as_deref() {
            log_line(&format!("remote: {note}"));
        }

        boot_stage(&handle, "server", "done", note.as_deref().unwrap_or(""));
        boot_stage(&handle, "open", "done", "Ready");
        set_app_url(&handle, &base_url);

        // Same 400ms as the loopback attach path, and for the same reason: the
        // splash script needs a moment to finish loading before it can be
        // asked to offer the launch choice.
        tokio::time::sleep(std::time::Duration::from_millis(400)).await;
        if let Some(window) = handle.get_webview_window("main") {
            let _ = window.show();
            let _ = window.set_focus();
            let url_js = js_escape(&base_url);
            let _ = window.eval(&format!(
                "(function(){{if(typeof offerLaunchChoice==='function'){{\
                    offerLaunchChoice('{url_js}');}}\
                    else{{window.location.replace('{url_js}');}}}})()"
            ));
        }
        update_check::note_app_started(&handle, env!("CARGO_PKG_VERSION"));

        // No child process and no port, so nothing anywhere reports this
        // server going away. On a network it is likelier to go away than a
        // loopback one, not less.
        tauri::async_runtime::spawn(watch_backend_liveness(
            handle.clone(),
            format!("{base_url}api/health"),
            remote_backend_lost_detail(&base_url),
            shutting_down,
            backend_lost,
        ));
    });
}

/// Tell the user which server was tried, why it did not work, and how to get
/// out of it.
///
/// The third sentence is the one that matters. A desktop application that opens
/// to a blank window because an address is wrong has no way out that does not
/// involve finding a file, and the people most likely to hit this are the least
/// likely to know which file. So every message on this path ends by naming the
/// button on this very screen that starts a server on this computer instead.
fn report_remote_unreachable(
    handle: &tauri::AppHandle,
    base_url: &str,
    source: server_config::ChoiceSource,
    reason: &str,
) {
    let message = format!(
        "Could not reach the OpenConstructionERP server at {base_url}, which is configured in \
{}. {reason} Use the button below to run a server on this computer instead.",
        source.describe()
    );
    report_fatal_stage(handle, "server", &message);
    offer_local_fallback(handle);
}

/// Put the way back to a local start on the failure screen.
///
/// Kept separate from the message so that adding a second failure path later
/// cannot accidentally ship without the button. This is the whole of the
/// promise that a user never has to edit a file to recover.
fn offer_local_fallback(handle: &tauri::AppHandle) {
    eval_in_splash(
        handle,
        "(function(){if(typeof offerLocalFallback==='function'){offerLocalFallback();}})()"
            .to_string(),
    );
}

// ---------------------------------------------------------------------------
// Temporary-folder housekeeping for the one-file sidecar.
//
// The shipped sidecar is a PyInstaller one-file bundle (desktop/pyinstaller.spec),
// so every start unpacks the whole program into a fresh `_MEI` directory: numpy,
// OpenCV, torch, sentence-transformers and a complete embedded PostgreSQL
// install. The bootloader removes that directory again when its process exits
// normally, and only then. `stop_backend` ends in a forced stop of the process
// tree whenever the clean stop is refused or times out, and a killed bootloader
// removes nothing, so every forced stop leaves a full extraction behind with
// nobody left to clear it.
//
// The launcher log from one reported machine names 84 of them over two and a
// half months, fifteen of its stops ended in the forced stop, and it had
// already logged "[Errno 28] No space left on device" eleven days before it
// stopped starting at all. What it showed the user in the end was the
// bootloader failing to decompress, which names nothing anybody can act on.
//
// So the launcher clears up after itself here, before it starts a sidecar, and
// refuses to start one at all when there is demonstrably no room to unpack it.
//
// Everything below is scoped to a directory this application owns, and that
// scoping is what makes it defensible rather than merely careful. `_MEI` is
// PyInstaller's prefix for every program built with it, so in the system
// temporary folder the sweep would be judging other vendors' abandoned
// directories, and the three guards it applies answer whether a directory is in
// use, which is a different question from whether it is ours to remove. The spec
// therefore unpacks into `EXTRACTION_ROOT_SPEC_LITERAL` and the sweep looks
// nowhere else. Extractions left in `%TEMP%` by a version built before that
// change are not swept and not counted; they stay until somebody deletes them.
// ---------------------------------------------------------------------------

/// Prefix the one-file bootloader gives every directory it unpacks into.
const EXTRACTION_PREFIX: &str = "_MEI";

/// The directory the sidecar unpacks itself into, exactly as the spec bakes it.
///
/// Paired with `runtime_tmpdir` in `desktop/pyinstaller.spec`, which writes this
/// same string into the executable's options, and with a test that reads that
/// file and fails when the two stop matching. Two copies of a path in two
/// languages is not something a comment can hold together: if the launcher swept
/// somewhere the bootloader does not unpack, the sweep would silently do nothing
/// forever, and nothing else in the system would notice.
///
/// It is a Windows path carrying a Windows environment variable because Windows
/// is the only platform whose bootloader expands one. See the spec for why POSIX
/// keeps the system temporary folder instead.
const EXTRACTION_ROOT_SPEC_LITERAL: &str = r"%LOCALAPPDATA%\OpenConstructionERP\extract";

/// How long a directory must have been untouched before the sweep considers it.
///
/// The cheapest of the guards and the weakest: it says nothing about whether
/// anything is using a directory, only that whatever wrote it stopped writing a
/// while ago. It is here to keep the rest of the sweep away from an extraction
/// that a second copy of the application is unpacking right now, whose files are
/// being written while we look at them.
const EXTRACTION_MINIMUM_AGE: Duration = Duration::from_secs(60 * 60);

/// How long the whole sweep may run before it leaves the rest for next time.
///
/// Removing one extraction means removing thousands of files, and the log this
/// was written from names 84 of them, so a sweep that insisted on finishing
/// would hold the backend back for minutes. This is real time a user waits on a
/// machine that has something to clear, which is why it is bounded at all;
/// whatever is left is still there next time, and every start makes it smaller.
const EXTRACTION_SWEEP_BUDGET: Duration = Duration::from_secs(90);

/// Most files the sweep will look at inside one directory before giving up.
///
/// Not a performance guard so much as a refusal to answer a question we did not
/// ask. A bundle this size unpacks to something on the order of ten thousand
/// files, and a directory holding vastly more than that is not the shape we
/// recognise. The safe answer for a shape we do not recognise is to leave it.
const EXTRACTION_FILE_CAP: usize = 60_000;

/// Roughly what one extraction costs on disk.
///
/// An estimate, and stated as one. The measured input is the shipped sidecar,
/// 577,686,860 bytes of compressed archive in `desktop/src-tauri/binaries`; what
/// it unpacks to is some multiple of that which nothing here measures. It is
/// used to tell a user what the application is about to need, never to decide
/// anything.
const EXTRACTION_ESTIMATED_BYTES: u64 = 3 * 1024 * 1024 * 1024 / 2;

/// Free space below which unpacking the sidecar cannot possibly succeed.
///
/// Deliberately far below what an extraction actually costs. Refusing to spawn
/// is a new way for this launcher to stop a machine that would have worked, so
/// the number that triggers a refusal has to be one where failure is certain
/// rather than likely: the compressed archive alone is over 550 MB, and the
/// bootloader writes more than that. Everything between here and
/// `EXTRACTION_SPACE_COMFORT` is reported to the log and started anyway.
const EXTRACTION_SPACE_FLOOR: u64 = 512 * 1024 * 1024;

/// Free space below which the sweep and the log have something to say.
///
/// One extraction plus the room the embedded database wants for a checkpoint.
/// Above this nothing is said at all.
const EXTRACTION_SPACE_COMFORT: u64 = 3 * 1024 * 1024 * 1024;

/// Expand `%NAME%` the way the Windows bootloader will expand it.
///
/// Pure, with the environment handed in, so the rule can be driven from a test
/// without one. All or nothing on purpose: a name that is unset or empty gives
/// no path at all rather than a half expanded one. Windows itself leaves an
/// unknown `%NAME%` standing in the string, which would have the bootloader
/// create a directory literally called `%LOCALAPPDATA%` beside itself, and a
/// launcher that swept that name would be inventing a folder rather than finding
/// one. Nothing we cannot resolve is anything we should touch.
fn expand_windows_env(literal: &str, lookup: &dyn Fn(&str) -> Option<String>) -> Option<String> {
    let parts: Vec<&str> = literal.split('%').collect();
    // Balanced markers split into an odd number of parts: text, name, text, and
    // so on. An even count means one `%` is unpaired.
    if parts.len() % 2 == 0 {
        return None;
    }

    let mut out = String::new();
    for (index, part) in parts.iter().enumerate() {
        if index % 2 == 0 {
            out.push_str(part);
            continue;
        }
        let value = lookup(part)?;
        if value.trim().is_empty() {
            return None;
        }
        out.push_str(&value);
    }
    Some(out)
}

/// The extraction root on this machine, if it can be resolved at all.
///
/// `None` is not a failure to report, it is an instruction to leave the disk
/// alone: the sweep skips and the space check measures nothing.
fn extraction_root() -> Option<PathBuf> {
    if !cfg!(target_os = "windows") {
        return None;
    }
    expand_windows_env(EXTRACTION_ROOT_SPEC_LITERAL, &|name| {
        std::env::var(name).ok()
    })
    .map(PathBuf::from)
}

/// Where this build's sidecar will unpack itself, for anything that only needs
/// to measure or to name the place.
///
/// The same directory the sweep works in on Windows. On POSIX the spec leaves
/// the choice to the bootloader, which is the system temporary folder, so that
/// is what gets measured and named there.
fn extraction_dir() -> Option<PathBuf> {
    if cfg!(target_os = "windows") {
        extraction_root()
    } else {
        Some(std::env::temp_dir())
    }
}

/// Create the extraction root before anybody asks a question about it.
///
/// The bootloader creates it on its own, including a missing parent chain, which
/// was measured rather than assumed. This exists for the measurement that
/// happens first: `GetDiskFreeSpaceExW` needs a directory that is already there,
/// so on a machine that has never started this version the free-space check
/// would otherwise measure nothing, decline to refuse anything, and be exactly
/// as useful as not having been written. Failure is logged and not acted on;
/// the sidecar may still be able to create it.
fn ensure_extraction_root(dir: &std::path::Path) {
    if let Err(e) = std::fs::create_dir_all(dir) {
        log_line(&format!(
            "extraction folder: could not create {}: {e}",
            dir.display()
        ));
    }
}

/// One entry of the extraction root, as the sweep sees it.
///
/// Holds no path and no handle, so the rule below can be driven from a
/// fabricated listing in a test rather than from a temporary folder full of
/// real extractions.
#[derive(Debug, Clone)]
struct TempEntry {
    /// The file name, not the path.
    name: String,
    is_dir: bool,
    /// How long ago it was last written to, or None when that cannot be read.
    age: Option<Duration>,
    /// Whether some process still holds a file inside it open.
    ///
    /// False before the probe has run, which is why a listing on its own can
    /// only ever produce a Keep. The driver asks the rule twice: once with what
    /// the listing said, to find out whether the probe is worth paying for, and
    /// once with what the probe found.
    in_use: bool,
}

/// What the sweep decided about one entry, and why.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum SweepVerdict {
    Remove,
    /// Not a file the one-file bootloader made, or not a directory at all.
    KeepNotAnExtraction,
    /// Young enough that a start happening right now could own it.
    KeepTooYoung,
    /// Its age could not be read, so nothing is known about it.
    KeepAgeUnknown,
    /// A live process holds a file inside it open.
    KeepInUse,
}

/// Decide the fate of one entry of the temporary folder.
///
/// The whole rule, and pure, so the interesting cases can be written down as
/// data. Note that the order is not decorative: everything cheap is asked first,
/// because a temporary folder holds hundreds of entries that have nothing to do
/// with us and walking one of them to answer a question the name already
/// answered would be the slowest possible way to say no.
fn sweep_verdict(entry: &TempEntry, minimum_age: Duration) -> SweepVerdict {
    if !entry.is_dir || !is_extraction_name(&entry.name) {
        return SweepVerdict::KeepNotAnExtraction;
    }
    match entry.age {
        None => return SweepVerdict::KeepAgeUnknown,
        Some(age) if age < minimum_age => return SweepVerdict::KeepTooYoung,
        Some(_) => {}
    }
    if entry.in_use {
        return SweepVerdict::KeepInUse;
    }
    SweepVerdict::Remove
}

/// `_MEI` followed by whatever the bootloader generated after it.
///
/// Nothing is read out of the suffix. On the machine this was written for it
/// looks like a process id (`_MEI195482`) and it is not one: the bootloader
/// generates it, and a process id would be reusable anyway, so the directory of
/// a live process and the directory of a dead one are the same kind of string.
/// The name says only that a PyInstaller bundle made this, which is why it is a
/// filter here and never the guard.
fn is_extraction_name(name: &str) -> bool {
    match name.strip_prefix(EXTRACTION_PREFIX) {
        Some(rest) => !rest.is_empty() && rest.chars().all(|c| c.is_ascii_alphanumeric()),
        None => false,
    }
}

/// What one walk of an extraction directory found.
struct ExtractionScan {
    /// Total size of every file below it, for the log line.
    bytes: u64,
    files: usize,
    /// The files a process still running out of this directory would be holding
    /// open: its executables, its libraries and its Python extension modules.
    /// Executables first, because the one that matters here is a postmaster.
    images: Vec<PathBuf>,
    /// True when the walk stopped early, so every other field is incomplete.
    truncated: bool,
}

/// Walk one extraction directory, without following anything out of it.
fn scan_extraction(dir: &std::path::Path, cap: usize) -> ExtractionScan {
    let mut scan = ExtractionScan {
        bytes: 0,
        files: 0,
        images: Vec::new(),
        truncated: false,
    };
    let mut stack = vec![dir.to_path_buf()];

    while let Some(current) = stack.pop() {
        let entries = match std::fs::read_dir(&current) {
            Ok(entries) => entries,
            // A directory we cannot even list is one we do not understand.
            Err(_) => {
                scan.truncated = true;
                continue;
            }
        };
        for entry in entries.flatten() {
            if scan.files >= cap {
                scan.truncated = true;
                return scan;
            }
            let file_type = match entry.file_type() {
                Ok(file_type) => file_type,
                Err(_) => {
                    scan.truncated = true;
                    continue;
                }
            };
            // Symlinks are counted and never followed: what one points at lives
            // somewhere else and is not ours to remove or to judge.
            if file_type.is_symlink() {
                scan.files += 1;
                continue;
            }
            if file_type.is_dir() {
                stack.push(entry.path());
                continue;
            }
            scan.files += 1;
            if let Ok(meta) = entry.metadata() {
                scan.bytes += meta.len();
            }
            let path = entry.path();
            if image_rank(&path).is_some() {
                scan.images.push(path);
            }
        }
    }

    scan.images.sort_by_key(|path| image_rank(path).unwrap_or(u8::MAX));
    scan
}

/// How likely a file is to be the one a live holder is holding, or None.
///
/// These three extensions are the files Windows keeps open for the lifetime of
/// a process that is running out of them, because they are mapped as images
/// rather than merely read. Everything else in an extraction is data, which is
/// opened and closed as it is needed and therefore says nothing when it opens.
fn image_rank(path: &std::path::Path) -> Option<u8> {
    let extension = path.extension()?.to_str()?.to_ascii_lowercase();
    match extension.as_str() {
        "exe" => Some(0),
        "dll" => Some(1),
        "pyd" => Some(2),
        _ => None,
    }
}

/// Whether one file is open in some process.
///
/// Windows refuses an open that asks for read access while denying it to
/// everybody else when somebody already has the file open, so a failure here is
/// the operating system saying the file is in use. Anything other than the file
/// having vanished counts as in use, including a plain permission error: the
/// question this answers is whether it is safe to delete the thing, and every
/// answer we cannot read has to mean no.
#[cfg(target_os = "windows")]
fn file_is_held_open(path: &std::path::Path) -> bool {
    use std::os::windows::fs::OpenOptionsExt;

    match std::fs::OpenOptions::new()
        .read(true)
        .share_mode(0)
        .open(path)
    {
        Ok(_) => false,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => false,
        Err(_) => true,
    }
}

/// POSIX has no mandatory locking, so an open here answers nothing.
#[cfg(not(target_os = "windows"))]
fn file_is_held_open(_path: &std::path::Path) -> bool {
    true
}

/// Whether a live process is still running out of this extraction.
///
/// THE GUARD, and the reason this file gained a sweep rather than a call to
/// remove a directory. An embedded PostgreSQL postmaster can outlive the
/// extraction it was started from: the log this was written from shows one
/// serving out of `_MEI195482` after that directory had lost files, escalating
/// to FATAL on `timezonesets` and then to crash recovery on every start after.
/// A sweep that deleted by age would have caused exactly that, and would have
/// turned tidying up into a way to corrupt a database.
///
/// What it is blind to, in order of how much it matters:
///
///   - a process holding only data files open. Only executables, libraries and
///     extension modules are probed, because those are the ones Windows keeps
///     open for as long as the process runs. A program that had merely opened a
///     configuration file inside an extraction would not be seen.
///   - the moment between this answer and the removal that follows it. Nothing
///     closes that window; `remove_extraction` narrows what it can cost by
///     removing the probed files first, so a holder that appears in between
///     stops the removal on the file it is holding rather than after the data
///     around it has gone.
///   - an extraction with no executable, library or extension module in it at
///     all, which is answered "not in use". That is a directory half removed by
///     an earlier interrupted sweep, and finishing it is the intent.
///   - everything on POSIX, where there is no such signal to read. The sweep
///     does not run there at all; see `sweep_extractions_in`.
fn extraction_is_in_use(scan: &ExtractionScan) -> bool {
    if !cfg!(target_os = "windows") {
        return true;
    }
    scan.images.iter().any(|image| file_is_held_open(image))
}

/// Remove one extraction, the files a holder would be holding first.
///
/// The order is the whole safety of this function. `remove_dir_all` walks in
/// whatever order the directory gives it, so on a directory that acquired a
/// holder since it was probed it would remove the data files it can and fail on
/// the executable it cannot, leaving a live process with its binaries and none
/// of the files it reads later. That is not a hypothetical: it is what the log
/// this change came from records happening to a postmaster and its
/// `timezonesets`. Removing the probed files first means the first thing we
/// touch is the thing such a process is holding, so the removal stops there with
/// everything else still on the disk.
fn remove_extraction(dir: &std::path::Path, scan: &ExtractionScan) -> std::io::Result<()> {
    for image in &scan.images {
        match std::fs::remove_file(image) {
            Ok(()) => {}
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
            Err(e) => return Err(e),
        }
    }
    std::fs::remove_dir_all(dir)
}

/// What the embedded cluster's pidfile says about a postmaster being alive.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ClusterState {
    /// A postmaster is running, or something we cannot rule out is.
    Running,
    /// No postmaster: no pidfile, or one naming a process that has gone.
    Stopped,
    /// The pidfile could not be read or made sense of.
    Unknown,
}

/// Read `postmaster.pid` and decide whether a cluster is live.
///
/// The backend keeps its cluster at `<data dir>/pgdata` and PostgreSQL writes
/// the postmaster's process id on the first line of `postmaster.pid` there. The
/// same file is read the same way on the Python side, in `_read_pidfile_pid` and
/// `_pid_alive` in `backend/app/core/embedded_pg.py`.
///
/// This asks only half of the question that module asks. It does not check
/// whether the process holding that id is still the postmaster that wrote the
/// file, because both answers point the same way here: uncertainty means live,
/// live means the sweep does not run, and a sweep that does not run costs disk
/// space rather than a database.
fn cluster_state_of(pidfile: &std::path::Path) -> ClusterState {
    let text = match std::fs::read_to_string(pidfile) {
        Ok(text) => text,
        Err(ref e) if e.kind() == std::io::ErrorKind::NotFound => return ClusterState::Stopped,
        Err(_) => return ClusterState::Unknown,
    };
    match text
        .lines()
        .next()
        .map(str::trim)
        .and_then(|line| line.parse::<u32>().ok())
    {
        Some(pid) if process_is_alive(pid) => ClusterState::Running,
        Some(_) => ClusterState::Stopped,
        None => ClusterState::Unknown,
    }
}

/// The state of this installation's own embedded cluster.
fn embedded_cluster_state() -> ClusterState {
    match workspace_data_dir() {
        Some(dir) => cluster_state_of(&dir.join("pgdata").join("postmaster.pid")),
        None => ClusterState::Unknown,
    }
}

/// Whether a process with this id currently exists.
///
/// Opening it is the direct answer. A refusal naming an invalid parameter is
/// Windows saying there is no such process; a refusal naming access denied is
/// Windows saying it exists and belongs to somebody else, which for this
/// question is alive. Anything else unrecognised is alive as well, because the
/// caller deletes files when told no.
///
/// Blind to process id reuse: a cluster that is long gone whose id now belongs
/// to some other program reads as running, and the sweep then never runs on that
/// machine until the id is free again. That direction costs disk space and
/// nothing else, which is why it is not tightened here.
#[cfg(target_os = "windows")]
fn process_is_alive(pid: u32) -> bool {
    use windows_sys::Win32::Foundation::{CloseHandle, ERROR_INVALID_PARAMETER};
    use windows_sys::Win32::System::Threading::{OpenProcess, PROCESS_QUERY_LIMITED_INFORMATION};

    if pid == 0 {
        return false;
    }
    // SAFETY: OpenProcess takes an id by value and returns either a handle we
    // close immediately or a null one; nothing here outlives the call.
    unsafe {
        let handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
        if handle.is_null() {
            let code = std::io::Error::last_os_error().raw_os_error();
            return code != Some(ERROR_INVALID_PARAMETER as i32);
        }
        CloseHandle(handle);
        true
    }
}

/// Not asked on POSIX: the sweep does not run there.
#[cfg(not(target_os = "windows"))]
fn process_is_alive(_pid: u32) -> bool {
    true
}

/// What one sweep did.
#[derive(Debug, Default, PartialEq, Eq)]
struct SweepReport {
    removed: usize,
    bytes_freed: u64,
    kept: usize,
    /// Kept because something is still running out of them. Counted separately
    /// because this is the number that says the guard did something.
    kept_in_use: usize,
    /// True when the budget ran out with entries still unexamined.
    stopped_early: bool,
    /// Set when nothing was examined at all, and why.
    skipped: Option<&'static str>,
}

/// Remove the extractions that forced stops left behind in `root`.
///
/// Every input is a parameter so the whole thing can be driven over a fabricated
/// root in a test, including the two that suspend it: a live cluster and a
/// minimum age. It never discovers a directory of its own, which is what keeps
/// the caller's ownership decision from being quietly widened here.
///
/// `on_first_removal` is called once, immediately before the first directory is
/// removed, because that is the point at which this stops being instant and the
/// user is owed a word about what their computer is doing.
fn sweep_extractions_in(
    root: &std::path::Path,
    cluster: ClusterState,
    minimum_age: Duration,
    budget: Duration,
    on_first_removal: &mut dyn FnMut(),
) -> SweepReport {
    let mut report = SweepReport::default();

    // Not on POSIX. The guard that makes this safe is an exclusive open, and
    // there is no such thing there: a POSIX process holds an inode, not a name,
    // so nothing about an open file can be read off the filesystem and every
    // directory would have to be judged by age alone. That is the rule that
    // corrupts a database, so this simply does not run.
    if !cfg!(target_os = "windows") {
        report.skipped = Some("only Windows can be asked whether a file is in use");
        return report;
    }

    match cluster {
        ClusterState::Running => {
            report.skipped = Some("an embedded database is running");
            return report;
        }
        ClusterState::Unknown => {
            report.skipped = Some("it is not known whether an embedded database is running");
            return report;
        }
        ClusterState::Stopped => {}
    }

    let entries = match std::fs::read_dir(root) {
        Ok(entries) => entries,
        Err(_) => {
            report.skipped = Some("the extraction folder could not be listed");
            return report;
        }
    };

    let deadline = Instant::now() + budget;
    for entry in entries.flatten() {
        if Instant::now() >= deadline {
            report.stopped_early = true;
            break;
        }

        let listed = TempEntry {
            name: entry.file_name().to_string_lossy().to_string(),
            is_dir: entry.file_type().map(|t| t.is_dir()).unwrap_or(false),
            age: entry
                .metadata()
                .ok()
                .and_then(|meta| meta.modified().ok())
                .and_then(|written| std::time::SystemTime::now().duration_since(written).ok()),
            in_use: false,
        };

        // What the listing knows. It can only ever say no from here, so a
        // Remove at this point means no more than "worth paying to look".
        if sweep_verdict(&listed, minimum_age) != SweepVerdict::Remove {
            report.kept += 1;
            continue;
        }

        let path = entry.path();
        let scan = scan_extraction(&path, EXTRACTION_FILE_CAP);
        if scan.truncated {
            report.kept += 1;
            log_line(&format!(
                "extraction sweep: leaving {} alone, it could not be read in full",
                listed.name
            ));
            continue;
        }

        let observed = TempEntry {
            in_use: extraction_is_in_use(&scan),
            ..listed
        };
        match sweep_verdict(&observed, minimum_age) {
            SweepVerdict::Remove => {
                if report.removed == 0 {
                    on_first_removal();
                }
                match remove_extraction(&path, &scan) {
                    Ok(()) => {
                        report.removed += 1;
                        report.bytes_freed += scan.bytes;
                        log_line(&format!(
                            "extraction sweep: removed {} ({}, {} files) left behind by an earlier run",
                            observed.name,
                            human_bytes(scan.bytes),
                            scan.files
                        ));
                    }
                    Err(e) => {
                        // Including a file that was opened in the moment between
                        // the probe and here. Nothing is retried and nothing is
                        // escalated: whatever is left stays where it is.
                        report.kept += 1;
                        log_line(&format!(
                            "extraction sweep: stopped removing {}: {e}",
                            observed.name
                        ));
                    }
                }
            }
            SweepVerdict::KeepInUse => {
                report.kept += 1;
                report.kept_in_use += 1;
                log_line(&format!(
                    "extraction sweep: leaving {} alone, a running program is still using it",
                    observed.name
                ));
            }
            _ => report.kept += 1,
        }
    }

    report
}

/// Clear what earlier runs left behind, before this one adds to it.
///
/// Only ever inside the root this application unpacks into. A directory we did
/// not create is not ours to judge, however confident the guards below are.
fn sweep_orphaned_extractions(handle: &tauri::AppHandle) {
    let root = match extraction_root() {
        Some(root) => root,
        None => {
            log_line("extraction sweep: not run, this build unpacks somewhere it does not own");
            return;
        }
    };
    ensure_extraction_root(&root);

    let mut announced = false;
    let report = sweep_extractions_in(
        &root,
        embedded_cluster_state(),
        EXTRACTION_MINIMUM_AGE,
        EXTRACTION_SWEEP_BUDGET,
        &mut || {
            announced = true;
            boot_stage(
                handle,
                "sidecar",
                "active",
                "Clearing files left by an earlier run",
            );
        },
    );

    match report.skipped {
        Some(reason) => log_line(&format!("extraction sweep: not run, {reason}")),
        None => log_line(&format!(
            "extraction sweep: removed {} of {} directories in {}, reclaiming {}{}{}",
            report.removed,
            report.removed + report.kept,
            root.display(),
            human_bytes(report.bytes_freed),
            if report.kept_in_use > 0 {
                format!(", {} still in use", report.kept_in_use)
            } else {
                String::new()
            },
            if report.stopped_early {
                ", stopped early and will continue next start"
            } else {
                ""
            }
        )),
    }

    if announced {
        boot_stage(handle, "sidecar", "active", "Starting the backend");
    }
}

/// Free bytes on the volume holding `path`, as far as this user may use them.
///
/// `lpFreeBytesAvailableToCaller` rather than the volume's own free total,
/// because a quota is as real a limit as a full disk and the bootloader hits it
/// the same way.
#[cfg(target_os = "windows")]
fn free_space_at(path: &std::path::Path) -> Option<u64> {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Storage::FileSystem::GetDiskFreeSpaceExW;

    let wide: Vec<u16> = path
        .as_os_str()
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();
    let mut available: u64 = 0;
    // SAFETY: `wide` is a NUL-terminated UTF-16 path that outlives the call, and
    // the two totals we have no use for are documented as optional.
    let ok = unsafe {
        GetDiskFreeSpaceExW(
            wide.as_ptr(),
            &mut available,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
        )
    };
    if ok == 0 {
        None
    } else {
        Some(available)
    }
}

/// Unmeasured elsewhere: no answer, and the caller carries on.
#[cfg(not(target_os = "windows"))]
fn free_space_at(_path: &std::path::Path) -> Option<u64> {
    None
}

/// What the free-space measurement means for a sidecar about to be started.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum SpaceVerdict {
    /// Nothing was measured. Never a reason to refuse anything.
    Unknown,
    Enough,
    /// Enough to try, and little enough to be worth a line in the log.
    Tight,
    /// Not enough to unpack into at all.
    TooLittle,
}

/// Judge a free-space measurement. Pure, and the only place a refusal is decided.
fn space_verdict(free: Option<u64>, floor: u64, comfort: u64) -> SpaceVerdict {
    match free {
        None => SpaceVerdict::Unknown,
        Some(free) if free < floor => SpaceVerdict::TooLittle,
        Some(free) if free < comfort => SpaceVerdict::Tight,
        Some(_) => SpaceVerdict::Enough,
    }
}

/// A byte count in the units a person reads, never in bytes.
fn human_bytes(bytes: u64) -> String {
    const KB: u64 = 1024;
    const MB: u64 = 1024 * KB;
    const GB: u64 = 1024 * MB;
    if bytes >= GB {
        format!("{:.1} GB", bytes as f64 / GB as f64)
    } else if bytes >= MB {
        format!("{} MB", bytes / MB)
    } else {
        format!("{} KB", bytes / KB)
    }
}

/// What to tell a user whose temporary folder has no room in it.
///
/// Both numbers are in it on purpose. "Not enough disk space" is a sentence
/// somebody can read twice and still not know what to do about, and the drive
/// that matters is not always the one they would think to check: it is whichever
/// one holds the temporary folder, which is why the folder is named.
fn out_of_space_message(dir: &str, free: u64) -> String {
    format!(
        "There is not enough free space to start the application. It unpacks itself into \
{dir} every time it starts, which needs about {}, and the drive holding that folder has \
{} free. Free some space on that drive and start OpenConstructionERP again.",
        human_bytes(EXTRACTION_ESTIMATED_BYTES),
        human_bytes(free)
    )
}

/// What the disk had to say, appended to a bootloader failure that has already
/// been recognised.
///
/// `classify_bootloader_failure` names free space as one of two usual causes,
/// which is as far as the text of the failure itself can take anyone. This is
/// the measurement that decides between them, so the user is told which of the
/// two they have rather than being handed both and left to guess.
fn extraction_space_note(dir: &std::path::Path) -> String {
    let free = match free_space_at(dir) {
        Some(free) => free,
        None => return String::new(),
    };
    match space_verdict(Some(free), EXTRACTION_SPACE_FLOOR, EXTRACTION_SPACE_COMFORT) {
        SpaceVerdict::TooLittle | SpaceVerdict::Tight => format!(
            " The drive holding {} has {} free and unpacking needs about {}, so this is a full \
disk rather than antivirus software.",
            dir.display(),
            human_bytes(free),
            human_bytes(EXTRACTION_ESTIMATED_BYTES)
        ),
        _ => format!(
            " The drive holding {} has {} free.",
            dir.display(),
            human_bytes(free)
        ),
    }
}

/// Check there is room to unpack the sidecar, and say so when there is not.
///
/// Returns whether to go on and start it. Only a measured number refuses: a
/// measurement that could not be taken is no reason to stop a machine that would
/// have worked, and neither is a drive that is merely tight, which is reported
/// to the log and started anyway.
fn extraction_space_allows_a_sidecar(handle: &tauri::AppHandle) -> bool {
    let dir = match extraction_dir() {
        Some(dir) => dir,
        None => return true,
    };
    // Before the measurement, not after: the drive is asked about a directory,
    // and on a machine that has not started this version yet there is not one.
    ensure_extraction_root(&dir);

    let free = free_space_at(&dir);
    match space_verdict(free, EXTRACTION_SPACE_FLOOR, EXTRACTION_SPACE_COMFORT) {
        SpaceVerdict::TooLittle => {
            let free = free.unwrap_or(0);
            report_fatal_stage(
                handle,
                "sidecar",
                &out_of_space_message(&dir.display().to_string(), free),
            );
            false
        }
        SpaceVerdict::Tight => {
            log_line(&format!(
                "extraction space: {} free at {}, unpacking needs about {}",
                human_bytes(free.unwrap_or(0)),
                dir.display(),
                human_bytes(EXTRACTION_ESTIMATED_BYTES)
            ));
            true
        }
        SpaceVerdict::Enough | SpaceVerdict::Unknown => true,
    }
}

/// Start a server locally, as a sidecar of this process, and open the app
/// against it once it is healthy.
///
/// This is the other arm of `BackendSource`, and it is what every user gets
/// today. It used to be the tail of `setup` with nothing separating it from
/// the decision to run it, which is why there was no place to put a second
/// answer. `base_url` is the address this server will be reachable on, handed
/// in by whoever made the decision rather than rebuilt here.
fn start_local_backend(
    handle: tauri::AppHandle,
    base_url: String,
    port: u16,
    bundled_converters: Option<PathBuf>,
    shutting_down: Arc<AtomicBool>,
    backend_lost: Arc<AtomicBool>,
) {
    // Read the shutdown secret out of managed state here, in
    // synchronous code, so the spawn below can hand it to the child.
    let shutdown_token = handle.state::<AppState>().shutdown_token.clone();

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
    let sidecar_cmd = match shell.sidecar("openconstructionerp-server") {
        Ok(cmd) => {
            // OE_DESKTOP=1 marks this backend as one we spawned from the
            // desktop shell (so the backend can run desktop-only
            // bootstrapping). We deliberately do NOT set it on the attach
            // path above, because an already-running dev backend must not
            // be treated as a desktop-bootstrapped one.
            // The second variable is the secret for the backend's own
            // shutdown endpoint, which is how this launcher stops it
            // cleanly on the way out. A backend started without it
            // refuses to shut down on request at all, which is the
            // right answer for every backend we did not start.
            let mut cmd = cmd
                .env("OE_DESKTOP", "1")
                .env("OE_DESKTOP_SHUTDOWN_TOKEN", shutdown_token.as_str())
                .args([
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
            // Give the sidecar a working directory it is allowed to
            // write to. Eighteen upload roots across ten modules are
            // declared as working-directory-relative literals and
            // create themselves with mkdir on first use, bypassing the
            // data-dir plumbing the rest of the platform goes through.
            // Nothing set the child's working directory, so it inherited
            // this process's, and the Start Menu shortcut of a
            // per-machine install starts the app in the install folder
            // under Program Files. Creating a directory there is denied
            // to an unelevated user, so attaching a file to a request
            // for information, a submittal, an inspection, a punch item,
            // a letter, a diary entry, a lien waiver, a closeout item or
            // a compliance document returned a bare 500 on every such
            // install, with ten registers carrying an attach button that
            // could not work.
            //
            // The note above about --data-dir is correct and was not
            // enough: it keeps the data directory writable and says
            // nothing about the working directory, which is a second
            // path the same process resolves against. Development and CI
            // both run with the repository root as the working
            // directory, which is writable, so those eighteen modules
            // look healthy everywhere they are ever tested.
            //
            // This moves them somewhere writable without editing the
            // eighteen declarations. It is a floor, not the repair: they
            // should answer to OE_CLI_DATA_DIR like everything else, and
            // until they do, a relative path written by any new module
            // lands here by accident rather than by design. Failing
            // through silently is deliberate, because an inherited
            // working directory is exactly what shipped, so a machine
            // whose home directory cannot be read is left no worse off
            // than it is today.
            if let Some(home) = home_dir() {
                let workdir = home.join(".openestimate");
                if std::fs::create_dir_all(&workdir).is_ok() {
                    cmd = cmd.current_dir(&workdir);
                }
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
            return;
        }
    };

    // Spawn and register under the one lock the exit path takes, and ask
    // first whether the application is still going. This runs off the main
    // thread now, behind a sweep of the extraction folder that can honestly
    // take a minute, which is long enough for somebody to close the splash
    // while it works. `stop_backend` sets `shutting_down` and then takes the
    // child out of this slot, so holding the slot across the check and the
    // spawn means it either finds the child, and stops it, or the check here
    // finds the flag, and nothing is started. Without the lock a close that
    // landed between the two would leave a backend and an embedded database
    // running that nothing is left alive to shut down, which is the very
    // thing the stop sequence in this file exists to prevent.
    let (mut rx, backend_exited) = {
        let state = handle.state::<AppState>();
        let mut child_slot = state.backend_child.lock().unwrap();
        if shutting_down.load(Ordering::SeqCst) {
            log_line("the application is closing; not starting a backend");
            return;
        }
        let (rx, child) = match sidecar_cmd.spawn() {
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
                return;
            }
        };
        log_line("sidecar spawned");
        // Keep the child handle alive (and stoppable on exit). The port
        // goes in beside it, because the clean stop is a request to the
        // backend and a request needs an address; it is recorded HERE, on
        // the spawn path only, so the exit path can never ask a backend we
        // merely attached to to shut itself down.
        *child_slot = Some(child);
        *state.backend_port.lock().unwrap() = Some(port);
        (rx, state.backend_exited.clone())
    };
    boot_stage(&handle, "sidecar", "done", "");
    boot_stage(&handle, "pg", "active", "Starting the local database");

    let backend_ready = Arc::new(AtomicBool::new(false));
    // Separate from readiness on purpose. Readiness means the backend
    // answered a health check, so it is only ever set on success and
    // says nothing about whether a failure has already been explained.
    // This one means the user has been shown a precise reason, which is
    // the question the startup timeout below actually needs answered.
    let fatal_reported = Arc::new(AtomicBool::new(false));
    let last_stderr = Arc::new(Mutex::new(String::new()));
    // Latch the real startup failure cause so the database-shutdown
    // noise that follows a crash cannot mask it: a STAGE:server:fail
    // marker (preferred), or the exception line of a Python traceback
    // on stderr when the backend died too early to emit a marker.
    let latched_fail = Arc::new(Mutex::new(None::<String>));
    let traceback = Arc::new(Mutex::new(TracebackCapture::default()));
    // Latched the same way and in the same pump as the two above,
    // because the startup wait needs to know whether the backend is
    // still working and what it is working on, and the pump is the only
    // place that sees either.
    let boot_progress = BootProgress::new();

    // Pump the sidecar's output into the log file and remember recent
    // stderr so a startup crash can be shown to the user verbatim.
    {
        let ready = backend_ready.clone();
        let fatal_flag = fatal_reported.clone();
        let stderr_buf = last_stderr.clone();
        let latched = latched_fail.clone();
        let traceback = traceback.clone();
        let handle_evt = handle.clone();
        let exited_flag = backend_exited.clone();
        let deliberate = shutting_down.clone();
        let lost_flag = backend_lost.clone();
        let progress = boot_progress.clone();
        tauri::async_runtime::spawn(async move {
            while let Some(event) = rx.recv().await {
                match event {
                    CommandEvent::Stdout(bytes) => {
                        let line = String::from_utf8_lossy(&bytes);
                        log_line(&format!("[backend] {}", line.trim_end()));
                        // A line, any line, is the backend saying it is
                        // still working.
                        progress.saw_output();
                        // Drive the visible boot checklist from the
                        // backend's machine-readable progress markers.
                        for raw in line.split('\n') {
                            if let Some((id, status, detail)) = parse_stage_marker(raw) {
                                boot_stage(&handle_evt, &id, &status, &detail);
                                progress.saw_stage(&id, &detail);
                                // Latch the first real failure cause.
                                if status == "failed" && !detail.is_empty() {
                                    let mut lf = latched.lock().unwrap();
                                    if lf.is_none() {
                                        *lf = Some(detail.clone());
                                    }
                                }
                            }
                        }
                    }
                    CommandEvent::Stderr(bytes) => {
                        let line = String::from_utf8_lossy(&bytes);
                        log_line(&format!("[backend:err] {}", line.trim_end()));
                        // Counts as working too: most of what a healthy
                        // start writes - uvicorn's own log, alembic,
                        // the module loader - comes out on stderr.
                        progress.saw_output();
                        // Some launchers/loggers route progress markers
                        // to stderr; honour them there too. Non-marker
                        // lines feed the traceback capture so a hard
                        // crash still yields a real cause with no marker.
                        for raw in line.split('\n') {
                            if let Some((id, status, detail)) = parse_stage_marker(raw) {
                                boot_stage(&handle_evt, &id, &status, &detail);
                                progress.saw_stage(&id, &detail);
                                if status == "failed" && !detail.is_empty() {
                                    let mut lf = latched.lock().unwrap();
                                    if lf.is_none() {
                                        *lf = Some(detail.clone());
                                    }
                                }
                            } else {
                                traceback.lock().unwrap().feed_line(raw);
                            }
                        }
                        let mut buf = stderr_buf.lock().unwrap();
                        buf.push_str(&line);
                        if buf.len() > 4000 {
                            // Advance the cut to a char boundary so
                            // slicing a UTF-8 string can never panic and
                            // kill the pump (which would strand the user
                            // on the splash for the whole timeout).
                            let mut cut = buf.len() - 4000;
                            while cut < buf.len() && !buf.is_char_boundary(cut) {
                                cut += 1;
                            }
                            *buf = buf[cut..].to_string();
                        }
                    }
                    CommandEvent::Error(err) => {
                        log_line(&format!("[backend:error] {err}"));
                        // A failure reading the child's own pipes went
                        // to the log and nowhere else, so on a startup
                        // that then failed the user was shown a tail of
                        // stderr with no sign of it. Add it to that tail
                        // rather than latching it as the cause: it is
                        // usually a symptom of the crash, and it must
                        // not displace the exception that explains it.
                        let mut buf = stderr_buf.lock().unwrap();
                        buf.push_str(&format!("launcher: {err}\n"));
                    }
                    CommandEvent::Terminated(payload) => {
                        log_line(&format!(
                            "[backend] terminated: code={:?} signal={:?}",
                            payload.code, payload.signal
                        ));
                        // Record the exit before anything else, so the
                        // shutdown path can wait for the process to
                        // really be gone instead of assuming it.
                        exited_flag.store(true, Ordering::SeqCst);
                        // If the backend died before ever becoming
                        // healthy, surface it now instead of leaving the
                        // user staring at the spinner for the full timeout.
                        if !ready.load(Ordering::SeqCst) {
                            // Prefer the real cause the backend reported
                            // (STAGE:server:fail), then the exception line
                            // of a captured Python traceback, and only as a
                            // last resort the raw stderr tail. This is what
                            // keeps the database-shutdown noise from masking
                            // the real reason startup failed.
                            let latched_cause = latched.lock().unwrap().clone();
                            let tb_cause = traceback.lock().unwrap().cause.clone();
                            let tail_now = stderr_buf.lock().unwrap().clone();
                            // A onefile bootloader failure happens before the
                            // bundled interpreter starts, so there is no latched
                            // stage and no traceback that could outrank it, and
                            // the text it leaves is unreadable. Name it first.
                            let boot_failure = classify_bootloader_failure(&tail_now);
                            let (fail_stage, core) = if let Some(f) = boot_failure {
                                // The text of the failure can name the two usual
                                // causes and cannot choose between them. The disk
                                // is the one of the two this launcher can measure,
                                // so it measures it and tells the user which one
                                // they have instead of handing them both.
                                let note = extraction_dir()
                                    .map(|dir| extraction_space_note(&dir))
                                    .unwrap_or_default();
                                (f.stage, format!("{}{note}", f.message))
                            } else if let Some(cause) = latched_cause.or(tb_cause) {
                                ("server", format!("The backend could not finish starting: {cause}"))
                            } else {
                                let tail = tail_now;
                                let core = if tail.trim().is_empty() {
                                    format!(
                                        "The backend stopped unexpectedly (exit code {:?}) \
before it finished starting.",
                                        payload.code
                                    )
                                } else {
                                    // Last resort: show the tail of stderr,
                                    // which usually carries the cause.
                                    let trimmed = tail.trim();
                                    let shown = if trimmed.len() > 600 {
                                        let mut start = trimmed.len() - 600;
                                        while start < trimmed.len()
                                            && !trimmed.is_char_boundary(start)
                                        {
                                            start += 1;
                                        }
                                        &trimmed[start..]
                                    } else {
                                        trimmed
                                    };
                                    format!(
                                        "The backend stopped unexpectedly during startup: {shown}"
                                    )
                                };
                                ("server", core)
                            };
                            // Always pair the cause with a clear next step.
                            // report_fatal_stage also surfaces the log path
                            // (the splash shows an Open-log button).
                            let detail = format!(
                                "{core} Open the log file for the full details, and if \
this keeps happening send it to info@datadrivenconstruction.io."
                            );
                            // The database step was set active before the
                            // process was spawned, and bootStage back-fills
                            // earlier steps only for active/done, never for
                            // failed. Marking an EARLIER step failed therefore
                            // left that spinner turning next to the red mark,
                            // which is what the screenshot on issue 462 shows.
                            if fail_stage == "sidecar" {
                                boot_stage(&handle_evt, "pg", "pending", "");
                            }
                            report_fatal_stage(&handle_evt, fail_stage, &detail);
                            // Record that the user now has the real
                            // reason, so the startup timeout does not
                            // replace it with a vaguer one later.
                            fatal_flag.store(true, Ordering::SeqCst);
                        } else if !deliberate.load(Ordering::SeqCst) {
                            // The backend had already gone healthy, and
                            // nobody asked it to stop. This case was
                            // silent: readiness was the end of the
                            // launcher's attention, so a sidecar that
                            // died an hour in left the window showing
                            // the last screen it had rendered while
                            // every request inside it failed, and the
                            // only record was a line in a log file the
                            // user had no reason to open.
                            report_backend_lost(
                                &handle_evt,
                                &lost_flag,
                                "The application backend has stopped",
                                &format!(
                                    "The backend exited unexpectedly (exit code {:?}), so \
this window can no longer load or save anything. Please close it and start \
OpenConstructionERP again. If this keeps happening, send the log file to \
info@datadrivenconstruction.io.",
                                    payload.code
                                ),
                            );
                        }
                        break;
                    }
                    _ => {}
                }
            }

            // The event channel can also just end: the sender is
            // dropped and no Terminated event ever arrives. Reaching
            // here means we have stopped watching the backend, and
            // saying nothing would leave whoever is using it to find
            // out from a screen that no longer works.
            if !exited_flag.load(Ordering::SeqCst)
                && !deliberate.load(Ordering::SeqCst)
                && ready.load(Ordering::SeqCst)
            {
                log_line("backend event stream ended without a termination event");
                report_backend_lost(
                    &handle_evt,
                    &lost_flag,
                    "The connection to the application backend was lost",
                    "The launcher can no longer see the backend it started, so this \
window may stop working. Please close it and start OpenConstructionERP again. If this keeps \
happening, send the log file to info@datadrivenconstruction.io.",
                );
            }
        });
    }

    // Wait for the backend to be ready, then navigate the webview from
    // the splash screen to the live application. First-run embedded
    // PostgreSQL setup (initdb, migrations, module load, demo seed) can
    // be slow on a cold machine, so allow up to 240 seconds.
    let handle_clone = handle.clone();
    let ready_flag = backend_ready.clone();
    let fatal_flag_wait = fatal_reported.clone();
    let shutting_down_wait = shutting_down.clone();
    let backend_lost_wait = backend_lost.clone();
    let progress_wait = boot_progress.clone();
    let base_url_wait = base_url;
    tauri::async_runtime::spawn(async move {
        // A first run that has to recover a large local database (WAL
        // replay + fsync) can take several minutes, so allow a generous
        // window. This number has one hard requirement: it must exceed
        // the backend's own budget for bringing embedded PostgreSQL up,
        // which is OE_PG_BOOT_TIMEOUT and defaults to 600s. It used to
        // be 600 as well, so the two were equal and a database that
        // spent its whole budget recovering left nothing at all for the
        // work that follows it: migrations, the module load, table
        // creation and first-run seeding. That is not a hypothetical
        // ordering. The installer stops a running instance by killing
        // the process tree, which crash-stops the embedded database, so
        // the next start after every upgrade is exactly the WAL replay
        // the 600s budget exists for. The user then saw a healthy,
        // still-working backend reported as one that had not started,
        // and retrying reproduced it because nothing had gone wrong to
        // clear. Doubling it keeps a comfortable margin above the inner
        // budget and costs nothing when a backend has genuinely failed,
        // because that path reports itself the moment the sidecar dies
        // rather than waiting for this window to close.
        //
        // This is the ceiling and no longer the only limit: a backend
        // that goes quiet is given up on after STARTUP_QUIET_TIMEOUT,
        // so the full window is only ever spent on a backend that is
        // demonstrably still working.
        match wait_for_backend(&handle_clone, port, 1200, &progress_wait).await {
            StartupOutcome::Ready => {
                ready_flag.store(true, Ordering::SeqCst);
                log_line("backend healthy; navigating to app");
                boot_stage(&handle_clone, "server", "done", "");
                boot_stage(&handle_clone, "open", "done", "Ready");
                    let url = base_url_wait;
                set_app_url(&handle_clone, &url);
                if let Some(window) = handle_clone.get_webview_window("main") {
                    let _ = window.show();
                    let _ = window.set_focus();
                    // Let the splash offer the one-time "app window or
                    // browser" choice; if that helper is missing for any
                    // reason, fall straight through to the app window so
                    // the user is never left on the splash.
                    let url_js = js_escape(&url);
                    let _ = window.eval(&format!(
                        "(function(){{if(typeof offerLaunchChoice==='function'){{\
                            offerLaunchChoice('{url_js}');}}\
                            else{{window.location.replace('{url_js}');}}}})()"
                    ));
                }
                update_check::note_app_started(&handle_clone, env!("CARGO_PKG_VERSION"));
                // Readiness is where the launcher used to stop looking.
                // Keep watching, so a backend that goes away later is
                // reported instead of being left for the user to find.
                tauri::async_runtime::spawn(watch_backend_liveness(
                    handle_clone.clone(),
                    format!("http://127.0.0.1:{port}/api/health"),
                    LOCAL_BACKEND_LOST_DETAIL.to_string(),
                    shutting_down_wait,
                    backend_lost_wait,
                ));
            }
            StartupOutcome::Broken(reason) => {
                // The backend is answering and telling us it cannot do
                // its job. Opening the app on top of that hands the user
                // a shell whose every action fails, which is how this
                // ended up looking like the product was broken rather
                // than the installation.
                log_line(&format!("backend is up but not fit to serve: {reason}"));
                if !fatal_flag_wait.load(Ordering::SeqCst) {
                    report_fatal_stage(
                        &handle_clone,
                        "server",
                        &format!(
                            "The backend started, but {reason}, so the app cannot open. \
Please close this window and try again. If the problem persists, please send the log file to \
info@datadrivenconstruction.io."
                        ),
                    );
                }
            }
            StartupOutcome::TimedOut(kind) => {
                let stage = progress_wait.stage();
                match &kind {
                    TimeoutKind::WentQuiet(quiet_for) => log_line(&format!(
                        "backend went quiet during startup: nothing written for {}s, last step reported was {}",
                        quiet_for.as_secs(),
                        stage
                            .as_ref()
                            .map(|(id, _)| id.as_str())
                            .unwrap_or("none"),
                    )),
                    TimeoutKind::TookTooLong => log_line(&format!(
                        "backend did not become healthy within the startup window; last step reported was {}",
                        stage
                            .as_ref()
                            .map(|(id, _)| id.as_str())
                            .unwrap_or("none"),
                    )),
                }
                // Only say "slow" when nothing better has been said. The
                // termination handler above names the real cause the
                // moment the sidecar dies, and this branch used to guard
                // on the readiness flag, which is set only when the
                // backend goes healthy. A backend that died during
                // startup therefore left readiness false and satisfied
                // this condition, so the timeout fired minutes afterwards
                // and overwrote a message carrying the actual exception
                // with one that said only that the backend had not
                // started in time. A user whose sidecar exited with a
                // FileNotFoundError nine minutes earlier read the second
                // message, looked for the fault on their own machine, and
                // had no way to know the first had ever been shown.
                if !ready_flag.load(Ordering::SeqCst)
                    && !fatal_flag_wait.load(Ordering::SeqCst)
                {
                    report_fatal_stage(
                        &handle_clone,
                        "server",
                        &startup_timeout_message(stage.as_ref(), &kind),
                    );
                }
            }
        }
    });
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
            shutting_down: Arc::new(AtomicBool::new(false)),
            backend_exited: Arc::new(AtomicBool::new(false)),
            backend_lost_reported: Arc::new(AtomicBool::new(false)),
            backend_port: Mutex::new(None),
            shutdown_token: new_shutdown_token(),
        })
        .invoke_handler(tauri::generate_handler![
            open_log_file,
            open_app_in_browser,
            open_external_url,
            reveal_path_in_os,
            get_app_url,
            get_server_choice,
            set_server_choice,
            use_local_server,
            update_check::set_update_check_enabled,
            update_check::decline_update_version
        ])
        .setup(move |app| {
            let handle = app.handle().clone();
            log_line(&format!("setup() running; backend port = {port}"));

            // Take the shared flags out of managed state once, here in
            // synchronous code, and hand the tasks below plain Arcs. A
            // `State` borrow lives on the handle it came from, and the tasks
            // that need these flags are async and long-lived.
            let (shutting_down, backend_lost) = {
                let state = handle.state::<AppState>();
                (
                    state.shutting_down.clone(),
                    state.backend_lost_reported.clone(),
                )
            };

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
            // Show the version from the first frame, not only once something has
            // failed, so a user who is merely puzzled can also read it off.
            report_app_version(&handle);
            boot_stage(&handle, "sidecar", "active", "Starting the backend");

            // Ask, in the background, whether a newer release exists. Started
            // here rather than when a failure is reported because a failure can
            // arrive in milliseconds - a sidecar binary that is not there fails
            // long before any request could finish - and a user staring at an
            // error is not going to be made to wait for a web request on top of
            // it. Never awaited, never blocking, and silent unless startup
            // fails: see the file for what it does and does not do.
            update_check::spawn(handle.clone(), env!("CARGO_PKG_VERSION").to_string());

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
                let mut menu = MenuBuilder::new(app).item(&show_item).item(&browser_item);

                // The way back, for the case the failure screen never sees: a
                // configured server that works perfectly well and is the wrong
                // one. In that state the application loads, so there is no
                // failure screen and no button on it, and the settings page
                // inside the application cannot help either, because that page
                // is served by the remote server and its origin is granted no
                // command here. The tray belongs to the launcher and answers to
                // nobody's access control list, which is exactly why the escape
                // hatch lives on it.
                //
                // Only shown when there is something to escape from. On an
                // ordinary local install this item would be an offer to switch
                // to what the user is already using.
                let local_item = match server_config::resolve() {
                    server_config::Resolution::Remote { .. }
                    | server_config::Resolution::Refused { .. } => Some(
                        MenuItemBuilder::with_id("tray_use_local", "Use a server on this computer")
                            .build(app)?,
                    ),
                    server_config::Resolution::Local { .. } => None,
                };
                if let Some(item) = local_item.as_ref() {
                    menu = menu.item(item);
                }

                menu.item(&sep).item(&quit_item).build()
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
                        "tray_use_local" => switch_to_local_and_restart(app),
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

            // Decide where the application server comes from, then carry that
            // decision out. Choosing and starting are two steps now rather than
            // one, so a server this launcher did not start has a place to be
            // chosen; see `BackendSource`. Both of today's answers are still
            // local, and both behave exactly as they did when this was one
            // straight line of code.
            match resolve_backend_source(port) {
                BackendSource::AlreadyRunning { base_url, port } => {
                    attach_to_running_backend(handle, base_url, port, shutting_down, backend_lost);
                }
                BackendSource::StartLocally { base_url, port } => {
                    // Three steps in one order: clear what earlier runs left in
                    // the temporary folder, check what is left to unpack into,
                    // and only then start the sidecar. The order is the point,
                    // because the sweep is what makes the room the check is
                    // about to measure.
                    //
                    // Off this thread, all of it. setup() runs before the event
                    // loop starts pumping, so work done here is time with no
                    // window painted, and the sweep is the one thing in this
                    // file that can honestly take a minute: the log this was
                    // written from names 84 extractions on a drive that had
                    // run out of space. A launcher that went quiet for that long while
                    // clearing up would be indistinguishable from the "I click
                    // the icon and nothing happens" failure this whole file is
                    // written against.
                    let reporter = handle.clone();
                    let start = move || {
                        sweep_orphaned_extractions(&handle);
                        if !extraction_space_allows_a_sidecar(&handle) {
                            return;
                        }
                        // Nothing between here and the spawn used to be able
                        // to take time, so the sidecar was always registered
                        // before the event loop could deliver an exit. A sweep
                        // that runs for a minute and a half is long enough for
                        // somebody to close the splash while it works, so the
                        // spawn now asks whether the application is still
                        // going, under the lock the exit path takes; see
                        // start_local_backend.
                        start_local_backend(
                            handle,
                            base_url,
                            port,
                            bundled_converters,
                            shutting_down,
                            backend_lost,
                        );
                    };
                    if let Err(e) = std::thread::Builder::new()
                        .name("oe-backend-start".to_string())
                        .spawn(start)
                    {
                        // The work went with the thread that could not be
                        // started, so there is nothing left to run here. Say it
                        // where the user can read it rather than leaving them
                        // watching a spinner that has nothing behind it.
                        report_fatal_stage(
                            &reporter,
                            "sidecar",
                            &format!(
                                "The backend could not be started ({e}). Close anything else \
that is running and start OpenConstructionERP again."
                            ),
                        );
                    }
                }
                BackendSource::Remote { base_url, source } => {
                    attach_to_remote_backend(
                        handle,
                        base_url,
                        source,
                        shutting_down,
                        backend_lost,
                    );
                }
                BackendSource::Refused {
                    source,
                    raw,
                    problem,
                } => {
                    // Nothing is started and nothing is contacted. The address
                    // was rejected before any of that, which is the point: a
                    // bad address should cost a message, not a timeout.
                    report_fatal_stage(
                        &handle,
                        "server",
                        &format!(
                            "The server address \"{raw}\", configured in {}, cannot be used. {} \
Use the button below to run a server on this computer instead.",
                            source.describe(),
                            problem.message()
                        ),
                    );
                    offer_local_fallback(&handle);
                }
            }

            Ok(())
        })
        .build(tauri::generate_context!());

    match app {
        Ok(app) => app.run(|app_handle, event| match event {
            // Both events, because nothing the sidecar owns may outlive the
            // launcher on any exit path, and stopping it twice is a no-op.
            RunEvent::ExitRequested { .. } | RunEvent::Exit => stop_backend(app_handle),
            _ => {}
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

/// How long the launcher waits for the backend to actually be gone.
///
/// A window that is already closed while its process lingers reads as a hang,
/// and at session logoff Windows gives an application very little time before it
/// is killed anyway, so this is a short wait for confirmation and not a budget
/// for the backend to finish work in.
const BACKEND_STOP_WAIT: Duration = Duration::from_secs(5);

/// How long the backend is given to stop itself once it accepts the request to.
///
/// Longer than the wait above, because this one is not a formality: the backend
/// is disposing its database engine and stopping the PostgreSQL cluster, and a
/// cluster with a large checkpoint to write takes a few seconds over it. Those
/// seconds are the entire point. Every one of them not spent here comes back on
/// the next start as write-ahead-log replay, which is measured in minutes.
///
/// The number comes from the budget the backend's own cluster gets rather than
/// from what feels like a reasonable pause. On the way out the backend
/// (`shutdown` in `backend/app/core/embedded_pg.py`) hands the cluster back to
/// the library that booted it, and that library stops it with `pg_ctl -w stop`
/// and no `-t`: a fast shutdown, waited on for pg_ctl's default of sixty
/// seconds, after which the library terminates the postmaster itself and the
/// backend goes on to exit. So a clean stop can legitimately take a minute, and
/// stopping short of that is worse than not asking at all. At ten seconds,
/// which is what this was, the launcher force killed every cluster whose
/// checkpoint took longer than that, taking the write-ahead-log replay it was
/// trying to avoid AND leaving the one-file loader no chance to remove the
/// payload it had unpacked into the temporary folder. Ten seconds on top cover
/// the signal delay, the connection drain and the engine disposal the backend
/// does before it reaches pg_ctl at all, and the termination the library falls
/// back to when pg_ctl gives up.
///
/// This is spent on the way out, on the main event loop, so it is time the user
/// can see. It is not time they usually pay: `wait_until_exited` polls at 100 ms
/// and returns the moment the process is gone, so a small cluster costs a
/// fraction of a second and the full budget is only ever reached in the one case
/// where the alternative is minutes of replay on the next start.
const GRACEFUL_STOP_WAIT: Duration = Duration::from_secs(70);

/// The clean-stop budget the backend's cluster gets before it is terminated.
///
/// `pg_ctl -w stop` with no `-t` is how `pixeltable-pgserver` stops the
/// postmaster it started, and with `PGCTLTIMEOUT` set nowhere in the backend
/// that waits pg_ctl's default of sixty seconds. Named here so the invariant
/// that matters - the launcher must not give up before the backend has finished
/// trying - is something a test can assert rather than something a reader has
/// to notice. The `("fast", 20)` leg in the same Python module is a different
/// path: it clears a mute postmaster found at START and says nothing about the
/// one stopped on the way out.
#[cfg(test)]
const BACKEND_CLEAN_STOP_BUDGET: Duration = Duration::from_secs(60);

/// How long the shutdown request itself may take to be answered.
///
/// The backend answers before it acts, so this bounds a round trip on loopback
/// and not the shutdown. A backend too busy to answer within it is one we go on
/// to stop the hard way.
const GRACEFUL_REQUEST_TIMEOUT: Duration = Duration::from_secs(3);

/// Step one, on every platform: ask the backend to shut itself down.
///
/// This is the only stop that is clean on Windows. A forced stop leaves the
/// embedded PostgreSQL cluster looking crashed, so the next start replays its
/// write-ahead log, which on a large cluster takes minutes - and that wait is
/// what users have been reading as "the application backend did not start in
/// time", on a machine where nothing was wrong.
///
/// Returns whether the backend accepted the request. It refuses unless it is a
/// desktop-mode backend, reached over loopback, presented with the token this
/// launcher generated for it; see `backend/app/core/desktop_shutdown.py`.
fn ask_backend_to_stop(port: u16, token: &str) -> bool {
    let url = format!("http://127.0.0.1:{port}/api/system/desktop-shutdown");
    tauri::async_runtime::block_on(async {
        let client = match reqwest::Client::builder()
            .timeout(GRACEFUL_REQUEST_TIMEOUT)
            .build()
        {
            Ok(client) => client,
            Err(e) => {
                log_line(&format!(
                    "backend stop: could not build the shutdown client: {e}"
                ));
                return false;
            }
        };

        match client
            .post(&url)
            .header("X-Desktop-Shutdown-Token", token)
            // Close it behind us. The server drains its open connections before
            // it exits, and a kept-alive socket of ours would be one of the
            // things it waits on.
            .header("Connection", "close")
            .send()
            .await
        {
            Ok(resp) if resp.status().is_success() => {
                log_line("backend stop: the backend accepted the request to shut itself down");
                true
            }
            Ok(resp) => {
                log_line(&format!(
                    "backend stop: the backend would not shut itself down ({})",
                    resp.status()
                ));
                false
            }
            Err(e) => {
                log_line(&format!("backend stop: the shutdown request failed: {e}"));
                false
            }
        }
    })
}

/// Step two, POSIX only: SIGTERM.
///
/// A real request rather than a kill - the server runs its own shutdown handler
/// on it, the same one the request above reaches. It is the second step and no
/// longer the first because the request works on every platform, and it is
/// still here because a signal arrives even when the HTTP port does not answer.
///
/// Returns whether a request was actually sent.
#[cfg(not(target_os = "windows"))]
fn signal_backend_stop(pid: u32) -> bool {
    let pid_arg = pid.to_string();
    match std::process::Command::new("kill")
        .args(["-TERM", pid_arg.as_str()])
        .status()
    {
        Ok(status) => {
            log_line(&format!(
                "backend stop: SIGTERM to pid {pid} exited {status}"
            ));
            status.success()
        }
        Err(e) => {
            log_line(&format!("backend stop: could not signal pid {pid}: {e}"));
            false
        }
    }
}

/// There is no second step on Windows.
///
/// A console process whose parent has no console cannot be handed a stop
/// request by any signal Windows will deliver, which is exactly why the backend
/// serves that request over HTTP instead.
#[cfg(target_os = "windows")]
fn signal_backend_stop(_pid: u32) -> bool {
    false
}

/// Step three: stop the process tree by force.
///
/// `taskkill /T` and not the child handle alone, because `CommandChild::kill`
/// is `TerminateProcess`, which stops that one process and nothing it started.
/// The sidecar starts the embedded PostgreSQL postmaster as a child of its own,
/// and the shipped sidecar is a one-file bundle whose bootloader runs the real
/// interpreter as a further child, so the process the launcher holds a handle
/// to need not be the process holding the database open.
///
/// This is an unclean stop for PostgreSQL, and it is now the last resort rather
/// than the first move.
#[cfg(target_os = "windows")]
fn force_backend_stop(pid: u32) {
    use std::os::windows::process::CommandExt;

    /// `CREATE_NO_WINDOW`: a console process spawned from a windowed one puts a
    /// black console on screen, and a console flashing up as the app closes is
    /// the last thing a user should see of it.
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;

    let pid_arg = pid.to_string();
    match std::process::Command::new("taskkill")
        .args(["/PID", pid_arg.as_str(), "/T", "/F"])
        .creation_flags(CREATE_NO_WINDOW)
        .status()
    {
        Ok(status) => log_line(&format!(
            "backend stop: taskkill on pid {pid} exited {status}"
        )),
        Err(e) => log_line(&format!(
            "backend stop: could not run taskkill on pid {pid}: {e}"
        )),
    }
}

/// Nothing extra to force on POSIX: the caller's `child.kill()` is SIGKILL.
#[cfg(not(target_os = "windows"))]
fn force_backend_stop(_pid: u32) {}

/// Wait for the sidecar to be observed exiting, up to `budget`.
fn wait_until_exited(exited: &Arc<AtomicBool>, budget: Duration) -> bool {
    let deadline = Instant::now() + budget;
    while !exited.load(Ordering::SeqCst) && Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(100));
    }
    exited.load(Ordering::SeqCst)
}

/// Stop the backend sidecar on the way out, in three steps, gentlest first.
///
/// 1. Ask the backend to shut itself down. It runs its own shutdown handler,
///    which stops the embedded PostgreSQL cluster cleanly, so the next start
///    has no write-ahead log to replay. This is what closing the app should
///    always have done, on every platform.
/// 2. SIGTERM, on POSIX, where the same handler can be reached by signal even
///    if the HTTP port cannot be reached at all.
/// 3. Force, taking the process tree with it. What was left behind before there
///    was any tree stop kept running with nobody to stop it: a postmaster still
///    attached to the cluster after the app had closed, killed eventually by
///    the operating system at logoff, which is an unclean stop, which is why
///    the next launch found a cluster to recover.
///
/// Each step is logged by name, so a user's log says which of the three
/// actually stopped their backend rather than only that it stopped.
fn stop_backend(app_handle: &tauri::AppHandle) {
    let state = app_handle.state::<AppState>();
    // Announce the shutdown before causing it. Every watcher treats a backend
    // that disappears as a failure worth telling the user about, and the stop
    // below is a disappearance; without this flag, closing the app would end
    // with a message claiming the backend had crashed.
    state.shutting_down.store(true, Ordering::SeqCst);
    let exited = state.backend_exited.clone();
    // Copy what the steps below need out of managed state first, each in its
    // own statement, so no MutexGuard temporary is still alive when `state`
    // goes out of scope. Holding a guard across the body borrowed `state` too
    // long and failed to compile (E0597) in the release build.
    let port = *state.backend_port.lock().unwrap();
    let token = state.shutdown_token.clone();
    let child = state.backend_child.lock().unwrap().take();
    let child = match child {
        Some(child) => child,
        // Nothing to stop: either we attached to a backend somebody else owns,
        // or this has already run once on the way out.
        None => return,
    };

    // Read the pid BEFORE kill(), which consumes the handle.
    let pid = child.pid();
    log_line(&format!("stopping the backend sidecar (pid {pid})"));

    // Step one. `port` is Some only for a sidecar we started ourselves, so a
    // backend we merely attached to is never asked to stop.
    if let Some(port) = port {
        if ask_backend_to_stop(port, &token) && wait_until_exited(&exited, GRACEFUL_STOP_WAIT) {
            log_line("backend stop: the backend shut itself down cleanly");
            return;
        }
    }

    // Step two.
    if signal_backend_stop(pid) && wait_until_exited(&exited, BACKEND_STOP_WAIT) {
        log_line("backend stop: the backend exited after SIGTERM");
        return;
    }

    // Step three.
    log_line("backend stop: falling back to a forced stop of the process tree");
    force_backend_stop(pid);
    let _ = child.kill();
    if wait_until_exited(&exited, BACKEND_STOP_WAIT) {
        log_line("the backend sidecar has exited");
    } else {
        log_line("the backend sidecar is still running after a forced stop");
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

#[cfg(test)]
mod tests {
    use super::*;

    /// The identity of the data directory the tests below speak from.
    ///
    /// Shared by the fixtures and by the probe calls, because a launcher and
    /// the backend it started read one file and therefore hold one value. Tests
    /// that want the other case say so by naming a different id.
    const TEST_WORKSPACE_ID: &str = "aaaaaaaabbbbbbbbccccccccdddddddd";

    /// The launcher must not give up on a clean stop before the backend has.
    ///
    /// This is the defect as an assertion. At ten seconds the launcher force
    /// killed a backend that was still inside the sixty second `pg_ctl -w stop`
    /// it had itself been asked to perform, so the shutdown that existed to
    /// avoid write-ahead-log replay caused it, and the forced stop denied the
    /// one-file loader the chance to remove what it had unpacked. Any value at or
    /// below the backend's own budget reintroduces both.
    #[test]
    fn the_launcher_waits_longer_than_the_backend_takes_to_stop_cleanly() {
        assert!(
            GRACEFUL_STOP_WAIT > BACKEND_CLEAN_STOP_BUDGET,
            "GRACEFUL_STOP_WAIT ({GRACEFUL_STOP_WAIT:?}) must exceed the backend's own clean \
stop budget ({BACKEND_CLEAN_STOP_BUDGET:?}, embedded_pg.py), or the launcher force kills a \
cluster that is still shutting down cleanly"
        );
    }

    /// A backend that ignores the request still has to die.
    ///
    /// The budget above is only safe because running out of it is not the end of
    /// the sequence. `wait_until_exited` has to report the failure rather than
    /// hang, so that `stop_backend` goes on to the forced stop; a version that
    /// waited forever would turn every wedged backend into an application that
    /// never closes.
    #[test]
    fn a_backend_that_never_exits_times_out_so_the_forced_stop_still_runs() {
        let never = Arc::new(AtomicBool::new(false));
        let started = Instant::now();

        assert!(
            !wait_until_exited(&never, Duration::from_millis(300)),
            "a backend that never exits must be reported as still running"
        );
        assert!(
            started.elapsed() >= Duration::from_millis(300),
            "the budget must actually be spent before giving up"
        );
    }

    /// And one that does exit is not waited on for the full budget.
    #[test]
    fn a_backend_that_exits_is_not_waited_on_any_longer() {
        let exited = Arc::new(AtomicBool::new(false));
        let flag = exited.clone();
        std::thread::spawn(move || {
            std::thread::sleep(Duration::from_millis(50));
            flag.store(true, Ordering::SeqCst);
        });

        let started = Instant::now();
        assert!(wait_until_exited(&exited, Duration::from_secs(30)));
        assert!(
            started.elapsed() < Duration::from_secs(5),
            "the wait must end when the process does, not when the budget does"
        );
    }

    /// The stderr the reporter's machine actually produced, transcribed from
    /// the screenshot on issue 462 (16.5.0, Windows 11).
    ///
    /// Kept verbatim rather than paraphrased because every word of it is the
    /// input the classifier has to survive: the doubled report, the trailing
    /// "!", the backslash in the entry name and the PID embedded in the tag.
    const ISSUE_462_STDERR: &str = "[PYI-16964:ERROR] Failed to extract cv2\\cv2.pyd: \
decompression resulted in return code -1! [PYI-16964:ERROR] Failed to extract entry: cv2\\cv2.pyd";

    /// A sidecar that died unpacking itself is not a server failure.
    ///
    /// This is the defect written as an assertion. The launcher hardcoded the
    /// "server" step for every pre-ready death, so a bundle that never started
    /// its interpreter reported that the application server had failed, and the
    /// one artefact a user can send us named the wrong half of the program.
    #[test]
    fn a_bootloader_unpack_failure_is_not_blamed_on_the_server() {
        let failure = classify_bootloader_failure(ISSUE_462_STDERR)
            .expect("the bootloader's own extraction error must be recognised");

        assert_ne!(
            failure.stage, "server",
            "no server code runs before the payload is unpacked"
        );
        assert_eq!(failure.stage, "sidecar");

        // The raw bootloader text must not reach the user, and what replaces it
        // has to name both the place and the two things they can act on.
        let msg = &failure.message;
        assert!(!msg.contains("[PYI-"), "raw bootloader noise leaked: {msg}");
        assert!(!msg.contains("return code"), "raw bootloader noise leaked: {msg}");
        assert!(msg.contains("temporary folder"), "must name where it failed: {msg}");
        assert!(msg.contains("antivirus"), "must name the usual cause: {msg}");
        assert!(msg.contains("free space"), "must name the other usual cause: {msg}");

        // The entry it stopped on is the one detail that distinguishes two
        // reports of this failure, so it has to survive into the message, and
        // the literal word "entry" from the second line is not a filename.
        assert!(msg.contains("cv2\\cv2.pyd"), "must name the entry: {msg}");
        assert_eq!(bootloader_failed_entry(ISSUE_462_STDERR).as_deref(), Some("cv2\\cv2.pyd"));
    }

    /// Everything that is not a bootloader failure keeps its old reporting.
    ///
    /// The classifier sits in front of the latched-stage and traceback paths,
    /// so a false positive here would silently replace a real diagnosis with a
    /// guess about antivirus. A Python traceback mentioning an extract call is
    /// the shape most likely to be misread, so it is the control.
    #[test]
    fn ordinary_backend_failures_are_left_alone() {
        for tail in [
            "",
            "Traceback (most recent call last):\n  File \"app/cli.py\", line 8\n\
RuntimeError: locale catalogue missing",
            "psycopg2.OperationalError: could not connect to server",
            "  File \"zipfile.py\", line 1: Failed to extract member from archive",
            "STAGE:server:fail:port 8712 already in use",
        ] {
            assert!(
                classify_bootloader_failure(tail).is_none(),
                "must not claim a bootloader failure for: {tail}"
            );
        }
    }

    /// Two accounts on one machine run one installed program, so every field
    /// the probe used to consult matches between them.
    ///
    /// This is the defect written as data. The two bodies below differ in
    /// exactly one place, which is the field this change added, and everything
    /// the launcher looked at before - version, status, database - is identical
    /// because it is the same install answering from two home directories. A
    /// rule that reads anything else cannot separate them.
    #[test]
    fn a_backend_from_another_account_is_not_a_candidate() {
        let ours = TEST_WORKSPACE_ID;
        let theirs = "11111111222222223333333344444444";

        let body = |workspace: &str| {
            serde_json::json!({
                "status": "healthy",
                "version": env!("CARGO_PKG_VERSION"),
                "database": "ok",
                "workspace_id": workspace,
            })
        };

        assert_eq!(workspace_id_of(&body(ours)), Some(ours));
        assert_ne!(workspace_id_of(&body(theirs)), Some(ours));
        // The control: nothing else in those two bodies disagrees, so this
        // field is the only thing standing between the two accounts.
        assert_eq!(blocking_fault(&body(theirs)), None);
        assert_eq!(
            body(ours).get("version"),
            body(theirs).get("version"),
            "the two accounts run the same build, which is why version cannot decide this"
        );
    }

    /// No identity published is refused, and so is an empty one.
    ///
    /// An older backend has no such field, and must not be attached to: we
    /// cannot tell whose data directory it holds, and "cannot tell" has to mean
    /// no. The empty string is the same answer for a different reason - two
    /// installations that both published one would compare equal to each other.
    #[test]
    fn a_backend_that_names_no_workspace_is_refused() {
        let older = serde_json::json!({"status": "healthy", "version": "16.7.1"});
        assert_eq!(workspace_id_of(&older), None);

        let blank = serde_json::json!({"workspace_id": "   "});
        assert_eq!(workspace_id_of(&blank), None);

        let wrong_type = serde_json::json!({"workspace_id": 12345});
        assert_eq!(workspace_id_of(&wrong_type), None);
    }

    /// The first writer's identity is the directory's identity, for everyone.
    ///
    /// The launcher writes this file when it starts before any backend has.
    /// Whoever arrives second has to read the first one's value rather than
    /// install its own, or a launcher and the backend it just spawned would
    /// hold two ids for one folder and refuse to recognise each other.
    #[test]
    fn an_identity_already_on_disk_is_read_rather_than_replaced() {
        let dir = std::env::temp_dir().join(format!(
            "oe-workspace-id-test-{}",
            uuid::Uuid::new_v4().simple()
        ));
        std::fs::create_dir_all(&dir).expect("temp dir");
        let path = dir.join(WORKSPACE_ID_FILENAME);

        std::fs::write(&path, "{\"workspace_id\": \"0123456789abcdef\"}\n").expect("plant an id");
        assert_eq!(
            read_workspace_id_file(&path),
            Some("0123456789abcdef".to_string())
        );

        // A second create must not replace it. This is the assertion that fails
        // if the write is ever changed to a rename, which replaces silently.
        let clobbered = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&path);
        assert!(clobbered.is_err(), "create_new overwrote an existing id");
        assert_eq!(
            read_workspace_id_file(&path),
            Some("0123456789abcdef".to_string())
        );

        let _ = std::fs::remove_dir_all(&dir);
    }

    /// A file that is not there, and one that is not readable as an identity.
    ///
    /// Both read as absent, and absent means this launcher writes one. What
    /// must not happen is a half-value: an id that parses to nothing is not an
    /// id that compares to something.
    #[test]
    fn an_unreadable_identity_file_reads_as_no_identity() {
        let dir = std::env::temp_dir().join(format!(
            "oe-workspace-id-missing-{}",
            uuid::Uuid::new_v4().simple()
        ));
        std::fs::create_dir_all(&dir).expect("temp dir");
        let path = dir.join(WORKSPACE_ID_FILENAME);

        assert_eq!(read_workspace_id_file(&path), None);

        std::fs::write(&path, "not json at all").expect("write");
        assert_eq!(read_workspace_id_file(&path), None);

        let _ = std::fs::remove_dir_all(&dir);
    }

    /// The log names enough of an id to be read, and not the id.
    #[test]
    fn a_logged_identity_is_a_prefix_and_not_the_value() {
        let id = TEST_WORKSPACE_ID;
        let shown = id_prefix(id);

        assert_eq!(shown, "aaaaaaaa");
        assert!(shown.len() < id.len(), "the log line carries the whole id");
        assert_eq!(id_prefix("short"), "short");
        assert_eq!(id_prefix(""), "");
    }

    /// A named server is warned about, never refused, and only across a major.
    ///
    /// The three cases below are the whole rule, and the middle one is the one
    /// that matters: a fleet whose server is upgraded before its desks is the
    /// ordinary state of the deployment this mode was built for, and a gate
    /// that fired there would take the office off its own ERP.
    #[test]
    fn a_remote_server_is_only_flagged_across_a_major_version() {
        assert!(remote_version_note("16.4.0", Some("16.4.0")).is_none());
        assert!(remote_version_note("16.4.0", Some("16.9.1")).is_none());

        let note = remote_version_note("16.4.0", Some("17.0.0")).expect("a major apart");
        // Both numbers, because "versions differ" sends the reader looking for
        // the two facts the message already had.
        assert!(note.contains("16.4.0"), "{note}");
        assert!(note.contains("17.0.0"), "{note}");
    }

    /// No version reported is an older server, not a mismatched one.
    ///
    /// The two absent cases are separate on purpose. A build too old to publish
    /// a version and a health body that would not parse both arrive here as
    /// `None`, and warning on either would be putting a claim about a
    /// difference on the one case where there is no evidence of one.
    #[test]
    fn a_server_that_reports_no_version_is_not_accused_of_anything() {
        assert!(remote_version_note("16.4.0", None).is_none());
        assert!(remote_version_note("16.4.0", Some("")).is_none());
        assert!(remote_version_note("16.4.0", Some("nightly")).is_none());
    }

    /// A server that has gone away is described differently depending on whose
    /// server it was.
    ///
    /// The local wording tells the user to close the window and start again,
    /// which is sound advice about a server this machine runs and useless
    /// advice about one it does not: reopening a window on this computer cannot
    /// restart a service on another. The two messages were one message with an
    /// address substituted into it until this test existed to say why they are
    /// not.
    #[test]
    fn a_lost_server_is_described_by_whose_server_it_was() {
        let remote = remote_backend_lost_detail("https://erp.example.com/");

        assert!(
            remote.contains("https://erp.example.com/"),
            "a remote failure has to name the server, or it names nothing the user can check"
        );
        assert!(
            !remote.contains("local address"),
            "the local wording describes a loopback socket and is false about a network server"
        );
        assert!(
            LOCAL_BACKEND_LOST_DETAIL.contains("local address"),
            "the local wording is the one that may talk about a local address"
        );
        assert_ne!(remote, LOCAL_BACKEND_LOST_DETAIL);
    }

    /// Every remote failure names the address, the layer that configured it,
    /// and the way out.
    ///
    /// These three are the entire difference between a startup failure a person
    /// can act on and a blank window. The address alone is not enough: with
    /// four places the value can come from, a user who does not know WHICH one
    /// holds it cannot change it, and the ones most likely to be wrong are the
    /// ones the user never wrote.
    #[test]
    fn a_remote_failure_says_what_was_tried_where_it_came_from_and_the_way_out() {
        for source in [
            server_config::ChoiceSource::Setting,
            server_config::ChoiceSource::Environment,
            server_config::ChoiceSource::AdminFile,
        ] {
            let message = format!(
                "Could not reach the OpenConstructionERP server at {}, which is configured in \
{}. {} Use the button below to run a server on this computer instead.",
                "https://erp.example.com/",
                source.describe(),
                "It did not answer."
            );
            assert!(message.contains("https://erp.example.com/"));
            assert!(message.contains(source.describe()));
            assert!(
                message.contains("run a server on this computer"),
                "the way out has to be in the message, because the button beside it has no \
other explanation"
            );
        }
    }

    /// The address the launcher will use is the address the settings page was
    /// told to show.
    ///
    /// One validator, in one place. A second copy in the web page would be a
    /// second opinion about what is acceptable, and the first day they disagree
    /// is the day the settings page accepts an address the launcher then
    /// refuses at the next start, which is the blank window this whole path
    /// exists to prevent.
    #[test]
    fn the_stored_address_is_the_canonical_one_and_not_what_was_typed() {
        let canonical = server_config::validate_server_url("HTTPS://ERP.Example.com").unwrap();
        assert_eq!(canonical, "https://erp.example.com/");
        // And it survives a second pass unchanged, which is what makes it safe
        // to hand to a webview, an HTTP client and a log line and expect all
        // three to mean the same server.
        assert_eq!(
            server_config::validate_server_url(&canonical).unwrap(),
            canonical
        );
    }

    /// The link the shell is given is the link the caller asked for.
    ///
    /// The whole claim of this opener is that nothing between the caller and
    /// the operating system reinterprets the string, so the assertion is on the
    /// exact wide buffer handed to `lpFile`, built independently of the code
    /// under test. Every one of these used to be handled by cmd.exe: the
    /// separators as text only because a later fix quoted them, and the percent
    /// forms not at all, since cmd substitutes those inside quotes as readily as
    /// outside.
    ///
    /// `%CD%` is in here as a case and not only as a sentence in a comment. The
    /// tempting cheap guard, refusing a percent followed by two hex digits, does
    /// not work precisely because of it: `CD` is a real variable that cmd
    /// expands, and C and D are both hex digits, so that rule would have to
    /// refuse it and would then also refuse every legitimately encoded
    /// character. Refusing names that `std::env::var` resolves fails on the same
    /// case for a different reason, since `CD` is a dynamic pseudo-variable that
    /// cmd expands while the environment block does not contain it at all.
    #[cfg(target_os = "windows")]
    #[test]
    fn the_shell_is_handed_the_link_exactly_as_written() {
        for target in [
            "https://example.invalid/&calc",
            "https://example.invalid/|calc",
            "http://example.invalid/?a=1&b=2",
            "https://example.invalid/^calc",
            "mailto:info@datadrivenconstruction.io?subject=a&body=b",
            "https://example.invalid/a%20b?q=%D0%BC%D0%B5%D1%82%D1%80",
            "https://example.invalid/?a=%CD%&b=%USERNAME%",
            "https://example.invalid/?a=%RANDOM%&b=%TIME%&c=%DATE%",
            "https://example.invalid/\"&calc",
            "https://example.invalid/\r\ncalc",
        ] {
            let handed = shell_target(target).expect("nothing here carries a null");
            // Built from the literal rather than by calling the same helper.
            // Two sides that share an implementation move together, and an
            // assertion that cannot disagree with the code it checks is not
            // checking it.
            let mut expected: Vec<u16> = target.encode_utf16().collect();
            expected.push(0);
            assert_eq!(
                handed, expected,
                "{target:?} must reach the shell unmodified: no quoting, no \
                 escaping and above all no substitution"
            );
        }
    }

    /// A null truncates the string the shell sees, so it is refused.
    ///
    /// The one character that cannot be passed through. Everything else is
    /// data to `ShellExecuteW`; this one ends the argument early and would open
    /// a prefix of the target without saying so.
    #[cfg(target_os = "windows")]
    #[test]
    fn a_target_carrying_a_null_is_refused() {
        assert!(shell_target("https://example.invalid/\0evil").is_err());
        assert!(shell_target("https://example.invalid/ok").is_ok());
    }

    /// Percent-encoded links keep working, which is why the guard is not a
    /// denylist.
    ///
    /// The old opener allowed percent signs deliberately, on the grounds that
    /// every encoded character in a URL is spelled with one. That reasoning was
    /// right and the conclusion was wrong: the answer was never to choose
    /// between encoded links and safe ones, it was to stop handing the string to
    /// something that parses it.
    #[cfg(target_os = "windows")]
    #[test]
    fn a_percent_encoded_link_is_not_refused() {
        assert!(shell_target("https://example.invalid/a%20b?q=%D0%BC%D0%B5%D1%82%D1%80").is_ok());
        assert!(shell_target("https://example.invalid/?path=%CD%").is_ok());
    }

    /// Parse a health body the way both judgements do, for the tests below.
    fn body(json: &str) -> serde_json::Value {
        serde_json::from_str(json).expect("the test body has to be valid JSON")
    }

    /// Is this body one `judge_health` would open the application on?
    fn judged_ready(json: &str) -> bool {
        matches!(judge_health(json), HealthProbe::Ready)
    }

    /// Serve one canned `/api/health` body on an ephemeral loopback port.
    ///
    /// The probe under test takes a port and builds its own URL, so the only way
    /// to exercise it for real is to put something on a port. One request is all
    /// it makes, so the task ends after one.
    async fn serve_one_health_body(body: String) -> u16 {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
            .await
            .expect("could not bind a loopback port");
        let port = listener.local_addr().expect("no local address").port();
        tokio::spawn(async move {
            if let Ok((mut socket, _)) = listener.accept().await {
                use tokio::io::{AsyncReadExt, AsyncWriteExt};
                let mut scratch = [0_u8; 2048];
                let _ = socket.read(&mut scratch).await;
                let response = format!(
                    "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\
Content-Length: {}\r\nConnection: close\r\n\r\n{}",
                    body.len(),
                    body
                );
                let _ = socket.write_all(response.as_bytes()).await;
                let _ = socket.shutdown().await;
            }
        });
        port
    }

    /// A health body of our own version AND our own workspace, so that only the
    /// fault question is left for the probe to decide.
    ///
    /// The workspace id is here for the same reason the version is: a body
    /// missing it is refused before any fault is looked at, and a test whose
    /// fixtures are refused on identity would report the fault rule as working
    /// while never reaching it.
    fn our_backend_saying(fields: &str) -> String {
        format!(
            r#"{{"version":"{}","workspace_id":"{TEST_WORKSPACE_ID}",{fields}}}"#,
            env!("CARGO_PKG_VERSION")
        )
    }

    #[tokio::test]
    async fn the_attach_probe_and_the_startup_judgement_agree_on_the_same_backend() {
        // The defect, tested end to end rather than through the shared helper.
        // One backend, two decisions: may the user open the app, and may we
        // attach instead of starting another one. They used to be written apart
        // and answered differently, and the disagreement was not academic - it
        // put a second backend on a live cluster's data directory.
        //
        // This drives the real probe over a real socket, so it still fails if
        // somebody puts an independent check back inside it. The bodies all
        // carry our own version, because version equality is the one question
        // the attach probe asks and the startup judgement rightly does not.
        //
        // They now also carry our own workspace id, which is the second such
        // question and the reason this loop is not the whole test any more. The
        // agreement being asserted is agreement about faults, and it holds
        // within one installation. Across two installations the two judgements
        // are meant to disagree, and the case below the loop says so, because a
        // reader who found only the loop would take this test as a promise that
        // anything openable is attachable - which is precisely the promise that
        // signed one user into another user's account.
        //
        // Writes a few lines to the launcher log, like every other call to the
        // attach probe. That is the probe being itself; there is nothing to
        // stub that would not also stub what is under test.
        let client = reqwest::Client::new();
        let bodies = [
            r#""status":"healthy","database":"ok","frontend_dist_present":true"#,
            // Behind on migrations, and serving its users perfectly well.
            r#""status":"degraded","database":"ok","frontend_dist_present":true,
               "alembic_head_matches":false"#,
            // Could not heal its schema, and likewise still serving.
            r#""status":"degraded","database":"ok","frontend_dist_present":true,
               "schema_heal_failed":true"#,
            // The two that really do leave nothing working.
            r#""status":"degraded","database":"error","frontend_dist_present":true"#,
            r#""status":"degraded","database":"ok","frontend_dist_present":false"#,
        ];

        for fields in bodies {
            let body = our_backend_saying(fields);
            let port = serve_one_health_body(body.clone()).await;
            let attachable = is_our_backend_healthy(&client, port, TEST_WORKSPACE_ID).await;
            let openable = judged_ready(&body);
            assert_eq!(
                attachable, openable,
                "the two judgements disagree about this backend: {body}"
            );
        }

        // The deliberate exception, over the same socket. A backend that
        // belongs to another account on this machine is perfectly fit for the
        // user who started it and must never be attached to by us. Its body is
        // otherwise identical to the first case above - same version, same
        // status, same fields - because it is the same installed program run by
        // somebody else, which is why nothing but the identity can decide it.
        let body =
            our_backend_saying(r#""status":"healthy","database":"ok","frontend_dist_present":true"#);
        let port = serve_one_health_body(body.clone()).await;
        assert!(judged_ready(&body), "its own user can open it");
        assert!(
            !is_our_backend_healthy(&client, port, "11111111222222223333333344444444").await,
            "attached to a backend holding another account's data"
        );
    }

    #[tokio::test]
    async fn the_one_disagreement_left_is_the_one_that_belongs_there() {
        // A backend of somebody else's version is fit for its own users and
        // unfit for us, and the two answers must stay different. Reaching
        // agreement here would mean attaching to a stranger's backend and
        // serving our users its frontend and its schema.
        //
        // Its workspace id is ours on purpose. Without it the refusal would
        // come from the identity test added since, and the version rule this
        // test is named for would go unexercised while the test still passed.
        let client = reqwest::Client::new();
        let body = format!(
            r#"{{"version":"0.0.1-not-ours","workspace_id":"{TEST_WORKSPACE_ID}","status":"healthy",
            "database":"ok","frontend_dist_present":true}}"#
        );
        let port = serve_one_health_body(body.clone()).await;

        assert!(judged_ready(&body), "its own users can still open it");
        assert!(
            !is_our_backend_healthy(&client, port, TEST_WORKSPACE_ID).await,
            "we must not attach to a backend that is not our version"
        );
    }

    #[test]
    fn the_shared_question_answers_the_same_way_for_both_callers() {
        // The content of the shared decision, pinned. Agreement between the two
        // callers is now structural - both delegate here - so what is worth
        // testing is WHAT it decides, and that it does not reach agreement by
        // finding nothing wrong with anything.
        let bodies = [
            r#"{"status":"healthy","database":"ok","frontend_dist_present":true}"#,
            r#"{"status":"ok","database":"ok","frontend_dist_present":true}"#,
            // Degraded for a reason that leaves the app usable.
            r#"{"status":"degraded","database":"ok","frontend_dist_present":true,
                "alembic_head_matches":false}"#,
            r#"{"status":"degraded","database":"ok","frontend_dist_present":true,
                "schema_heal_failed":true}"#,
            // Degraded for a reason that does not.
            r#"{"status":"degraded","database":"error","frontend_dist_present":true}"#,
            r#"{"status":"degraded","database":"ok","frontend_dist_present":false}"#,
            // Fields absent, renamed or of an unexpected type.
            r#"{"status":"degraded"}"#,
            r#"{"status":"something-new","database":"error"}"#,
            r#"{}"#,
        ];

        for json in bodies {
            let ready = judged_ready(json);
            let attachable = blocking_fault(&body(json)).is_none();
            assert_eq!(
                ready, attachable,
                "the two judgements disagree about this backend: {json}"
            );
        }
    }

    #[test]
    fn a_stale_migration_head_does_not_cost_a_user_a_second_backend() {
        // The regression, named. A backend whose schema is behind reports
        // status=degraded and alembic_head_matches=false, and it is serving its
        // users. Rejecting it did not mean looking elsewhere; it meant starting
        // a second backend against the first one's data directory.
        let json = r#"{"status":"degraded","version":"1.0.0","database":"ok",
            "frontend_dist_present":true,"alembic_head_matches":false}"#;

        assert!(judged_ready(json), "the app must still open");
        assert!(
            blocking_fault(&body(json)).is_none(),
            "and the launcher must attach to it rather than start another backend"
        );
    }

    #[test]
    fn a_head_that_cannot_be_determined_is_not_a_fault() {
        // What the desktop build actually reports. It ships no migration tree,
        // so the head comparison answers null forever. Null is "I could not
        // tell", and I-could-not-tell must never be the reason a second backend
        // is started.
        for json in [
            r#"{"status":"healthy","database":"ok","frontend_dist_present":true,
                "alembic_head_matches":null}"#,
            r#"{"status":"healthy","database":"ok","frontend_dist_present":true}"#,
        ] {
            assert!(judged_ready(json), "got a fault for: {json}");
            assert!(blocking_fault(&body(json)).is_none(), "got a fault for: {json}");
        }
    }

    #[test]
    fn the_faults_that_stop_everything_still_stop_it() {
        // The other polarity. A shared question that never finds a fault would
        // pass the agreement test above and put users in front of an
        // application shell with every request inside it failing.
        let no_database = r#"{"status":"degraded","database":"error","frontend_dist_present":true}"#;
        let reason = blocking_fault(&body(no_database)).expect("a dead database is a fault");
        assert!(reason.contains("database"), "got: {reason}");
        assert!(!judged_ready(no_database));

        let no_frontend = r#"{"status":"degraded","database":"ok","frontend_dist_present":false}"#;
        let reason = blocking_fault(&body(no_frontend)).expect("no application files is a fault");
        assert!(reason.contains("application files"), "got: {reason}");
        assert!(!judged_ready(no_frontend));
    }

    #[test]
    fn an_unreadable_body_keeps_meaning_two_different_things() {
        // Not an oversight, and not to be tidied. A body that will not parse
        // means "open the user's own installation" to judge_health and "do not
        // trust this stranger" to the attach probe, because the two are asking
        // about different machines. The shared question sits below the parse in
        // both, so it never gets the chance to flatten them.
        assert!(
            judged_ready("not json at all"),
            "a body we cannot read must not hold a user out of their own install"
        );
        assert!(
            serde_json::from_str::<serde_json::Value>("not json at all").is_err(),
            "and the attach probe rejects on exactly this parse failing"
        );
    }

    #[test]
    fn the_timeout_message_names_the_step_the_backend_was_on() {
        let stage = (
            "pg".to_string(),
            "Recovering the local database".to_string(),
        );
        let quiet = startup_timeout_message(
            Some(&stage),
            &TimeoutKind::WentQuiet(Duration::from_secs(300)),
        );

        assert!(
            quiet.contains("preparing the local database"),
            "the step has to be named, got: {quiet}"
        );
        assert!(
            quiet.contains("Recovering the local database"),
            "got: {quiet}"
        );
        assert!(
            quiet.contains("5 minutes"),
            "the silence has to be quantified, got: {quiet}"
        );

        let slow = startup_timeout_message(Some(&stage), &TimeoutKind::TookTooLong);
        assert!(slow.contains("preparing the local database"), "got: {slow}");
        // A backend that kept talking is slow, not unresponsive, and the two
        // must not be described in the same words.
        assert!(!slow.contains("stopped responding"), "got: {slow}");
    }

    #[test]
    fn the_timeout_message_falls_back_when_no_step_was_reported() {
        // Nothing was ever heard from the backend, so there is nothing to name
        // and the old wording is the honest one.
        let message = startup_timeout_message(None, &TimeoutKind::TookTooLong);
        assert!(message.contains("did not start in time"), "got: {message}");
        assert!(
            message.contains("info@datadrivenconstruction.io"),
            "got: {message}"
        );
    }

    #[test]
    fn every_boot_stage_id_has_words_of_its_own() {
        // The ids the backend and the launcher actually emit. A new stage that
        // is not described here reads as the generic fallback, which is the
        // failure this whole change is about.
        for id in ["sidecar", "pg", "migrate", "model", "server", "open"] {
            assert_ne!(
                describe_stage(id),
                describe_stage("something-else"),
                "stage {id} has no words of its own"
            );
        }
    }

    #[test]
    fn progress_latches_the_last_output_and_the_last_stage() {
        let progress = BootProgress::new();
        assert!(progress.stage().is_none());

        progress.saw_stage("pg", "Starting embedded PostgreSQL");
        let (id, detail) = progress.stage().expect("a stage was seen");
        assert_eq!(id, "pg");
        assert_eq!(detail, "Starting embedded PostgreSQL");

        std::thread::sleep(Duration::from_millis(60));
        assert!(
            progress.quiet_for() >= Duration::from_millis(50),
            "silence has to accumulate while nothing is written"
        );

        progress.saw_output();
        assert!(
            progress.quiet_for() < Duration::from_millis(50),
            "any line at all has to reset the silence"
        );
        // Output is not a stage: what the backend was doing is still the last
        // step it named.
        assert_eq!(progress.stage().expect("still latched").0, "pg");
    }

    #[test]
    fn a_backend_that_exits_is_seen_to_exit_and_one_that_does_not_is_not() {
        // This is what decides which of the three stop steps the log reports.
        // If a clean shutdown were not observed, the launcher would announce a
        // forced kill after a stop that was in fact graceful - the exact kind
        // of misleading log this work exists to remove.
        let exited = Arc::new(AtomicBool::new(false));
        let flag = exited.clone();
        std::thread::spawn(move || {
            std::thread::sleep(Duration::from_millis(150));
            flag.store(true, Ordering::SeqCst);
        });

        let started = Instant::now();
        assert!(
            wait_until_exited(&exited, Duration::from_secs(5)),
            "an exit that happens inside the budget has to be seen"
        );
        assert!(
            started.elapsed() < Duration::from_secs(2),
            "and seen when it happens, not after the whole budget"
        );

        // The other polarity: a backend that never goes has to be reported as
        // still running, so the next step actually runs.
        let stuck = Arc::new(AtomicBool::new(false));
        let started = Instant::now();
        assert!(!wait_until_exited(&stuck, Duration::from_millis(300)));
        assert!(
            started.elapsed() >= Duration::from_millis(250),
            "giving up early would force-kill a backend still shutting down"
        );
    }

    /// The grant on the application window has to cover every address the
    /// launcher can serve the application from, measured with Tauri's matcher.
    ///
    /// `capabilities/app-window.json` is the whole of what stands between the
    /// application page and an access control list that refuses every command
    /// it invokes, and the user-visible shape of that refusal is that every
    /// outbound link in the product does nothing at all when clicked. The grant
    /// hangs on one string, `http://127.0.0.1:*`, and whether that string
    /// covers `http://127.0.0.1:8732/boq` is a question about Tauri's URL
    /// pattern parser and not about anything written here: `RemoteUrlPattern`
    /// substitutes a wildcard for a pathname that is absent or bare `/`, which
    /// is why a pattern carrying no path still covers every route. A
    /// reimplementation of that rule can agree with it today and part company
    /// with it on the next upgrade, so this asks the real type, the one the
    /// running application consults, rather than a model of it.
    ///
    /// Both the default port and an arbitrary one are asserted because the
    /// launcher picks between them at runtime: 8732 when it is free and any
    /// free port otherwise. A pattern narrowed to the default port would leave
    /// the second copy of the app started on a machine with dead links, and a
    /// gate that only ever tried 8732 would call that fixed.
    ///
    /// The non-loopback cases are the other half and are not decoration. This
    /// capability grants the OS opener to whatever origin it names, so a
    /// pattern that widened to a host on the network, or to the internet, would
    /// hand that opener to a page nobody on this machine wrote.
    #[test]
    fn the_app_window_grant_covers_every_address_the_launcher_can_serve() {
        use tauri::utils::acl::RemoteUrlPattern;
        use tauri::Url;

        const CAPABILITY: &str = include_str!("../capabilities/app-window.json");
        let capability: serde_json::Value =
            serde_json::from_str(CAPABILITY).expect("app-window.json has to be valid JSON");

        let patterns: Vec<RemoteUrlPattern> = capability["remote"]["urls"]
            .as_array()
            .expect(
                "the application window is a remote origin as far as the ACL is concerned, so \
                 the capability that grants it anything needs a remote.urls list",
            )
            .iter()
            .map(|entry| {
                entry
                    .as_str()
                    .expect("a URL pattern is written as a string")
                    .parse::<RemoteUrlPattern>()
                    .expect("Tauri has to be able to parse the pattern this build ships")
            })
            .collect();
        assert!(
            !patterns.is_empty(),
            "an empty remote.urls grants the application window nothing, which is the state \
             where every outbound link is silently dead"
        );

        let covered = |url: &str| {
            let parsed = Url::parse(url).expect("the addresses below are valid URLs");
            patterns.iter().any(|pattern| pattern.test(&parsed))
        };

        for served in [
            // The bare origin, which is where the launcher navigates.
            "http://127.0.0.1:8732/",
            // A route, which is where the user is by the time they click a link.
            "http://127.0.0.1:8732/boq",
            // The arbitrary free port, taken whenever 8732 is already in use.
            "http://127.0.0.1:49512/",
            // A deep route carrying a query and a fragment, which is what the
            // single-page router leaves in the address bar.
            "http://127.0.0.1:49512/projects/1/boq?tab=items#row-3",
        ] {
            assert!(
                covered(served),
                "the launcher serves the application at {served}, so a window there has to be \
                 covered by the grant or every command it invokes is refused"
            );
        }

        for elsewhere in [
            "http://erp.example.invalid/",
            "https://erp.example.invalid/",
            "http://192.168.1.10:8732/",
        ] {
            assert!(
                !covered(elsewhere),
                "{elsewhere} is not a server this launcher started, and this capability hands \
                 the OS opener to whatever it covers"
            );
        }
    }

    /// The grant has to resolve, through the permission file, to the command
    /// that opens a link.
    ///
    /// A capability names permission identifiers, a permission names commands,
    /// and only the second half decides what the page may call. Renaming a
    /// permission, or dropping one from the list, severs the grant while
    /// leaving both files reading plausibly, and the failure is silent: the
    /// access control list refuses `open_external_url`, the frontend catches a
    /// rejected promise, and the link does nothing. So this resolves the chain
    /// rather than checking that a file contains a name.
    #[test]
    fn the_app_window_grant_reaches_the_commands_that_open_a_link() {
        use std::collections::{HashMap, HashSet};

        const CAPABILITY: &str = include_str!("../capabilities/app-window.json");
        const PERMISSIONS: &str = include_str!("../permissions/app-commands.json");

        let capability: serde_json::Value =
            serde_json::from_str(CAPABILITY).expect("app-window.json has to be valid JSON");
        let declared: serde_json::Value =
            serde_json::from_str(PERMISSIONS).expect("app-commands.json has to be valid JSON");

        let mut commands_of: HashMap<&str, Vec<&str>> = HashMap::new();
        for permission in declared["permission"]
            .as_array()
            .expect("the application declares its permissions as a list")
        {
            let identifier = permission["identifier"]
                .as_str()
                .expect("every permission is named by an identifier");
            let allowed = permission["commands"]["allow"]
                .as_array()
                .map(|list| list.iter().filter_map(|c| c.as_str()).collect())
                .unwrap_or_default();
            commands_of.insert(identifier, allowed);
        }

        let mut members_of: HashMap<&str, Vec<&str>> = HashMap::new();
        for set in declared
            .get("set")
            .and_then(|s| s.as_array())
            .map(Vec::as_slice)
            .unwrap_or_default()
        {
            let identifier = set["identifier"]
                .as_str()
                .expect("every permission set is named by an identifier");
            let members = set["permissions"]
                .as_array()
                .map(|list| list.iter().filter_map(|p| p.as_str()).collect())
                .unwrap_or_default();
            members_of.insert(identifier, members);
        }

        // Expand the capability's identifiers into commands, following sets one
        // level at a time and never twice, so a set that names itself cannot
        // spin here.
        let mut granted: HashSet<&str> = HashSet::new();
        let mut seen: HashSet<&str> = HashSet::new();
        let mut pending: Vec<&str> = capability["permissions"]
            .as_array()
            .expect("a capability grants a list of permissions")
            .iter()
            .filter_map(|p| p.as_str())
            .collect();
        while let Some(identifier) = pending.pop() {
            if !seen.insert(identifier) {
                continue;
            }
            if let Some(commands) = commands_of.get(identifier) {
                granted.extend(commands);
            } else if let Some(members) = members_of.get(identifier) {
                pending.extend(members);
            }
        }

        for command in ["open_external_url", "open_app_in_browser", "reveal_path_in_os"] {
            assert!(
                granted.contains(command),
                "the application page calls {command} to put a link in front of the user, and \
                 an ungranted command is refused before it runs"
            );
        }
    }

    /// What a reveal request is allowed to open.
    ///
    /// The rule is what stands between a page naming a path and the operating
    /// system being asked to open it, so it is tested on the two answers that
    /// matter rather than on the happy one alone: a path inside the workspace
    /// resolves to a folder, and a path outside it resolves to a refusal.
    ///
    /// Real directories are created for this. `folder_to_reveal` asks the
    /// filesystem whether the target is a directory, so a test built out of
    /// invented paths would exercise a different branch than a user does and
    /// would keep passing while the real one broke.
    #[test]
    fn a_reveal_only_ever_opens_a_folder_inside_the_workspace() {
        let base = std::env::temp_dir().join(format!("oe-reveal-{}", uuid::Uuid::new_v4().simple()));
        let root = base.join("workspace");
        let inner = root.join("files").join("project");
        std::fs::create_dir_all(&inner).expect("the test needs a workspace on disk");
        let outside = base.join("elsewhere");
        std::fs::create_dir_all(&outside).expect("the test needs a folder outside it");

        let file = inner.join("drawing.pdf");
        std::fs::write(&file, b"x").expect("the test needs a file to reveal");
        let stray = outside.join("secret.txt");
        std::fs::write(&stray, b"x").expect("the test needs a file outside the workspace");

        let root_c = std::fs::canonicalize(&root).expect("the workspace resolves");
        let file_c = std::fs::canonicalize(&file).expect("the file resolves");
        let inner_c = std::fs::canonicalize(&inner).expect("the folder resolves");
        let stray_c = std::fs::canonicalize(&stray).expect("the stray file resolves");

        // A file inside the workspace is answered with its folder, never itself,
        // which is what keeps the shell from launching it by extension.
        assert_eq!(
            folder_to_reveal(&root_c, &file_c).expect("a file in the workspace can be shown"),
            inner_c,
            "a file must be shown by opening the folder that holds it"
        );

        // A folder inside the workspace is itself.
        assert_eq!(
            folder_to_reveal(&root_c, &inner_c).expect("a folder in the workspace can be shown"),
            inner_c
        );

        // Anything outside is refused, and the workspace root itself is inside.
        assert!(
            folder_to_reveal(&root_c, &stray_c).is_err(),
            "a path outside the workspace must be refused"
        );
        assert!(folder_to_reveal(&root_c, &root_c).is_ok(), "the workspace itself is inside it");

        // A sibling whose name merely begins with the workspace's name is
        // outside. This is the case a string prefix gets wrong and
        // Path::starts_with gets right, so it is asserted rather than assumed.
        let sibling = base.join("workspace-backup");
        std::fs::create_dir_all(&sibling).expect("the test needs a lookalike sibling");
        let sibling_c = std::fs::canonicalize(&sibling).expect("the sibling resolves");
        assert!(
            folder_to_reveal(&root_c, &sibling_c).is_err(),
            "a folder whose name only starts with the workspace's name is not in it"
        );

        let _ = std::fs::remove_dir_all(&base);
    }

    /// One line of a fabricated directory listing.
    ///
    /// The rule the sweep runs on takes nothing but this, which is what lets
    /// every interesting case be written down here instead of being built out of
    /// real extractions on a real disk.
    fn listed(name: &str, hours_old: u64) -> TempEntry {
        TempEntry {
            name: name.to_string(),
            is_dir: true,
            age: Some(Duration::from_secs(hours_old * 60 * 60)),
            in_use: false,
        }
    }

    const AN_HOUR: Duration = Duration::from_secs(60 * 60);

    /// A temporary directory of this test's own, removed by the caller.
    fn fixture_dir(label: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "oe-{label}-{}",
            uuid::Uuid::new_v4().simple()
        ));
        std::fs::create_dir_all(&dir).expect("a fixture directory");
        dir
    }

    /// An abandoned extraction is the only thing the sweep will remove.
    ///
    /// Every other row is a way of saying no, and they are here together because
    /// the danger in this feature is not a missed directory, it is a removed one.
    #[test]
    fn an_abandoned_extraction_is_the_only_thing_the_sweep_removes() {
        assert_eq!(
            sweep_verdict(&listed("_MEI195482", 5), AN_HOUR),
            SweepVerdict::Remove
        );

        for (entry, expected, why) in [
            (
                TempEntry {
                    is_dir: false,
                    ..listed("_MEI195482", 5)
                },
                SweepVerdict::KeepNotAnExtraction,
                "a file that happens to be named like one is not one",
            ),
            (
                listed("chrome_installer.log", 5),
                SweepVerdict::KeepNotAnExtraction,
                "a temporary folder is full of other people's work",
            ),
            (
                listed("_MEI", 5),
                SweepVerdict::KeepNotAnExtraction,
                "the prefix alone is not a name the bootloader generates",
            ),
            (
                listed("_MEI195482", 0),
                SweepVerdict::KeepTooYoung,
                "a start happening right now owns a directory this new",
            ),
            (
                TempEntry {
                    age: None,
                    ..listed("_MEI195482", 5)
                },
                SweepVerdict::KeepAgeUnknown,
                "nothing is known about it, so nothing is done to it",
            ),
            (
                TempEntry {
                    in_use: true,
                    ..listed("_MEI195482", 5)
                },
                SweepVerdict::KeepInUse,
                "a live program is still running out of it",
            ),
        ] {
            assert_eq!(
                sweep_verdict(&entry, AN_HOUR),
                expected,
                "{why}: {:?}",
                entry.name
            );
        }
    }

    /// Neither the name nor the age may carry this decision on its own.
    ///
    /// The directory in the report, `_MEI195482`, had a perfect name and was
    /// hours old, and an embedded PostgreSQL was still serving out of it. Age
    /// only ever grows, so a rule built on it says yes more confidently the
    /// longer the process it would kill has been running.
    #[test]
    fn a_perfect_name_and_a_long_life_still_do_not_add_up_to_a_removal() {
        for hours in [1, 24, 24 * 365] {
            assert_eq!(
                sweep_verdict(
                    &TempEntry {
                        in_use: true,
                        ..listed("_MEI195482", hours)
                    },
                    AN_HOUR
                ),
                SweepVerdict::KeepInUse,
                "{hours} hours old and still in use"
            );
        }
    }

    /// The reverse check, on the real sweep and not on the rule.
    ///
    /// A file held open the way a running program holds its own executable, in a
    /// directory shaped like the one from the report, with a data file beside it
    /// standing in for the `timezonesets` that a live postmaster went FATAL on
    /// when its extraction lost files underneath it.
    ///
    /// The last two assertions are the ones that matter. Counting what was kept
    /// proves the holder was noticed; only looking for the files proves that
    /// nothing was taken on the way to noticing, which is the difference between
    /// this sweep and the accident it exists to avoid.
    #[cfg(windows)]
    #[test]
    fn an_extraction_a_program_is_still_running_out_of_survives_intact() {
        use std::os::windows::fs::OpenOptionsExt;

        let root = fixture_dir("sweep-live");
        let extraction = root.join("_MEI195482");
        let bin = extraction.join("pgserver").join("bin");
        let share = extraction.join("pgserver").join("share").join("timezonesets");
        std::fs::create_dir_all(&bin).expect("a fixture bin directory");
        std::fs::create_dir_all(&share).expect("a fixture share directory");
        let postgres = bin.join("postgres.exe");
        let timezones = share.join("Default");
        std::fs::write(&postgres, b"stands in for a postmaster").expect("a fixture executable");
        std::fs::write(&timezones, b"@Default").expect("a fixture data file");
        // Sorts before `pgserver`, so a removal that walked the directory in the
        // order the filesystem hands it back would take this file before it ever
        // reached the executable it cannot take. That is what makes the last
        // assertion below a test of the removal order rather than of luck.
        let library = extraction.join("base_library.zip");
        std::fs::write(&library, b"stands in for the payload").expect("a fixture archive");

        let held = std::fs::OpenOptions::new()
            .read(true)
            .share_mode(0)
            .open(&postgres)
            .expect("hold the executable open the way a running program does");

        let report = sweep_extractions_in(
            &root,
            ClusterState::Stopped,
            Duration::ZERO,
            Duration::from_secs(30),
            &mut || {},
        );

        assert!(postgres.exists(), "the held executable was removed");
        assert!(
            timezones.exists(),
            "a data file the holder reads later was removed, which is the failure in the log"
        );
        assert!(
            library.exists(),
            "a file that sorts ahead of the held one was removed, so the removal order is \
walking the directory rather than taking the held files first"
        );
        assert_eq!(report.removed, 0, "a directory in use was removed");
        assert_eq!(report.kept_in_use, 1, "the file held open was not noticed");

        drop(held);
        let _ = std::fs::remove_dir_all(&root);
    }

    /// And an extraction nothing is using goes, with its neighbours left alone.
    ///
    /// The control for the test above: the same sweep, the same folder, and the
    /// only thing that changed is that nothing holds the files.
    #[cfg(windows)]
    #[test]
    fn an_extraction_nothing_is_using_is_removed_and_its_neighbours_are_not() {
        let root = fixture_dir("sweep-orphan");
        let orphan = root.join("_MEI700001");
        std::fs::create_dir_all(orphan.join("numpy")).expect("a fixture package directory");
        std::fs::write(orphan.join("numpy").join("_multiarray.pyd"), vec![0u8; 2048])
            .expect("a fixture extension module");
        std::fs::write(orphan.join("base_library.zip"), vec![0u8; 4096])
            .expect("a fixture archive");

        let stranger = root.join("chrome_BITS_1234");
        std::fs::create_dir_all(&stranger).expect("a fixture stranger");
        let not_ours = stranger.join("payload.bin");
        std::fs::write(&not_ours, b"belongs to somebody else").expect("a fixture file");

        let report = sweep_extractions_in(
            &root,
            ClusterState::Stopped,
            Duration::ZERO,
            Duration::from_secs(30),
            &mut || {},
        );

        assert_eq!(report.removed, 1);
        assert_eq!(report.bytes_freed, 2048 + 4096);
        assert!(!orphan.exists(), "the abandoned extraction is still there");
        assert!(not_ours.exists(), "a directory that is not ours was touched");

        let _ = std::fs::remove_dir_all(&root);
    }

    /// A live cluster stops the sweep before it looks at anything.
    ///
    /// The one in the report was detached and had outlived the launcher that
    /// started it, so it was not a child of anything this process could ask.
    /// What it did leave is a pidfile in the data directory, which is the same
    /// file the backend reads in `embedded_pg.py`.
    #[cfg(windows)]
    #[test]
    fn a_running_cluster_suspends_the_sweep_entirely() {
        let root = fixture_dir("sweep-cluster");
        let orphan = root.join("_MEI700002");
        std::fs::create_dir_all(&orphan).expect("a fixture extraction");
        std::fs::write(orphan.join("base_library.zip"), b"payload").expect("a fixture file");

        for state in [ClusterState::Running, ClusterState::Unknown] {
            let report = sweep_extractions_in(
                &root,
                state,
                Duration::ZERO,
                Duration::from_secs(30),
                &mut || {},
            );
            assert_eq!(report.removed, 0, "{state:?} swept anyway");
            assert!(report.skipped.is_some(), "{state:?} did not say why it stopped");
            assert!(orphan.exists(), "{state:?} removed a directory");
        }

        let _ = std::fs::remove_dir_all(&root);
    }

    /// A directory written minutes ago is left for a later run.
    #[cfg(windows)]
    #[test]
    fn a_freshly_written_extraction_is_left_alone() {
        let root = fixture_dir("sweep-young");
        let fresh = root.join("_MEI700003");
        std::fs::create_dir_all(&fresh).expect("a fixture extraction");
        std::fs::write(fresh.join("base_library.zip"), b"payload").expect("a fixture file");

        let report = sweep_extractions_in(
            &root,
            ClusterState::Stopped,
            AN_HOUR,
            Duration::from_secs(30),
            &mut || {},
        );

        assert_eq!(report.removed, 0);
        assert!(fresh.exists());

        let _ = std::fs::remove_dir_all(&root);
    }

    /// The pidfile is what says whether a cluster is running, and an unreadable
    /// one says nothing rather than saying no.
    #[test]
    fn the_pidfile_is_what_says_a_cluster_is_running() {
        let dir = fixture_dir("pidfile");
        let pidfile = dir.join("postmaster.pid");

        assert_eq!(
            cluster_state_of(&pidfile),
            ClusterState::Stopped,
            "no pidfile at all means no cluster"
        );

        // PostgreSQL writes the postmaster's process id on the first line and
        // five more lines under it. This process is the one id known to be alive.
        std::fs::write(
            &pidfile,
            format!("{}\n/data\n1750000000\n5432\n\n127.0.0.1\n", std::process::id()),
        )
        .expect("write a pidfile");
        assert_eq!(cluster_state_of(&pidfile), ClusterState::Running);

        std::fs::write(&pidfile, "\n").expect("write an empty pidfile");
        assert_eq!(
            cluster_state_of(&pidfile),
            ClusterState::Unknown,
            "a pidfile that cannot be read must not read as an absent one"
        );

        let _ = std::fs::remove_dir_all(&dir);
    }

    /// Only a measured number may refuse to start the backend.
    ///
    /// A refusal is a new way for this launcher to stop a machine that would
    /// have worked, so a measurement that could not be taken has to mean carry
    /// on, and so does a drive that is merely tight.
    #[test]
    fn only_a_measured_number_refuses_to_start_the_backend() {
        assert_eq!(
            space_verdict(None, EXTRACTION_SPACE_FLOOR, EXTRACTION_SPACE_COMFORT),
            SpaceVerdict::Unknown
        );
        assert_eq!(
            space_verdict(
                Some(EXTRACTION_SPACE_FLOOR - 1),
                EXTRACTION_SPACE_FLOOR,
                EXTRACTION_SPACE_COMFORT
            ),
            SpaceVerdict::TooLittle
        );
        assert_eq!(
            space_verdict(
                Some(EXTRACTION_SPACE_FLOOR),
                EXTRACTION_SPACE_FLOOR,
                EXTRACTION_SPACE_COMFORT
            ),
            SpaceVerdict::Tight
        );
        assert_eq!(
            space_verdict(
                Some(EXTRACTION_SPACE_COMFORT),
                EXTRACTION_SPACE_FLOOR,
                EXTRACTION_SPACE_COMFORT
            ),
            SpaceVerdict::Enough
        );
    }

    /// The refusal fires only where unpacking cannot succeed.
    ///
    /// The floor has to sit below what an extraction costs rather than near it.
    /// A floor at the estimate would refuse to start on every machine inside the
    /// band where the bootloader might still have managed, and this launcher
    /// does not measure that band well enough to be right about it.
    #[test]
    fn the_refusal_sits_below_what_an_extraction_costs() {
        assert!(
            EXTRACTION_SPACE_FLOOR < EXTRACTION_ESTIMATED_BYTES,
            "a refusal at or above the estimate stops machines that would have started"
        );
        assert!(
            EXTRACTION_SPACE_COMFORT >= EXTRACTION_ESTIMATED_BYTES,
            "there is no point warning about a drive that has room for an extraction"
        );
    }

    /// The message names the number and the folder it is about.
    ///
    /// The folder because the drive that matters is not the one anybody would
    /// think to check, it is whichever one holds the temporary folder, and the
    /// number because "not enough disk space" can be read twice and still leave
    /// somebody with nothing to do.
    #[test]
    fn the_out_of_space_message_carries_the_number_and_the_folder() {
        let folder = "C:\\Users\\example\\AppData\\Local\\Temp";
        let message = out_of_space_message(folder, 412 * 1024 * 1024);

        assert!(message.contains("412 MB"), "{message}");
        assert!(message.contains(folder), "{message}");
        assert!(message.contains("1.5 GB"), "{message}");
    }

    /// Sizes are shown the way a person reads them.
    #[test]
    fn a_size_is_shown_in_the_units_somebody_can_act_on() {
        assert_eq!(human_bytes(0), "0 KB");
        assert_eq!(human_bytes(412 * 1024 * 1024), "412 MB");
        assert_eq!(human_bytes(EXTRACTION_ESTIMATED_BYTES), "1.5 GB");
    }

    /// The bootloader failure now arrives with the measurement that settles it.
    ///
    /// `classify_bootloader_failure` names two usual causes and cannot choose
    /// between them from the text, because the text does not contain the answer.
    /// This is the half that does, and it has to attach without disturbing what
    /// was already there.
    #[cfg(windows)]
    #[test]
    fn a_bootloader_failure_is_paired_with_what_the_disk_actually_had() {
        // The measurement is taken on a fixture, not on the real extraction
        // root. All the note needs is a directory that exists on a drive, and
        // creating the product's own folder here would leave one behind in the
        // profile of everybody who runs this suite.
        extraction_dir().expect("Windows resolves an extraction root");
        let dir = fixture_dir("space-note");
        let note = extraction_space_note(&dir);
        assert!(
            note.contains("free"),
            "the note must say what was free: {note}"
        );

        let failure =
            classify_bootloader_failure(ISSUE_462_STDERR).expect("still recognised as one");
        let shown = format!("{}{note}", failure.message);
        assert!(shown.contains("free space"), "{shown}");
        assert!(!shown.contains("[PYI-"), "raw bootloader noise leaked: {shown}");

        let _ = std::fs::remove_dir_all(&dir);
    }

    /// The launcher sweeps the folder the spec unpacks into, or it sweeps nothing.
    ///
    /// The two live in different languages and neither can read the other at
    /// build time, so this reads the spec off disk and pairs them. Get it wrong
    /// and nothing anywhere goes red: the bootloader would unpack into one
    /// directory, the sweep would tidy another, and the only symptom would be a
    /// disk filling up exactly as it did before this was written.
    #[test]
    fn the_sweep_looks_where_the_spec_unpacks() {
        let spec = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("pyinstaller.spec");
        let text = std::fs::read_to_string(&spec)
            .unwrap_or_else(|e| panic!("the spec must be readable at {}: {e}", spec.display()));

        // The whole assignment, closing quote included, rather than the path on
        // its own. A substring match reads a spec that unpacks into
        // `...\extraction` as agreeing with a launcher that sweeps
        // `...\extract`, which is measured: it passed that mutation happily.
        let assignment = format!("_WINDOWS_RUNTIME_TMPDIR = r\"{EXTRACTION_ROOT_SPEC_LITERAL}\"");
        assert!(
            text.contains(&assignment),
            "desktop/pyinstaller.spec no longer sets {assignment}, so the sidecar unpacks \
somewhere this launcher does not sweep"
        );
        assert!(
            text.contains("runtime_tmpdir=(_WINDOWS_RUNTIME_TMPDIR"),
            "the spec still holds the path but no longer hands it to the bootloader"
        );
    }

    /// Anything the environment cannot answer gives no path at all.
    ///
    /// Windows leaves an unresolved `%NAME%` standing in the string, so the
    /// dangerous failure here is not an error, it is a plausible looking path
    /// with a literal `%LOCALAPPDATA%` in it. The sweep would then create and
    /// tidy a folder of its own invention while the sidecar unpacked elsewhere.
    #[test]
    fn a_name_the_machine_cannot_answer_produces_no_path_at_all() {
        let known = |name: &str| match name {
            "LOCALAPPDATA" => Some(r"C:\Users\somebody\AppData\Local".to_string()),
            "EMPTY" => Some("   ".to_string()),
            _ => None,
        };

        assert_eq!(
            expand_windows_env(EXTRACTION_ROOT_SPEC_LITERAL, &known).as_deref(),
            Some(r"C:\Users\somebody\AppData\Local\OpenConstructionERP\extract")
        );
        assert_eq!(expand_windows_env(r"%NOT_SET%\extract", &known), None);
        assert_eq!(expand_windows_env(r"%EMPTY%\extract", &known), None);
        assert_eq!(expand_windows_env(r"%LOCALAPPDATA\extract", &known), None);
        assert_eq!(
            expand_windows_env(r"C:\fixed\path", &known).as_deref(),
            Some(r"C:\fixed\path")
        );
    }

    /// And on this machine it resolves to somewhere absolute that we own.
    #[cfg(windows)]
    #[test]
    fn the_resolved_root_is_ours_and_absolute() {
        let root = extraction_root().expect("Windows always has LOCALAPPDATA");
        assert!(root.is_absolute(), "{}", root.display());
        assert!(
            root.ends_with("OpenConstructionERP/extract")
                || root.ends_with(r"OpenConstructionERP\extract"),
            "the root must be the one we own: {}",
            root.display()
        );
        assert!(
            !root.starts_with(std::env::temp_dir()),
            "the whole point is that this is not the system temporary folder: {}",
            root.display()
        );
    }

    /// A sweep with no root to sweep does nothing, loudly enough to read.
    ///
    /// The unresolvable case is the one that must not improvise. There is no
    /// fallback to the system temporary folder here on purpose: that folder is
    /// full of other vendors' extractions, and a launcher that cannot say where
    /// its own went has no business deleting anything.
    #[test]
    fn without_a_root_of_our_own_nothing_is_swept() {
        let nowhere = fixture_dir("mei_absent_root").join("never_created");
        let report = sweep_extractions_in(
            &nowhere,
            ClusterState::Stopped,
            AN_HOUR,
            Duration::from_secs(5),
            &mut || panic!("nothing may be removed when there is nothing to sweep"),
        );
        assert_eq!(report.removed, 0);
        assert!(report.skipped.is_some(), "a missing root must be reported");
    }
}
