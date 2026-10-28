# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A pid file left by a killed postmaster used to protect its data dir forever.

The reaper removed a throwaway cluster only when its directory had no
``postmaster.pid`` at all, on the reasoning that a pid file means somebody is
serving out of that directory. That covers a live session and a session whose
postmaster is still up, and both of those do have a live postmaster. It does
not cover the third case, which is the one that accumulates: a postmaster that
was force-killed leaves its pid file behind and nothing comes back to remove
it, so the directory is excluded from reaping for good.

Measured on this machine at the time of writing, eleven directories were being
held out of reach by pid files naming processes that no longer existed, and
the suite's own warning was reporting them as clusters still running.

What these tests pin is narrow and deliberate. The reaper must ask
``embedded_pg._pidfile_owner_is_live`` rather than test liveness itself: that
function answers yes when it cannot tell and treats a pid that is alive but
belongs to something else as gone, and a bare ``pid in os.listdir('/proc')``
style check gets the second one wrong on Windows often enough to matter. So
one test asserts the answer is acted on and another asserts the question is
asked of that function, about the directory the pid file is actually in.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from app.core import embedded_pg
from tests import conftest

_MIN_AGE = conftest._PG_REAP_MIN_AGE_SECONDS


def _cluster(root: Path, name: str, *, pid: int | None) -> Path:
    """Build a throwaway data dir, optionally with a pid file naming ``pid``."""
    entry = root / f"oe-tests-pg-{name}"
    (entry / "pgdata").mkdir(parents=True)
    if pid is not None:
        (entry / "pgdata" / "postmaster.pid").write_text(f"{pid}\n{entry}\n{int(time.time())}\n5432\n")
    # Older than the minimum age, so nothing is spared merely for being fresh.
    old = time.time() - _MIN_AGE - 60
    os.utime(entry, (old, old))
    return entry


def test_a_pidfile_naming_a_dead_process_no_longer_protects_its_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The leak, stated as a test: dead owner, directory goes.

    The liveness question is answered by a stub rather than by a real pid,
    because the property being pinned is that the reaper acts on the answer.
    Which pids are alive is the other function's subject and it has its own
    rules about uncertainty and recycling.
    """
    root = tmp_path
    monkeypatch.setattr(conftest, "_PG_TEMP_ROOT", root)

    dead = _cluster(root, "deadpid", pid=424242)
    live = _cluster(root, "livepid", pid=424243)
    clean = _cluster(root, "nopidfile", pid=None)

    monkeypatch.setattr(
        embedded_pg,
        "_pidfile_owner_is_live",
        lambda pgdata, pid: pid == 424243,
    )

    with pytest.warns(UserWarning, match="live postmaster"):
        conftest._reap_stale_pg_data_dirs()

    assert not dead.exists(), "a data dir whose postmaster is gone must be reaped"
    assert live.exists(), "a data dir with a live postmaster must be left alone"
    assert not clean.exists(), "a data dir with no pid file was always reapable"


def test_an_unreadable_pidfile_keeps_its_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No pid means no evidence, and no evidence must not become permission.

    A truncated or half-written pid file is what a machine that lost power
    leaves behind, and reading it as "nobody owns this" would delete a cluster
    on exactly the run that is trying to recover.

    The warning has to say which of the two reasons kept the dir. Counting an
    unreadable file in with the live postmasters would report a half-written
    file as a running database, and the whole point of the warning is to tell
    somebody what is actually holding their disk.
    """
    root = tmp_path
    monkeypatch.setattr(conftest, "_PG_TEMP_ROOT", root)

    entry = _cluster(root, "garbagepid", pid=None)
    (entry / "pgdata" / "postmaster.pid").write_text("not a number\n")
    old = time.time() - _MIN_AGE - 60
    os.utime(entry, (old, old))

    def _must_not_be_asked(pgdata: Path, pid: int) -> bool:  # pragma: no cover - guard
        raise AssertionError("liveness was asked about a pid file that has no pid in it")

    monkeypatch.setattr(embedded_pg, "_pidfile_owner_is_live", _must_not_be_asked)

    with pytest.warns(UserWarning, match="could not read") as caught:
        conftest._reap_stale_pg_data_dirs()

    assert entry.exists(), "an unreadable pid file must keep its data dir"
    message = str(caught[0].message)
    assert "live postmaster" not in message, f"an unreadable pid file was reported as a running server: {message}"


def test_the_question_goes_to_the_product_function_about_the_right_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pins where the pid file is, not just that something was consulted.

    ``_PG_PIDFILE_RELPATHS`` allows the file at ``<entry>/pgdata/postmaster.pid``
    or directly at ``<entry>/postmaster.pid``, and the helper takes the
    directory containing the file rather than the cluster root. Handing it the
    wrong one of those two reads no pid, which lands in the branch above and
    looks exactly like caution instead of like a bug.
    """
    root = tmp_path
    monkeypatch.setattr(conftest, "_PG_TEMP_ROOT", root)

    nested = _cluster(root, "nested", pid=555001)
    flat = root / "oe-tests-pg-flat"
    flat.mkdir()
    (flat / "postmaster.pid").write_text(f"555002\n{flat}\n{int(time.time())}\n5432\n")
    old = time.time() - _MIN_AGE - 60
    os.utime(flat, (old, old))

    asked: list[tuple[Path, int]] = []

    def _record(pgdata: Path, pid: int) -> bool:
        asked.append((Path(pgdata), pid))
        return True

    monkeypatch.setattr(embedded_pg, "_pidfile_owner_is_live", _record)

    with pytest.warns(UserWarning, match="live postmaster"):
        conftest._reap_stale_pg_data_dirs()

    directories = {directory for directory, _ in asked}
    assert nested / "pgdata" in directories, "the nested pid file must be asked about its own directory"
    assert flat in directories, "a pid file at the cluster root must be asked about the root"
