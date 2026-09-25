# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Running an upgrade of this install, and knowing when it cannot be run at all.

The desktop app ships as a PyInstaller sidecar, so ``sys.executable`` there is
the frozen binary rather than an interpreter. A ``[sys.executable, "-m", "pip",
"install", ...]`` command therefore feeds its own tokens straight back into this
application's argparse CLI, which answers ``invalid choice: 'pip'`` and shows
the user a usage dump where an upgrade should have been (issue #403). The
bundle carries no pip to fix that with either: on the desktop the installer
replaces the whole application.

Two places build that command - the ``/api/system/upgrade`` route and the
``upgrade`` CLI command - and both must refuse identically, so the decision and
the wording live here rather than being written out twice.

The upgrade itself also lives here, as a job rather than a function call.
Downloading a release, resolving its dependencies and installing them takes as
long as it takes, which on a slow link is minutes, and no request can be held
open that long: the browser gave up at 45 seconds and reported a failure over
an upgrade that was still running and would go on to succeed (issue #430). Worse
than the wrong message, the work ran inline in the event loop of a single worker
process, so for its whole duration the server answered nothing at all, and the
user watching it had no way to tell a stuck upgrade from a slow one.

So the request starts a job and returns its id, the work runs in a thread, and
the state is polled. One job runs at a time; asking again while one is running
returns the one already going rather than starting a second pip against the same
site-packages.

The registry is in this process's memory on purpose. An upgrade ends by asking
the user to restart, and a restart is exactly what discards the record, which is
correct: after the restart the installed version answers the question the job
was tracking. Deployments that run more than one worker cannot share a lock this
way and should leave the route off, as it is unless ``ALLOW_RUNTIME_UPGRADE=true``
is set (see :func:`runtime_upgrade_enabled`), which is what a pipeline-managed
install wants regardless.
"""

from __future__ import annotations

import logging
import os
import subprocess  # noqa: S404 - this module's whole job is to run pip
import sys
import sysconfig
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

RELEASES_URL = "https://github.com/datadrivenconstruction/OpenConstructionERP/releases/latest"

#: Shown verbatim to the user when a frozen build is asked to upgrade itself.
FROZEN_REFUSAL = (
    "The desktop app cannot upgrade itself with pip. Download the latest "
    f"installer from {RELEASES_URL} and run it over this install - your "
    "projects and settings stay where they are."
)

#: Repairing a bundle that shipped something broken.
DESKTOP_REPAIR = (
    "This is the desktop build and it carries no pip. Repair it by reinstalling "
    f"the app from its installer ({RELEASES_URL}), which replaces the whole "
    "application and leaves your projects and settings where they are."
)

#: Adding something the bundle never carried in the first place.
DESKTOP_NO_EXTRA = (
    "This is the desktop build. It ships a fixed set of packages and has no pip "
    "to add to them, so this cannot be switched on here. It needs either a build "
    "that carries it or the server install."
)


def repair_hint(pip_advice: str, frozen_advice: str = DESKTOP_REPAIR) -> str:
    """Give advice the reader can carry out where they are standing.

    Remedies across this codebase are written for a pip install, which is where
    most of them are read. In the bundle they are not merely awkward, they are
    impossible: ``sys.executable`` is the app binary, so a pip command feeds its
    own tokens back into this application's CLI. Somebody who follows one learns
    only that the tool which found the fault cannot fix it either, and the next
    message they are shown gets less trust than it deserves.

    Here rather than at each call site for the reason this module already gives
    about the upgrade refusal: two places wording the same decision drift, and
    the second one is always written by somebody who has not read the first.

    ``is_frozen_build`` and not :func:`app.config.desktop_mode`: the question is
    the mechanical one, whether ``sys.executable`` can run ``-m pip``. The
    Windows installer builds are desktop too and run a real interpreter out of a
    private venv, so pip advice is right for them.

    Args:
        pip_advice: What to say where pip exists, which is most installs.
        frozen_advice: What to say inside a bundle. Defaults to repairing a
            damaged install; pass :data:`DESKTOP_NO_EXTRA` when the thing was
            never carried, because telling somebody to reinstall in that case
            sends them round a loop that changes nothing.
    """
    return frozen_advice if is_frozen_build() else pip_advice


def is_frozen_build() -> bool:
    """True when running inside a PyInstaller bundle.

    Deliberately reads ``sys.frozen`` rather than the ``OE_DESKTOP`` environment
    variable that :func:`app.config.desktop_mode` also honours. What matters
    here is not "is this the desktop product" but the narrower, purely mechanical
    question "is ``sys.executable`` an interpreter that can run ``-m pip``".
    The Windows installer builds are desktop too, yet they run a real
    ``python.exe`` out of a private venv and upgrade themselves perfectly well.
    """
    return bool(getattr(sys, "frozen", False))


#: The switch that lets an admin run ``pip install --upgrade`` from the browser.
RUNTIME_UPGRADE_ENV = "ALLOW_RUNTIME_UPGRADE"

#: Why the browser may not run an upgrade here. The UI reads the code, not the text.
UPGRADE_DISABLED = "disabled"
UPGRADE_DEMO_ACCOUNT = "demo_account"

#: The refusal the route answers when the switch is off.
DISABLED_REFUSAL = (
    "Updating from the browser is disabled on this install. To switch it on, set "
    f"{RUNTIME_UPGRADE_ENV}=true in the server's environment and restart it. Or run "
    "`pip install --upgrade openconstructionerp` from a shell on the server, then restart."
)

#: The refusal the route answers to a shared demo login.
DEMO_ACCOUNT_REFUSAL = "Demo accounts cannot update the installation. Sign in with your own administrator account."


def runtime_upgrade_enabled() -> bool:
    """Whether ``ALLOW_RUNTIME_UPGRADE`` switches the browser upgrade on. Off unless set.

    It defaulted to on, so any admin session could replace the packages of the
    environment the server runs from, and the seeded demo login is an admin
    that needs no password wherever the demo login is offered. One press
    upgraded every instance sharing that environment. The installs that
    actually used it are single-user pip installs, and for them switching it on
    is one line; the desktop bundle never could (it has no pip), and a Docker
    container should be upgraded by pulling an image, not by pip inside it.

    Read at call time so a test, or an operator restarting with a new
    environment, is not fighting a value cached at import.
    """
    return os.environ.get(RUNTIME_UPGRADE_ENV, "").strip().lower() in ("true", "1", "yes")


def runtime_upgrade_refusal(caller_email: str | None) -> str | None:
    """Why this caller may not start an upgrade from the browser, or ``None``.

    Only the browser route asks. The ``upgrade`` CLI command is an operator at
    a shell on the server, who is not the person this protects against.

    A demo account is refused even with the switch on: it is a login shared
    by everyone the demo is shown to, several of them password-free.
    """
    from app.core.demo_accounts import is_demo_account

    if not runtime_upgrade_enabled():
        return UPGRADE_DISABLED
    if is_demo_account(caller_email):
        return UPGRADE_DEMO_ACCOUNT
    return None


#: How long pip is given before the job is failed rather than left hanging.
UPGRADE_TIMEOUT_SECONDS = 600

RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"


@dataclass
class UpgradeJob:
    """One attempt at upgrading this install, from start to whatever ended it.

    Carries the log rather than a summary of it. An upgrade that fails does so
    inside pip's output, and a user who cannot read that output has nothing to
    act on but the word "failed".
    """

    id: str
    command: list[str]
    running_version: str
    started_at: str
    status: str = RUNNING
    finished_at: str | None = None
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    installed_version: str = ""
    error: str = ""
    #: Launchers moved aside on Windows, restored if pip does not replace them.
    _renamed: list[tuple[Path, Path]] = field(default_factory=list, repr=False)

    @property
    def restart_required(self) -> bool:
        """Whether the running process is now older than what is on disk.

        Python caches imports, so pip can replace files while every module
        already loaded stays exactly as it was. Nothing about a successful
        install makes this process the new version.
        """
        return bool(self.installed_version) and self.installed_version != self.running_version

    def as_dict(self) -> dict[str, Any]:
        """The job as the API reports it."""
        return {
            "job_id": self.id,
            "status": self.status,
            "ok": self.status == SUCCEEDED,
            "command": " ".join(self.command),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "exit_code": self.exit_code,
            "stdout": self.stdout[-4000:],
            "stderr": self.stderr[-2000:],
            "error": self.error,
            "installed_version": self.installed_version,
            "running_version": self.running_version,
            "restart_required": self.restart_required,
            "restart_hint": (
                "Restart your launcher (start.bat / `openconstructionerp serve`) "
                "or the host's systemd unit to load the new version."
            ),
        }


_lock = threading.Lock()
_current: UpgradeJob | None = None


def current_upgrade() -> UpgradeJob | None:
    """The upgrade running now, or the last one this process ran."""
    with _lock:
        return _current


def claim_upgrade(command: list[str], running_version: str) -> tuple[UpgradeJob, bool]:
    """Take the upgrade slot, or report who already holds it.

    Returns the job and whether this call is the one that started it. A caller
    that gets ``False`` should attach to the returned job rather than treat it
    as an error state of its own: pressing a button twice, or pressing it again
    after the browser gave up waiting, is the ordinary way this happens.

    Claiming and starting are separate steps so the slot is taken while the
    lock is held, before any of the work begins.
    """
    global _current
    with _lock:
        if _current is not None and _current.status == RUNNING:
            return _current, False
        _current = UpgradeJob(
            id=uuid.uuid4().hex,
            command=list(command),
            running_version=running_version,
            started_at=datetime.now(UTC).isoformat(),
        )
        return _current, True


def _move_windows_launchers_aside(job: UpgradeJob) -> None:
    """Rename the console scripts this process is holding open.

    On Windows the running launcher keeps an open handle on its own .exe, so
    pip cannot overwrite it and the whole install aborts with WinError 32.
    Windows does allow renaming a running .exe, so the locked launchers move
    aside and pip writes fresh ones in their place. The renamed stubs stay
    locked until this process exits and are swept on the next upgrade.
    """
    if sys.platform != "win32":
        return
    scripts_dir = Path(sysconfig.get_path("scripts"))
    for stale in scripts_dir.glob("*.oce-old-*"):
        try:
            stale.unlink()
        except OSError:
            pass  # a leftover still locked by an older process - skip
    for exe_name in (
        "openconstructionerp.exe",
        "openconstructionerp-server.exe",
        "openestimate.exe",
        "openestimate-server.exe",
    ):
        exe = scripts_dir / exe_name
        if not exe.exists():
            continue
        aside = exe.with_name(f"{exe.name}.oce-old-{os.getpid()}")
        try:
            exe.rename(aside)
            job._renamed.append((exe, aside))
        except OSError:
            pass  # best effort - let pip surface the real error


def _restore_missing_launchers(job: UpgradeJob) -> None:
    """Never leave the user without a launcher.

    If pip did not recreate one we moved aside, for instance because the
    target was already satisfied and it installed nothing, put the original
    back where it was.
    """
    for original, aside in job._renamed:
        if not original.exists() and aside.exists():
            try:
                aside.rename(original)
            except OSError:
                logger.warning("Could not restore launcher %s after upgrade", original)


def _installed_version(fallback: str) -> str:
    """What the distribution reports on disk now, or ``fallback``."""
    try:
        from importlib.metadata import version

        return version("openconstructionerp")
    except Exception:  # noqa: BLE001 - a missing or unreadable dist is not fatal here
        return fallback


def run_upgrade(job: UpgradeJob) -> UpgradeJob:
    """Run one claimed job to completion. Blocking, meant for a worker thread.

    Never raises: an upgrade that fell over is a job that says so, because the
    caller is a background task whose exception nobody would ever see.
    """
    try:
        _move_windows_launchers_aside(job)
        proc = subprocess.run(  # noqa: S603 - the command is built and sanitised by the caller
            job.command,
            capture_output=True,
            text=True,
            timeout=UPGRADE_TIMEOUT_SECONDS,
        )
        job.exit_code = proc.returncode
        job.stdout = proc.stdout or ""
        job.stderr = proc.stderr or ""
        job.status = SUCCEEDED if proc.returncode == 0 else FAILED
    except subprocess.TimeoutExpired:
        job.status = FAILED
        job.error = (
            f"The upgrade did not finish within {UPGRADE_TIMEOUT_SECONDS} seconds and was stopped. "
            "Run `pip install --upgrade openconstructionerp` from a shell to see where it stalls."
        )
        logger.warning("Upgrade job %s timed out after %ss", job.id, UPGRADE_TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 - reported through the job, not raised
        job.status = FAILED
        job.error = str(exc)
        logger.exception("Upgrade job %s failed", job.id)
    finally:
        _restore_missing_launchers(job)
        job.installed_version = _installed_version(job.running_version)
        job.finished_at = datetime.now(UTC).isoformat()
    return job


def reset_upgrade_state() -> None:
    """Forget the current job. For tests, which must not inherit one another."""
    global _current
    with _lock:
        _current = None
