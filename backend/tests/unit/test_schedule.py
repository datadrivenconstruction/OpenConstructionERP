"""Unit tests for :class:`ScheduleService`.

Scope:
    Covers schedule CRUD, activity CRUD with auto-duration calculation,
    dependency handling, milestone tracking, progress auto-status,
    BOQ position linking, and Gantt data generation.
    Repositories and event bus are stubbed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.schedule.schemas import (
    ActivityCreate,
    ActivityUpdate,
    ScheduleCreate,
    ScheduleUpdate,
)
from app.modules.schedule.service import ScheduleService, _normalize_deps, compute_duration

# ── Helpers / stubs ───────────────────────────────────────────────────────

PROJECT_ID = uuid.uuid4()


def _make_service() -> ScheduleService:
    service = ScheduleService.__new__(ScheduleService)
    service.session = SimpleNamespace()
    service.schedule_repo = _StubScheduleRepo()
    service.activity_repo = _StubActivityRepo()
    service.work_order_repo = _StubWorkOrderRepo()
    return service


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

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Any], int]:
        rows = [r for r in self.rows.values() if r.project_id == project_id]
        return rows[offset : offset + limit], len(rows)

    async def update_fields(self, schedule_id: uuid.UUID, **kwargs: Any) -> None:
        s = self.rows.get(schedule_id)
        if s:
            for k, v in kwargs.items():
                setattr(s, k, v)
            s.updated_at = datetime.now(UTC)

    async def delete(self, schedule_id: uuid.UUID) -> None:
        self.rows.pop(schedule_id, None)


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

    async def update_fields(self, activity_id: uuid.UUID, **kwargs: Any) -> None:
        a = self.rows.get(activity_id)
        if a:
            for k, v in kwargs.items():
                setattr(a, k, v)
            a.updated_at = datetime.now(UTC)

    async def delete(self, activity_id: uuid.UUID) -> None:
        self.rows.pop(activity_id, None)

    async def get_max_sort_order(self, schedule_id: uuid.UUID) -> int:
        rows = [r for r in self.rows.values() if r.schedule_id == schedule_id]
        if not rows:
            return 0
        return max(r.sort_order for r in rows)

    async def get_max_activity_code_seq(self, schedule_id: uuid.UUID) -> int:
        return len([r for r in self.rows.values() if r.schedule_id == schedule_id])


class _StubWorkOrderRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def create(self, wo: Any) -> Any:
        if getattr(wo, "id", None) is None:
            wo.id = uuid.uuid4()
        self.rows[wo.id] = wo
        return wo

    async def get_by_id(self, wo_id: uuid.UUID) -> Any:
        return self.rows.get(wo_id)


async def _create_schedule(svc: ScheduleService) -> Any:
    data = ScheduleCreate(
        project_id=PROJECT_ID,
        name="Master Schedule",
        start_date="2026-05-01",
        end_date="2027-03-31",
    )
    return await svc.create_schedule(data)


async def _create_activity(svc: ScheduleService, schedule_id: uuid.UUID, **overrides: Any) -> Any:
    defaults = {
        "schedule_id": schedule_id,
        "name": "Foundation work",
        "start_date": "2026-05-01",
        "end_date": "2026-06-01",
        "activity_type": "task",
    }
    defaults.update(overrides)
    data = ActivityCreate(**defaults)
    return await svc.create_activity(data)


# ── Tests ─────────────────────────────────────────────────────────────────


def test_compute_duration_weekdays() -> None:
    """Mon 2026-04-06 to Fri 2026-04-10 = 5 working days."""
    assert compute_duration("2026-04-06", "2026-04-10") == 5


def test_compute_duration_includes_weekend() -> None:
    """Mon to next Mon = 6 working days (skip Sat/Sun)."""
    assert compute_duration("2026-04-06", "2026-04-13") == 6


def test_compute_duration_invalid_dates() -> None:
    assert compute_duration("bad", "date") == 0


def test_compute_duration_end_before_start() -> None:
    assert compute_duration("2026-04-10", "2026-04-01") == 0


def test_normalize_deps_string_input() -> None:
    result = _normalize_deps(["some-uuid-string"])
    assert result == [{"activity_id": "some-uuid-string", "type": "FS", "lag_days": 0}]


def test_normalize_deps_dict_passthrough() -> None:
    dep = {"activity_id": "abc", "type": "FF", "lag_days": 2}
    result = _normalize_deps([dep])
    assert result == [dep]


@pytest.mark.asyncio
async def test_create_schedule() -> None:
    svc = _make_service()
    schedule = await _create_schedule(svc)

    assert schedule.id is not None
    assert schedule.name == "Master Schedule"
    assert schedule.status == "draft"
    assert schedule.start_date == "2026-05-01"


@pytest.mark.asyncio
async def test_get_schedule_not_found() -> None:
    svc = _make_service()
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await svc.get_schedule(uuid.uuid4())
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_update_schedule() -> None:
    svc = _make_service()
    schedule = await _create_schedule(svc)

    updated = await svc.update_schedule(
        schedule.id,
        ScheduleUpdate(name="Revised Schedule", status="active"),
    )
    assert updated.name == "Revised Schedule"
    assert updated.status == "active"


@pytest.mark.asyncio
async def test_delete_schedule() -> None:
    svc = _make_service()
    schedule = await _create_schedule(svc)
    await svc.delete_schedule(schedule.id)

    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        await svc.get_schedule(schedule.id)


@pytest.mark.asyncio
async def test_create_activity_auto_duration() -> None:
    svc = _make_service()
    schedule = await _create_schedule(svc)

    activity = await _create_activity(svc, schedule.id)
    assert activity.id is not None
    assert activity.duration_days > 0  # auto-computed from dates
    assert activity.activity_code.startswith("ACT-")


@pytest.mark.asyncio
async def test_create_milestone() -> None:
    svc = _make_service()
    schedule = await _create_schedule(svc)

    milestone = await _create_activity(
        svc,
        schedule.id,
        name="Foundation complete",
        activity_type="milestone",
        start_date="2026-06-01",
        end_date="2026-06-01",
        duration_days=0,
    )
    assert milestone.activity_type == "milestone"
    assert milestone.name == "Foundation complete"


@pytest.mark.asyncio
async def test_update_activity_recalculates_duration() -> None:
    svc = _make_service()
    schedule = await _create_schedule(svc)
    activity = await _create_activity(svc, schedule.id)

    updated = await svc.update_activity(
        activity.id,
        ActivityUpdate(start_date="2026-05-01", end_date="2026-05-15"),
    )
    # 2026-05-01 (Thu) to 2026-05-15 (Thu) = 11 working days
    assert updated.duration_days == 11


@pytest.mark.asyncio
async def test_update_progress_auto_status() -> None:
    """Progress 0 -> not_started, 50 -> in_progress, 100 -> completed."""
    svc = _make_service()
    schedule = await _create_schedule(svc)
    activity = await _create_activity(svc, schedule.id)

    updated = await svc.update_progress(activity.id, 50.0)
    assert updated.status == "in_progress"
    assert updated.progress_pct == "50.0"

    updated = await svc.update_progress(activity.id, 100.0)
    assert updated.status == "completed"

    updated = await svc.update_progress(activity.id, 0.0)
    assert updated.status == "not_started"


@pytest.mark.asyncio
async def test_link_boq_position() -> None:
    svc = _make_service()
    schedule = await _create_schedule(svc)
    activity = await _create_activity(svc, schedule.id)
    boq_id = uuid.uuid4()

    linked = await svc.link_boq_position(activity.id, boq_id)
    assert str(boq_id) in linked.boq_position_ids


@pytest.mark.asyncio
async def test_link_boq_position_duplicate_rejected() -> None:
    svc = _make_service()
    schedule = await _create_schedule(svc)
    activity = await _create_activity(svc, schedule.id)
    boq_id = uuid.uuid4()

    await svc.link_boq_position(activity.id, boq_id)

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await svc.link_boq_position(activity.id, boq_id)
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_gantt_data_generation() -> None:
    svc = _make_service()
    schedule = await _create_schedule(svc)
    await _create_activity(svc, schedule.id, name="Task A", status="completed")
    await _create_activity(svc, schedule.id, name="Task B", status="in_progress")
    await _create_activity(svc, schedule.id, name="Task C", status="not_started")

    gantt = await svc.get_gantt_data(schedule.id)
    assert len(gantt.activities) == 3
    assert gantt.summary.total_activities == 3
    assert gantt.summary.completed == 1
    assert gantt.summary.in_progress == 1
    assert gantt.summary.not_started == 1


@pytest.mark.asyncio
async def test_gantt_duration_matches_stored_working_days() -> None:
    """Regression: Gantt ``duration_days`` must equal the stored
    working-day duration (compute_duration), NOT a raw calendar-day diff.

    2026-05-01 (Fri) → 2026-05-15 (Fri) spans 14 calendar days but only
    11 working days. The old code reported 14 here while the activity
    table / CPM reported 11 — a visible inconsistency in the UI.
    """
    svc = _make_service()
    schedule = await _create_schedule(svc)
    activity = await _create_activity(
        svc,
        schedule.id,
        start_date="2026-05-01",
        end_date="2026-05-15",
    )
    assert activity.duration_days == 11  # working days

    gantt = await svc.get_gantt_data(schedule.id)
    assert gantt.activities[0].duration_days == 11, (
        "Gantt duration must match the stored working-day duration, not the calendar-day diff"
    )


# ── Cycle-detection performance (2026-05-21 audit fix #5) ─────────────────


@pytest.mark.asyncio
async def test_reject_dependency_cycles_single_traversal_for_many_predecessors() -> None:
    """Audit fix: previously ``_reject_dependency_cycles`` ran a BFS per
    proposed predecessor (O(P × V)). The refactor pre-computes reachability
    from ``activity_id`` once and reduces each per-predecessor check to a
    hash-set membership test (O(V+E) total). We assert behaviour first;
    the call-count instrumentation guards against a regression.
    """
    svc = _make_service()
    schedule = await _create_schedule(svc)

    # Build a chain A -> B -> C -> D -> E so reachability from A is {B,C,D,E}.
    a = await _create_activity(svc, schedule.id, name="A")
    b = await _create_activity(svc, schedule.id, name="B")
    c = await _create_activity(svc, schedule.id, name="C")
    d = await _create_activity(svc, schedule.id, name="D")
    e = await _create_activity(svc, schedule.id, name="E")

    # Each "dependencies" entry on activity X is a predecessor → edge
    # ``pred -> X``. So to build A -> B -> ... -> E, B's deps = [A], C's = [B], etc.
    b.dependencies = [{"activity_id": str(a.id), "type": "FS", "lag_days": 0}]
    c.dependencies = [{"activity_id": str(b.id), "type": "FS", "lag_days": 0}]
    d.dependencies = [{"activity_id": str(c.id), "type": "FS", "lag_days": 0}]
    e.dependencies = [{"activity_id": str(d.id), "type": "FS", "lag_days": 0}]

    # Attempt to add B, C, D, and E as predecessors of A — all of these
    # would close a cycle. The first detected one raises.
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await svc._reject_dependency_cycles(
            activity_id=a.id,
            schedule_id=schedule.id,
            proposed_predecessors=[b.id, c.id, d.id, e.id],
        )
    assert exc_info.value.status_code == 400
    assert "circular" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_reject_dependency_cycles_allows_safe_predecessors() -> None:
    """Adding a predecessor that is NOT in the reachability set must NOT
    raise. Pins the negative side of the audit fix so the refactor's
    single-pass traversal doesn't over-reject."""
    svc = _make_service()
    schedule = await _create_schedule(svc)

    a = await _create_activity(svc, schedule.id, name="A")
    b = await _create_activity(svc, schedule.id, name="B")
    # Disconnected node — safe to depend on.
    disconnected = await _create_activity(svc, schedule.id, name="X")

    # A -> B exists. Adding "disconnected -> A" is safe (no cycle).
    b.dependencies = [{"activity_id": str(a.id), "type": "FS", "lag_days": 0}]

    # No raise expected:
    await svc._reject_dependency_cycles(
        activity_id=a.id,
        schedule_id=schedule.id,
        proposed_predecessors=[disconnected.id],
    )


@pytest.mark.asyncio
async def test_reject_dependency_cycles_lists_activities_only_once() -> None:
    """Performance contract: even when N proposed predecessors are passed,
    the helper must load the schedule's activity list ONCE — the previous
    code already did this, the refactor preserves it. We wrap the repo
    method to count calls.
    """
    svc = _make_service()
    schedule = await _create_schedule(svc)
    a = await _create_activity(svc, schedule.id, name="A")
    others = [await _create_activity(svc, schedule.id, name=f"N{i}") for i in range(5)]

    original = svc.activity_repo.list_for_schedule
    counter = {"n": 0}

    async def _counting(*args, **kwargs):  # type: ignore[no-untyped-def]
        counter["n"] += 1
        return await original(*args, **kwargs)

    svc.activity_repo.list_for_schedule = _counting  # type: ignore[assignment]

    # 5 proposed predecessors, none in cycle -> no raise.
    await svc._reject_dependency_cycles(
        activity_id=a.id,
        schedule_id=schedule.id,
        proposed_predecessors=[o.id for o in others],
    )

    assert counter["n"] == 1, f"Expected one repo load for the whole batch; got {counter['n']}."
