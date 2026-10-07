# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Evidence for native crashes and event-loop stalls, plus a memory probe.

A native crash (``0xC0000005`` on Windows, ``SIGSEGV`` elsewhere) kills the
interpreter without a Python traceback, so the only record used to be the exit
code the desktop launcher saw. Desktop reports showed the same shape twice: the
backend stopped answering ``/api/health`` for a minute or more, then died with
an access violation, and one of the two sessions had logged ``The paging file
is too small for this operation to complete (os error 1455)`` shortly before,
which means the machine had run out of commit memory (RAM plus page file).

This module makes the next one diagnosable and gives the vector layer a way to
back off before it walks into the same wall:

* :func:`enable_crash_log` turns on :mod:`faulthandler` for every thread,
  writing to ``<data_dir>/logs/backend-crash.log``. The desktop launcher reads
  the tail of that file when the backend dies and copies it into its own log.
* :func:`start_loop_stall_watchdog` dumps every thread's stack plus a memory
  snapshot to the same file when the event loop stops turning, because the
  hang comes before the crash and names the culprit while it is still running.
* :func:`available_commit_mb` reports how much memory the OS can still promise
  this process, so heavy native work (model loads, batch inference) can decline
  instead of failing an allocation deep inside native code.

Standard library and ``ctypes`` only, nothing new to ship.
"""

from __future__ import annotations

import asyncio
import contextlib
import ctypes
import faulthandler
import logging
import os
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

logger = logging.getLogger(__name__)

CRASH_LOG_NAME = "backend-crash.log"
# Rotated once past this size so a machine that crashes daily does not grow a
# file nobody reads. One previous generation is kept.
_MAX_LOG_BYTES = 1024 * 1024

# faulthandler writes to the raw file descriptor at crash time, so the file
# object must stay open for the life of the process.
_crash_file: IO[str] | None = None
_crash_path: Path | None = None
_write_lock = threading.Lock()


def crash_log_path(data_dir: Path) -> Path:
    """Where the crash log for ``data_dir`` lives."""
    return Path(data_dir) / "logs" / CRASH_LOG_NAME


def enable_crash_log(data_dir: Path) -> Path | None:
    """Route faulthandler output for all threads into the data dir.

    Idempotent. Returns the log path, or ``None`` when the file could not be
    opened, in which case faulthandler still writes to stderr, which the
    desktop launcher also captures.
    """
    global _crash_file, _crash_path
    if _crash_file is not None:
        return _crash_path
    path = crash_log_path(data_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > _MAX_LOG_BYTES:
            os.replace(path, path.with_suffix(".log.1"))
        fh = open(path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115 - must outlive this call
        fh.write(f"\n=== backend start {datetime.now(UTC).isoformat()} pid={os.getpid()} ===\n")
        fh.write(f"memory: {format_snapshot(memory_snapshot())}\n")
        fh.flush()
        faulthandler.enable(file=fh, all_threads=True)
    except Exception as exc:  # noqa: BLE001 - diagnostics must never stop a start
        logger.warning("Crash log unavailable (%s); native crashes will only reach stderr", exc)
        with contextlib.suppress(Exception):
            faulthandler.enable(all_threads=True)
        return None
    _crash_file, _crash_path = fh, path
    return path


def write_crash_note(text: str) -> None:
    """Append a line to the crash log, if one is open."""
    fh = _crash_file
    if fh is None:
        return
    with _write_lock, contextlib.suppress(Exception):
        fh.write(f"[{datetime.now(UTC).isoformat()}] {text}\n")
        fh.flush()


# ── Memory probe ──────────────────────────────────────────────────────────


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [  # noqa: RUF012 - ctypes layout
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [  # noqa: RUF012 - ctypes layout
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


_MB = 1024 * 1024


def _windows_snapshot() -> dict[str, float]:
    status = _MemoryStatusEx()
    status.dwLength = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined]
        return {}
    snap = {
        "total_ram_mb": status.ullTotalPhys / _MB,
        "avail_ram_mb": status.ullAvailPhys / _MB,
        # ullTotalPageFile/ullAvailPageFile are the commit limit and what is
        # left of it, not the page file alone. Running out of the latter is
        # what os error 1455 reports.
        "commit_limit_mb": status.ullTotalPageFile / _MB,
        "avail_commit_mb": status.ullAvailPageFile / _MB,
    }
    counters = _ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi = ctypes.windll.psapi  # type: ignore[attr-defined]
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    if psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        snap["process_private_mb"] = counters.PrivateUsage / _MB
        snap["process_peak_commit_mb"] = counters.PeakPagefileUsage / _MB
        snap["process_working_set_mb"] = counters.WorkingSetSize / _MB
    return snap


def _proc_meminfo_snapshot() -> dict[str, float]:
    values: dict[str, float] = {}
    with open("/proc/meminfo", encoding="ascii") as fh:
        for line in fh:
            key, _, rest = line.partition(":")
            parts = rest.split()
            if parts:
                values[key] = float(parts[0]) / 1024  # kB -> MB
    snap: dict[str, float] = {}
    if "MemTotal" in values:
        snap["total_ram_mb"] = values["MemTotal"]
    if "MemAvailable" in values:
        snap["avail_ram_mb"] = values["MemAvailable"]
    if "CommitLimit" in values and "Committed_AS" in values:
        snap["commit_limit_mb"] = values["CommitLimit"]
        # Linux overcommits by default, so the honest "what is left" for an
        # allocation is available RAM plus free swap, not the commit limit.
        snap["avail_commit_mb"] = values.get("MemAvailable", 0.0) + values.get("SwapFree", 0.0)
    return snap


def memory_snapshot() -> dict[str, float]:
    """Machine and process memory in MB. Empty when the platform gives nothing."""
    try:
        if sys.platform == "win32":
            return _windows_snapshot()
        if os.path.exists("/proc/meminfo"):
            return _proc_meminfo_snapshot()
    except Exception:  # noqa: BLE001 - a probe must never raise
        logger.debug("memory snapshot failed", exc_info=True)
    return {}


def available_commit_mb() -> float | None:
    """Memory the OS can still promise this process, or ``None`` if unknown."""
    return memory_snapshot().get("avail_commit_mb")


def format_snapshot(snap: dict[str, Any]) -> str:
    """One line, stable key order, for logs."""
    if not snap:
        return "unavailable"
    return " ".join(f"{k}={v:.0f}" for k, v in sorted(snap.items()))


def is_out_of_memory_error(exc: BaseException) -> bool:
    """True for the errors that mean the machine ran out of memory.

    ``MemoryError`` from Python, and the Windows commit-limit failure that the
    safetensors and torch loaders surface as an ``OSError`` or as a plain
    exception carrying ``os error 1455`` in its text.
    """
    if isinstance(exc, MemoryError):
        return True
    if isinstance(exc, OSError) and getattr(exc, "winerror", None) == 1455:
        return True
    text = str(exc).lower()
    return "os error 1455" in text or "paging file is too small" in text


# ── Event-loop stall watchdog ────────────────────────────────────────────

_watchdog_thread: threading.Thread | None = None
_last_beat: float = 0.0


def start_loop_stall_watchdog(
    loop: asyncio.AbstractEventLoop,
    *,
    threshold_s: float = 20.0,
    poll_s: float = 2.0,
) -> bool:
    """Dump all thread stacks when ``loop`` stops turning for ``threshold_s``.

    A heartbeat task on the loop records the time each second; a daemon thread
    compares it against the clock. One dump per stall: the watchdog re-arms
    only after the loop has beaten again. Returns ``False`` if already running.
    """
    global _watchdog_thread, _last_beat
    if _watchdog_thread is not None and _watchdog_thread.is_alive():
        return False

    _last_beat = time.monotonic()

    async def _heartbeat() -> None:
        global _last_beat
        while True:
            _last_beat = time.monotonic()
            await asyncio.sleep(1.0)

    loop.call_soon_threadsafe(lambda: loop.create_task(_heartbeat()))

    def _watch() -> None:
        dumped = False
        while not loop.is_closed():
            time.sleep(poll_s)
            stalled_for = time.monotonic() - _last_beat
            if stalled_for < threshold_s:
                dumped = False
                continue
            if dumped:
                continue
            dumped = True
            snap = format_snapshot(memory_snapshot())
            logger.warning("Event loop stalled for %.0fs; memory: %s", stalled_for, snap)
            write_crash_note(f"event loop stalled for {stalled_for:.0f}s; memory: {snap}; all thread stacks follow")
            fh = _crash_file
            with contextlib.suppress(Exception):
                faulthandler.dump_traceback(file=fh if fh is not None else sys.stderr, all_threads=True)

    _watchdog_thread = threading.Thread(target=_watch, name="oe-loop-watchdog", daemon=True)
    _watchdog_thread.start()
    return True
