"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A slow crash recovery has to keep saying that it is still recovering.

Why this is worth a test of its own: the desktop launcher gives up on a backend
that has written nothing for a few minutes, and that limit is only safe because
the longest legitimately quiet step - waiting out a write-ahead-log replay -
reports itself while it waits. Without the heartbeat the launcher would have to
keep its old, useless rule of waiting out the whole twenty-minute window.

So this pins the contract the two sides share: while the cluster is not
answering, ``pg`` / ``progress`` markers keep coming.
"""

from __future__ import annotations

import time

import pytest


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


def test_a_recovery_that_never_answers_keeps_reporting(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing to connect to, so the wait runs out - and it is not silent."""
    from pathlib import Path

    from app.core import embedded_pg

    emitted = _capture(monkeypatch)
    monkeypatch.setattr(embedded_pg, "_accepts_a_connection", lambda _pgdata: False)
    # Spin the loop instead of living through it, and make the heartbeat quick
    # enough that a short window still contains several of them.
    monkeypatch.setattr(time, "sleep", lambda *_args: None)
    monkeypatch.setattr(embedded_pg, "_RECOVERY_HEARTBEAT_SECONDS", 0.01)

    deadline = time.monotonic() + 0.3
    assert embedded_pg._wait_until_connectable(Path("nowhere"), deadline) is False

    assert len(emitted) >= 2, f"a quiet recovery is the failure this exists to prevent: {emitted}"
    assert {(stage, status) for stage, status, _ in emitted} == {("pg", "progress")}
    assert all("Recovering the local database" in detail for _, _, detail in emitted)
    assert all("s left)" in detail for _, _, detail in emitted), "the countdown is the point"


def test_a_cluster_that_answers_at_once_says_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The heartbeat is for a wait, so a boot with no wait must not emit one."""
    from pathlib import Path

    from app.core import embedded_pg

    emitted = _capture(monkeypatch)
    monkeypatch.setattr(embedded_pg, "_accepts_a_connection", lambda _pgdata: True)
    monkeypatch.setattr(time, "sleep", lambda *_args: None)

    assert embedded_pg._wait_until_connectable(Path("nowhere"), time.monotonic() + 30) is True
    assert emitted == []
