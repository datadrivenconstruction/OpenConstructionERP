//! What the startup failure screen offers beyond the message: a readable exit
//! status, the log tail to copy, and a Repair that never deletes user data.
//!
//! Kept out of main.rs so each rule is a plain function over paths and numbers
//! and can be tested without a window or a backend.

use std::path::{Path, PathBuf};

/// Written by the Repair button, consumed by the next start before the backend
/// is spawned, so the repair runs while nothing of ours holds the data folder.
pub const REPAIR_MARKER: &str = "repair.requested";

/// One sentence for how the backend process ended, never a bare negative number.
///
/// Windows reports an NTSTATUS as the exit code, which arrives here as a signed
/// 32-bit int: -1073741819 is 0xC0000005. The same table lives on the Python
/// side for the converters in `backend/app/core/windows_exit_status.py`.
pub fn describe_exit_code(code: Option<i32>) -> String {
    let Some(code) = code else {
        return "it ended without an exit code".to_string();
    };
    let status = code as u32;
    if status < 0x8000_0000 {
        return format!("it ended with exit code {code}");
    }
    let hex = format!("0x{status:08X}");
    let meaning = match status {
        0xC000_0005 => "it crashed (access violation). Security software that injects itself into other programs is a common cause: add the OpenConstructionERP install folder to its exclusions",
        0xC000_0135 => "a system library it needs is missing. Install the Microsoft Visual C++ Redistributable (x64) from https://aka.ms/vs/17/release/vc_redist.x64.exe",
        0xC000_0142 => "one of its libraries failed to initialise. Restart the computer; if it persists, install the Microsoft Visual C++ Redistributable (x64)",
        0xC000_007B => "Windows refused one of its files as damaged. Reinstall OpenConstructionERP; your projects are kept",
        0xC000_0409 | 0xC000_00FD => "it stopped itself after an internal error",
        0xC000_0017 | 0xC000_012D => "it ran out of memory. Close other programs and start it again",
        0xC000_001D | 0xC000_0096 => "Windows blocked a processor instruction it uses. This happens in some virtual machines and with some security software; try it on the computer directly or add the install folder to the antivirus exclusions",
        0xC000_0022 => "Windows denied it access. Security software or folder permissions blocked it",
        0xC000_013A => "it was closed before it finished starting",
        _ => "Windows stopped it",
    };
    format!("{meaning} (Windows error {hex})")
}

/// The last `max_lines` lines of a log file, lossily decoded; empty when unreadable.
pub fn log_tail(path: &Path, max_lines: usize) -> String {
    match std::fs::read(path) {
        Ok(bytes) => {
            let text = String::from_utf8_lossy(&bytes);
            let lines: Vec<&str> = text.lines().collect();
            let start = lines.len().saturating_sub(max_lines);
            lines[start..].join("\n")
        }
        Err(_) => String::new(),
    }
}

/// What one repair did. Nothing in it is ever a deletion of user data.
#[derive(Debug, Default, PartialEq, Eq)]
pub struct RepairReport {
    /// A `postmaster.pid` whose process is gone was removed.
    pub stale_pidfile_removed: bool,
    /// A database folder that never started was moved here, out of the way of
    /// a fresh initialisation. Moved, not deleted.
    pub set_aside: Option<PathBuf>,
    /// The remembered port was forgotten.
    pub port_file_removed: bool,
    /// Set when the repair stopped before touching anything, and why.
    pub refused: Option<&'static str>,
}

/// Put a data folder back into a state the next start can initialise from.
///
/// Safe by construction:
/// - a database whose postmaster is still alive is not touched at all;
/// - a database that has ever started (PostgreSQL writes `postmaster.opts` on
///   every start, initdb never does) keeps everything except a stale pidfile;
/// - a database folder that never started holds no user data, because nothing
///   could have written to it; it is renamed aside, not deleted, so a failed
///   initdb (antivirus lock, power loss, full disk) is retried from empty.
pub fn repair_data_dir(
    data_dir: &Path,
    cluster: &Path,
    last_port_file: &str,
    now_secs: u64,
    alive: &dyn Fn(u32) -> bool,
) -> RepairReport {
    let mut report = RepairReport::default();
    let pidfile = cluster.join("postmaster.pid");
    if let Ok(text) = std::fs::read_to_string(&pidfile) {
        let pid = text
            .lines()
            .next()
            .and_then(|l| l.trim().parse::<u32>().ok());
        if let Some(pid) = pid {
            if alive(pid) {
                report.refused = Some("database_running");
                return report;
            }
        }
        report.stale_pidfile_removed = std::fs::remove_file(&pidfile).is_ok();
    }

    let has_content = std::fs::read_dir(cluster)
        .map(|mut entries| entries.next().is_some())
        .unwrap_or(false);
    if has_content && !cluster.join("postmaster.opts").is_file() {
        let name = cluster
            .file_name()
            .map(|n| n.to_string_lossy().to_string())
            .unwrap_or_else(|| "pgdata".to_string());
        let aside = cluster.with_file_name(format!("{name}.incomplete-{now_secs}"));
        if std::fs::rename(cluster, &aside).is_ok() {
            report.set_aside = Some(aside);
        }
    }

    let port_file = data_dir.join(last_port_file);
    report.port_file_removed = port_file.is_file() && std::fs::remove_file(&port_file).is_ok();
    report
}

