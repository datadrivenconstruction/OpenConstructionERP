// OpenConstructionERP Desktop, launcher-side update check.
//
// Why this exists, and why it lives in the launcher rather than in the app.
//
// The application already tells a user about a new release from inside itself:
// `GET /api/system/version-check` answers the question and a sidebar card shows
// it. That whole path needs a backend that started. Version 15.0.0 shipped
// without the locale catalogue its sidecar reads while starting, so on every
// machine the backend died during startup and the window never got past the
// splash. The people it happened to are exactly the people who most need to
// hear that a fixed build exists, and they are the only people the in-app
// notice can never reach, because the notice is served by the thing that did
// not start.
//
// So the launcher can ask the question for itself, over one plain HTTPS GET, and
// say the answer in the failure window that otherwise only offers to mail a log
// file.
//
// ONLY WHEN ASKED. It used to send that GET on every start, healthy or not, in
// the background. That is a connection the user did not start, on every launch,
// and a desktop app that phones out unasked is exactly what reputation checkers
// and careful administrators object to. Now the failure screen carries a
// "Check for a newer version" button, and the GET happens when it is pressed.
// A healthy start sends nothing; inside the application, About offers the same
// check through the backend.
//
// A VERSION CHECK THAT CAN STOP THE PRODUCT FROM STARTING IS A WORSE BUG THAN
// THE ONE IT IS THERE TO CATCH. Every failure here - no network, a rate-limited
// API, a proxy answering with its own login page, a machine with no DNS, a
// malformed tag - ends in exactly one thing: nothing is said, and startup is
// untouched. Nothing in this file is ever awaited by the startup path.
//
// Privacy. This is an outbound request to a third party from an AGPL product
// that people run on private networks, so: it is one anonymous
// GET, it sends no identifier, no telemetry and no version of ours (the
// user-agent below is a bare product token with no version in it, because
// GitHub rejects a request with no user-agent at all), the notice says on its
// face that GitHub was asked, an administrator can turn it off for a whole
// image with an environment variable, and the user can turn it off from the
// notice itself.

use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::Duration;

use tauri::Manager;

/// The repository the desktop build is published from.
const REPO: &str = "datadrivenconstruction/OpenConstructionERP";

/// Bare product token. GitHub answers 403 to a request that carries no
/// user-agent at all, so one is required; it deliberately carries no version,
/// no machine name and nothing else that would report anything outward.
const USER_AGENT: &str = "OpenConstructionERP-Desktop";

/// Short on purpose. This runs beside startup and must never be the reason
/// anything waits, so a proxy that accepts a connection and then says nothing
/// costs five seconds in a background task and nothing anywhere else.
const REQUEST_TIMEOUT: Duration = Duration::from_secs(5);

/// Administrators imaging machines set this to keep the launcher off the
/// network. Sibling of `VITE_DISABLE_UPDATE_CHECK`, which turns off the
/// in-app notice at build time; this one turns off the launcher's own check at
/// run time. Any of `1`, `true`, `yes`, `on` (any case) disables it.
pub const DISABLE_ENV: &str = "OE_DISABLE_UPDATE_CHECK";

/// The user's own opt-out, written by the "Turn off update checks" link on the
/// notice. It has to be a file rather than a setting in the database, because
/// the one moment this feature matters is the moment the database is not there.
const OPT_OUT_FILE: &str = "no-update-check";

/// The version the user pressed "Not now" on. Separate from the opt-out above,
/// because declining one version is not the same as declining the feature.
const DECLINED_FILE: &str = "update-declined";

/// A published release that is newer than the running build.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AvailableUpdate {
    /// Version as published, with any leading `v` already stripped.
    pub version: String,
    /// Page to send the user to. Always a github.com release page.
    pub url: String,
}

/// The answer, once we have one. `None` means "not known yet or nothing newer".
static LATEST: Mutex<Option<AvailableUpdate>> = Mutex::new(None);
/// Set the first time startup reports a fatal error.
static STARTUP_FAILED: AtomicBool = AtomicBool::new(false);
/// Set once the webview has been pointed at the running application.
///
/// The second occasion to speak, and the one that covers a working install.
/// The application carries an update notice of its own, but every place it is
/// mounted sits behind the login screen, so a machine that has just been set up
/// reaches the sign-in page with nothing offering it the newer build. This is
/// the moment that page appears.
static APP_STARTED: AtomicBool = AtomicBool::new(false);
/// Set once the notice has been put on screen, so it is written once however
/// many times the two writers below call in.
static PAINTED: AtomicBool = AtomicBool::new(false);

// --- Version comparison -----------------------------------------------------

/// Parse a dotted version into a sortable tuple of numbers.
///
/// Mirrors `_semver_tuple` in `backend/app/main.py`, deliberately and exactly:
/// the product must not carry two update checkers that disagree about which of
/// two numbers is newer. Each dotted part contributes its leading digits, so
/// `15.1.0rc1` reads as `[15, 1, 0]` and a part with no leading digit reads as
/// `0`. A leading `v` is stripped, because a git tag writes one and a package
/// version does not.
fn version_parts(v: &str) -> Vec<u64> {
    v.trim()
        .trim_start_matches('v')
        .trim_start_matches('V')
        .split('.')
        .map(|part| {
            let digits: String = part.chars().take_while(char::is_ascii_digit).collect();
            digits.parse::<u64>().unwrap_or(0)
        })
        .collect()
}

/// Whether `latest` names a strictly newer release than `current`.
///
/// Zero-pads the shorter side before comparing, so `15.1` and `15.1.0` are the
/// same release rather than one being newer than the other. This is the same
/// rule `_same_version` applies in `backend/app/main.py`; our own tags and our
/// own crate version are both always three-part, so the two checkers cannot
/// reach different answers about a real release either way.
///
/// This is a numeric comparison, never a string one, and the project's own
/// versioning is why that matters rather than being a nicety: the minor runs
/// 0 to 9 and then rolls the major, so `15.0.0` follows `14.9.3`, and a lexical
/// compare would read `"9" > "1"` and conclude the new release was older.
///
/// Anything unparseable reads as `0` and therefore never offers an update. That
/// is the fail-open direction: an API that answers with something we do not
/// understand leaves the user exactly where they were.
pub fn is_newer(latest: &str, current: &str) -> bool {
    let mut a = version_parts(latest);
    let mut b = version_parts(current);
    let width = a.len().max(b.len());
    a.resize(width, 0);
    b.resize(width, 0);
    a > b
}

// --- Reading one release ----------------------------------------------------

