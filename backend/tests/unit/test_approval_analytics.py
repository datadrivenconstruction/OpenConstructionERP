# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure approval-cycle aggregate.

Mirrors ``test_approval_timeline.py``: fixed clock, ``InstanceInput``s built by
hand, no DB. Every test pins one rule of ``analytics.aggregate`` so a naive
transcription of the per-instance timeline into a cross-instance sum is caught -
in particular the phantom held time an unreached step reports (see
``analytics`` module docstring and the ``breach``/``future`` tests below).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from app.modules.approval_routes.analytics import (
    InstanceInput,
    StepMeta,
    aggregate,
)

_START = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)
_NOW = _START + timedelta(hours=200)  # a late reference for open steps


def _at(hours: float) -> datetime:
    return _START + timedelta(hours=hours)


def _inst(
    *,
    status: str,
    steps: list[tuple[int, str | None, int | None]],
    decisions: list[tuple[int, datetime | None]],
    current: int = 1,
    completed: datetime | None = None,
    started: datetime | None = None,
    route_id: str = "r1",
    route_name: str = "Route One",
    iid: str = "i1",
) -> InstanceInput:
    return InstanceInput(
        instance_id=iid,
        route_id=route_id,
        route_name=route_name,
        status=status,
        started_at=started or _START,
        completed_at=completed,
        current_step_ordinal=current,
        steps=tuple(StepMeta(o, role, sla) for (o, role, sla) in steps),
        decisions=tuple(decisions),
    )


def _role(result, name: str | None):
    return next(r for r in result.by_role if r.role == name)


def test_avg_and_median_held_time_per_role() -> None:
    # Two single-step "manager" instances holding 24h and 48h.
    a = _inst(
        status="approved",
        steps=[(1, "manager", None)],
        decisions=[(1, _at(24))],
        completed=_at(24),
        iid="a",
    )
    b = _inst(
        status="approved",
        steps=[(1, "manager", None)],
        decisions=[(1, _at(48))],
        completed=_at(48),
        route_id="r2",
        iid="b",
    )
    result = aggregate([a, b], reference=_NOW)
    mgr = _role(result, "manager")
    assert mgr.decided_count == 2
    assert mgr.avg_hours == 36.0
    assert mgr.median_hours == 36.0
    assert mgr.max_hours == 48


def test_breach_rate_per_role() -> None:
    # Three decided "reviewer" steps against a 10h SLA; only the 20h one breaches.
    holds = [5, 5, 20]
    insts = [
        _inst(
            status="approved",
            steps=[(1, "reviewer", 10)],
            decisions=[(1, _at(h))],
            completed=_at(h),
            route_id=f"r{i}",
            iid=f"i{i}",
        )
        for i, h in enumerate(holds)
    ]
    result = aggregate(insts, reference=_NOW)
    rev = _role(result, "reviewer")
    assert rev.decided_count == 3
    assert rev.breach_count == 1
    assert rev.breach_rate == round(1 / 3, 3)


def test_future_unreached_steps_excluded() -> None:
    # Step 1 decided; instance now sits at step 2 of 3. Steps 2 and 3 are
    # unreached and must not appear in the decided by-step stats.
    inst = _inst(
        status="pending",
        steps=[(1, "a", None), (2, "b", None), (3, "c", None)],
        decisions=[(1, _at(24)), (2, None), (3, None)],
        current=2,
    )
    result = aggregate([inst], reference=_NOW)
    ordinals = {s.ordinal for s in result.by_step}
    assert ordinals == {1}


def test_pending_first_step_breach_not_inflated() -> None:
    # The core §5.3 guard: an instance stuck at step 1 of 3 with every SLA
    # exceeded reports ONE breach (its live step), not three. A literal
    # sum of Timeline.breached_steps would give 3 - the phantom future holds.
    inst = _inst(
        status="pending",
        steps=[(1, "a", 10), (2, "b", 10), (3, "c", 10)],
        decisions=[(1, None), (2, None), (3, None)],
        current=1,
    )
    result = aggregate([inst], reference=_NOW)
    assert result.kpis.breached_steps_total == 1
    assert result.kpis.instances_with_breach == 1
    assert result.kpis.open_overdue_now == 1
    assert result.by_step == ()  # nothing decided yet
    assert result.by_role == ()


def test_current_open_overdue_counts_once() -> None:
    # Step 1 decided clean, step 2 current + overdue. The overdue live step
    # feeds open_overdue_now but never the decided by-step stats.
    inst = _inst(
        status="pending",
        steps=[(1, "a", 100), (2, "b", 10)],
        decisions=[(1, _at(5)), (2, None)],
        current=2,
    )
    result = aggregate([inst], reference=_NOW)
    assert result.kpis.open_overdue_now == 1
    assert {s.ordinal for s in result.by_step} == {1}


