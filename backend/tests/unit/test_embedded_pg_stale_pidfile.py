# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A leftover ``postmaster.pid`` must not be believed just because its number is alive.

Operating systems reuse process identifiers, and Windows reuses them quickly.
A pidfile left behind by a force-killed postmaster keeps naming a number, and
once the system hands that number to an unrelated program the file describes a
process that has nothing to do with the cluster. Asking only whether the number
is alive therefore answers a different question than the one that matters.

This is the ordinary aftermath of upgrading rather than a rare accident: the
installer hooks force-kill the sidecar and its children on every install and
every uninstall, which is exactly what leaves the file behind.

Measured on a real machine before the fix: a pidfile written in July named a PID
then held by a licensing service, the check saw a live process and kept the
file, the cluster reported itself ready on a port where nothing was listening,
and the backend refused to start with a connection error. The user was told the
database was ready and the application server was not, which is the least
useful pair of statements the product could have made.

The blind spot of this file: it exercises the decision, not the boot. Whether
clearing the file actually returns the cluster to the clean-start path is a
property of pixeltable-pgserver and is covered where the cluster is really
started, not here.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.core.embedded_pg import (
    _clear_stale_pidfile,
    _pid_was_recycled,
    _read_pidfile_start_time,
)

psutil = pytest.importorskip("psutil", reason="the recycling check needs psutil to see process identity")


def _write_pidfile(pgdata: Path, pid: int, start_time: float | None, port: int = 50214) -> Path:
    """Write a postmaster.pid in PostgreSQL's own eight line shape."""
    pidfile = pgdata / "postmaster.pid"
    third = "" if start_time is None else str(int(start_time))
    pidfile.write_text(
        "\n".join([str(pid), str(pgdata), third, str(port), str(pgdata), "127.0.0.1", "", "ready"]) + "\n",
        encoding="utf-8",
    )
    return pidfile


def _own_start_time() -> float:
    return psutil.Process(os.getpid()).create_time()


def test_a_live_pid_that_started_at_another_time_is_a_recycled_pid() -> None:
    """The number is alive and is not the process that wrote the file."""
    recorded = _own_start_time() - 3600.0
    assert _pid_was_recycled(os.getpid(), recorded) is True


def test_a_live_pid_whose_start_time_matches_is_the_same_process() -> None:
    """The recorded time answers on its own, whatever the process is called.

    Without this the check would fall through to the name, and the name of the
    process running the tests is not a postmaster, so a matching start time has
    to be enough on its own or the fix would delete pidfiles it must keep.
    """
    assert _pid_was_recycled(os.getpid(), _own_start_time()) is False


def test_a_pidfile_naming_a_recycled_pid_is_removed(tmp_path: Path) -> None:
    """The whole decision, through the function the boot path calls."""
    pidfile = _write_pidfile(tmp_path, os.getpid(), _own_start_time() - 86_400.0)
    _clear_stale_pidfile(tmp_path)
    assert not pidfile.exists(), (
        "A pidfile naming a PID held by a different process was kept. The cluster then reports "
        "itself ready on the port that file records, nothing is listening there, and the backend "
        "fails to start with a connection error while the user is told the database is ready."
    )


def test_a_pidfile_naming_the_process_that_wrote_it_is_kept(tmp_path: Path) -> None:
    """The opposite mistake is worse and must stay impossible.

    Removing the pidfile of a live postmaster invites a second one onto the same
    data directory, so anything short of positive evidence of recycling has to
    leave the file alone.
    """
    pidfile = _write_pidfile(tmp_path, os.getpid(), _own_start_time())
    _clear_stale_pidfile(tmp_path)
    assert pidfile.exists(), "A pidfile whose postmaster is still alive was deleted"


def test_the_start_time_is_read_from_the_line_postgresql_writes_it_on(tmp_path: Path) -> None:
    _write_pidfile(tmp_path, 4242, 1785476471.0)
    assert _read_pidfile_start_time(tmp_path) == pytest.approx(1785476471.0)


def test_an_unreadable_start_time_does_not_pretend_to_be_zero(tmp_path: Path) -> None:
    """Zero would read as a start time in 1970 and condemn every live postmaster."""
    _write_pidfile(tmp_path, 4242, None)
    assert _read_pidfile_start_time(tmp_path) is None


def test_a_pidfile_with_no_start_time_falls_back_to_the_process_name(tmp_path: Path) -> None:
    """The tests do not run inside a postmaster, so this process fails the name test."""
    pidfile = _write_pidfile(tmp_path, os.getpid(), None)
    _clear_stale_pidfile(tmp_path)
    assert not pidfile.exists()


def test_no_pidfile_is_not_an_error(tmp_path: Path) -> None:
    _clear_stale_pidfile(tmp_path)