/// Pull the release out of the GitHub API body, or decide there is nothing to
/// say about it.
///
/// Returns `None` for a draft or a pre-release (the endpoint used already
/// excludes both, so this is a second lock on the same door), for a body that
/// is not the shape we expect, and for a tag that carries no version number.
fn release_from_json(body: &serde_json::Value) -> Option<AvailableUpdate> {
    if body.get("draft").and_then(|v| v.as_bool()).unwrap_or(false) {
        return None;
    }
    if body.get("prerelease").and_then(|v| v.as_bool()).unwrap_or(false) {
        return None;
    }
    let tag = body.get("tag_name").and_then(|v| v.as_str())?.trim();
    let version = tag.trim_start_matches('v').trim_start_matches('V').trim();
    // A tag with no digits at all is not a version, whatever else it is.
    if version.is_empty() || !version.chars().any(|c| c.is_ascii_digit()) {
        return None;
    }
    // Only ever send the user to github.com. The URL in the body comes from a
    // third party, so it is used only when it is the page we expected, and
    // otherwise replaced with the canonical one we can construct ourselves.
    let url = body
        .get("html_url")
        .and_then(|v| v.as_str())
        .filter(|u| u.starts_with("https://github.com/"))
        .map(str::to_string)
        .unwrap_or_else(|| format!("https://github.com/{REPO}/releases/latest"));
    Some(AvailableUpdate {
        version: version.to_string(),
        url,
    })
}

// --- Turning the check off --------------------------------------------------

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

/// Where the user's own opt-out is recorded, beside the launcher log and the
/// application's data.
fn opt_out_path() -> Option<PathBuf> {
    home_dir().map(|h| h.join(".openestimate").join(OPT_OUT_FILE))
}

/// Where a declined version is remembered, beside the opt-out.
fn declined_path() -> Option<PathBuf> {
    home_dir().map(|h| h.join(".openestimate").join(DECLINED_FILE))
}

/// The version the user last said no to, if they have said no to one.
fn declined_version() -> Option<String> {
    let text = std::fs::read_to_string(declined_path()?).ok()?;
    let version = text.trim().to_string();
    (!version.is_empty()).then_some(version)
}

/// Whether an offer has already been turned down.
///
/// Pure, because the rule is the whole of it and it is easier to get wrong than
/// it looks: saying no once must silence that version and no more than that
/// version. A notice that comes back at every start after the answer was no is
/// not an offer any more, and the person it wears down hardest is the one who
/// has decided to stay where they are for a reason of their own. Compared by
/// version rather than by string equality so that the next release still gets
/// to speak.
fn was_declined(offered: &str, declined: Option<&str>) -> bool {
    match declined {
        Some(declined) => !is_newer(offered, declined),
        None => false,
    }
}

/// Whether a value read from the environment means "yes".
fn env_flag_is_on(raw: &str) -> bool {
    matches!(
        raw.trim().to_ascii_lowercase().as_str(),
        "1" | "true" | "yes" | "on"
    )
}

/// Whether the check may run when the user presses the button.
///
/// Off in a development build and in tests (`debug_assertions` covers both a
/// `cargo run` from the source tree and `cargo test`), and off when an
/// administrator has set the environment variable, which is a policy about the
/// machine. The user's own "Turn off update checks" file is not read here: it
/// switches off checks nobody asked for (the application's in-app notice reads
/// it through the backend), and pressing "Check for a newer version" is asking.
pub fn is_enabled() -> bool {
    if cfg!(debug_assertions) || cfg!(test) {
        return false;
    }
    !std::env::var(DISABLE_ENV).map(|v| env_flag_is_on(&v)).unwrap_or(false)
}

/// Record the user's choice to stop checking, or to start again.
///
/// Best effort by design: a home directory that cannot be written to leaves the
/// user exactly as they were, which is the same place every other failure in
/// this file leaves them.
pub fn set_enabled(enabled: bool) -> Result<(), String> {
    let path = opt_out_path().ok_or_else(|| "Could not resolve your home folder".to_string())?;
    if enabled {
        match std::fs::remove_file(&path) {
            Ok(()) => Ok(()),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(()),
            Err(e) => Err(e.to_string()),
        }
    } else {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        std::fs::write(
            &path,
            b"OpenConstructionERP does not check for a newer version while this file exists.\n",
        )
        .map_err(|e| e.to_string())
    }
}

// --- Deciding when to speak -------------------------------------------------

/// Whether the notice should be written to the window right now.
///
/// Kept as a pure function because the ordering it settles is the whole
/// difficulty and it cannot be observed by running the app: the check and the
/// occasion race each other, and either can win. A missing sidecar binary fails
/// startup in well under a second, long before any HTTP request lands; a
/// backend that never becomes healthy fails it ten minutes later, long after;
/// a healthy one navigates to the application somewhere in between. Every order
/// must end with the notice on screen, so all three writers ask this, and it
/// answers yes exactly once.
fn should_paint(
    update: Option<&AvailableUpdate>,
    startup_failed: bool,
    app_started: bool,
    already_painted: bool,
) -> bool {
    update.is_some() && (startup_failed || app_started) && !already_painted
}

/// Escape a string for embedding inside a single-quoted JavaScript literal.
///
/// Same rule as the launcher's own `js_escape`; kept here so this module needs
/// nothing from `main.rs` but the two calls that drive it.
fn js_escape(s: &str) -> String {
    s.replace('\\', "\\\\")
        .replace('\'', "\\'")
        .replace('\n', " ")
        .replace('\r', " ")
}

/// The user-facing sentences of the notice.
///
/// All English. The splash and every other launcher string are English-only
/// today, so these are consistent with what is already there and are listed for
/// translation alongside them.
/// `after_failure` picks the body. The two occasions are not the same sentence:
/// on a startup that has just failed the newer build is a candidate fix and
/// saying so is the point, while on a working install the same words would tell
/// somebody there is a problem when there is not.
fn notice_text(update: &AvailableUpdate, current: &str, after_failure: bool) -> (String, String) {
    let headline = format!("Version {} is available", update.version);
    // "Your projects and settings stay where they are" describes where the data
    // lives; the sentence this replaced promised that an upgrade would carry it
    // across, which is a stronger claim than the product makes. 15.1.0 refuses
    // to open a data directory a newer PostgreSQL major cannot read, and names
    // the routes that keep the data before the one that destroys it, but a
    // refusal that preserves data is not a migration that moves it.
    let body = if after_failure {
        format!(
            "This copy is version {current}. A newer version has been published, and it may \
already contain a fix for the problem above. Your projects and settings stay where they are."
        )
    } else {
        format!(
            "This copy is version {current}. A newer version has been published. Your projects \
and settings stay where they are."
        )
    };
    (headline, body)
}

/// Write the notice into whatever document the window is showing.
///
/// Built out of plain DOM by the launcher rather than by calling into the page,
/// for the same reason `report_backend_lost` is: the splash is the only page
/// there is on this path, and a startup failure can happen before its script
/// has run. Idempotent by element id, because the eval that carries it is
/// retried several times.
fn paint(handle: &tauri::AppHandle, update: &AvailableUpdate, current: &str, after_failure: bool) {
    let js = notice_script(update, current, after_failure);
    // Eight tries at a quarter of a second is what the launcher's other retried
    // evals use, and on the failure screen the document is already there and
    // settled. The other occasion has to outlast a document being replaced: the
    // call comes in as the webview is handed to the application, and on a first
    // run the splash may first put up its "app window or browser" card and wait
    // for an answer, so the navigation can be a long way off. Keep offering for
    // a minute, which costs an idle eval twice a second and covers both a slow
    // first start and a user who took a while to choose.
    let (tries, interval) = if after_failure { (8, 250) } else { (120, 500) };

    // Retried, not raised: the window is already in front, showing a failure or
    // showing the application, and this must not fight it for focus.
    let handle = handle.clone();
    tauri::async_runtime::spawn(async move {
        for _ in 0..tries {
            if let Some(window) = handle.get_webview_window("main") {
                let _ = window.eval(&js);
            }
            tokio::time::sleep(Duration::from_millis(interval)).await;
        }
    });
}

