"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A data directory with a live postmaster must not get a second one.

Two OpenConstructionERP processes on one machine share ``~/.openestimate``, and
the desktop launcher can decide to start a backend while another one is already
running. Whether that is survivable comes down to a single property of
:mod:`app.core.embedded_pg`: a bring-up aimed at an occupied data directory
attaches to the cluster that is there and never creates, clears or launches
anything.

The property holds today, and it holds by accident of three separate guards
rather than by anything that states it:

* ``_pre_initialize_cluster`` and ``_clear_incomplete_cluster`` both return on
  ``PG_VERSION`` existing, and a live cluster always has one.
* ``_clear_stale_pidfile`` refuses to remove a pidfile naming a live process.
* ``pgserver.get_server()`` attaches to a running postmaster rather than
  starting another.

Nothing tested any of that, so nothing would notice it going. This is a
characterization test: it adds no behaviour and pins the behaviour there is, so
that swapping ``get_server()`` for a direct launch, or relaxing either
``PG_VERSION`` gate, fails here instead of on somebody's data.

Both polarities are asserted throughout. A module that refused to initialise
anything would pass every "leaves it alone" assertion and would never bring up a
cluster on a fresh machine, so each guard is also shown firing on the input it
was written for.
"""

from __future__ import annotations

import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.core import embedded_pg

# What PostgreSQL writes as the first eight lines of postmaster.pid: pid, data
# directory, start time, port, socket directory, listen address, shared memory
# and status. The parsers under test read lines one, three and four by position.
_PIDFILE_TEMPLATE = "{pid}\n{pgdata}\n{start}\n56139\n\n127.0.0.1\n  5432001         0\nready   \n"


def _real_start_time(pid: int) -> float:
    """The epoch second the process actually started, as PostgreSQL would record it.

    Line three is not decoration. ``_pid_was_recycled`` compares it against the
    process's real creation time, which is how a pidfile naming a number some
    unrelated service now holds is told apart from one naming a live postmaster.
    A fixture that writes an arbitrary constant there is therefore describing a
    recycled pid, and would test the wrong branch while looking like it tested
    this one.

    Falls back to now when :mod:`psutil` is absent, which is fine: without it
    ``_pid_was_recycled`` has no evidence and answers no before reading this
    value at all.
    """
    try:
        import psutil

        return float(psutil.Process(pid).create_time())
    except Exception:
        return time.time()


@pytest.fixture
def live_pid() -> Iterator[int]:
    """A process that is certainly running for the duration of the test."""
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

    ``yield`` rather than ``return`` on purpose: it keeps ``proc`` referenced,
    and on Windows the open handle is what stops the number being handed to
    something else mid-test.
    """
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait(timeout=60)
    assert not embedded_pg._pid_alive(proc.pid), "a process that has exited still reads as alive"
    yield proc.pid  # noqa: PT022


def _make_cluster(tmp_path: Path, *, pid: int | None, version: str | None, start: float | None = None) -> Path:
    """Build a pgdata directory, with a sentinel file to detect a wipe.

    ``version`` writes ``PG_VERSION`` (an initialised cluster); ``None`` leaves
    it out (the debris of an interrupted initdb). ``pid`` writes a pidfile, whose
    recorded start time defaults to the one ``pid`` really has.
    """
    pgdata = tmp_path / "pgdata"
    pgdata.mkdir(parents=True, exist_ok=True)
    (pgdata / "base").mkdir(exist_ok=True)
    (pgdata / "base" / "irreplaceable").write_text("the user's data", encoding="utf-8")
    if version is not None:
        (pgdata / "PG_VERSION").write_text(f"{version}\n", encoding="utf-8")
    if pid is not None:
        recorded = _real_start_time(pid) if start is None else start
        (pgdata / "postmaster.pid").write_text(
            _PIDFILE_TEMPLATE.format(pid=pid, pgdata=pgdata, start=f"{recorded:.0f}"),
            encoding="utf-8",
        )
    return pgdata


def _sentinel_survives(pgdata: Path) -> bool:
    return (pgdata / "base" / "irreplaceable").is_file()


def test_a_live_cluster_is_not_re_initialised(tmp_path: Path, live_pid: int) -> None:
    """The whole point: the bring-up creates nothing over a running cluster."""
    pgdata = _make_cluster(tmp_path, pid=live_pid, version="16")

    assert embedded_pg.cluster_postmaster_pid(tmp_path) == live_pid, "the fixture is not set up as a live cluster"
    assert embedded_pg._pre_initialize_cluster(pgdata) is False
    assert _sentinel_survives(pgdata)


