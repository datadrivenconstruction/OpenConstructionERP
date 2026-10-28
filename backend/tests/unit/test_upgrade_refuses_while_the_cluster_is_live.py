"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠An upgrade must not overwrite the binaries it is running from.

``pip install --upgrade`` replaces files in site-packages, and on this install
some of those files are executing: the embedded PostgreSQL binaries ship inside
pixeltable_pgserver, so ``postgres`` runs from the same tree pip is about to
rewrite. On Windows the running image is locked and pip fails partway, leaving
an install that is neither version. Elsewhere it succeeds and the live process
becomes a mixture, because this codebase imports inside functions and every
later import reads the new file.

So the question the upgrade has to ask is not ``is_running()``, which answers
about the calling process and is always False in the short-lived CLI. It is
"does this machine have a postmaster serving that data directory", and the only
honest source for that is the operating system, not the pidfile: the pidfile
outlives an unclean stop, and a leftover must not be the reason an upgrade
refuses.

Both directions are asserted here. A checker that never refuses is the bug
being fixed; a checker that always refuses replaces a torn install with an
install nobody can perform.

"Is the machine running a postmaster" has a second half that is easy to miss:
the number in the pidfile has to still belong to the postmaster that wrote it.
Operating systems reuse process identifiers, Windows quickly, so a pidfile left
by a force-killed postmaster eventually names an unrelated service. Reading
that as a live cluster is the always-refuses failure in its worst form, because
it never clears on its own. Both polarities of that are asserted too.
"""

from __future__ import annotations

import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.core import embedded_pg


@pytest.fixture
def live_pid() -> Iterator[int]:
    """A process that is definitely running for the duration of the test."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        assert embedded_pg._pid_alive(proc.pid), "a process we just started does not read as alive"
        yield proc.pid
    finally:
        proc.kill()
        proc.wait(timeout=30)


@pytest.fixture
def dead_pid() -> Iterator[int]:
    """A pid that named a process and no longer does.

    The ``yield`` is deliberate and must not be turned into a ``return``: it
    keeps ``proc`` referenced, and on Windows the open process handle is what
    reserves the pid against reuse. Let the handle go and the number may be
    handed to something else mid-test, which would quietly invert the assertion
    this fixture exists to support.
    """
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait(timeout=60)
    assert not embedded_pg._pid_alive(proc.pid), "a process that has exited still reads as alive"
    yield proc.pid  # noqa: PT022


def _real_start_time(pid: int) -> float:
    """The epoch second ``pid`` actually started, as PostgreSQL would record it.

    Line three of the pidfile is not decoration. It is what tells a live
    postmaster apart from a live stranger holding a recycled number, so a
    fixture that writes an arbitrary constant there is describing a recycled
    pid whatever it meant to describe.

    Falls back to now when :mod:`psutil` is missing, which is consistent:
    without it the recycling check has no evidence and answers no anyway.
    """
    try:
        import psutil

        return float(psutil.Process(pid).create_time())
    except Exception:
        return time.time()


def _write_pidfile(data_dir: Path, pid: int, start: float | None = None) -> Path:
    """Lay down a postmaster.pid the way PostgreSQL does.

    ``start`` defaults to the time ``pid`` really started, which is what makes
    this a live postmaster rather than a stranger. Pass one explicitly to
    describe a recycled pid.
    """
    pgdata = data_dir / "pgdata"
    pgdata.mkdir(parents=True, exist_ok=True)
    pidfile = pgdata / "postmaster.pid"
    recorded = _real_start_time(pid) if start is None else start
    pidfile.write_text(
        f"{pid}\n{pgdata}\n{recorded:.0f}\n56139\n\n127.0.0.1\n  5432001         0\nready   \n",
        encoding="utf-8",
    )
    return pidfile


def test_a_live_postmaster_is_reported(tmp_path: Path, live_pid: int) -> None:
    """The case the guard exists for."""
    _write_pidfile(tmp_path, live_pid)

    assert embedded_pg.cluster_postmaster_pid(tmp_path) == live_pid


def test_a_stale_pidfile_is_not_a_running_cluster(tmp_path: Path, dead_pid: int) -> None:
    """The control, and the one that keeps the guard usable.

    A pidfile left behind by an unclean stop is the ordinary state of a machine
    that crashed. Reading it as a live cluster would refuse every upgrade on
    exactly the installs most in need of one.
    """
    _write_pidfile(tmp_path, dead_pid)

    assert embedded_pg.cluster_postmaster_pid(tmp_path) is None


def test_no_pidfile_at_all_is_not_a_running_cluster(tmp_path: Path) -> None:
    (tmp_path / "pgdata").mkdir(parents=True)

    assert embedded_pg.cluster_postmaster_pid(tmp_path) is None