/// Build the snippet, separately from sending it.
///
/// Split out so the script can be read and checked without a window to run it
/// in. A syntax error in here would not fail a build, would not fail a test that
/// only asserted the launcher's decisions, and would show up exactly once: as a
/// notice that never appears, on the machine of the one user who needed it.
fn notice_script(update: &AvailableUpdate, current: &str, after_failure: bool) -> String {
    let (headline, body) = notice_text(update, current, after_failure);
    // Only the failure document is the launcher's to reshape. See `reserveSpace`.
    let reserve = if after_failure { "true" } else { "false" };
    let head_js = js_escape(&headline);
    let body_js = js_escape(&body);
    let url_js = js_escape(&update.url);
    let version_js = js_escape(&update.version);
    let get_label = js_escape(&format!("Get version {}", update.version));
    let later_label = js_escape("Not now");
    let privacy_js = js_escape(
        "To find this, OpenConstructionERP asked github.com which version is the latest. \
Nothing about you or this computer was sent.",
    );
    let off_label = js_escape("Turn off update checks");
    let off_done = js_escape("Update checks are off. Set the OE_DISABLE_UPDATE_CHECK environment \
variable to turn them off for every user on this computer.");
    // What the two buttons say when the launcher refuses the command behind
    // them. Both name the consequence rather than the fault, because the fault
    // is ours and the consequence is the only part the reader can act on.
    let later_failed = js_escape("This choice could not be saved, so the notice will appear again \
the next time the application starts.");
    let off_failed = js_escape("Update checks could not be turned off. Set the \
OE_DISABLE_UPDATE_CHECK environment variable to turn them off instead.");

    format!(
        "(function(){{\
            var d=document;\
            if(!d||d.getElementById('oe-update-notice')){{return;}}\
            var host=d.body||d.documentElement;\
            if(!host){{return;}}\
            /* Wait while the splash is asking which way to open. That card is \
in the ordinary flow of the page with no stacking of its own, so a strip pinned \
to the bottom of the viewport would sit on top of the two buttons the user has \
to press to get into the product, and an offer that blocks the way in is worse \
than no offer. The eval behind this is retried, so waiting costs nothing: the \
card answers or times out, and the notice appears after it. On the failure \
screen the card was never shown and this is inert. */\
            var choice=d.getElementById('choice');\
            if(choice&&choice.offsetHeight>0){{return;}}\
            /* Call a launcher command, and treat a command that is not there, \
throws, or comes back rejected as one failure with one recovery. The rejected \
case is the one worth spelling out: a machine with no registered browser \
answers the open request with an error rather than by never answering, so \
without this the button would look like it had worked and nothing would open. \
\
The success callback matters for the same reason and is easier to forget. A \
button that reports what it did BEFORE the command answers reports the thing it \
attempted, not the thing that happened, and the two differ every time the call \
is refused. Anything that changes its own label to say a setting was written \
has to wait to be told the setting was written. \
\
A call that comes back as something other than a promise is treated as a \
failure rather than as a success, because there is nothing in that answer that \
says the command ran. Reporting a success nobody gave us is the whole defect \
this callback exists to remove, and it would be no better for being in a \
branch that Tauri does not currently take. */\
            function invoke(name,args,onfail,onok){{\
                function failed(){{if(onfail){{onfail();}}}}\
                function ok(){{if(onok){{onok();}}}}\
                var t=window.__TAURI__;\
                var f=t&&((t.core&&t.core.invoke)||t.invoke);\
                if(!f){{failed();return;}}\
                try{{\
                    var p=f(name,args);\
                    if(p&&p.then){{p.then(ok,failed);}}else{{failed();}}\
                }}catch(e){{failed();}}\
            }}\
            var box=d.createElement('div');\
            box.id='oe-update-notice';\
            box.setAttribute('style','position:fixed;left:0;right:0;bottom:0;\
z-index:2147483645;background:#0f1115;color:#f5f7fa;padding:18px 22px;text-align:left;\
font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:14px;\
line-height:1.55;box-shadow:0 -8px 24px rgba(0,0,0,0.35);max-height:45vh;overflow-y:auto');\
            /* The failure screen carries the log path and the Copy details \
button, and a strip pinned to the bottom would sit on top of them. Reserve the \
strip's height at the foot of the page instead, and give it back when the strip \
is dismissed, so nothing the user needs is ever hidden behind the offer. \
Only on that screen: the failure document is the launcher's own, while the \
running application owns its body and may size it to the viewport with its own \
scrolling inside, so padding it from out here would leave a stray scrollbar or \
clip its chrome. There the strip simply overlaps the last few pixels. */\
            var reserve={reserve};\
            function reserveSpace(px){{\
                if(reserve&&d.body){{d.body.style.paddingBottom=px;}}\
            }}\
            var inner=d.createElement('div');\
            inner.setAttribute('style','max-width:640px;margin:0 auto');\
            /* Where a refused command gets to say so. One strip for both \
buttons, built up front and left empty, so a handler reporting a refusal is a \
single call and the two cannot drift into reporting it differently. Hidden \
until something has been written into it: an empty line at the foot of the \
notice would read as a rendering fault. */\
            var warnBox=d.createElement('div');\
            warnBox.setAttribute('style','margin-top:10px;font-size:12.5px;\
color:#ffb3a7;display:none');\
            function warn(text){{\
                warnBox.textContent=text;\
                warnBox.style.display='';\
                reserveSpace((box.offsetHeight+24)+'px');\
            }}\
            var h=d.createElement('div');\
            h.setAttribute('style','font-size:16px;font-weight:600;margin-bottom:6px');\
            h.textContent='{head_js}';\
            var p=d.createElement('div');\
            p.textContent='{body_js}';\
            var row=d.createElement('div');\
            row.setAttribute('style','margin-top:14px;display:flex;gap:10px;flex-wrap:wrap;\
align-items:center');\
            var get=d.createElement('button');\
            get.type='button';\
            get.textContent='{get_label}';\
            get.setAttribute('style','border:0;border-radius:10px;padding:10px 16px;\
font:inherit;font-weight:600;cursor:pointer;color:#fff;\
background:linear-gradient(135deg,#0066ff,#5856d6)');\
            get.onclick=function(){{\
                invoke('open_external_url',{{url:'{url_js}'}},function(){{\
                    try{{window.open('{url_js}','_blank');}}catch(e){{}}\
                }});\
            }};\
            var later=d.createElement('button');\
            later.type='button';\
            later.textContent='{later_label}';\
            later.setAttribute('style','border:1px solid rgba(245,247,250,0.35);\
border-radius:10px;padding:10px 16px;font:inherit;cursor:pointer;color:#f5f7fa;\
background:transparent');\
            /* Hidden and marked, not removed. The eval that carries this is \
retried for as long as the notice has to survive a page change, and the guard \
at the top of this function is the only thing keeping it from being built twice: \
remove the element and the very next retry puts a dismissed notice straight back \
on screen. Left in the document, it is its own record that the user answered. */\
            /* Dismissed only once the launcher has written the dismissal down. \
Hiding first and asking afterwards is what made this button lie: the strip went \
away whether or not the choice was recorded, and a choice that was not recorded \
brings the same notice back on the next start, so the user is left believing \
they answered a question they will be asked again. The wait costs nothing a \
person can perceive, since this is local IPC that either answers or is refused \
at once, and the refusal now has somewhere to appear. */\
            later.onclick=function(){{\
                invoke('decline_update_version',{{version:'{version_js}'}},function(){{\
                    warn('{later_failed}');\
                }},function(){{\
                    box.style.display='none';\
                    box.setAttribute('data-oe-dismissed','1');\
                    reserveSpace('');\
                }});\
            }};\
            row.appendChild(get);row.appendChild(later);\
            var note=d.createElement('div');\
            note.setAttribute('style','margin-top:12px;font-size:12.5px;\
color:rgba(245,247,250,0.72)');\
            note.textContent='{privacy_js} ';\
            var off=d.createElement('button');\
            off.type='button';\
            off.textContent='{off_label}';\
            off.setAttribute('style','border:0;background:transparent;padding:0;font:inherit;\
color:rgba(245,247,250,0.72);text-decoration:underline;cursor:pointer');\
            /* The label changes only after the setting has been written. It \
used to change on the way out, which made this the plainest false statement in \
the launcher: the note read that update checks were off while the command that \
turns them off had been refused and nothing on disk had changed. */\
            off.onclick=function(){{\
                invoke('set_update_check_enabled',{{enabled:false}},function(){{\
                    warn('{off_failed}');\
                }},function(){{\
                    note.textContent='{off_done}';\
                }});\
            }};\
            note.appendChild(off);\
            inner.appendChild(h);inner.appendChild(p);inner.appendChild(row);\
            inner.appendChild(note);inner.appendChild(warnBox);\
            box.appendChild(inner);host.appendChild(box);\
            reserveSpace((box.offsetHeight+24)+'px');\
        }})()"
    )
}

