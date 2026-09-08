"""Unit tests for :class:`ScheduleService`.

Scope:
    Covers schedule CRUD, activity CRUD with auto-duration calculation,
    dependency handling, milestone tracking, progress auto-status,
    BOQ position linking, and Gantt data generation.
    Repositories and event bus are stubbed.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Coroutine
from datetime import UTC, date, datetime, timedelta
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


def _session_get_project(region: str | None) -> Callable[..., Coroutine[Any, Any, Any]]:
    """Stub for ``AsyncSession.get``: the project a schedule belongs to.

    The service resolves the project once per request for the regional working
    week (``ScheduleService.resolve_project_region``). ``None`` stands for a
    project that cannot be found, which falls back to the DEFAULT
    Monday-to-Friday week the older tests in this file count on.
    """

    async def _get(*_args: Any, **_kwargs: Any) -> Any:
        if region is None:
            return None
        return SimpleNamespace(id=PROJECT_ID, region=region)

    return _get


class _StubRelationshipRepo:
    """No canonical predecessor edges — the completion guard passes through."""

    async def list_predecessors(self, activity_id: uuid.UUID) -> list[Any]:
        return []


def _make_service(project_region: str | None = None) -> ScheduleService:
    service = ScheduleService.__new__(ScheduleService)
    service.session = SimpleNamespace(get=_session_get_project(project_region))
    service.schedule_repo = _StubScheduleRepo()
    service.activity_repo = _StubActivityRepo()
    service.work_order_repo = _StubWorkOrderRepo()
    service.relationship_repo = _StubRelationshipRepo()
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

    async def bulk_update_fields(self, updates: list[dict[str, Any]]) -> None:
        for entry in updates:
            data = dict(entry)
            aid = data.pop("id")
            a = self.rows.get(aid)
            if a:
                for k, v in data.items():
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


# ── One project, one working week ─────────────────────────────────────────
#
# Sunday 7 June 2026 to Saturday 13 June 2026 is one whole week. The Gulf works
# Sunday to Thursday and Germany Monday to Friday, so the two count different
# days of it: Friday is a working day only in Berlin, Sunday only in Doha.
_WEEK_SUNDAY = "2026-06-07"
_WEEK_MONDAY = "2026-06-08"
_WEEK_THURSDAY = "2026-06-11"
_WEEK_FRIDAY = "2026-06-12"
_WEEK_SATURDAY = "2026-06-13"

# Stored the way the project picker stores them, so the calendar is reached the
# way a project created in the product reaches it, not by a calendar key.
_GULF = "GulfStates"
_GERMANY = "DACH"
_GULF_REST_DAYS = {4, 5}  # Friday, Saturday
_GERMAN_REST_DAYS = {5, 6}  # Saturday, Sunday


def _weekdays_between(start: str, end: str) -> list[int]:
    """Every weekday index from ``start`` to ``end`` inclusive, the tests' own oracle."""
    first = date.fromisoformat(start)
    last = date.fromisoformat(end)
    return [(first + timedelta(days=offset)).weekday() for offset in range((last - first).days + 1)]


def _working_days(start: str, end: str, rest_days: set[int]) -> int:
    return sum(1 for weekday in _weekdays_between(start, end) if weekday not in rest_days)