def test_no_data_directory_at_all_is_not_a_running_cluster(tmp_path: Path) -> None:
    """A first-ever install has no pgdata. It must upgrade freely."""
    assert embedded_pg.cluster_postmaster_pid(tmp_path / "never-created") is None


def test_an_unreadable_pidfile_does_not_block_an_upgrade(tmp_path: Path) -> None:
    """Unknown means no reason to refuse.

    This answer only ever gates an action; it never authorises one. So the
    failure direction has to be permissive, or a corrupt byte in a file nobody
    looks at becomes an install that can never be updated again.
    """
    pgdata = tmp_path / "pgdata"
    pgdata.mkdir(parents=True)
    (pgdata / "postmaster.pid").write_bytes(b"\xff\xfe not a pid at all\n")

    assert embedded_pg.cluster_postmaster_pid(tmp_path) is None


def test_it_asks_about_the_machine_not_about_this_process(
    tmp_path: Path, live_pid: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The distinction the fix turns on.

    ``is_running`` reports whether *this* process booted a cluster. The upgrade
    command always runs in a process that did not, so a guard written on it
    would have answered False on every install and protected nobody.

    ``_server`` is forced to None rather than assumed to be None: the test
    session's own conftest boots an embedded cluster, so in here the module
    global is set and the assertion would otherwise pass or fail depending on
    which suite it was run beside. Pinning it makes the contrast the point of
    the test rather than a side effect of the harness.
    """
    monkeypatch.setattr(embedded_pg, "_server", None, raising=False)
    _write_pidfile(tmp_path, live_pid)

    assert embedded_pg.is_running() is False, "the process-local answer should be no"
    assert embedded_pg.cluster_postmaster_pid(tmp_path) == live_pid, (
        "the machine-wide answer should still find the cluster"
    )


def test_a_recycled_pid_does_not_block_an_upgrade(tmp_path: Path, live_pid: int) -> None:
    """A live number is not a live cluster, and the difference is line three.

    This is the permanent version of the always-refuses failure. A stale
    pidfile whose number has been handed to some unrelated service names a
    process that really is running, so a liveness-only check reads a cluster
    that does not exist and refuses the upgrade. Nothing clears it: the service
    keeps running, the pidfile keeps naming it, and the machine can never be
    upgraded again by the one command that would repair it.
    """
    pytest.importorskip("psutil", reason="recycling can only be detected with psutil")
    _write_pidfile(tmp_path, live_pid, start=1_600_000_000.0)

    assert embedded_pg.cluster_postmaster_pid(tmp_path) is None
    assert embedded_pg._pid_alive(live_pid), "the reading must not disturb the process"


def test_the_same_live_pid_answers_differently_depending_on_who_it_is(tmp_path: Path, live_pid: int) -> None:
    """Both polarities on one process, which is the whole claim in one place.

    The pid, the machine and the data directory are identical across the two
    halves; only the recorded start time differs. So this cannot pass by the
    guard having stopped blocking, which is the way a one-sided test would be
    satisfied by deleting the protection instead of correcting it.
    """
    pytest.importorskip("psutil", reason="recycling can only be detected with psutil")

    _write_pidfile(tmp_path, live_pid)
    assert embedded_pg.cluster_postmaster_pid(tmp_path) == live_pid, (
        "a genuinely live postmaster must still block the upgrade"
    )

    _write_pidfile(tmp_path, live_pid, start=1_600_000_000.0)
    assert embedded_pg.cluster_postmaster_pid(tmp_path) is None, (
        "the same number held by something else must not block the upgrade"
    )


def test_an_unreadable_start_time_falls_back_to_what_the_process_is(tmp_path: Path, live_pid: int) -> None:
    """The other half of the recycling check, which the timestamp tests never reach.

    With line three intact the recorded time settles the question on its own.
    Corrupt it and the check falls back to asking what the process actually is,
    a branch nothing else in the suite exercises. A live process that is plainly
    not a postmaster is not this cluster whatever the pidfile says, and a real
    postmaster survives this because it is named like one.
    """
    pytest.importorskip("psutil", reason="the fallback needs a process name")
    pgdata = tmp_path / "pgdata"
    pgdata.mkdir(parents=True, exist_ok=True)
    (pgdata / "postmaster.pid").write_text(
        f"{live_pid}\n{pgdata}\nNOT-A-TIME\n56139\n\n127.0.0.1\n  5432001         0\nready   \n",
        encoding="utf-8",
    )

    assert embedded_pg._read_pidfile_start_time(pgdata) is None, "the fixture must reach the fallback"
    assert embedded_pg.cluster_postmaster_pid(tmp_path) is None
