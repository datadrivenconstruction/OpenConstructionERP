# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The data-dir reaper must not delete a cluster that is serving.

``_reap_stale_pg_data_dirs`` removes throwaway PostgreSQL data dirs left by
runs that ended without cleaning up. It is guarded twice: a directory is spared
if a postmaster pid file says a cluster is live, and separately if it was
touched recently. The conftest comment calls the age check "a belt to the
braces", meaning the pid file is supposed to be the real guard.

The brace was not fastened. The check tested ``<dir>/postmaster.pid`` while
``embedded_pg.boot`` puts the cluster in ``<dir>/pgdata`` and the postmaster
writes its pid file there, so the test matched nothing on any machine.
Measured on this tree before the fix: of the data dirs present, none carried a
pid file at the bare name and every one carried it under ``pgdata``. The guard
had therefore never fired once, and every live cluster older than the age cut
was one ``shutil.rmtree`` away from being deleted out from under the session
using it.

Nothing went red, because a guard that spares nothing looks exactly like a
guard with nothing to spare. The count it reports is the tell: it said zero
running clusters on a machine where every cluster was running.
"""

from __future__ import annotations

import os
import time
import warnings
from pathlib import Path

import pytest

from app.core import embedded_pg
from tests import conftest

#: Comfortably past ``_PG_REAP_MIN_AGE_SECONDS`` so the age belt never decides
#: the outcome. These tests are about the pid file, and a directory young
#: enough to be spared on age would pass them for the wrong reason.
_OLDER_THAN_THE_CUT = conftest._PG_REAP_MIN_AGE_SECONDS + 3600

#: The pid every "live" data dir here writes into its pid file. The reaper now
#: reads that pid and asks whether its owner is alive, so a real number would
#: make the outcome depend on the machine: a development box that happened to
#: have a process at 4242 spared the dir, and every CI runner, which did not,
#: deleted it. The autouse fixture below answers the question by pid instead.
_LIVE_PID = 4242


def _data_dir(root: Path, name: str, pidfile: str | None) -> Path:
    """Build one throwaway data dir, optionally holding a pid file.

    ``pidfile`` is a path relative to the data dir, so a caller can place it
    where a postmaster really puts it or where the old check looked for it.
    The directory's own mtime is aged last: writing a file inside refreshes
    it, and a dir that looks fresh is spared by the wrong guard.
    """
    entry = root / name
    entry.mkdir(parents=True)
    if pidfile is not None:
        target = entry / pidfile
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"{_LIVE_PID}\n", encoding="utf-8")
    old = time.time() - _OLDER_THAN_THE_CUT
    os.utime(entry, (old, old))
    return entry


@pytest.fixture
def reap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Run the reaper against a temp root instead of the real one."""
    monkeypatch.setattr(conftest, "_PG_TEMP_ROOT", tmp_path)

    def _run() -> None:
        # The reaper warns whenever it spares something, which is the normal
        # outcome here rather than a problem to surface.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            conftest._reap_stale_pg_data_dirs()

    return _run


@pytest.fixture(autouse=True)
def _live_pid_is_a_live_postmaster(monkeypatch: pytest.MonkeyPatch) -> None:
    """Say ``_LIVE_PID`` is a running postmaster and every other pid is gone.

    What these tests pin is where the reaper looks for the pid file, not which
    processes a given machine happens to be running. Whether a pid is alive is
    ``embedded_pg._pidfile_owner_is_live``'s subject, and
    test_the_reaper_reads_the_pidfile_it_counts.py pins that the reaper acts on
    its answer, including a dead owner and an unreadable file.
    """
    monkeypatch.setattr(embedded_pg, "_pidfile_owner_is_live", lambda _pgdata, pid: pid == _LIVE_PID)


def test_a_cluster_with_a_live_pid_file_survives(tmp_path: Path, reap) -> None:
    """The real layout: the pid file lives under ``pgdata``."""
    entry = _data_dir(tmp_path, "oe-tests-pg-live", "pgdata/postmaster.pid")

    reap()

    assert entry.exists(), "a serving cluster's data dir was deleted"


def test_a_cluster_with_no_pid_file_is_still_reaped(tmp_path: Path, reap) -> None:
    """The control, and the reason the test above means anything.

    A reaper that had simply stopped deleting would pass every other case
    here. This is the one that fails if the fix went too far, so the pair
    pins the guard from both sides.
    """
    entry = _data_dir(tmp_path, "oe-tests-pg-dead", None)

    reap()

    assert not entry.exists(), "an abandoned data dir was left behind"


def test_the_bare_pid_file_location_also_spares_a_dir(tmp_path: Path, reap) -> None:
    """A pid file directly in the data dir counts too.

    Not the layout ``boot`` writes today. It is honoured because the cost of
    the two mistakes is not symmetric: sparing a dead directory wastes disk,
    and reaping a live one destroys a database somebody is serving from.
    """
    entry = _data_dir(tmp_path, "oe-tests-pg-legacy", "postmaster.pid")

    reap()

    assert entry.exists()


def test_a_recently_touched_dir_is_spared_even_with_no_pid_file(tmp_path: Path, reap) -> None:
    """The age belt still holds on its own.

    A session that has just made its data dir, whose postmaster has not yet
    written a pid file, is indistinguishable from a dead one for a moment.
    """
    entry = tmp_path / "oe-tests-pg-starting"
    entry.mkdir()

    reap()

    assert entry.exists()


def test_the_check_that_shipped_would_have_deleted_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the broken guard and watch it take the live cluster.

    Pointing the constant back at the single bare name reproduces the pre-fix
    code exactly. Without this case the suite cannot tell the fix apart from a
    reaper that has quietly stopped deleting anything, and that is the failure
    mode the original bug had: it looked like a guard doing its job.
    """
    monkeypatch.setattr(conftest, "_PG_TEMP_ROOT", tmp_path)
    monkeypatch.setattr(conftest, "_PG_PIDFILE_RELPATHS", ("postmaster.pid",))
    entry = _data_dir(tmp_path, "oe-tests-pg-live", "pgdata/postmaster.pid")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        conftest._reap_stale_pg_data_dirs()

    assert not entry.exists(), (
        "the pre-fix guard was expected to delete a serving cluster; if it no longer "
        "does, this file has stopped proving that the fix changed anything"
    )


def test_the_count_it_reports_is_the_number_it_spared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The warning has to name how many live clusters it stepped around.

    This is the number that read zero for as long as the guard was broken,
    on machines where it should have read one or more. A silent reaper and a
    reaper with nothing to do print the same thing, so the count is the only
    place the difference was ever visible.
    """
    monkeypatch.setattr(conftest, "_PG_TEMP_ROOT", tmp_path)
    _data_dir(tmp_path, "oe-tests-pg-live-a", "pgdata/postmaster.pid")
    _data_dir(tmp_path, "oe-tests-pg-live-b", "pgdata/postmaster.pid")
    _data_dir(tmp_path, "oe-tests-pg-gone", None)

    with pytest.warns(UserWarning, match=r"2 are still served by a live postmaster") as caught:
        conftest._reap_stale_pg_data_dirs()

    # The spared count is matched above; the reaped one is asserted here so a
    # guard that spared all three would not satisfy this test.
    assert "reaped 1 abandoned data dir" in str(caught[0].message)