/// Paint if, and only if, both halves have arrived. Called by every writer.
fn paint_if_ready(handle: &tauri::AppHandle, current: &str) {
    let update = { LATEST.lock().ok().and_then(|g| g.clone()) };
    let failed = STARTUP_FAILED.load(Ordering::SeqCst);
    let started = APP_STARTED.load(Ordering::SeqCst);
    let already = PAINTED.load(Ordering::SeqCst);
    if !should_paint(update.as_ref(), failed, started, already) {
        return;
    }
    // Claim the single paint before doing it, so two threads arriving together
    // produce one notice.
    if PAINTED
        .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
        .is_err()
    {
        return;
    }
    if let Some(update) = update {
        // A failure that has happened decides the wording even if the
        // application also came up, because a backend can be lost after a good
        // start and the reason on screen is then the more useful thing to speak
        // to.
        paint(handle, &update, current, failed);
    }
}

/// Turn whatever the far end said into an offer, or into silence.
///
/// Split out of the request so that failing open is a tested behaviour rather
/// than an argument about the shape of the code. Everything GitHub or anything
/// standing in front of it can answer with arrives here: a rate limit, an
/// authentication challenge, a captive portal's own login page, a proxy's error
/// page, an empty body, valid JSON that is not a release, a release older than
/// this one. Every one of them is silence.
#[cfg(test)]
fn update_from_response(status: u16, body: &str, current: &str) -> Option<AvailableUpdate> {
    match outcome_from_response(status, body, current) {
        CheckOutcome::Newer(release) => Some(release),
        _ => None,
    }
}

/// What a check the user asked for came back with.
///
/// Three answers rather than an `Option`, because the person who pressed the
/// button is owed the difference between "you are up to date" and "GitHub could
/// not be asked", which the silent background check never had to say.
#[derive(Clone, Debug, PartialEq, Eq)]
enum CheckOutcome {
    Newer(AvailableUpdate),
    Current,
    Unreachable,
}

impl CheckOutcome {
    /// The word handed back to the button's script.
    fn as_str(&self) -> &'static str {
        match self {
            CheckOutcome::Newer(_) => "newer",
            CheckOutcome::Current => "current",
            CheckOutcome::Unreachable => "unreachable",
        }
    }
}

/// Everything the far end can answer, sorted into the three outcomes.
///
/// Anything that is not a readable release (an error status, a proxy's page,
/// a body that is not a release) is "could not be asked", never "up to date":
/// telling somebody they have the latest version on the strength of a captive
/// portal's login page would be a false reassurance.
fn outcome_from_response(status: u16, body: &str, current: &str) -> CheckOutcome {
    if !(200..300).contains(&status) {
        return CheckOutcome::Unreachable;
    }
    let Ok(parsed) = serde_json::from_str::<serde_json::Value>(body) else {
        return CheckOutcome::Unreachable;
    };
    match release_from_json(&parsed) {
        Some(release) if is_newer(&release.version, current) => CheckOutcome::Newer(release),
        Some(_) => CheckOutcome::Current,
        None => CheckOutcome::Unreachable,
    }
}

// --- The entry points the launcher uses -------------------------------------

/// Ask GitHub for the latest release. One GET, five seconds at most.
async fn fetch_latest(current_version: &str) -> CheckOutcome {
    let client = match reqwest::Client::builder()
        .user_agent(USER_AGENT)
        .timeout(REQUEST_TIMEOUT)
        .build()
    {
        Ok(client) => client,
        Err(_) => return CheckOutcome::Unreachable,
    };
    let url = format!("https://api.github.com/repos/{REPO}/releases/latest");
    // The socket itself is the one part of this that cannot be reached from a
    // test. Everything the far end can say back is handed to a plain function
    // so that it can be.
    match client
        .get(&url)
        .header("Accept", "application/vnd.github+json")
        .send()
        .await
    {
        Ok(resp) => {
            let status = resp.status().as_u16();
            match resp.text().await {
                Ok(text) => outcome_from_response(status, &text, current_version),
                // Connection cut part way through the body.
                Err(_) => CheckOutcome::Unreachable,
            }
        }
        // Offline, DNS failure, TLS failure, timed out.
        Err(_) => CheckOutcome::Unreachable,
    }
}

/// The "Check for a newer version" button on the startup failure screen.
///
/// Answers `newer`, `current`, `unreachable` or `disabled`, and on `newer` puts
/// the usual notice on screen. A version the user once declined is shown
/// anyway: pressing the button is a fresh question.
#[tauri::command]
pub async fn check_for_update_now(handle: tauri::AppHandle) -> Result<String, String> {
    let current = env!("CARGO_PKG_VERSION");
    if !is_enabled() {
        return Ok("disabled".to_string());
    }
    let outcome = fetch_latest(current).await;
    let word = outcome.as_str().to_string();
    if let CheckOutcome::Newer(release) = outcome {
        if let Ok(mut guard) = LATEST.lock() {
            *guard = Some(release);
        }
        PAINTED.store(false, Ordering::SeqCst);
        paint_if_ready(&handle, current);
    }
    Ok(word)
}