@pytest.mark.asyncio
async def test_a_gulf_project_and_a_german_project_count_the_same_dates_differently() -> None:
    """Monday to Saturday holds four Gulf working days and five German ones.

    Before the project's region reached ``compute_duration`` every project was
    counted Monday to Friday, so both projects stored 5 here, and a Gulf schedule
    drawn Sunday to Thursday by BOQ generation was recounted on the wrong week
    the first time anyone saved a date. Asserted through the service methods the
    activity routes call: create, update and the Gantt fallback for a row with
    no stored duration.
    """
    doha = _make_service(project_region=_GULF)
    berlin = _make_service(project_region=_GERMANY)
    doha_schedule = await _create_schedule(doha)
    berlin_schedule = await _create_schedule(berlin)
    monday_to_saturday = {"start_date": _WEEK_MONDAY, "end_date": _WEEK_SATURDAY}

    doha_task = await _create_activity(doha, doha_schedule.id, **monday_to_saturday)
    berlin_task = await _create_activity(berlin, berlin_schedule.id, **monday_to_saturday)
    assert doha_task.duration_days == 4, "Doha rests on Friday and Saturday"
    assert berlin_task.duration_days == 5, "Berlin rests on Saturday only"

    # Moving both onto Sunday to Thursday flips it: only Doha works the Sunday.
    sunday_to_thursday = ActivityUpdate(start_date=_WEEK_SUNDAY, end_date=_WEEK_THURSDAY)
    doha_task = await doha.update_activity(doha_task.id, sunday_to_thursday)
    berlin_task = await berlin.update_activity(berlin_task.id, sunday_to_thursday)
    assert doha_task.duration_days == 5
    assert berlin_task.duration_days == 4

    # A row stored with no duration is counted at read time, on the same week.
    doha_unsized = await _create_activity(doha, doha_schedule.id, duration_days=0, **monday_to_saturday)
    berlin_unsized = await _create_activity(berlin, berlin_schedule.id, duration_days=0, **monday_to_saturday)
    doha_gantt = {a.id: a for a in (await doha.get_gantt_data(doha_schedule.id)).activities}
    berlin_gantt = {a.id: a for a in (await berlin.get_gantt_data(berlin_schedule.id)).activities}
    assert doha_gantt[doha_unsized.id].duration_days == 4
    assert berlin_gantt[berlin_unsized.id].duration_days == 5


@pytest.mark.asyncio
async def test_five_working_days_end_on_thursday_in_doha_and_on_friday_in_berlin() -> None:
    """From the same Sunday start, five working days end a day earlier in Doha.

    Sunday to Thursday is five working days in the Gulf and four in Germany,
    where the fifth is the Friday. Friday adds nothing in Doha, so the Gulf
    activity is five days long either way.
    """
    doha = _make_service(project_region=_GULF)
    berlin = _make_service(project_region=_GERMANY)
    doha_schedule = await _create_schedule(doha)
    berlin_schedule = await _create_schedule(berlin)
    to_thursday = {"start_date": _WEEK_SUNDAY, "end_date": _WEEK_THURSDAY}
    to_friday = {"start_date": _WEEK_SUNDAY, "end_date": _WEEK_FRIDAY}

    assert (await _create_activity(doha, doha_schedule.id, **to_thursday)).duration_days == 5
    assert (await _create_activity(berlin, berlin_schedule.id, **to_thursday)).duration_days == 4
    assert (await _create_activity(berlin, berlin_schedule.id, **to_friday)).duration_days == 5
    assert (await _create_activity(doha, doha_schedule.id, **to_friday)).duration_days == 5


def _boq_section_with_three_positions() -> list[Any]:
    """One BOQ section and three priced children with crew data, as the BOQ repo would hand them over."""
    section_id = uuid.uuid4()

    def _position(ordinal: str, quantity: int) -> Any:
        return SimpleNamespace(
            id=uuid.uuid4(),
            parent_id=section_id,
            ordinal=ordinal,
            description=f"Position {ordinal}",
            unit="m3",
            quantity=str(quantity),
            unit_rate="10",
            total=str(quantity * 10),
            metadata_={"labor_hours": 1, "workers_per_unit": 2},
        )

    section = SimpleNamespace(
        id=section_id,
        parent_id=None,
        ordinal="1",
        description="Earthworks",
        unit="",
        quantity="0",
        unit_rate="0",
        total="0",
        metadata_={},
    )
    return [section, _position("1.1", 50), _position("1.2", 100), _position("1.3", 200)]


