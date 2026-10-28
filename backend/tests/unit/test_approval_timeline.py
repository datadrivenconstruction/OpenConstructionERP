# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Held-days / approval-timeline analytics (pure computation).

Pins the timeline maths that the held-days report reads: a step's held time is
measured from the previous hand-off, a pending step accrues against the
reference time and blocks the steps after it, total cycle time closes at
completion, and per-step SLA breaches are counted. Jurisdiction-neutral - only
hours, no country rule. No DB, no clock.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.modules.approval_routes.timeline import compute_timeline

_START = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)


def _at(hours: float) -> datetime:
    return _START + timedelta(hours=hours)


def test_sequential_held_time_measured_between_handoffs() -> None:
    # Step 1 decided 24h after start, step 2 decided 12h after that.
    tl = compute_timeline(
        status="approved",
        started_at=_START,
        completed_at=_at(36),
        reference=_at(100),  # ignored once complete
        decisions=[(1, _at(24)), (2, _at(36))],
    )
    assert tl.steps[0].held_hours == 24
    assert tl.steps[1].held_hours == 12
    assert tl.steps[1].held_days == 0.5
    assert tl.total_hours == 36
    assert tl.open_hours == 0


def test_pending_step_accrues_to_reference_and_blocks_followers() -> None:
    # Step 1 decided at 10h; step 2 still pending at reference 30h.
    tl = compute_timeline(
        status="pending",
        started_at=_START,
        completed_at=None,
        reference=_at(30),
        decisions=[(1, _at(10)), (2, None)],
    )
    assert tl.steps[0].held_hours == 10
    # Pending step held = reference - previous decision = 20h.
    assert tl.steps[1].held_hours == 20
    assert tl.steps[1].decided_at is None
    assert tl.open_hours == 30  # instance still running


def test_sla_breach_flagged_and_counted() -> None:
    tl = compute_timeline(
        status="approved",
        started_at=_START,
        completed_at=_at(80),
        reference=_at(80),
        decisions=[(1, _at(20)), (2, _at(80))],
        sla_hours_by_ordinal={1: 48, 2: 24},  # step 2 took 60h vs 24h SLA
    )
    assert tl.steps[0].overdue is False
    assert tl.steps[1].overdue is True
    assert tl.breached_steps == 1


def test_out_of_order_timestamps_never_go_negative() -> None:
    tl = compute_timeline(
        status="approved",
        started_at=_START,
        completed_at=_at(5),
        reference=_at(5),
        decisions=[(1, _at(2)), (2, _at(1))],  # step 2 "before" step 1
    )
    assert tl.steps[1].held_hours == 0  # clamped, not negative


def test_as_dict_is_json_friendly() -> None:
    tl = compute_timeline(
        status="approved",
        started_at=_START,
        completed_at=_at(24),
        reference=_at(24),
        decisions=[(1, _at(24))],
        sla_hours_by_ordinal={1: 48},
    )
    d = tl.as_dict()
    assert d["status"] == "approved"
    assert d["total_days"] == 1.0
    assert d["steps"][0]["ordinal"] == 1
    assert d["steps"][0]["overdue"] is False
    assert d["completed_at"].startswith("2026-07-02")
