"""The blocking bring-up call has to keep talking while it blocks.

The desktop launcher abandons a backend that has written nothing for four
minutes. That rule is only safe while every long step says something, and the
longest step said nothing at all: ``pgserver.get_server()`` is one call that can
run for many minutes on a cluster replaying its write-ahead log, and everything
it reports while it runs goes through a ``logging`` call at INFO level, which is
discarded because the embedded cluster boots before the application configures
logging and ``logging.lastResort`` only passes WARNING and above.

So a user whose database took six minutes to recover was killed at four, by us,
while it was working. These tests pin the repair: output is produced *while the
blocking call is outstanding*, and it stops when the boot budget runs out so a
call that never returns cannot be kept alive forever.

Nothing here asserts a wall-clock duration. The tests that hold ``get_server()``
open do it with an event, and assert that markers appeared before that event was
released, which is the mechanism itself rather than a stopwatch reading. The two
that check reporting has stopped assert that the emission count cannot grow
again, which is likewise a property and not a duration.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

#: Longest any test here waits on a condition before calling it a failure. Well
#: clear of a starved machine, and bounded so a broken change cannot hang the
#: suite.
_PATIENCE = 10.0


def _capture(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, str]]:
    """Record every stage marker instead of printing it."""
    from app.core import embedded_pg

    emitted: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        embedded_pg,
        "emit_stage",
        lambda stage, status, detail="": emitted.append((stage, status, detail)),
    )
    return emitted


def _wait_until(predicate, patience: float = _PATIENCE) -> bool:
    """Poll ``predicate`` until it holds or ``patience`` runs out."""
    limit = time.monotonic() + patience
    while time.monotonic() < limit:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class _BlockingPgserver:
    """A ``pgserver`` stand-in whose ``get_server`` blocks until released.

    This is the shape of the real failure: one call that has entered the
    library and will not come back for minutes.
    """

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.server = SimpleNamespace(name="fake-server")

    def get_server(self, _pgdata: str) -> object:
        self.entered.set()
        # Bounded, so a change that never releases fails the test instead of
        # hanging the suite.
        self.release.wait(_PATIENCE)
        return self.server


def _run_boot_once(
    embedded_pg,
    pgserver: object,
    pgdata: Path,
    deadline: float,
) -> tuple[threading.Thread, dict]:
    """Drive ``_boot_once`` on a worker so the test can watch it while it blocks."""
    result: dict = {}

    def target() -> None:
        result["value"] = embedded_pg._boot_once(pgserver, pgdata, pgdata, None, deadline)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread, result


def test_the_blocking_bring_up_reports_while_it_is_still_blocking(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Markers arrive before ``get_server()`` has returned, which is the whole fix."""
    from app.core import embedded_pg

    emitted = _capture(monkeypatch)
    monkeypatch.setattr(embedded_pg, "_RECOVERY_HEARTBEAT_SECONDS", 0.05)
    # A live postmaster owns the data directory: the recovering-cluster case.
    monkeypatch.setattr(embedded_pg, "_postmaster_recovering", lambda _pgdata: True)
    monkeypatch.setattr(embedded_pg, "_accepts_a_connection", lambda _pgdata: True)

    pgserver = _BlockingPgserver()
    thread, result = _run_boot_once(embedded_pg, pgserver, tmp_path, time.monotonic() + _PATIENCE)

    assert pgserver.entered.wait(_PATIENCE), "the bring-up call was never reached"
    assert _wait_until(lambda: len(emitted) >= 2), (
        f"the blocking bring-up said nothing while it blocked, which is the defect: {emitted}"
    )
    # The assertion that makes this about the mechanism and not about timing:
    # the markers above exist and the call has not been let go yet.
    assert not pgserver.release.is_set(), "the test released the call before checking"

    pgserver.release.set()
    thread.join(_PATIENCE)
    assert not thread.is_alive()
    assert result["value"] == (pgserver.server, None)

    # It reports the phase it can actually observe, and no invented percentage.
    assert {(stage, status) for stage, status, _ in emitted} == {("pg", "progress")}
    assert all("local database" in detail for _, _, detail in emitted)
    assert all("%" not in detail for _, _, detail in emitted), "no fake progress figure"