def test_cycle_time_over_terminal_only() -> None:
    approved = _inst(
        status="approved",
        steps=[(1, "a", None)],
        decisions=[(1, _at(48))],
        completed=_at(48),  # 2.0 d
        iid="ap",
    )
    rejected = _inst(
        status="rejected",
        steps=[(1, "a", None)],
        decisions=[(1, _at(24))],
        completed=_at(24),  # 1.0 d
        route_id="r2",
        iid="rj",
    )
    cancelled = _inst(
        status="cancelled",
        steps=[(1, "a", None)],
        decisions=[(1, None)],
        completed=_at(120),  # 5.0 d - excluded
        route_id="r3",
        iid="cx",
    )
    pending = _inst(
        status="pending",
        steps=[(1, "a", None)],
        decisions=[(1, None)],
        route_id="r4",
        iid="pd",
    )
    result = aggregate([approved, rejected, cancelled, pending], reference=_NOW)
    assert result.kpis.avg_cycle_days == 1.5
    assert result.kpis.median_cycle_days == 1.5


def test_approval_rate_none_when_no_terminal() -> None:
    insts = [
        _inst(
            status="pending",
            steps=[(1, "a", None)],
            decisions=[(1, None)],
            route_id=f"r{i}",
            iid=f"i{i}",
        )
        for i in range(3)
    ]
    result = aggregate(insts, reference=_NOW)
    assert result.kpis.approval_rate is None
    assert result.kpis.avg_cycle_days is None


def test_approval_rate_basic() -> None:
    insts = []
    for i in range(3):
        insts.append(
            _inst(
                status="approved",
                steps=[(1, "a", None)],
                decisions=[(1, _at(1))],
                completed=_at(1),
                route_id=f"a{i}",
                iid=f"a{i}",
            ),
        )
    insts.append(
        _inst(
            status="rejected",
            steps=[(1, "a", None)],
            decisions=[(1, _at(1))],
            completed=_at(1),
            route_id="rj",
            iid="rj",
        ),
    )
    result = aggregate(insts, reference=_NOW)
    assert result.kpis.approval_rate == 0.75
    assert result.kpis.approved == 3
    assert result.kpis.rejected == 1


def test_breach_rollups() -> None:
    # inst1: a decided-overdue step -> 1 breach. inst2: clean. inst3: a live
    # overdue step -> 1 breach. Totals: 2 breaches across 2 instances.
    inst1 = _inst(
        status="approved",
        steps=[(1, "m", 10), (2, "m", 100)],
        decisions=[(1, _at(20)), (2, _at(25))],
        completed=_at(25),
        current=2,
        route_id="r1",
        iid="i1",
    )
    inst2 = _inst(
        status="approved",
        steps=[(1, "m", 100)],
        decisions=[(1, _at(10))],
        completed=_at(10),
        route_id="r2",
        iid="i2",
    )
    inst3 = _inst(
        status="pending",
        steps=[(1, "m", 10), (2, "m", 10)],
        decisions=[(1, _at(5)), (2, None)],
        current=2,
        route_id="r3",
        iid="i3",
    )
    result = aggregate([inst1, inst2, inst3], reference=_NOW)
    assert result.kpis.breached_steps_total == 2
    assert result.kpis.instances_with_breach == 2
    assert result.kpis.open_overdue_now == 1


def test_bottleneck_ranked_by_median_desc() -> None:
    # Role A holds 60h, role B holds 10h. A must top the ranking.
    slow = _inst(
        status="approved",
        steps=[(1, "A", None)],
        decisions=[(1, _at(60))],
        completed=_at(60),
        route_id="ra",
        iid="ia",
    )
    fast = _inst(
        status="approved",
        steps=[(1, "B", None)],
        decisions=[(1, _at(10))],
        completed=_at(10),
        route_id="rb",
        iid="ib",
    )
    result = aggregate([slow, fast], reference=_NOW)
    assert result.bottlenecks[0].ref == "A"
    assert result.bottlenecks[0].kind == "role"


def test_empty_input_is_all_zero() -> None:
    result = aggregate([], reference=_NOW)
    assert result.kpis.total_instances == 0
    assert result.kpis.approval_rate is None
    assert result.kpis.avg_cycle_days is None
    assert result.kpis.breached_steps_total == 0
    assert result.by_role == ()
    assert result.by_step == ()
    assert result.bottlenecks == ()


def test_result_as_dict_json_friendly() -> None:
    inst = _inst(
        status="approved",
        steps=[(1, "manager", 10), (2, None, None)],
        decisions=[(1, _at(20)), (2, _at(30))],
        completed=_at(30),
        current=2,
    )
    result = aggregate([inst], reference=_NOW)
    payload = result.as_dict()
    # Serialises without a custom encoder (no datetimes leak through).
    json.dumps(payload)
    assert isinstance(payload["by_role"], list)
    assert isinstance(payload["by_step"], list)
    assert isinstance(payload["bottlenecks"], list)
    assert isinstance(payload["kpis"], dict)