/// The button, its privacy line and the line its answer is written into.
///
/// Plain DOM for the same reason as the notice: the failure document is the
/// launcher's own and may be up before any of its script has run. Idempotent by
/// element id, because the eval that carries it is retried.
fn check_button_script() -> String {
    let label = js_escape("Check for a newer version");
    let privacy = js_escape(
        "This asks github.com which version is the latest. Nothing about you or this \
computer is sent, and nothing is asked until you press the button.",
    );
    let checking = js_escape("Checking...");
    let current = js_escape("This is the latest version.");
    let unreachable = js_escape(
        "github.com could not be reached. The releases page lists every version: \
https://github.com/datadrivenconstruction/OpenConstructionERP/releases",
    );
    let disabled = js_escape("Update checks are turned off on this computer by an administrator.");
    let refused = js_escape("The check could not be started.");
    format!(
        "(function(){{\
            var d=document;\
            if(!d||d.getElementById('oe-update-check')){{return;}}\
            var host=d.body||d.documentElement;\
            if(!host){{return;}}\
            var wrap=d.createElement('div');\
            wrap.id='oe-update-check';\
            wrap.setAttribute('style','max-width:640px;margin:18px auto 0;text-align:left;\
font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:13px;line-height:1.5');\
            var btn=d.createElement('button');\
            btn.type='button';\
            btn.textContent='{label}';\
            btn.setAttribute('style','border:1px solid rgba(127,127,127,0.5);border-radius:10px;\
padding:8px 14px;font:inherit;cursor:pointer;background:transparent;color:inherit');\
            var note=d.createElement('div');\
            note.setAttribute('style','margin-top:6px;opacity:0.75');\
            note.textContent='{privacy}';\
            var out=d.createElement('div');\
            out.setAttribute('style','margin-top:6px');\
            function say(t){{out.textContent=t;btn.disabled=false;}}\
            btn.onclick=function(){{\
                var t=window.__TAURI__;\
                var f=t&&((t.core&&t.core.invoke)||t.invoke);\
                if(!f){{say('{refused}');return;}}\
                btn.disabled=true;out.textContent='{checking}';\
                try{{\
                    var p=f('check_for_update_now',{{}});\
                    if(!p||!p.then){{say('{refused}');return;}}\
                    p.then(function(r){{\
                        if(r==='newer'){{say('');}}\
                        else if(r==='current'){{say('{current}');}}\
                        else if(r==='disabled'){{say('{disabled}');}}\
                        else{{say('{unreachable}');}}\
                    }},function(){{say('{refused}');}});\
                }}catch(e){{say('{refused}');}}\
            }};\
            wrap.appendChild(btn);wrap.appendChild(note);wrap.appendChild(out);\
            host.appendChild(wrap);\
        }})()"
    )
}

/// Put the button on the failure screen, retried like the notice.
fn paint_check_button(handle: &tauri::AppHandle) {
    let js = check_button_script();
    let handle = handle.clone();
    tauri::async_runtime::spawn(async move {
        for _ in 0..8 {
            if let Some(window) = handle.get_webview_window("main") {
                let _ = window.eval(&js);
            }
            tokio::time::sleep(Duration::from_millis(250)).await;
        }
    });
}

/// Tell the check that startup has failed and the user is looking at the reason.
///
/// Called from the launcher's single fatal-report funnel, so every way startup
/// can fail carries the offer: a sidecar that could not be located, a sidecar
/// that would not spawn, a backend that died before answering, a backend that
/// answered and said it could not do its job, and a backend that never answered
/// at all.
pub fn note_startup_failed(handle: &tauri::AppHandle, current_version: &str) {
    STARTUP_FAILED.store(true, Ordering::SeqCst);
    // Nothing has been asked yet; the button asks when pressed. An offer that
    // is already known (the button was pressed on an earlier failure in this
    // run) is still painted.
    paint_check_button(handle);
    paint_if_ready(handle, current_version);
}

/// Tell the check that the webview has been sent to the running application.
///
/// Called at each point the launcher hands the window over, whether it booted
/// the backend itself or attached to one already running. The application has
/// an update notice of its own and it is the better one, being translated and
/// inside the product, but it is mounted only on screens that require a signed
/// in user. Somebody who has just installed the product sees the sign-in page
/// first, and on a fresh machine that is the whole of what they see, so without
/// this the moment the offer was asked for is the one moment nothing makes it.
pub fn note_app_started(handle: &tauri::AppHandle, current_version: &str) {
    APP_STARTED.store(true, Ordering::SeqCst);
    paint_if_ready(handle, current_version);
}

/// Turn the launcher's update check on or off for this user.
///
/// Exposed to the notice so the sentence about contacting GitHub comes with a
/// way to stop it, on the one screen where the sentence is ever read.
#[tauri::command]
pub fn set_update_check_enabled(enabled: bool) -> Result<(), String> {
    set_enabled(enabled)
}