def test_the_reported_phase_follows_whether_a_postmaster_is_there(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With no live postmaster the wait is a set-up, not a start, and says so."""
    from app.core import embedded_pg

    emitted = _capture(monkeypatch)
    monkeypatch.setattr(embedded_pg, "_RECOVERY_HEARTBEAT_SECONDS", 0.05)
    monkeypatch.setattr(embedded_pg, "_postmaster_recovering", lambda _pgdata: False)
    monkeypatch.setattr(embedded_pg, "_accepts_a_connection", lambda _pgdata: True)

    pgserver = _BlockingPgserver()
    thread, _result = _run_boot_once(embedded_pg, pgserver, tmp_path, time.monotonic() + _PATIENCE)

    assert pgserver.entered.wait(_PATIENCE)
    assert _wait_until(lambda: len(emitted) >= 1), f"still silent while blocked: {emitted}"
    assert not pgserver.release.is_set()
    details = [detail for _, _, detail in emitted]

    pgserver.release.set()
    thread.join(_PATIENCE)

    assert all("Setting up" in detail for detail in details), (
        f"with no postmaster alive the message must not claim one is starting: {details}"
    )


def test_a_bring_up_that_returns_at_once_says_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A normal start must stay silent, or the visible boot checklist churns.

    The property is one line, the wait that comes before the first report, and
    it is exactly the line a later "why is the first report fifteen seconds
    late?" edit would remove. The interval is deliberately left at its real
    value here: that is the point being pinned.
    """
    from app.core import embedded_pg

    emitted = _capture(monkeypatch)
    monkeypatch.setattr(embedded_pg, "_postmaster_recovering", lambda _pgdata: True)
    monkeypatch.setattr(embedded_pg, "_accepts_a_connection", lambda _pgdata: True)

    fast = SimpleNamespace(get_server=lambda _pgdata: SimpleNamespace(name="fast-server"))
    server, exc = embedded_pg._boot_once(fast, tmp_path, tmp_path, None, time.monotonic() + 30)

    assert exc is None and server is not None
    assert emitted == [], f"a boot with no wait in it must not report a wait: {emitted}"


def test_the_heartbeat_stops_before_the_failure_handler_speaks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The two heartbeats must not overlap when the bring-up call raises.

    The existing recovery heartbeat lives in the handler for this exception, so
    the wrapper has to be finished by the time that handler runs. It is, because
    a context manager exits during propagation and ahead of the handler body,
    and this is what holds that to be true rather than only asserted in a
    comment.
    """
    from app.core import embedded_pg

    emitted = _capture(monkeypatch)
    monkeypatch.setattr(embedded_pg, "_RECOVERY_HEARTBEAT_SECONDS", 0.05)
    # False on both readings: it decides the wrapper's phase text while the call
    # blocks, and then it sends the handler down its fail-fast return.
    monkeypatch.setattr(embedded_pg, "_postmaster_recovering", lambda _pgdata: False)

    entered = threading.Event()
    release = threading.Event()

    def blocking_then_raising(_pgdata: str) -> object:
        entered.set()
        release.wait(_PATIENCE)
        raise RuntimeError("pg_ctl gave up")

    pgserver = SimpleNamespace(get_server=blocking_then_raising)
    thread, result = _run_boot_once(embedded_pg, pgserver, tmp_path, time.monotonic() + _PATIENCE)

    assert entered.wait(_PATIENCE)
    assert _wait_until(lambda: len(emitted) >= 2), f"silent while blocked: {emitted}"
    release.set()
    thread.join(_PATIENCE)
    assert not thread.is_alive()

    server, exc = result["value"]
    assert server is None and isinstance(exc, RuntimeError)

    # The wrapper is stopped by the time the handler decided anything, so the
    # count cannot move again on its own.
    settled = len(emitted)
    time.sleep(0.3)
    assert len(emitted) == settled, f"the wrapper outlived the call it wrapped: {emitted[settled:]}"


def test_a_bring_up_that_never_returns_stops_being_fed_at_the_deadline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The repair must not keep a genuinely wedged start alive forever.

    A heartbeat with no end would defeat the launcher's quiet timeout outright,
    which is a worse bug than the one being fixed. It is bounded by the same
    boot budget the rest of the bring-up shares, so silence returns when that
    budget is spent and the launcher can then do its job.
    """
    from app.core import embedded_pg

    emitted = _capture(monkeypatch)
    monkeypatch.setattr(embedded_pg, "_RECOVERY_HEARTBEAT_SECONDS", 0.05)
    monkeypatch.setattr(embedded_pg, "_postmaster_recovering", lambda _pgdata: True)
    monkeypatch.setattr(embedded_pg, "_accepts_a_connection", lambda _pgdata: True)

    deadline = time.monotonic() + 0.4
    pgserver = _BlockingPgserver()
    thread, _result = _run_boot_once(embedded_pg, pgserver, tmp_path, deadline)

    assert pgserver.entered.wait(_PATIENCE)
    assert _wait_until(lambda: len(emitted) >= 2), f"never fed at all: {emitted}"

    # Wait the budget out with the call still held open, then take two readings.
    # Once the deadline has passed no further marker is possible, so the two
    # readings must agree however badly this machine is scheduling threads.
    assert _wait_until(lambda: time.monotonic() > deadline)
    settled = len(emitted)
    time.sleep(0.3)
    assert len(emitted) == settled, (
        f"the heartbeat outlived the boot budget it belongs to, so a wedged start "
        f"would never be given up on: {emitted[settled:]}"
    )

    pgserver.release.set()
    thread.join(_PATIENCE)
    assert not thread.is_alive()