def _patch_boq_repositories(monkeypatch: pytest.MonkeyPatch, positions: list[Any]) -> uuid.UUID:
    """Stand in for the BOQ repositories ``generate_from_boq`` imports; returns the BOQ id they answer for."""
    import app.modules.boq.repository as boq_repo_mod

    boq_id = uuid.uuid4()

    class _FakeBOQRepo:
        def __init__(self, session: object) -> None:
            self.session = session

        async def get_by_id(self, wanted: uuid.UUID) -> Any:
            return SimpleNamespace(id=wanted, metadata_={}) if wanted == boq_id else None

    class _FakePositionRepo:
        def __init__(self, session: object) -> None:
            self.session = session

        async def list_for_boq(self, wanted: uuid.UUID, **_kwargs: Any) -> tuple[list[Any], int]:
            return (positions, len(positions)) if wanted == boq_id else ([], 0)

    monkeypatch.setattr(boq_repo_mod, "BOQRepository", _FakeBOQRepo)
    monkeypatch.setattr(boq_repo_mod, "PositionRepository", _FakePositionRepo)
    return boq_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("region", "rest_days"),
    [(_GULF, _GULF_REST_DAYS), (_GERMANY, _GERMAN_REST_DAYS)],
    ids=["doha", "berlin"],
)
async def test_the_same_project_is_counted_on_one_week_by_both_paths(
    monkeypatch: pytest.MonkeyPatch, region: str, rest_days: set[int]
) -> None:
    """BOQ generation draws dates on the regional week and a re-save recounts them on it.

    Two paths in the module give an activity its duration: generation steps the
    project's working week to place each activity, and ``compute_duration``
    recounts the working days whenever a date is saved. Before the project's
    region reached the second path it counted Monday to Friday for every
    project, so a Gulf schedule drawn Sunday to Thursday got a different number
    the first time anyone re-saved a date without changing it. Here the dates
    generation drew are re-saved unchanged, and the recount must equal an
    independent count of the region's working days between them. Berlin is the
    control: its week is the old default, so it agreed before and must still.
    """
    svc = _make_service(project_region=region)
    schedule = await svc.create_schedule(
        ScheduleCreate(project_id=PROJECT_ID, name="Generated", start_date=_WEEK_SUNDAY, end_date="2027-03-31")
    )
    boq_id = _patch_boq_repositories(monkeypatch, _boq_section_with_three_positions())

    async def _no_reconcile(_schedule_id: uuid.UUID) -> dict[str, int]:
        return {}

    monkeypatch.setattr(svc, "reconcile_dependency_sources", _no_reconcile)

    await svc.generate_from_boq(schedule.id, boq_id, total_project_days=120)

    tasks = [a for a in svc.activity_repo.rows.values() if a.activity_type == "task"]
    assert len(tasks) == 3
    spans = [_weekdays_between(t.start_date, t.end_date) for t in tasks]
    # Generation lands every end on a working day of the region...
    assert all(span[-1] not in rest_days for span in spans)
    # ...and the first task starts on the Sunday, the day the two weeks disagree
    # on, so a recount on the wrong week cannot come out equal by chance.
    assert spans[0][0] == 6
    if region == _GULF:
        monday_to_friday = [_working_days(t.start_date, t.end_date, _GERMAN_REST_DAYS) for t in tasks]
        regional = [_working_days(t.start_date, t.end_date, rest_days) for t in tasks]
        assert regional != monday_to_friday

    for task in tasks:
        resaved = await svc.update_activity(task.id, ActivityUpdate(start_date=task.start_date, end_date=task.end_date))
        assert resaved.duration_days == _working_days(task.start_date, task.end_date, rest_days), (
            f"{task.name}: {task.start_date} to {task.end_date} recounted on another week than it was drawn on"
        )


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
    # Unfinished activities whose planned end is already past are reported as
    # "delayed" (effective status), so keep the open tasks in the future to
    # pin the plain status mapping here. The delay derivation has its own test.
    svc = _make_service()
    schedule = await _create_schedule(svc)
    await _create_activity(svc, schedule.id, name="Task A", status="completed")
    await _create_activity(
        svc,
        schedule.id,
        name="Task B",
        status="in_progress",
        start_date="2026-12-01",
        end_date="2026-12-15",
    )
    await _create_activity(
        svc,
        schedule.id,
        name="Task C",
        status="not_started",
        start_date="2027-01-04",
        end_date="2027-01-15",
    )

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
