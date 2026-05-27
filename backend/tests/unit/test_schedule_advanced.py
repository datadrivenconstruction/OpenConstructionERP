"""Unit tests for :class:`ScheduleAdvancedService` and module pure helpers.

Scope:
    * Pure helpers: ``compute_ppc``, ``compute_rnc_pareto``,
      ``compute_baseline_delta``, ``is_constraint_blocking_task``,
      ``weeks_from_lookahead``, ``validate_commitment``.
    * State machines: phase / look-ahead / constraint / commitment /
      weekly / baseline.
    * Service orchestration: close-weekly with PPC + event emission,
      commit-to-week, mark-complete, mark-missed (with paired RNC),
      clear-constraint with event, capture-baseline with event, delta
      computation orchestrator.
    * Repository CRUD smoke.
    * Permission constants registered.

Repositories and event bus are stubbed (no DB); the service is built
directly via ``__new__`` and patched-in stub repos, mirroring
``tests/unit/test_safety.py``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.modules.schedule_advanced.permissions import register_schedule_advanced_permissions
from app.modules.schedule_advanced.schemas import (
    BaselineCreate,
    CalendarCreate,
    CommitmentCreate,
    ConstraintCreate,
    LookAheadCreate,
    MasterScheduleCreate,
    PhasePlanCreate,
    RNCCreate,
    WeeklyWorkPlanCreate,
)
from app.modules.schedule_advanced.service import (
    ScheduleAdvancedService,
    allowed_baseline_transitions,
    allowed_commitment_transitions,
    allowed_constraint_transitions,
    allowed_look_ahead_transitions,
    allowed_phase_transitions,
    allowed_weekly_transitions,
    compute_baseline_delta,
    compute_evm,
    compute_ppc,
    compute_rnc_pareto,
    cpm_forward_backward_pass,
    is_constraint_blocking_task,
    time_impact_analysis,
    validate_commitment,
    weeks_from_lookahead,
)

PROJECT_ID = uuid.uuid4()


# ── Generic stub helpers ──────────────────────────────────────────────────


class _StubSession:
    async def refresh(self, obj: Any) -> None:  # noqa: ARG002
        return None

    async def execute(self, stmt: Any) -> Any:  # noqa: ARG002
        return SimpleNamespace(
            scalar_one_or_none=lambda: None,
            scalar_one=lambda: 0,
            scalars=lambda: SimpleNamespace(all=lambda: [], first=lambda: None),
            all=lambda: [],
        )


class _StubRepo:
    """Generic in-memory repo used to back every entity in the service."""

    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def create(self, inst: Any) -> Any:
        if getattr(inst, "id", None) is None:
            inst.id = uuid.uuid4()
        now = datetime.now(UTC)
        inst.created_at = now
        inst.updated_at = now
        self.rows[inst.id] = inst
        return inst

    async def get_by_id(self, inst_id: uuid.UUID) -> Any:
        return self.rows.get(inst_id)

    async def delete(self, inst_id: uuid.UUID) -> None:
        self.rows.pop(inst_id, None)

    async def update_fields(self, inst_id: uuid.UUID, **fields: Any) -> None:
        row = self.rows.get(inst_id)
        if row is not None:
            for k, v in fields.items():
                setattr(row, k, v)
            row.updated_at = datetime.now(UTC)


class _StubMasterRepo(_StubRepo):
    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[Any], int]:
        rows = [r for r in self.rows.values() if r.project_id == project_id]
        if status is not None:
            rows = [r for r in rows if r.status == status]
        return rows[offset : offset + limit], len(rows)


class _StubPhaseRepo(_StubRepo):
    async def list_for_master(self, master_schedule_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if r.master_schedule_id == master_schedule_id]


class _StubLookAheadRepo(_StubRepo):
    async def list_for_master(self, master_schedule_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if r.master_schedule_id == master_schedule_id]

    async def current_for_master(self, master_schedule_id: uuid.UUID, today: date) -> Any:
        for r in self.rows.values():
            if r.master_schedule_id == master_schedule_id and r.period_start <= today <= r.period_end:
                return r
        return None


class _StubConstraintRepo(_StubRepo):
    async def list_for_look_ahead(self, look_ahead_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if r.look_ahead_id == look_ahead_id]

    async def open_constraints_for_project(self, project_id: uuid.UUID) -> list[Any]:  # noqa: ARG002
        return [r for r in self.rows.values() if r.status in ("open", "in_progress", "escalated")]

    async def list_open_for_task(self, task_ref: uuid.UUID) -> list[Any]:
        return [
            r for r in self.rows.values() if r.task_ref == task_ref and r.status in ("open", "in_progress", "escalated")
        ]


class _StubWeeklyRepo(_StubRepo):
    async def list_for_master(self, master_schedule_id: uuid.UUID, *, limit: int = 52) -> list[Any]:  # noqa: ARG002
        return [r for r in self.rows.values() if r.master_schedule_id == master_schedule_id]

    async def current_week_plan(self, master_schedule_id: uuid.UUID, today: date) -> Any:
        for r in self.rows.values():
            if r.master_schedule_id == master_schedule_id and r.week_start_date <= today <= r.week_end_date:
                return r
        return None

    async def current_week_commitment_count(
        self,
        project_id: uuid.UUID,
        today: date,  # noqa: ARG002
    ) -> int:
        # Mirrors the real aggregate: commitments in current-week plans
        # of active masters. The stub weekly rows don't carry master
        # status, so count commitments whose week plan brackets today.
        commit_repo = getattr(self, "_commit_repo", None)
        if commit_repo is None:
            return 0
        total = 0
        for w in self.rows.values():
            if w.week_start_date <= today <= w.week_end_date:
                total += len([c for c in commit_repo.rows.values() if c.week_plan_id == w.id])
        return total

    async def last_n_weeks_ppc(self, project_id: uuid.UUID, n: int = 12) -> list[Any]:  # noqa: ARG002
        return [r for r in self.rows.values() if r.status == "closed"][:n]


class _StubCommitmentRepo(_StubRepo):
    async def commitments_for_week(self, week_plan_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if r.week_plan_id == week_plan_id]


class _StubRNCRepo(_StubRepo):
    async def list_for_commitment(self, commitment_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if r.commitment_id == commitment_id]

    async def list_for_project_period(
        self,
        project_id: uuid.UUID,  # noqa: ARG002
        period_start: date,  # noqa: ARG002
        period_end: date,  # noqa: ARG002
    ) -> list[Any]:
        return list(self.rows.values())


class _StubBaselineRepo(_StubRepo):
    async def list_for_master(self, master_schedule_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if r.master_schedule_id == master_schedule_id]

    async def list_for_project(self, project_id: uuid.UUID, *, status: str | None = None) -> list[Any]:  # noqa: ARG002
        rows = list(self.rows.values())
        if status is not None:
            rows = [r for r in rows if r.status == status]
        return rows


class _StubBaselineDeltaRepo(_StubRepo):
    async def list_for_baseline(self, baseline_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if r.baseline_id == baseline_id]


class _StubCalendarRepo(_StubRepo):
    async def list_for_project(self, project_id: uuid.UUID) -> list[Any]:
        return [r for r in self.rows.values() if r.project_id == project_id]

    async def default_for_project(self, project_id: uuid.UUID) -> Any:
        for r in self.rows.values():
            if r.project_id == project_id and r.is_default:
                return r
        return None


def _make_service() -> ScheduleAdvancedService:
    svc = ScheduleAdvancedService.__new__(ScheduleAdvancedService)
    svc.session = _StubSession()
    svc.master_repo = _StubMasterRepo()
    svc.phase_repo = _StubPhaseRepo()
    svc.look_ahead_repo = _StubLookAheadRepo()
    svc.constraint_repo = _StubConstraintRepo()
    svc.weekly_repo = _StubWeeklyRepo()
    svc.commitment_repo = _StubCommitmentRepo()
    # Let the weekly stub resolve commitments for the aggregate count,
    # mirroring the real cross-table join.
    svc.weekly_repo._commit_repo = svc.commitment_repo  # noqa: SLF001
    svc.rnc_repo = _StubRNCRepo()
    svc.baseline_repo = _StubBaselineRepo()
    svc.baseline_delta_repo = _StubBaselineDeltaRepo()
    svc.calendar_repo = _StubCalendarRepo()
    return svc


def _patch_event_bus() -> Any:
    return patch(
        "app.modules.schedule_advanced.service.event_bus",
        MagicMock(publish_detached=MagicMock(return_value=None)),
    )


# ── Pure helpers: PPC ─────────────────────────────────────────────────────


def test_compute_ppc_empty_returns_zero() -> None:
    assert compute_ppc([]) == Decimal("0")


def test_compute_ppc_all_complete() -> None:
    commitments = [
        SimpleNamespace(status="completed"),
        SimpleNamespace(status="completed"),
        SimpleNamespace(status="completed"),
    ]
    assert compute_ppc(commitments) == Decimal("100.00")


def test_compute_ppc_partial() -> None:
    commitments = [
        SimpleNamespace(status="completed"),
        SimpleNamespace(status="completed"),
        SimpleNamespace(status="missed"),
        SimpleNamespace(status="missed"),
    ]
    assert compute_ppc(commitments) == Decimal("50.00")


def test_compute_ppc_zero_committed_returns_zero() -> None:
    # Pure "planned" rows aren't in the denominator
    commitments = [SimpleNamespace(status="planned"), SimpleNamespace(status="planned")]
    assert compute_ppc(commitments) == Decimal("0")


# ── Pure helpers: RNC pareto ──────────────────────────────────────────────


def test_compute_rnc_pareto_per_category_counts() -> None:
    rncs = [
        SimpleNamespace(category="manpower"),
        SimpleNamespace(category="manpower"),
        SimpleNamespace(category="material"),
        SimpleNamespace(category="weather"),
    ]
    out = compute_rnc_pareto(rncs, date.today(), date.today())
    assert out["manpower"] == 2
    assert out["material"] == 1
    assert out["weather"] == 1
    assert out["equipment"] == 0  # zero-filled


def test_compute_rnc_pareto_unknown_category_bucketed_as_other() -> None:
    rncs = [SimpleNamespace(category="not_a_real_category")]
    out = compute_rnc_pareto(rncs, date.today(), date.today())
    assert out["other"] == 1


# ── Pure helpers: Baseline delta ──────────────────────────────────────────


def test_compute_baseline_delta_positive_variance() -> None:
    t1 = str(uuid.uuid4())
    baseline = [
        {"task_ref": t1, "planned_start": "2026-04-01", "planned_finish": "2026-04-10"},
    ]
    current = [
        {"task_ref": t1, "planned_start": "2026-04-03", "planned_finish": "2026-04-15"},
    ]
    deltas = compute_baseline_delta(baseline, current)
    assert len(deltas) == 1
    assert deltas[0]["schedule_variance_days"] == 5  # 04-15 - 04-10


def test_compute_baseline_delta_negative_variance() -> None:
    t1 = str(uuid.uuid4())
    baseline = [{"task_ref": t1, "planned_start": "2026-04-01", "planned_finish": "2026-04-15"}]
    current = [{"task_ref": t1, "planned_start": "2026-04-01", "planned_finish": "2026-04-10"}]
    deltas = compute_baseline_delta(baseline, current)
    assert deltas[0]["schedule_variance_days"] == -5


def test_compute_baseline_delta_missing_task_zero_variance() -> None:
    t1 = str(uuid.uuid4())
    baseline = [{"task_ref": t1, "planned_start": "2026-04-01", "planned_finish": "2026-04-10"}]
    deltas = compute_baseline_delta(baseline, [])
    assert deltas[0]["schedule_variance_days"] == 0
    assert deltas[0]["planned_finish_current"] is None


def test_compute_baseline_delta_wrapper_dict_shape() -> None:
    t1 = str(uuid.uuid4())
    baseline = {"tasks": [{"task_ref": t1, "planned_start": "2026-04-01", "planned_finish": "2026-04-10"}]}
    current = [{"task_ref": t1, "planned_start": "2026-04-01", "planned_finish": "2026-04-12"}]
    deltas = compute_baseline_delta(baseline, current)
    assert deltas[0]["schedule_variance_days"] == 2


# ── Pure helpers: constraint blocking ─────────────────────────────────────


def test_is_constraint_blocking_task_open_overdue() -> None:
    task_id = uuid.uuid4()
    today = date(2026, 5, 12)
    constraints = [
        SimpleNamespace(
            task_ref=task_id,
            status="open",
            target_clear_date=date(2026, 5, 1),
        ),
    ]
    assert is_constraint_blocking_task(task_id, constraints, today) is True


def test_is_constraint_blocking_task_cleared_does_not_block() -> None:
    task_id = uuid.uuid4()
    today = date(2026, 5, 12)
    constraints = [
        SimpleNamespace(
            task_ref=task_id,
            status="cleared",
            target_clear_date=date(2026, 5, 1),
        ),
    ]
    assert is_constraint_blocking_task(task_id, constraints, today) is False


def test_is_constraint_blocking_task_future_target_does_not_block() -> None:
    task_id = uuid.uuid4()
    today = date(2026, 5, 12)
    constraints = [
        SimpleNamespace(
            task_ref=task_id,
            status="open",
            target_clear_date=date(2026, 6, 1),
        ),
    ]
    assert is_constraint_blocking_task(task_id, constraints, today) is False


# ── Pure helpers: weeks_from_lookahead ────────────────────────────────────


def test_weeks_from_lookahead_six_week_window() -> None:
    today = date(2026, 5, 12)  # Tuesday
    weeks = weeks_from_lookahead(today, window_weeks=6)
    assert len(weeks) == 6
    assert weeks[0] == date(2026, 5, 11)  # Monday of that week
    assert weeks[1] == date(2026, 5, 18)
    assert weeks[5] == date(2026, 5, 11) + timedelta(weeks=5)


def test_weeks_from_lookahead_zero_returns_empty() -> None:
    assert weeks_from_lookahead(date(2026, 5, 12), window_weeks=0) == []


# ── Pure helpers: validate_commitment ─────────────────────────────────────


def test_validate_commitment_weekend_rejected() -> None:
    commitment = {
        "planned_start": date(2026, 5, 16),  # Saturday
        "planned_finish": date(2026, 5, 18),  # Monday
    }
    ok, errs = validate_commitment(commitment, None)
    assert ok is False
    assert any("non-working" in e for e in errs)


def test_validate_commitment_valid_weekday() -> None:
    commitment = {
        "planned_start": date(2026, 5, 11),  # Monday
        "planned_finish": date(2026, 5, 15),  # Friday
    }
    ok, errs = validate_commitment(commitment, None)
    assert ok is True, errs


def test_validate_commitment_start_after_finish() -> None:
    commitment = {
        "planned_start": date(2026, 5, 15),
        "planned_finish": date(2026, 5, 11),
    }
    ok, errs = validate_commitment(commitment, None)
    assert ok is False
    assert any("on or before" in e for e in errs)


def test_validate_commitment_holiday_rejected() -> None:
    cal = {"work_days": [0, 1, 2, 3, 4], "holidays": ["2026-05-11"]}
    commitment = {
        "planned_start": date(2026, 5, 11),  # Monday but holiday
        "planned_finish": date(2026, 5, 15),
    }
    ok, errs = validate_commitment(commitment, cal)
    assert ok is False
    assert any("holiday" in e for e in errs)


# ── State machines ────────────────────────────────────────────────────────


def test_phase_transitions() -> None:
    assert "pulled" in allowed_phase_transitions("in_planning")
    assert "active" in allowed_phase_transitions("pulled")
    assert "completed" in allowed_phase_transitions("active")
    # Completed is terminal
    assert allowed_phase_transitions("completed") == {"completed"}


def test_look_ahead_transitions() -> None:
    assert "reviewed" in allowed_look_ahead_transitions("draft")
    assert "published" in allowed_look_ahead_transitions("reviewed")
    assert allowed_look_ahead_transitions("published") == {"published"}


def test_constraint_transitions() -> None:
    assert "cleared" in allowed_constraint_transitions("open")
    assert "escalated" in allowed_constraint_transitions("in_progress")
    assert allowed_constraint_transitions("cleared") == {"cleared"}


def test_commitment_transitions() -> None:
    assert "committed" in allowed_commitment_transitions("planned")
    assert "completed" in allowed_commitment_transitions("committed")
    assert "missed" in allowed_commitment_transitions("committed")
    assert allowed_commitment_transitions("completed") == {"completed"}


def test_weekly_transitions() -> None:
    assert "committed" in allowed_weekly_transitions("draft")
    assert "closed" in allowed_weekly_transitions("in_progress")
    assert allowed_weekly_transitions("closed") == {"closed"}


def test_baseline_transitions() -> None:
    assert "superseded" in allowed_baseline_transitions("active")
    assert "archived" in allowed_baseline_transitions("superseded")
    assert allowed_baseline_transitions("archived") == {"archived"}


# ── Service orchestration ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_master_schedule() -> None:
    svc = _make_service()
    m = await svc.create_master_schedule(
        MasterScheduleCreate(project_id=PROJECT_ID, name="MS-1"),
        user_id="user-1",
    )
    assert m.name == "MS-1"
    assert m.project_id == PROJECT_ID
    assert m.created_by == "user-1"


@pytest.mark.asyncio
async def test_get_master_schedule_404() -> None:
    svc = _make_service()
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await svc.get_master_schedule(uuid.uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_phase_plan_pull_emits_event() -> None:
    svc = _make_service()
    m = await svc.create_master_schedule(
        MasterScheduleCreate(project_id=PROJECT_ID, name="MS"),
        user_id="u",
    )
    p = await svc.create_phase_plan(PhasePlanCreate(master_schedule_id=m.id, name="P1"))
    with _patch_event_bus() as mock_bus:
        pulled = await svc.pull_phase(p.id, user_id="u")
    assert pulled.pulled_status == "pulled"
    assert pulled.pull_session_at is not None
    mock_bus.publish_detached.assert_called_once()
    event_name = mock_bus.publish_detached.call_args.args[0]
    assert event_name == "schedule_advanced.phase.pulled"


@pytest.mark.asyncio
async def test_phase_plan_illegal_transition_rejected() -> None:
    svc = _make_service()
    m = await svc.create_master_schedule(
        MasterScheduleCreate(project_id=PROJECT_ID, name="MS"),
        user_id="u",
    )
    p = await svc.create_phase_plan(PhasePlanCreate(master_schedule_id=m.id, name="P1", pulled_status="completed"))
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc, _patch_event_bus():
        await svc.pull_phase(p.id, user_id="u")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_close_weekly_plan_computes_ppc_and_emits_event() -> None:
    svc = _make_service()
    m = await svc.create_master_schedule(
        MasterScheduleCreate(project_id=PROJECT_ID, name="MS"),
        user_id="u",
    )
    w = await svc.create_weekly_plan(
        WeeklyWorkPlanCreate(
            master_schedule_id=m.id,
            week_start_date=date(2026, 5, 11),
            week_end_date=date(2026, 5, 15),
            status="in_progress",
        )
    )
    # 4 commitments: 2 completed, 2 missed → 50% PPC
    for status in ("completed", "completed", "missed", "missed"):
        await svc.create_commitment(
            CommitmentCreate(
                week_plan_id=w.id,
                task_ref=uuid.uuid4(),
                status=status,
            )
        )
    with _patch_event_bus() as mock_bus:
        closed = await svc.close_weekly_plan(w.id)
    assert closed.status == "closed"
    assert closed.ppc_percent == Decimal("50.00")
    assert mock_bus.publish_detached.call_args.args[0] == "schedule_advanced.weekly_plan.closed"
    payload = mock_bus.publish_detached.call_args.args[1]
    assert payload["ppc_percent"] == "50.00"
    assert len(payload["missed_commitments"]) == 2


@pytest.mark.asyncio
async def test_commit_to_week_emits_event() -> None:
    svc = _make_service()
    m = await svc.create_master_schedule(
        MasterScheduleCreate(project_id=PROJECT_ID, name="MS"),
        user_id="u",
    )
    w = await svc.create_weekly_plan(
        WeeklyWorkPlanCreate(
            master_schedule_id=m.id,
            week_start_date=date(2026, 5, 11),
            week_end_date=date(2026, 5, 15),
        )
    )
    c = await svc.create_commitment(
        CommitmentCreate(week_plan_id=w.id, task_ref=uuid.uuid4()),
    )
    user_id = str(uuid.uuid4())
    with _patch_event_bus() as mock_bus:
        committed = await svc.commit_to_week(c.id, user_id=user_id)
    assert committed.status == "committed"
    assert committed.made_at is not None
    assert mock_bus.publish_detached.call_args.args[0] == "schedule_advanced.commitment.made"


@pytest.mark.asyncio
async def test_mark_commitment_complete_sets_actual_qty() -> None:
    svc = _make_service()
    m = await svc.create_master_schedule(
        MasterScheduleCreate(project_id=PROJECT_ID, name="MS"),
        user_id="u",
    )
    w = await svc.create_weekly_plan(
        WeeklyWorkPlanCreate(
            master_schedule_id=m.id,
            week_start_date=date(2026, 5, 11),
            week_end_date=date(2026, 5, 15),
        )
    )
    c = await svc.create_commitment(
        CommitmentCreate(
            week_plan_id=w.id,
            task_ref=uuid.uuid4(),
            status="committed",
        )
    )
    done = await svc.mark_commitment_complete(c.id, actual_qty=Decimal("12.5"))
    assert done.status == "completed"
    assert done.actual_qty == Decimal("12.5")
    assert done.completed_at is not None


@pytest.mark.asyncio
async def test_mark_commitment_missed_creates_rnc() -> None:
    svc = _make_service()
    m = await svc.create_master_schedule(
        MasterScheduleCreate(project_id=PROJECT_ID, name="MS"),
        user_id="u",
    )
    w = await svc.create_weekly_plan(
        WeeklyWorkPlanCreate(
            master_schedule_id=m.id,
            week_start_date=date(2026, 5, 11),
            week_end_date=date(2026, 5, 15),
        )
    )
    c = await svc.create_commitment(
        CommitmentCreate(
            week_plan_id=w.id,
            task_ref=uuid.uuid4(),
            status="committed",
        )
    )
    rnc_payload = RNCCreate(commitment_id=c.id, category="material", description="No concrete")
    missed, rnc = await svc.mark_commitment_missed(c.id, rnc_payload)
    assert missed.status == "missed"
    assert rnc.category == "material"
    assert rnc.commitment_id == c.id


@pytest.mark.asyncio
async def test_clear_constraint_emits_event() -> None:
    svc = _make_service()
    # Don't need a real look-ahead — look_ahead_id is nullable
    c = await svc.create_constraint(
        ConstraintCreate(
            task_ref=uuid.uuid4(),
            constraint_type="material",
            description="No concrete",
        )
    )
    user_id = str(uuid.uuid4())
    with _patch_event_bus() as mock_bus:
        cleared = await svc.clear_constraint(c.id, user_id=user_id)
    assert cleared.status == "cleared"
    assert cleared.cleared_at is not None
    assert mock_bus.publish_detached.call_args.args[0] == "schedule_advanced.constraint.cleared"


@pytest.mark.asyncio
async def test_capture_baseline_emits_event_and_persists_snapshot() -> None:
    svc = _make_service()
    m = await svc.create_master_schedule(
        MasterScheduleCreate(project_id=PROJECT_ID, name="MS"),
        user_id="u",
    )
    snapshot = [
        {"task_ref": str(uuid.uuid4()), "planned_start": "2026-04-01", "planned_finish": "2026-04-10"},
    ]
    with _patch_event_bus() as mock_bus:
        b = await svc.capture_baseline(m.id, snapshot, "Baseline v1", user_id="u")
    assert b.name == "Baseline v1"
    assert b.snapshot == snapshot
    assert mock_bus.publish_detached.call_args.args[0] == "schedule_advanced.baseline.captured"


@pytest.mark.asyncio
async def test_compute_baseline_delta_orchestrator() -> None:
    svc = _make_service()
    m = await svc.create_master_schedule(
        MasterScheduleCreate(project_id=PROJECT_ID, name="MS"),
        user_id="u",
    )
    t1 = uuid.uuid4()
    snapshot = [{"task_ref": str(t1), "planned_start": "2026-04-01", "planned_finish": "2026-04-10"}]
    with _patch_event_bus():
        b = await svc.capture_baseline(m.id, snapshot, "B1", user_id="u")
    current = [{"task_ref": str(t1), "planned_start": "2026-04-01", "planned_finish": "2026-04-15"}]
    result = await svc.compute_baseline_delta_for_schedule(b.id, current)
    assert result.total_tasks == 1
    assert result.delayed_tasks == 1
    assert result.entries[0].schedule_variance_days == 5


# ── Repository CRUD smoke ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_calendar_crud_basics() -> None:
    svc = _make_service()
    cal = await svc.create_calendar(
        CalendarCreate(
            project_id=PROJECT_ID,
            name="Mon-Fri",
            is_default=True,
        )
    )
    assert cal.is_default is True
    fetched = await svc.get_calendar(cal.id)
    assert fetched.name == "Mon-Fri"
    await svc.delete_calendar(cal.id)
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        await svc.get_calendar(cal.id)


@pytest.mark.asyncio
async def test_look_ahead_crud_basics() -> None:
    svc = _make_service()
    m = await svc.create_master_schedule(
        MasterScheduleCreate(project_id=PROJECT_ID, name="MS"),
        user_id="u",
    )
    la = await svc.create_look_ahead(
        LookAheadCreate(
            master_schedule_id=m.id,
            period_start=date(2026, 5, 11),
            period_end=date(2026, 6, 22),
            window_weeks=6,
            status="reviewed",
        )
    )
    assert la.status == "reviewed"
    pub = await svc.publish_look_ahead(la.id)
    assert pub.status == "published"


@pytest.mark.asyncio
async def test_rnc_pareto_aggregation() -> None:
    svc = _make_service()
    m = await svc.create_master_schedule(
        MasterScheduleCreate(project_id=PROJECT_ID, name="MS"),
        user_id="u",
    )
    w = await svc.create_weekly_plan(
        WeeklyWorkPlanCreate(
            master_schedule_id=m.id,
            week_start_date=date(2026, 5, 11),
            week_end_date=date(2026, 5, 15),
        )
    )
    c = await svc.create_commitment(CommitmentCreate(week_plan_id=w.id, task_ref=uuid.uuid4(), status="committed"))
    await svc.create_rnc(
        RNCCreate(commitment_id=c.id, category="manpower"),
        user_id=None,
    )
    await svc.create_rnc(
        RNCCreate(commitment_id=c.id, category="material"),
        user_id=None,
    )
    out = await svc.rnc_pareto_for_project(
        PROJECT_ID,
        date(2026, 4, 1),
        date(2026, 6, 1),
    )
    assert out["manpower"] == 1
    assert out["material"] == 1


# ── Idempotency: actions must not double-promote / double-emit ────────────


@pytest.mark.asyncio
async def test_pull_phase_idempotent_no_double_event() -> None:
    """Pulling an already-pulled phase is a no-op (no re-stamp, no re-emit)."""
    svc = _make_service()
    m = await svc.create_master_schedule(
        MasterScheduleCreate(project_id=PROJECT_ID, name="MS"),
        user_id="u",
    )
    p = await svc.create_phase_plan(PhasePlanCreate(master_schedule_id=m.id, name="P"))
    with _patch_event_bus() as mock_bus:
        await svc.pull_phase(p.id, user_id="u")
        first_pulled_at = p.pull_session_at
        again = await svc.pull_phase(p.id, user_id="u")
    assert again.pulled_status == "pulled"
    assert again.pull_session_at == first_pulled_at  # not re-stamped
    mock_bus.publish_detached.assert_called_once()  # not re-emitted


@pytest.mark.asyncio
async def test_commit_to_week_idempotent_no_double_event() -> None:
    svc = _make_service()
    m = await svc.create_master_schedule(
        MasterScheduleCreate(project_id=PROJECT_ID, name="MS"),
        user_id="u",
    )
    w = await svc.create_weekly_plan(
        WeeklyWorkPlanCreate(
            master_schedule_id=m.id,
            week_start_date=date(2026, 5, 11),
            week_end_date=date(2026, 5, 15),
        )
    )
    c = await svc.create_commitment(CommitmentCreate(week_plan_id=w.id, task_ref=uuid.uuid4()))
    with _patch_event_bus() as mock_bus:
        await svc.commit_to_week(c.id, user_id="u")
        made_at_1 = c.made_at
        again = await svc.commit_to_week(c.id, user_id="u")
    assert again.status == "committed"
    assert again.made_at == made_at_1  # not re-stamped
    mock_bus.publish_detached.assert_called_once()


@pytest.mark.asyncio
async def test_clear_constraint_idempotent_preserves_audit() -> None:
    svc = _make_service()
    c = await svc.create_constraint(ConstraintCreate(task_ref=uuid.uuid4(), constraint_type="material"))
    u1 = str(uuid.uuid4())
    u2 = str(uuid.uuid4())
    with _patch_event_bus() as mock_bus:
        cleared = await svc.clear_constraint(c.id, user_id=u1)
        first_cleared_at = cleared.cleared_at
        first_cleared_by = cleared.cleared_by
        again = await svc.clear_constraint(c.id, user_id=u2)
    assert again.status == "cleared"
    # Original audit trail must survive a re-clear with a different user.
    assert again.cleared_at == first_cleared_at
    assert again.cleared_by == first_cleared_by
    mock_bus.publish_detached.assert_called_once()


@pytest.mark.asyncio
async def test_close_weekly_plan_idempotent_no_double_event() -> None:
    svc = _make_service()
    m = await svc.create_master_schedule(
        MasterScheduleCreate(project_id=PROJECT_ID, name="MS"),
        user_id="u",
    )
    w = await svc.create_weekly_plan(
        WeeklyWorkPlanCreate(
            master_schedule_id=m.id,
            week_start_date=date(2026, 5, 11),
            week_end_date=date(2026, 5, 15),
            status="in_progress",
        )
    )
    await svc.create_commitment(CommitmentCreate(week_plan_id=w.id, task_ref=uuid.uuid4(), status="completed"))
    with _patch_event_bus() as mock_bus:
        await svc.close_weekly_plan(w.id)
        again = await svc.close_weekly_plan(w.id)
    assert again.status == "closed"
    mock_bus.publish_detached.assert_called_once()


# ── Dashboard aggregate (N+1 → single query) ──────────────────────────────


@pytest.mark.asyncio
async def test_lps_dashboard_counts_current_week_commitments() -> None:
    """Dashboard rolls up commitments of the current week via the aggregate.

    Regression guard for the N+1 → single-query refactor: the count must
    come out of ``current_week_commitment_count`` and equal the number of
    commitments whose week plan brackets ``today``.
    """
    svc = _make_service()
    m = await svc.create_master_schedule(
        MasterScheduleCreate(project_id=PROJECT_ID, name="MS"),
        user_id="u",
    )
    today = date(2026, 5, 13)  # Wednesday
    w = await svc.create_weekly_plan(
        WeeklyWorkPlanCreate(
            master_schedule_id=m.id,
            week_start_date=date(2026, 5, 11),
            week_end_date=date(2026, 5, 17),
            status="in_progress",
        )
    )
    for _ in range(3):
        await svc.create_commitment(CommitmentCreate(week_plan_id=w.id, task_ref=uuid.uuid4()))
    payload = await svc.lps_dashboard_for_project(PROJECT_ID, today=today)
    assert payload["current_week_commitments"] == 3
    assert payload["active_master_schedules"] == 1


# ── Permission constants ──────────────────────────────────────────────────


def test_permission_constants_registered() -> None:
    """All 9 permissions must register without error."""
    from app.core.permissions import permission_registry

    register_schedule_advanced_permissions()

    expected = (
        "schedule_advanced.read",
        "schedule_advanced.create",
        "schedule_advanced.update",
        "schedule_advanced.delete",
        "schedule_advanced.pull_phase",
        "schedule_advanced.commit",
        "schedule_advanced.clear_constraint",
        "schedule_advanced.close_weekly",
        "schedule_advanced.capture_baseline",
    )
    for perm in expected:
        # ``_permissions`` is the internal map name in PermissionRegistry
        assert perm in permission_registry._permissions, f"missing {perm}"  # noqa: SLF001


# ── Schema sanity ─────────────────────────────────────────────────────────


def test_baseline_create_accepts_list_snapshot() -> None:
    b = BaselineCreate(
        master_schedule_id=uuid.uuid4(),
        name="B1",
        snapshot=[{"task_ref": str(uuid.uuid4()), "planned_finish": "2026-04-10"}],
    )
    assert isinstance(b.snapshot, list)


def test_constraint_create_with_all_fields() -> None:
    c = ConstraintCreate(
        task_ref=uuid.uuid4(),
        constraint_type="permit",
        description="Build permit pending",
        target_clear_date=date(2026, 5, 30),
    )
    assert c.constraint_type == "permit"
    assert c.status == "open"


# ── Phase plan CRUD + lifecycle (Phase Plans page coverage) ───────────────


@pytest.mark.asyncio
async def test_create_phase_plan_with_dates_persisted() -> None:
    """End-to-end create — verifies dates + notes flow through."""
    svc = _make_service()
    m = await svc.create_master_schedule(
        MasterScheduleCreate(project_id=PROJECT_ID, name="MS"),
        user_id="u",
    )
    p = await svc.create_phase_plan(
        PhasePlanCreate(
            master_schedule_id=m.id,
            name="Foundation",
            planned_start=date(2026, 6, 1),
            planned_finish=date(2026, 6, 30),
            notes="Spread foundations + crane pad",
        )
    )
    assert p.name == "Foundation"
    assert p.planned_start == date(2026, 6, 1)
    assert p.planned_finish == date(2026, 6, 30)
    assert p.notes == "Spread foundations + crane pad"
    assert p.pulled_status == "in_planning"


@pytest.mark.asyncio
async def test_update_phase_plan_changes_dates_and_notes() -> None:
    """The edit modal patches name + dates + notes; service must apply them."""
    from app.modules.schedule_advanced.schemas import PhasePlanUpdate

    svc = _make_service()
    m = await svc.create_master_schedule(
        MasterScheduleCreate(project_id=PROJECT_ID, name="MS"),
        user_id="u",
    )
    p = await svc.create_phase_plan(
        PhasePlanCreate(master_schedule_id=m.id, name="Phase A"),
    )
    updated = await svc.update_phase_plan(
        p.id,
        PhasePlanUpdate(
            name="Phase A (revised)",
            planned_start=date(2026, 7, 1),
            planned_finish=date(2026, 7, 31),
            notes="Re-baselined after permit delay",
        ),
    )
    assert updated.name == "Phase A (revised)"
    assert updated.planned_start == date(2026, 7, 1)
    assert updated.planned_finish == date(2026, 7, 31)
    assert "permit delay" in updated.notes


@pytest.mark.asyncio
async def test_update_phase_plan_rejects_illegal_status_transition() -> None:
    """Direct status changes via PATCH must obey the transition table."""
    from fastapi import HTTPException

    from app.modules.schedule_advanced.schemas import PhasePlanUpdate

    svc = _make_service()
    m = await svc.create_master_schedule(
        MasterScheduleCreate(project_id=PROJECT_ID, name="MS"),
        user_id="u",
    )
    p = await svc.create_phase_plan(
        PhasePlanCreate(master_schedule_id=m.id, name="P"),
    )
    # in_planning → completed is NOT a legal transition
    with pytest.raises(HTTPException) as exc:
        await svc.update_phase_plan(
            p.id,
            PhasePlanUpdate(pulled_status="completed"),
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_delete_phase_plan_removes_row() -> None:
    """Delete must actually remove the row (UI confirm dialog calls this)."""
    from fastapi import HTTPException

    svc = _make_service()
    m = await svc.create_master_schedule(
        MasterScheduleCreate(project_id=PROJECT_ID, name="MS"),
        user_id="u",
    )
    p = await svc.create_phase_plan(
        PhasePlanCreate(master_schedule_id=m.id, name="P"),
    )
    await svc.delete_phase_plan(p.id)
    with pytest.raises(HTTPException) as exc:
        await svc.get_phase_plan(p.id)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_phase_plan_404_when_missing() -> None:
    """Deleting a phase that doesn't exist must 404, not silently succeed."""
    from fastapi import HTTPException

    svc = _make_service()
    with pytest.raises(HTTPException) as exc:
        await svc.delete_phase_plan(uuid.uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_full_phase_lifecycle_planning_pulled_active_completed() -> None:
    """Walk every legal transition in one shot — mirrors the UI lifecycle buttons."""
    svc = _make_service()
    m = await svc.create_master_schedule(
        MasterScheduleCreate(project_id=PROJECT_ID, name="MS"),
        user_id="u",
    )
    p = await svc.create_phase_plan(
        PhasePlanCreate(master_schedule_id=m.id, name="P"),
    )
    assert p.pulled_status == "in_planning"
    with _patch_event_bus():
        p = await svc.pull_phase(p.id, user_id="u")
    assert p.pulled_status == "pulled"
    p = await svc.start_phase(p.id)
    assert p.pulled_status == "active"
    p = await svc.complete_phase(p.id)
    assert p.pulled_status == "completed"


@pytest.mark.asyncio
async def test_phase_finish_before_start_currently_accepted_at_schema_level() -> None:
    """Pins current backend permissiveness — UI guards finish<start in PhaseFormModal."""
    svc = _make_service()
    m = await svc.create_master_schedule(
        MasterScheduleCreate(project_id=PROJECT_ID, name="MS"),
        user_id="u",
    )
    p = await svc.create_phase_plan(
        PhasePlanCreate(
            master_schedule_id=m.id,
            name="P",
            planned_start=date(2026, 8, 1),
            planned_finish=date(2026, 7, 1),
        )
    )
    assert p.planned_start > p.planned_finish


@pytest.mark.asyncio
async def test_phase_plans_listed_for_master() -> None:
    """list_for_master returns every phase created against the master id."""
    svc = _make_service()
    m = await svc.create_master_schedule(
        MasterScheduleCreate(project_id=PROJECT_ID, name="MS"),
        user_id="u",
    )
    await svc.create_phase_plan(
        PhasePlanCreate(master_schedule_id=m.id, name="Late", planned_start=date(2026, 12, 1)),
    )
    await svc.create_phase_plan(
        PhasePlanCreate(master_schedule_id=m.id, name="Early", planned_start=date(2026, 6, 1)),
    )
    items = await svc.phase_repo.list_for_master(m.id)
    assert {p.name for p in items} == {"Late", "Early"}


# ── CPM forward/backward pass ─────────────────────────────────────────────


def test_cpm_simple_chain_critical_path() -> None:
    """A → B → C linear chain: every activity is critical, ES/EF roll up."""
    acts = [
        {"id": "A", "duration": 3},
        {"id": "B", "duration": 5},
        {"id": "C", "duration": 2},
    ]
    deps = [
        {"predecessor": "A", "successor": "B"},
        {"predecessor": "B", "successor": "C"},
    ]
    out = cpm_forward_backward_pass(acts, deps)
    assert out["A"]["ef"] == 3
    assert out["B"]["es"] == 3
    assert out["B"]["ef"] == 8
    assert out["C"]["ef"] == 10
    assert all(out[a]["is_critical"] for a in ("A", "B", "C"))
    assert all(out[a]["total_float"] == 0 for a in ("A", "B", "C"))


def test_cpm_parallel_branch_float() -> None:
    """A→B(5) and A→C(2)→D, D after both: C has positive float."""
    acts = [
        {"id": "A", "duration": 2},
        {"id": "B", "duration": 5},
        {"id": "C", "duration": 2},
        {"id": "D", "duration": 1},
    ]
    deps = [
        {"predecessor": "A", "successor": "B"},
        {"predecessor": "A", "successor": "C"},
        {"predecessor": "B", "successor": "D"},
        {"predecessor": "C", "successor": "D"},
    ]
    out = cpm_forward_backward_pass(acts, deps)
    assert out["D"]["ef"] == 8  # A(2)+B(5)+D(1)
    assert out["B"]["total_float"] == 0
    assert out["C"]["total_float"] == 3  # 5 - 2 slack on the short branch


def test_cpm_cycle_does_not_raise_500() -> None:
    """Regression: a cycle-node predecessor must not crash the pass.

    Before the fix ``max()``/``min()`` were called on an empty generator
    when a node's predecessor was a cycle node (excluded from the
    topological order) — a 500 on /cpm and /tia. ``D`` is reachable from
    the indeg-0 root ``S`` but also lists cycle-node ``B`` as a
    predecessor; its ES must default off the resolvable predecessor.
    """
    acts = [
        {"id": "S", "duration": 2},
        {"id": "B", "duration": 1},
        {"id": "C", "duration": 1},
        {"id": "D", "duration": 3},
    ]
    # B↔C is a 2-node cycle. D depends on both S (resolvable) and B (cycle).
    deps = [
        {"predecessor": "B", "successor": "C"},
        {"predecessor": "C", "successor": "B"},
        {"predecessor": "S", "successor": "D"},
        {"predecessor": "B", "successor": "D"},
    ]
    # The pure regression assertion: this call must NOT raise ValueError
    # ("max() arg is an empty sequence"). Cycle-blocked nodes are simply
    # dropped from the schedule; the resolvable root still computes.
    out = cpm_forward_backward_pass(acts, deps)
    assert "S" in out
    assert out["S"]["ef"] == 2


def test_tia_delay_on_critical_path_slips_finish() -> None:
    acts = [
        {"id": "A", "duration": 2},
        {"id": "B", "duration": 3},
    ]
    deps = [{"predecessor": "A", "successor": "B"}]
    res = time_impact_analysis(acts, deps, "B", 4)
    assert res["original_finish_workday"] == 5
    assert res["impacted_finish_workday"] == 9
    assert res["delta_days"] == 4


# ── EVM ───────────────────────────────────────────────────────────────────


def test_evm_zero_cpi_keeps_sunk_cost_in_eac() -> None:
    """Regression: AC>0 but EV=0 must NOT collapse EAC to BAC.

    PMI fallback when CPI is undefined is EAC = AC + (BAC − EV). The old
    ``eac = bac_total`` discarded the money already spent, so VAC read 0
    even after real overspend.
    """
    acts = [
        {
            "id": "A",
            "budget_at_completion": "1000",
            "percent_complete": "0",
            "actual_cost": "300",
            "planned_start_workday": 0,
            "planned_finish_workday": 10,
        },
    ]
    out = compute_evm(acts, today_workday=5)
    assert out["ac"] == Decimal("300.00")
    assert out["ev"] == Decimal("0.00")
    assert out["cpi"] == Decimal("0.0000")
    # EAC = 300 + (1000 - 0) = 1300, not 1000.
    assert out["eac"] == Decimal("1300.00")
    assert out["etc"] == Decimal("1000.00")
    assert out["vac"] == Decimal("-300.00")


def test_evm_on_track_metrics() -> None:
    acts = [
        {
            "id": "A",
            "budget_at_completion": "1000",
            "percent_complete": "50",
            "actual_cost": "500",
            "planned_start_workday": 0,
            "planned_finish_workday": 10,
        },
    ]
    out = compute_evm(acts, today_workday=5)
    assert out["pv"] == Decimal("500.00")
    assert out["ev"] == Decimal("500.00")
    assert out["spi"] == Decimal("1.0000")
    assert out["cpi"] == Decimal("1.0000")
    assert out["eac"] == Decimal("1000.00")