/// One log line for what the repair did.
pub fn repair_summary(report: &RepairReport) -> String {
    if let Some(why) = report.refused {
        return format!("repair skipped: {why}; nothing was changed");
    }
    let mut done = Vec::new();
    if report.stale_pidfile_removed {
        done.push("removed a stale postmaster.pid".to_string());
    }
    if let Some(aside) = &report.set_aside {
        done.push(format!(
            "moved a database folder that never started to {}",
            aside.display()
        ));
    }
    if report.port_file_removed {
        done.push("forgot the remembered port".to_string());
    }
    if done.is_empty() {
        "repair found nothing to change".to_string()
    } else {
        format!("repair: {}", done.join("; "))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tmp(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("oe-repair-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn windows_statuses_are_named_not_printed_raw() {
        let text = describe_exit_code(Some(-1073741819));
        assert!(text.contains("0xC0000005"), "{text}");
        assert!(text.contains("access violation"), "{text}");
        assert!(!text.contains("-1073741819"), "{text}");
        let dll = describe_exit_code(Some(-1073741515));
        assert!(dll.contains("Visual C++"), "{dll}");
        let unknown = describe_exit_code(Some(-1073741000));
        assert!(unknown.contains("0xC0000338"), "{unknown}");
        assert_eq!(describe_exit_code(Some(3)), "it ended with exit code 3");
        assert_eq!(describe_exit_code(None), "it ended without an exit code");
    }

    #[test]
    fn a_running_database_is_never_touched() {
        let data = tmp("running");
        let cluster = data.join("pgdata");
        std::fs::create_dir_all(&cluster).unwrap();
        std::fs::write(cluster.join("postmaster.pid"), "4242\n").unwrap();
        std::fs::write(cluster.join("PG_VERSION"), "16\n").unwrap();
        std::fs::write(data.join("last_port"), "8732\n").unwrap();
        let report = repair_data_dir(&data, &cluster, "last_port", 1, &|_| true);
        assert_eq!(report.refused, Some("database_running"));
        assert!(cluster.join("postmaster.pid").is_file());
        assert!(cluster.join("PG_VERSION").is_file());
        assert!(data.join("last_port").is_file());
        let _ = std::fs::remove_dir_all(&data);
    }

    #[test]
    fn a_database_that_has_run_keeps_everything_but_the_stale_pidfile() {
        let data = tmp("used");
        let cluster = data.join("pgdata");
        std::fs::create_dir_all(cluster.join("base")).unwrap();
        std::fs::write(cluster.join("postmaster.pid"), "4242\n").unwrap();
        std::fs::write(cluster.join("postmaster.opts"), "postgres\n").unwrap();
        std::fs::write(cluster.join("PG_VERSION"), "16\n").unwrap();
        let report = repair_data_dir(&data, &cluster, "last_port", 1, &|_| false);
        assert!(report.stale_pidfile_removed);
        assert_eq!(report.set_aside, None);
        assert!(cluster.join("PG_VERSION").is_file());
        assert!(cluster.join("base").is_dir());
        assert!(!cluster.join("postmaster.pid").exists());
        let _ = std::fs::remove_dir_all(&data);
    }

    #[test]
    fn a_database_that_never_started_is_moved_aside_not_deleted() {
        let data = tmp("never");
        let cluster = data.join("pgdata");
        std::fs::create_dir_all(cluster.join("global")).unwrap();
        std::fs::write(cluster.join("PG_VERSION"), "16\n").unwrap();
        std::fs::write(data.join("last_port"), "8732\n").unwrap();
        let report = repair_data_dir(&data, &cluster, "last_port", 77, &|_| false);
        let aside = data.join("pgdata.incomplete-77");
        assert_eq!(report.set_aside.as_deref(), Some(aside.as_path()));
        assert!(aside.join("PG_VERSION").is_file());
        assert!(!cluster.exists());
        assert!(report.port_file_removed);
        assert!(repair_summary(&report).contains("never started"));
        let _ = std::fs::remove_dir_all(&data);
    }

    #[test]
    fn an_empty_or_missing_database_folder_is_left_alone() {
        let data = tmp("empty");
        let cluster = data.join("pgdata");
        let report = repair_data_dir(&data, &cluster, "last_port", 1, &|_| false);
        assert_eq!(report, RepairReport::default());
        assert_eq!(repair_summary(&report), "repair found nothing to change");
        std::fs::create_dir_all(&cluster).unwrap();
        let report = repair_data_dir(&data, &cluster, "last_port", 1, &|_| false);
        assert_eq!(report.set_aside, None);
        let _ = std::fs::remove_dir_all(&data);
    }

    #[test]
    fn log_tail_keeps_the_end() {
        let data = tmp("tail");
        let log = data.join("x.log");
        std::fs::write(&log, "a\nb\nc\nd\n").unwrap();
        assert_eq!(log_tail(&log, 2), "c\nd");
        assert_eq!(log_tail(&data.join("missing.log"), 5), "");
        let _ = std::fs::remove_dir_all(&data);
    }
}
