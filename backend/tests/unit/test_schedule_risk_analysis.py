"""Unit tests for :meth:`ScheduleService.get_risk_analysis` (PERT).

Scope:
    The /risk-analysis/ endpoint runs CPM, then derives a three-point
    (optimistic / most-likely / pessimistic) PERT estimate per activity and
    a normal-approximation P50/P80/P95 over the critical-path variance.

    This module had no dedicated test before: the surrounding waves verified
    the clamping logic by hand but left no pin, so a refactor of the bound
    arithmetic could silently break the ``O <= M <= P`` invariant or the
    percentile roll-up. These tests lock both the per-activity bounds (with
    special attention to the short-duration clamp) and the project-level
    aggregation, exercising the real service against in-memory repo stubs
    (no DB, no event bus needed - ``_safe_publish`` swallows its failures).

    The numbers are hand-computed and cross-checked:
        optimistic  = min(max(3, int(d * 0.75)), d)
        pessimistic = max(d + 2, int(d * 1.60), optimistic)
        expected    = (O + 4d + P) / 6
        std_dev     = (P - O) / 6
    Project std = sqrt(sum of critical-activity variances); the percentiles
    use z(0.80)=0.84 and z(0.95)=1.645 off the deterministic duration.
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.modules.schedule.schemas import ActivityCreate, ScheduleCreate
from app.modules.schedule.service import (
    _PERT_OPTIMISTIC,
    _PERT_PESSIMISTIC,
    ScheduleService,
)

PROJECT_ID = uuid.uuid4()


# ── Stubs ──────────────────────────────────────────────────────────────────


class _StubScheduleRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def create(self, schedule: Any) -> Any:
        if getattr(schedule, "id", None) is None:
            schedule.id = uuid.uuid4()
        now = datetime.now(UTC)
        schedule.created_at = now
        schedule.updated_at = now
        self.rows[schedule.id] = schedule
        return schedule

    async def get_by_id(self, schedule_id: uuid.UUID) -> Any:
        return self.rows.get(schedule_id)


class _StubActivityRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def create(self, activity: Any) -> Any:
        if getattr(activity, "id", None) is None:
            activity.id = uuid.uuid4()
        now = datetime.now(UTC)
        activity.created_at = now
        activity.updated_at = now
        self.rows[activity.id] = activity
        return activity

    async def get_by_id(self, activity_id: uuid.UUID) -> Any:
        return self.rows.get(activity_id)

    async def list_for_schedule(
        self,
        schedule_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 1000,
    ) -> tuple[list[Any], int]:
        rows = [r for r in self.rows.values() if r.schedule_id == schedule_id]
        return rows[offset : offset + limit], len(rows)

    async def bulk_update_fields(self, updates: list[dict[str, Any]]) -> None:
        for entry in updates:
            data = dict(entry)
            aid = data.pop("id")
            a = self.rows.get(aid)
            if a:
                for k, v in data.items():
                    setattr(a, k, v)

    async def list_outline(self, schedule_id: uuid.UUID) -> list[tuple[uuid.UUID, uuid.UUID | None, int, str]]:
        return [
            (r.id, getattr(r, "parent_id", None), getattr(r, "sort_order", 0) or 0, getattr(r, "wbs_code", "") or "")
            for r in self.rows.values()
            if r.schedule_id == schedule_id
        ]

    async def get_max_sort_order(self, schedule_id: uuid.UUID) -> int:
        rows = [r for r in self.rows.values() if r.schedule_id == schedule_id]
        return max((r.sort_order for r in rows), default=0)

    async def get_max_activity_code_seq(self, schedule_id: uuid.UUID) -> int:
        return len([r for r in self.rows.values() if r.schedule_id == schedule_id])


class _StubRelationshipRepo:
    """Canonical edge store. ``calculate_critical_path`` reads ``list_for_schedule``."""

    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def list_for_schedule(self, schedule_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if r.schedule_id == schedule_id]

    def add_edge(
        self,
        schedule_id: uuid.UUID,
        predecessor_id: uuid.UUID,
        successor_id: uuid.UUID,
        *,
        relationship_type: str = "FS",
        lag_days: int = 0,
    ) -> None:
        from types import SimpleNamespace

        rid = uuid.uuid4()
        self.rows[rid] = SimpleNamespace(
            id=rid,
            schedule_id=schedule_id,
            predecessor_id=predecessor_id,
            successor_id=successor_id,
            relationship_type=relationship_type,
            lag_days=lag_days,
        )


def _make_service() -> ScheduleService:
    svc = ScheduleService.__new__(ScheduleService)
    svc.schedule_repo = _StubScheduleRepo()
    svc.activity_repo = _StubActivityRepo()
    svc.relationship_repo = _StubRelationshipRepo()
    svc.session = None  # never touched: no deps -> no completion guard / project lookup
    return svc


async def _create_schedule(svc: ScheduleService) -> Any:
    return await svc.create_schedule(
        ScheduleCreate(
            project_id=PROJECT_ID,
            name="Master Schedule",
            start_date="2026-05-01",
            end_date="2027-03-31",
        )
    )


async def _create_activity(svc: ScheduleService, schedule_id: uuid.UUID, *, name: str, duration: int) -> Any:
    # Pass an explicit duration_days so the PERT bounds are deterministic and
    # independent of the working-day calendar. start/end are filler.
    return await svc.create_activity(
        ActivityCreate(
            schedule_id=schedule_id,
            name=name,
            start_date="2026-05-01",
            end_date="2026-06-01",
            duration_days=duration,
            activity_type="task",
        )
    )


def _risk_for(resp: Any, name: str) -> dict[str, Any]:
    for r in resp.activity_risks:
        if r["name"] == name:
            return r
    raise AssertionError(f"no activity risk named {name!r} in {resp.activity_risks!r}")


# ── Per-activity three-point bounds ────────────────────────────────────────


@pytest.mark.asyncio
async def test_risk_single_activity_bounds_and_percentiles() -> None:
    """One 10-day critical activity: O=7, M=10, P=16; P80 carries a 1-day buffer."""
    svc = _make_service()
    sched = await _create_schedule(svc)
    await _create_activity(svc, sched.id, name="Foundation", duration=10)

    resp = await svc.get_risk_analysis(sched.id)

    assert resp.deterministic_days == 10
    risk = _risk_for(resp, "Foundation")
    assert (risk["optimistic"], risk["most_likely"], risk["pessimistic"]) == (7, 10, 16)
    assert risk["expected"] == 10.5  # (7 + 40 + 16) / 6
    assert risk["std_dev"] == 1.5  # (16 - 7) / 6
    assert risk["is_critical"] is True

    # Project-level: variance = 2.25 -> std 1.5.
    assert resp.std_dev_days == 1.5
    assert resp.p50_days == 10  # median == deterministic for the symmetric approx
    assert resp.p80_days == 11  # int(10 + 0.84 * 1.5) = int(11.26)
    assert resp.p95_days == 12  # int(10 + 1.645 * 1.5) = int(12.47)
    assert resp.mean_days == 10.5
    assert resp.risk_buffer_days == 1  # P80 - deterministic


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("duration", "expected_bounds"),
    [
        (1, (1, 1, 3)),  # int(0.75)=0 -> max(3,0)=3 -> clamped down to M=1
        (2, (2, 2, 4)),  # int(1.5)=1 -> max(3,1)=3 -> clamped down to M=2
        (3, (3, 3, 5)),  # int(2.25)=2 -> max(3,2)=3 == M
        (5, (3, 5, 8)),  # int(3.75)=3; pessimistic max(7, int(8.0)=8) = 8
        (20, (15, 20, 32)),  # int(15.0)=15; pessimistic max(22, int(32.0)=32) = 32
    ],
)
async def test_risk_three_point_clamp_preserves_ordering(duration: int, expected_bounds: tuple[int, int, int]) -> None:
    """O <= M <= P must hold for every duration, especially short tasks.

    For 1-2 day tasks the optimistic floor (max(3, ...)) would exceed the
    most-likely duration; the ``min(..., duration)`` clamp pulls it back so the
    three-point ordering - and a non-negative std_dev - is preserved.
    """
    svc = _make_service()
    sched = await _create_schedule(svc)
    await _create_activity(svc, sched.id, name="Task", duration=duration)

    resp = await svc.get_risk_analysis(sched.id)
    risk = _risk_for(resp, "Task")
    o, m, p = risk["optimistic"], risk["most_likely"], risk["pessimistic"]
    assert (o, m, p) == expected_bounds
    assert o <= m <= p, f"PERT ordering broken for duration={duration}: {o},{m},{p}"
    assert risk["std_dev"] >= 0


@pytest.mark.asyncio
async def test_risk_milestone_zero_duration_has_no_spread() -> None:
    """A zero-duration milestone gets O=M=P=0 and contributes zero variance."""
    svc = _make_service()
    sched = await _create_schedule(svc)
    await _create_activity(svc, sched.id, name="Gate", duration=0)

    resp = await svc.get_risk_analysis(sched.id)
    risk = _risk_for(resp, "Gate")
    assert (risk["optimistic"], risk["most_likely"], risk["pessimistic"]) == (0, 0, 0)
    assert risk["std_dev"] == 0.0
    # No spread anywhere -> deterministic == every percentile, zero buffer.
    assert resp.std_dev_days == 0.0
    assert resp.p80_days == resp.deterministic_days
    assert resp.risk_buffer_days == 0


# ── Project-level aggregation over the critical path ───────────────────────


@pytest.mark.asyncio
async def test_risk_sums_variance_only_over_critical_path() -> None:
    """Variance roll-up must include critical activities and exclude floated ones.

    Build A(10) -> B(20) on the critical chain plus a parallel C(5) that runs
    alongside B with slack (so it is non-critical). The project std must come
    from A+B variance only; C must be reported but excluded from the sum.
    """
    svc = _make_service()
    sched = await _create_schedule(svc)
    a = await _create_activity(svc, sched.id, name="A", duration=10)
    b = await _create_activity(svc, sched.id, name="B", duration=20)
    # C is short and hangs off A in parallel with B; B's 20 days dominate so C
    # carries float and is not critical.
    c = await _create_activity(svc, sched.id, name="C", duration=5)
    svc.relationship_repo.add_edge(sched.id, a.id, b.id)
    svc.relationship_repo.add_edge(sched.id, a.id, c.id)

    resp = await svc.get_risk_analysis(sched.id)

    risk_a = _risk_for(resp, "A")
    risk_b = _risk_for(resp, "B")
    risk_c = _risk_for(resp, "C")
    assert risk_a["is_critical"] is True
    assert risk_b["is_critical"] is True
    assert risk_c["is_critical"] is False

    assert resp.deterministic_days == 30  # A(10) + B(20)
    # variance(A)=2.25, variance(B)=((32-15)/6)^2; C excluded.
    var_a = ((16 - 7) / 6.0) ** 2
    var_b = ((32 - 15) / 6.0) ** 2
    expected_std = round(math.sqrt(var_a + var_b), 1)
    assert resp.std_dev_days == expected_std
    assert resp.p80_days == int(30 + 0.84 * math.sqrt(var_a + var_b))
    assert resp.p95_days == int(30 + 1.645 * math.sqrt(var_a + var_b))
    # mean = sum of expected over the critical activities only.
    assert resp.mean_days == round(risk_a["expected"] + risk_b["expected"], 1)


@pytest.mark.asyncio
async def test_risk_percentiles_are_monotonic_non_decreasing() -> None:
    """P50 <= P80 <= P95 must always hold (normal-approx ordering)."""
    svc = _make_service()
    sched = await _create_schedule(svc)
    a = await _create_activity(svc, sched.id, name="A", duration=8)
    b = await _create_activity(svc, sched.id, name="B", duration=12)
    svc.relationship_repo.add_edge(sched.id, a.id, b.id)

    resp = await svc.get_risk_analysis(sched.id)
    assert resp.p50_days <= resp.p80_days <= resp.p95_days
    assert resp.risk_buffer_days == resp.p80_days - resp.deterministic_days
    assert resp.risk_buffer_days >= 0


@pytest.mark.asyncio
async def test_risk_analysis_404_when_no_activities() -> None:
    """An empty schedule has no critical path - CPM 404s and risk surfaces it."""
    from fastapi import HTTPException

    svc = _make_service()
    sched = await _create_schedule(svc)

    with pytest.raises(HTTPException) as exc:
        await svc.get_risk_analysis(sched.id)
    assert exc.value.status_code == 404


# ── Guard the PERT constants the bounds depend on ──────────────────────────


def test_pert_factor_constants() -> None:
    """Pin the distribution factors so a tweak is a conscious, tested change.

    The hand-computed expectations above are derived from these exact values;
    if they move, the bound tests must be re-derived in lock-step.
    """
    assert _PERT_OPTIMISTIC == 0.75
    assert _PERT_PESSIMISTIC == 1.60