/// Remember that the user said no to this particular version.
///
/// Best effort, like the opt-out: a home directory that cannot be written to
/// costs the user a repeated notice rather than anything they would miss.
#[tauri::command]
pub fn decline_update_version(version: String) -> Result<(), String> {
    let path = declined_path().ok_or_else(|| "Could not resolve your home folder".to_string())?;
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    std::fs::write(&path, version.trim().as_bytes()).map_err(|e| e.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_minor_roll_reads_as_newer() {
        // The version scheme this project uses: the minor runs 0 to 9 and then
        // rolls the major, so this is the ordinary release step and the exact
        // one a lexical compare gets backwards.
        assert!(is_newer("15.0.0", "14.9.3"));
        assert!(is_newer("15.0.0", "14.9.9"));
        assert!(!is_newer("14.9.3", "15.0.0"));
    }

    #[test]
    fn the_broken_build_is_offered_the_fix() {
        // The case this feature was written for.
        assert!(is_newer("15.0.1", "15.0.0"));
    }

    #[test]
    fn a_string_compare_would_get_these_wrong() {
        assert!(is_newer("9.10.0", "9.9.0"));
        assert!(is_newer("5.2.10", "5.2.9"));
        assert!(!is_newer("9.9.0", "9.10.0"));
    }

    #[test]
    fn the_same_version_says_nothing() {
        assert!(!is_newer("15.0.0", "15.0.0"));
        assert!(!is_newer("v15.0.0", "15.0.0"));
    }

    #[test]
    fn a_missing_trailing_zero_is_the_same_release() {
        assert!(!is_newer("15.1", "15.1.0"));
        assert!(!is_newer("15.1.0", "15.1"));
    }

    #[test]
    fn an_older_published_version_says_nothing() {
        assert!(!is_newer("14.9.0", "15.0.0"));
        assert!(!is_newer("15.0.0", "15.0.1"));
    }

    #[test]
    fn a_malformed_tag_says_nothing() {
        for tag in ["", "v", "not-a-version", "latest", "release", "..", "v.x.y"] {
            assert!(
                !is_newer(tag, "15.0.0"),
                "a tag of {tag:?} must never offer an update"
            );
        }
    }

    #[test]
    fn a_pre_release_suffix_does_not_outrank_the_release() {
        // Digit-prefix parsing, the same rule the backend applies: the suffix
        // is dropped, so a release candidate never reads as newer than the
        // release it is a candidate for.
        assert!(!is_newer("15.0.0-rc1", "15.0.0"));
        assert!(!is_newer("15.0.0rc1", "15.0.0"));
    }

    #[test]
    fn a_draft_or_pre_release_is_not_offered() {
        let draft = serde_json::json!({"tag_name": "v16.0.0", "draft": true});
        assert_eq!(release_from_json(&draft), None);
        let pre = serde_json::json!({"tag_name": "v16.0.0", "prerelease": true});
        assert_eq!(release_from_json(&pre), None);
    }

    #[test]
    fn a_release_body_yields_its_tag_and_page() {
        let body = serde_json::json!({
            "tag_name": "v15.0.1",
            "html_url": "https://github.com/datadrivenconstruction/OpenConstructionERP/releases/tag/v15.0.1",
        });
        let release = release_from_json(&body).expect("a plain release body should parse");
        assert_eq!(release.version, "15.0.1");
        assert!(release.url.ends_with("/releases/tag/v15.0.1"));
        assert!(is_newer(&release.version, "15.0.0"));
    }

    #[test]
    fn a_body_that_is_not_a_release_says_nothing() {
        // What a rate-limited API, a proxy login page or a renamed field all
        // look like from here.
        assert_eq!(
            release_from_json(&serde_json::json!({"message": "API rate limit exceeded"})),
            None
        );
        assert_eq!(release_from_json(&serde_json::json!({"tag_name": ""})), None);
        assert_eq!(release_from_json(&serde_json::json!({"tag_name": "nightly"})), None);
        assert_eq!(release_from_json(&serde_json::json!([1, 2, 3])), None);
    }

    #[test]
    fn a_release_url_off_github_is_replaced_with_our_own() {
        let body = serde_json::json!({
            "tag_name": "v15.0.1",
            "html_url": "https://example.invalid/somewhere-else",
        });
        let release = release_from_json(&body).expect("the tag is still usable");
        assert_eq!(
            release.url,
            "https://github.com/datadrivenconstruction/OpenConstructionERP/releases/latest"
        );
    }

    // --- The failure path, in both orders -----------------------------------

    fn some_update() -> AvailableUpdate {
        AvailableUpdate {
            version: "15.0.1".to_string(),
            url: "https://github.com/datadrivenconstruction/OpenConstructionERP/releases/latest"
                .to_string(),
        }
    }

    /// A real answer, so the tests below are the difference between this and
    /// each way the far end can disappoint us.
    fn good_body() -> String {
        r#"{"tag_name":"v15.0.1","draft":false,"prerelease":false,
            "html_url":"https://github.com/datadrivenconstruction/OpenConstructionERP/releases/tag/v15.0.1"}"#
            .to_string()
    }

    #[test]
    fn a_good_answer_is_the_only_one_that_speaks() {
        let offer = update_from_response(200, &good_body(), "15.0.0");
        assert_eq!(offer.map(|u| u.version), Some("15.0.1".to_string()));
    }

    #[test]
    fn every_way_the_answer_can_disappoint_us_is_silence() {
        // The half of this feature that protects users is not that it parses a
        // release correctly, it is that nothing else it can ever receive turns
        // into a notice or into a panic. The socket failing is a match arm that
        // cannot be reached from here; everything the far end can actually
        // reply with can, so all of it is listed.
        let cases: Vec<(u16, &str, &str)> = vec![
            (403, r#"{"message":"API rate limit exceeded"}"#, "rate limited"),
            (401, r#"{"message":"Bad credentials"}"#, "unauthorised"),
            (404, r#"{"message":"Not Found"}"#, "repository or release missing"),
            (500, "", "GitHub itself failing"),
            (502, "<html><body>Bad Gateway</body></html>", "a gateway in the way"),
            (301, "", "a redirect that was not followed"),
            (200, "", "an empty body with a good status"),
            (200, "<!DOCTYPE html><title>Sign in</title>", "a captive portal login page"),
            (200, "not json at all", "a proxy sending plain text"),
            (200, "{", "JSON cut off part way"),
            (200, "[]", "valid JSON of the wrong shape"),
            (200, "null", "valid JSON that is nothing"),
            (200, r#"{"tag_name":"v15.0.1","draft":true,"prerelease":false}"#, "a draft"),
            (200, r#"{"tag_name":"v16.0.0","draft":false,"prerelease":true}"#, "a pre-release"),
            (200, r#"{"tag_name":"","draft":false,"prerelease":false}"#, "an empty tag"),
            (200, r#"{"tag_name":"latest","draft":false,"prerelease":false}"#, "a tag with no digits"),
            (200, r#"{"draft":false,"prerelease":false}"#, "a release with no tag at all"),
            (200, r#"{"tag_name":"v14.9.9","draft":false,"prerelease":false}"#, "an older release"),
            (200, r#"{"tag_name":"v15.0.0","draft":false,"prerelease":false}"#, "the version we are"),
        ];
        for (status, body, what) in cases {
            assert_eq!(
                update_from_response(status, body, "15.0.0"),
                None,
                "{what} must not produce a notice"
            );
        }
    }

    #[test]
    fn a_hostile_body_cannot_send_the_user_anywhere_but_github() {
        // The URL out of the answer ends up in a button the user presses. A
        // release page that is not on github.com is replaced rather than
        // trusted, so a compromised or spoofed answer cannot use this as a way
        // to put a link of its choosing in front of somebody.
        let body = r#"{"tag_name":"v99.0.0","draft":false,"prerelease":false,
            "html_url":"https://example.invalid/please-run-this.exe"}"#;
        let offer = update_from_response(200, body, "15.0.0").expect("a newer version was offered");
        assert!(
            offer.url.starts_with("https://github.com/datadrivenconstruction/"),
            "the button must not be able to point off github, got {}",
            offer.url
        );
    }

    #[test]
    fn saying_no_once_silences_that_version_and_only_that_version() {
        // Declining is not opting out. The version that was turned down goes
        // quiet, and the next one still gets to speak, or the notice stops
        // being an offer and becomes something the user has to endure.
        assert!(was_declined("15.0.1", Some("15.0.1")), "the declined version must go quiet");
        assert!(was_declined("15.0.1", Some("15.1.0")), "an older offer than the one declined");
        assert!(!was_declined("15.1.0", Some("15.0.1")), "a newer version must still speak");
        assert!(!was_declined("16.0.0", Some("15.9.9")), "the major roll must still speak");
        assert!(!was_declined("15.0.1", None), "nothing declined yet, so nothing is silenced");
        // Whatever ends up in that file, it must not be able to silence the
        // check permanently by accident.
        assert!(!was_declined("15.0.1", Some("")), "an empty marker silences nothing");
        assert!(!was_declined("15.0.1", Some("not-a-version")), "a junk marker silences nothing");
    }

    #[test]
    fn the_dismiss_button_records_which_version_was_declined() {
        let script = notice_script(&some_update(), "15.0.0", false);
        assert!(
            script.contains("decline_update_version"),
            "pressing Not now must reach the launcher, or the notice returns next start"
        );
        assert!(
            script.contains("version:'15.0.1'"),
            "the version declined must be the one that was offered"
        );
    }

    #[test]
    fn neither_button_reports_an_outcome_it_was_not_given() {
        // Both of these buttons used to act on the way out. Not now hid the
        // strip and then asked the launcher to remember the dismissal, and the
        // opt-out link rewrote its own label to say update checks were off and
        // then asked for them to be turned off. On the application page both
        // commands were refused, so the strip came back on the next start and
        // the label said a setting had been written that had not been. A
        // control that reports a success it did not get is worse than one that
        // does nothing, because the user has no reason to look again.
        //
        // The discriminator is the close paren. `invoke(name,args)` with the
        // arguments closed off immediately is the old shape and cannot be
        // told anything; the callbacks are the whole fix, so their absence is
        // what this refuses. Checked on both documents, since the failure
        // screen builds the same script.
        for after_failure in [true, false] {
            let script = notice_script(&some_update(), "15.0.0", after_failure);
            assert!(
                !script.contains("version:'15.0.1'});"),
                "Not now must pass callbacks to invoke, or it cannot know the dismissal was saved"
            );
            assert!(
                !script.contains("{enabled:false});"),
                "the opt-out must pass callbacks to invoke, or its label is a guess"
            );
            // And the answer has to have somewhere to appear.
            assert!(
                script.matches("warn(").count() >= 3,
                "both handlers must report a refusal through the one warning strip"
            );
            assert!(
                script.contains("the notice will appear again"),
                "a dismissal that was not saved has to say the notice is coming back"
            );
            assert!(
                script.contains("Update checks could not be turned off"),
                "a refused opt-out has to say so rather than claim it worked"
            );
            // The callbacks are only worth having if the helper cannot reach
            // the success one without being told. A call that answers with
            // something other than a promise has told us nothing, and treating
            // that as success would put the same lie back one level down.
            assert!(
                !script.contains("else{ok();}"),
                "an answer that is not a promise is not a success, and must not be reported as one"
            );
            assert!(
                script.contains("else{failed();}"),
                "the helper must fail closed when the call does not come back as a promise"
            );
        }
    }

    #[test]
    fn the_notice_does_not_promise_to_carry_the_data_across() {
        // The product refuses to open a data directory a newer PostgreSQL major
        // cannot read, which protects the data; it does not migrate it. The
        // notice must describe the first and not claim the second.
        for after_failure in [true, false] {
            let (_, body) = notice_text(&some_update(), "15.0.0", after_failure);
            assert!(body.contains("stay where they are"));
            assert!(!body.contains("keeps your existing data"));
        }
    }

    #[test]
    fn nothing_is_said_before_an_occasion_arrives() {
        // The answer is in hand, but the window is still showing the boot
        // checklist and nothing has happened to speak to yet.
        assert!(!should_paint(Some(&some_update()), false, false, false));
    }

    #[test]
    fn a_failure_with_nothing_newer_offers_nothing() {
        assert!(!should_paint(None, true, false, false));
    }

    #[test]
    fn the_check_can_land_after_the_failure() {
        // A sidecar that cannot be located fails startup in milliseconds, long
        // before any HTTP request finishes. The failure is recorded first and
        // the answer arrives second, and the notice must still appear.
        let update = some_update();
        assert!(!should_paint(None, true, false, false));
        assert!(should_paint(Some(&update), true, false, false));
    }

    #[test]
    fn the_check_can_land_before_the_failure() {
        // A backend that never becomes healthy fails startup ten minutes in,
        // long after the answer arrived.
        let update = some_update();
        assert!(!should_paint(Some(&update), false, false, false));
        assert!(should_paint(Some(&update), true, false, false));
    }

    #[test]
    fn a_working_install_is_offered_the_update_too() {
        // The occasion the founder asked for: the product starts, the sign-in
        // page appears, and the newer build is offered there. Every mount of
        // the application's own notice is behind that sign-in, so on a machine
        // the product was just installed on this is the only offer there is.
        let update = some_update();
        assert!(should_paint(Some(&update), false, true, false));
    }

    #[test]
    fn the_check_can_land_after_the_application_did() {
        // The webview reaches the application in a second or two on a machine
        // that has run before; a slow network answers later than that.
        let update = some_update();
        assert!(!should_paint(None, false, true, false));
        assert!(should_paint(Some(&update), false, true, false));
    }

    #[test]
    fn a_failure_after_a_good_start_keeps_the_failure_wording() {
        // Both flags can end up set, because a backend can be lost after the
        // window has already been handed to the application. The reason on
        // screen is then the more useful thing to speak to.
        let update = some_update();
        let (_, failure_body) = notice_text(&update, "15.0.0", true);
        let (_, plain_body) = notice_text(&update, "15.0.0", false);
        assert!(failure_body.contains("problem above"));
        assert!(!plain_body.contains("problem above"));
        assert!(should_paint(Some(&update), true, true, false));
    }

    #[test]
    fn the_notice_is_written_once() {
        assert!(!should_paint(Some(&some_update()), true, false, true));
        assert!(!should_paint(Some(&some_update()), false, true, true));
        assert!(!should_paint(Some(&some_update()), true, true, true));
    }

    #[test]
    fn an_administrator_can_turn_the_check_off() {
        for on in ["1", "true", "TRUE", "yes", "On", " true "] {
            assert!(env_flag_is_on(on), "{on:?} should read as on");
        }
        for off in ["", "0", "false", "no", "off", "maybe"] {
            assert!(!env_flag_is_on(off), "{off:?} should not read as on");
        }
    }

    #[test]
    fn a_development_build_never_checks() {
        // Tests are debug builds, so this asserts the real guard rather than a
        // restatement of it: if the check ever became enabled here it would be
        // enabled on every developer's machine too.
        assert!(!is_enabled());
    }

    #[test]
    fn the_notice_names_both_versions() {
        for after_failure in [true, false] {
            let (headline, body) = notice_text(&some_update(), "15.0.0", after_failure);
            assert!(headline.contains("15.0.1"));
            assert!(body.contains("15.0.0"));
        }
    }

    #[test]
    fn the_notice_script_carries_what_the_user_needs() {
        for after_failure in [true, false] {
            let script = notice_script(&some_update(), "15.0.0", after_failure);
            assert!(script.contains("oe-update-notice"), "the notice needs its id to stay idempotent");
            assert!(script.contains("15.0.1"), "the notice must name the version on offer");
            assert!(script.contains("open_external_url"), "the button must reach the opener");
            assert!(
                script.contains("set_update_check_enabled"),
                "the opt-out must reach the launcher"
            );
            assert!(script.contains("github.com"), "the notice must say who was asked");
            // A brace left unpaired by the format string is a script that never
            // runs, and nothing else in this file would notice.
            let opens = script.matches('{').count();
            let closes = script.matches('}').count();
            assert_eq!(opens, closes, "unbalanced braces in the notice script");
        }
    }

    #[test]
    fn only_the_failure_screen_is_reshaped() {
        // The failure document belongs to the launcher and the strip must not
        // cover the log path on it. The application's document does not: it can
        // size itself to the viewport and scroll inside, so padding its body
        // from out here would leave a stray scrollbar or clip its own chrome.
        assert!(notice_script(&some_update(), "15.0.0", true).contains("var reserve=true"));
        assert!(notice_script(&some_update(), "15.0.0", false).contains("var reserve=false"));
    }

    #[test]
    fn the_way_into_the_product_is_never_covered() {
        // The splash asks which way to open on a first run, and its card is an
        // ordinary block in the flow of that page with no stacking context of
        // its own. A strip fixed to the bottom of the viewport outranks it, so
        // the notice has to wait rather than land on the two buttons the user
        // has to press. Guarded on both scripts: on the failure screen the card
        // was never shown and the guard costs nothing.
        for after_failure in [true, false] {
            let script = notice_script(&some_update(), "15.0.0", after_failure);
            assert!(
                script.contains("getElementById('choice')"),
                "the notice must look for the launch choice card"
            );
            assert!(
                script.contains("choice.offsetHeight>0"),
                "the guard must test whether the card is on screen, not whether it exists"
            );
        }
    }

    #[test]
    fn a_dismissed_notice_is_not_built_again() {
        // The eval is retried for as long as the notice has to survive a page
        // change, and the guard on the element id is the only thing standing
        // between a dismissal and the notice reappearing a quarter of a second
        // later. That guard only works while the element is still in the
        // document, so dismissal has to hide it rather than remove it.
        let script = notice_script(&some_update(), "15.0.0", false);
        assert!(
            script.contains("getElementById('oe-update-notice')"),
            "the script must recognise a notice it already built"
        );
        assert!(
            !script.contains("removeChild(box)"),
            "removing the notice on dismiss lets the next retry rebuild it"
        );
        assert!(script.contains("box.style.display='none'"), "dismissal must hide the notice");
    }

    #[test]
    fn the_notice_script_is_valid_javascript() {
        // The pure-Rust checks above cannot tell a balanced script from a
        // parseable one. Node is what the frontend of this repository is built
        // with, so it is here to be used; a machine without it skips rather
        // than failing over a tool that is not the thing under test.
        for (n, after_failure) in [(0, true), (1, false)] {
            let script = notice_script(&some_update(), "15.0.0", after_failure);
            let path = std::env::temp_dir().join(format!("oe_update_notice_check_{n}.js"));
            if std::fs::write(&path, script.as_bytes()).is_err() {
                return;
            }
            let checked = std::process::Command::new("node").arg("--check").arg(&path).output();
            let _ = std::fs::remove_file(&path);
            let Ok(output) = checked else {
                return; // No node on this machine.
            };
            assert!(
                output.status.success(),
                "the notice script is not valid JavaScript (after_failure={after_failure}):\n{}",
                String::from_utf8_lossy(&output.stderr)
            );
        }
    }

    #[test]
    fn a_pressed_button_is_told_apart_from_an_unreachable_host() {
        // Up to date and "could not ask" are different answers for a person
        // who pressed a button, and only a readable release may say the first.
        assert_eq!(outcome_from_response(200, &good_body(), "15.0.1"), CheckOutcome::Current);
        assert_eq!(outcome_from_response(200, &good_body(), "16.0.0"), CheckOutcome::Current);
        assert!(matches!(
            outcome_from_response(200, &good_body(), "15.0.0"),
            CheckOutcome::Newer(_)
        ));
        let good = good_body();
        for (status, body) in [
            (403, good.as_str()),
            (200, "<html>captive portal</html>"),
            (200, ""),
            (200, "{\"message\":\"Not Found\"}"),
        ] {
            assert_eq!(
                outcome_from_response(status, body, "15.0.0"),
                CheckOutcome::Unreachable,
                "status {status} with body {body:?} must not read as up to date"
            );
        }
        assert_eq!(CheckOutcome::Current.as_str(), "current");
        assert_eq!(CheckOutcome::Unreachable.as_str(), "unreachable");
    }

    #[test]
    fn the_failure_screen_button_calls_the_command_and_nothing_else() {
        let script = check_button_script();
        assert!(script.contains("'check_for_update_now'"));
        assert!(script.contains("getElementById('oe-update-check')"), "retries must not add a second button");
        // It asks nothing on its own: the only call sits inside the click handler.
        let click = script.find("btn.onclick").expect("the button has a click handler");
        let call = script.find("f('check_for_update_now'").expect("the command is invoked");
        assert!(call > click, "the check must run on the click, not when the button is drawn");
        for word in ["'current'", "'disabled'", "'newer'"] {
            assert!(script.contains(word), "the script handles the {word} answer");
        }
    }

    #[test]
    fn the_failure_screen_is_granted_the_check() {
        // The failure screen is a local-origin document, governed by
        // capabilities/default.json. A command it is not granted is refused
        // before it runs, and the button would only ever say it could not start.
        use std::collections::{HashMap, HashSet};
        const CAPABILITY: &str = include_str!("../capabilities/default.json");
        const PERMISSIONS: &str = include_str!("../permissions/app-commands.json");
        let capability: serde_json::Value = serde_json::from_str(CAPABILITY).unwrap();
        let declared: serde_json::Value = serde_json::from_str(PERMISSIONS).unwrap();
        let mut commands_of: HashMap<String, Vec<String>> = HashMap::new();
        for p in declared["permission"].as_array().unwrap() {
            let cmds = p["commands"]["allow"]
                .as_array()
                .map(|l| l.iter().filter_map(|c| c.as_str().map(str::to_string)).collect())
                .unwrap_or_default();
            commands_of.insert(p["identifier"].as_str().unwrap().to_string(), cmds);
        }
        let mut members_of: HashMap<String, Vec<String>> = HashMap::new();
        for set in declared["set"].as_array().unwrap() {
            let members = set["permissions"]
                .as_array()
                .map(|l| l.iter().filter_map(|c| c.as_str().map(str::to_string)).collect())
                .unwrap_or_default();
            members_of.insert(set["identifier"].as_str().unwrap().to_string(), members);
        }
        let mut granted: HashSet<String> = HashSet::new();
        let mut seen: HashSet<String> = HashSet::new();
        let mut pending: Vec<String> = capability["permissions"]
            .as_array()
            .unwrap()
            .iter()
            .filter_map(|p| p.as_str().map(str::to_string))
            .collect();
        while let Some(id) = pending.pop() {
            if !seen.insert(id.clone()) {
                continue;
            }
            if let Some(cmds) = commands_of.get(&id) {
                granted.extend(cmds.iter().cloned());
            } else if let Some(members) = members_of.get(&id) {
                pending.extend(members.iter().cloned());
            }
        }
        assert!(granted.contains("check_for_update_now"));
    }

    #[test]
    fn the_check_button_script_is_valid_javascript() {
        let path = std::env::temp_dir().join("oe_update_check_button.js");
        if std::fs::write(&path, check_button_script().as_bytes()).is_err() {
            return;
        }
        let checked = std::process::Command::new("node").arg("--check").arg(&path).output();
        let _ = std::fs::remove_file(&path);
        let Ok(output) = checked else {
            return; // No node on this machine.
        };
        assert!(
            output.status.success(),
            "the check button script is not valid JavaScript:\n{}",
            String::from_utf8_lossy(&output.stderr)
        );
    }
}
