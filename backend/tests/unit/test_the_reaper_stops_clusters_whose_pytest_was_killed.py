# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A test cluster whose pytest was killed is stopped and removed by the next run.

``atexit`` stops the session's postmaster, but a pytest killed by a timeout
never reaches it. The postmaster keeps running, its pid file names a live
process, and the reaper rightly refuses to touch a cluster that is being
served from. One machine had eight such servers running at once.

The owner file closes that gap: the session records which pytest booted the
cluster, and a later run that finds a live postmaster whose owner is dead stops
it and takes the dir. Without an owner file, or with an owner that is alive,
nothing changes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.core import embedded_pg
from tests import conftest


def _cluster(root: Path, name: str, *, owner_pid: int | None, owner_started: float | None = None) -> Path:
    entry = root / f"oe-tests-pg-{name}"
    (entry / "pgdata").mkdir(parents=True)
    (entry / "pgdata" / "postmaster.pid").write_text(f"777001\n{entry}\n{int(time.time())}\n5432\n")
    if owner_pid is not None:
        (entry / conftest._PG_OWNER_FILE).write_text(json.dumps({"pid": owner_pid, "started": owner_started}))
    # Fresh on purpose: an orphan is reaped for its dead owner, not for its age.
    return entry


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])  # noqa: S603
    proc.wait()
    return proc.pid


@pytest.fixture
def stops(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[tuple[Path, int]]:
    monkeypatch.setattr(conftest, "_PG_TEMP_ROOT", tmp_path)
    # The postmaster itself is "alive"; what differs per test is its owner.
    monkeypatch.setattr(embedded_pg, "_pidfile_owner_is_live", lambda pgdata, pid: True)
    calls: list[tuple[Path, int]] = []

    def _stop(pgdata: Path, pid: int) -> bool:
        calls.append((pgdata, pid))
        return True

    monkeypatch.setattr(conftest, "_stop_orphan_postmaster", _stop)
    return calls


def test_a_cluster_whose_pytest_is_dead_is_stopped_and_removed(tmp_path: Path, stops: list) -> None:
    orphan = _cluster(tmp_path, "orphan", owner_pid=_dead_pid())

    with pytest.warns(UserWarning, match="stopped 1 orphaned"):
        conftest._reap_stale_pg_data_dirs()

    assert stops == [(orphan / "pgdata", 777001)]
    assert not orphan.exists()


def test_a_cluster_whose_pytest_is_alive_is_left_alone(tmp_path: Path, stops: list) -> None:
    me = os.getpid()
    # Another live process, not this one: this one is excluded on its own.
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])  # noqa: S603
    try:
        served = _cluster(
            tmp_path, "served", owner_pid=sleeper.pid, owner_started=conftest._process_start_time(sleeper.pid)
        )
        mine = _cluster(tmp_path, "mine", owner_pid=me, owner_started=conftest._process_start_time(me))
        with pytest.warns(UserWarning, match="live postmaster"):
            conftest._reap_stale_pg_data_dirs()
    finally:
        sleeper.kill()
        sleeper.wait()

    assert stops == []
    assert served.exists()
    assert mine.exists()


def test_a_cluster_without_an_owner_file_keeps_the_old_treatment(tmp_path: Path, stops: list) -> None:
    legacy = _cluster(tmp_path, "legacy", owner_pid=None)

    with pytest.warns(UserWarning, match="live postmaster"):
        conftest._reap_stale_pg_data_dirs()

    assert stops == []
    assert legacy.exists()


def test_a_recycled_owner_pid_counts_as_dead(tmp_path: Path, stops: list) -> None:
    """The pid is alive but started long after the owner did: someone else has it."""
    me = os.getpid()
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])  # noqa: S603
    try:
        recycled = _cluster(tmp_path, "recycled", owner_pid=other.pid, owner_started=time.time() - 86_400)
        with pytest.warns(UserWarning, match="stopped 1 orphaned"):
            conftest._reap_stale_pg_data_dirs()
    finally:
        other.kill()
        other.wait()

    assert me != other.pid
    assert len(stops) == 1
    assert not recycled.exists()


def test_a_stop_that_fails_keeps_the_dir(tmp_path: Path, stops: list, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(conftest, "_stop_orphan_postmaster", lambda pgdata, pid: False)
    stuck = _cluster(tmp_path, "stuck", owner_pid=_dead_pid())

    with pytest.warns(UserWarning, match="live postmaster"):
        conftest._reap_stale_pg_data_dirs()

    assert stuck.exists()


def test_stop_ends_a_real_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The stop itself, against a stand-in postmaster; pg_ctl is kept out of it."""
    monkeypatch.setattr(embedded_pg, "_pg_ctl_path", lambda: None)
    stand_in = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])  # noqa: S603
    try:
        assert conftest._stop_orphan_postmaster(tmp_path, stand_in.pid) is True
        assert stand_in.wait(timeout=10) is not None
    finally:
        if stand_in.poll() is None:
            stand_in.kill()
            stand_in.wait()


def test_the_session_writes_its_owner_file(tmp_path: Path) -> None:
    conftest._write_pg_owner(tmp_path)
    payload = json.loads((tmp_path / conftest._PG_OWNER_FILE).read_text(encoding="utf-8"))
    assert payload["pid"] == os.getpid()
    assert conftest._pg_owner_is_gone(tmp_path) is False