def test_a_live_cluster_is_never_reached_by_the_directory_wipe(
    tmp_path: Path, live_pid: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not merely "the files are still there" but "the wipe was never called".

    Asserting only on the surviving file would keep passing if the clear were
    reached and happened to fail on a locked handle, which is a different and
    much worse install than one where it was never reached.
    """
    pgdata = _make_cluster(tmp_path, pid=live_pid, version="16")
    calls: list[Path] = []
    monkeypatch.setattr(embedded_pg, "_clear_incomplete_cluster", lambda path: calls.append(path))

    embedded_pg._pre_initialize_cluster(pgdata)

    assert calls == [], "the directory wipe was reached on a live cluster"


def test_the_wipe_still_clears_the_debris_it_was_written_for(tmp_path: Path, dead_pid: int) -> None:
    """The control. A guard that never fires is not a guard, it is dead code.

    An interrupted initdb leaves a directory with no ``PG_VERSION``, and initdb
    refuses to run into a non-empty one, so this really does have to clear it or
    a user stuck that way stays stuck.
    """
    pgdata = _make_cluster(tmp_path, pid=dead_pid, version=None)

    embedded_pg._clear_incomplete_cluster(pgdata)

    assert not _sentinel_survives(pgdata), "the debris of a failed initdb was left in place"


def test_the_wipe_refuses_a_directory_that_is_a_real_cluster(tmp_path: Path) -> None:
    """``PG_VERSION`` is the whole guard, so test it as the whole guard.

    No pidfile here at all: a cleanly stopped cluster is not running and still
    must never be emptied.
    """
    pgdata = _make_cluster(tmp_path, pid=None, version="16")

    embedded_pg._clear_incomplete_cluster(pgdata)

    assert _sentinel_survives(pgdata)


def test_a_live_postmasters_pidfile_is_left_alone(tmp_path: Path, live_pid: int) -> None:
    """Removing it would let a second postmaster start on top of the first."""
    pgdata = _make_cluster(tmp_path, pid=live_pid, version="16")

    embedded_pg._clear_stale_pidfile(pgdata)

    assert (pgdata / "postmaster.pid").is_file()


def test_a_dead_postmasters_pidfile_is_cleared(tmp_path: Path, dead_pid: int) -> None:
    """The control again: the ordinary aftermath of a force-kill has to clear."""
    pgdata = _make_cluster(tmp_path, pid=dead_pid, version="16")

    embedded_pg._clear_stale_pidfile(pgdata)

    assert not (pgdata / "postmaster.pid").exists()


def test_a_recycled_pid_is_not_a_live_postmaster(tmp_path: Path, live_pid: int) -> None:
    """A live number is not a live postmaster, and the difference is line three.

    This came out of a fixture bug and is worth keeping as a test. The pidfile
    here names a process that really is running and records a start time that
    process cannot have, which is exactly what a July pidfile naming a PID some
    licensing service now holds looks like. Treating it as a live cluster is how
    the machine ends up reporting a database ready on a port where nothing is
    listening, so it has to clear.
    """
    pytest.importorskip("psutil", reason="a recycled pid can only be detected with psutil")
    pgdata = _make_cluster(tmp_path, pid=live_pid, version="16", start=1_600_000_000.0)

    embedded_pg._clear_stale_pidfile(pgdata)

    assert not (pgdata / "postmaster.pid").exists(), "a pidfile describing a different process was kept"
    assert embedded_pg._pid_alive(live_pid), "clearing the file must not touch the process"


def test_a_cluster_that_is_not_proven_mute_is_never_stopped(tmp_path: Path, live_pid: int) -> None:
    """The one function in the module that ends a process must refuse here.

    ``_stop_mute_postmaster`` exists for a postmaster that holds its port and
    has stopped answering on it. This fixture is a live process that holds no
    port at all, which is what a data directory shared with an unrelated
    program looks like, and stopping it would be killing a stranger.
    """
    pgdata = _make_cluster(tmp_path, pid=live_pid, version="16")

    assert embedded_pg._stop_mute_postmaster(pgdata) is False
    assert embedded_pg._pid_alive(live_pid), "a process that was not ours was stopped"
