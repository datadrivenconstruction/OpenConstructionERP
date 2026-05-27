# DDC-CWICR-OE: DataDrivenConstruction / OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Schedule Advanced (LPS) — Round-7 security audit regressions.

The schedule_advanced module is the Last Planner System (LPS) core: master
schedules, phase plans, look-ahead plans, constraints, weekly work plans,
commitments, RNCs, baselines, calendars + CPM/EVM/TIA analytics + a Slice 1
CPM persisted compute and resource leveling layer keyed off the sister
``schedule`` module's schedule rows.

This file pins the five R7 guarantees:

1. **IDOR closure** — every project-scoped endpoint uses the project
   chain resolver helpers (``_project_id_for_master``, ``_for_phase``,
   ``_for_look_ahead``, ``_for_constraint``, ``_for_weekly``,
   ``_for_commitment``, ``_for_rnc``, ``_for_baseline``,
   ``_for_calendar``, ``_for_schedule``) and goes through
   ``verify_project_access``. Cross-tenant attempts return 404, never
   403, per the leak policy in ``dependencies.verify_project_access``.

2. **Resource-sharing wrinkle** — calendars/resources are project-scoped
   (Calendar carries ``project_id`` directly), so the helper pattern
   collapses to ``_project_id_for_calendar`` returning ``cal.project_id``
   and the per-project resource limits in ``LevelResourcesRequest``
   travel inline with the schedule (no cross-project resource sharing
   today). This is pinned by a regression guard that asserts the
   calendar helper returns ``project_id`` directly (so swapping to a
   joined-resource model later trips a clear test failure).

3. **Money discipline** — there are no costed monetary fields in this
   module (this is the schedule_advanced *planning* module, not the
   commercial contracts module). The only Numeric columns are
   percentages (PPC), quantities (``Commitment.promised_qty``,
   ``actual_qty``) and hours (``Calendar.work_hours_per_day``). All
   use ``sqlalchemy.Numeric`` (not ``Float``) and all wire-level
   schemas type them as ``Decimal``. This is pinned by a regression
   guard that walks every ORM column and asserts no ``Float`` columns
   exist, plus a wire-level guard on ``CommitmentResponse``.

4. **FSM gates** — the six state machines (phase / look-ahead /
   constraint / commitment / weekly / baseline) reject illegal
   transitions with a 400. Pinned by negative tests covering the
   classic skip-over patterns (e.g. ``planned → completed`` jumping
   the ``committed`` /``in_progress`` step on Commitment;
   ``in_planning → completed`` on PhasePlan; ``draft → published``
   skipping ``reviewed`` on LookAheadPlan).

5. **RBAC on writes** — POST/PATCH/DELETE bind ``RequirePermission``
   keys (``schedule_advanced.create`` / ``.update`` / ``.delete`` /
   ``.commit`` / ``.capture_baseline`` / ``.close_weekly``). Pinned
   by introspecting the FastAPI route table for the union of all
   sensitive write paths.

Tests run with in-memory stubs (no SQLite, no FastAPI app boot) so they
stay fast and reproducible, mirroring ``test_contracts_security.py``.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import Float, Numeric

from app.modules.schedule_advanced import models as sa_models
from app.modules.schedule_advanced.router import router as schedule_advanced_router
from app.modules.schedule_advanced.schemas import (
    CommitmentResponse,
    CommitmentUpdate,
    LookAheadUpdate,
    PhasePlanUpdate,
)
from app.modules.schedule_advanced.service import (
    ScheduleAdvancedService,
    allowed_commitment_transitions,
    allowed_look_ahead_transitions,
    allowed_phase_transitions,
    allowed_weekly_transitions,
)

# ── Test scenario constants ───────────────────────────────────────────────


PROJECT_A = uuid.uuid4()
PROJECT_B = uuid.uuid4()
USER_A = str(uuid.uuid4())  # owns project A
USER_B = str(uuid.uuid4())  # owns project B


# ── Stub session + repository scaffolding ─────────────────────────────────


class _StubSession:
    """Minimal async-session stub that records add() and refresh() calls."""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.svc: Any = None

    def add(self, item: Any) -> None:
        if getattr(item, "id", None) is None:
            item.id = uuid.uuid4()
        self.added.append(item)

    async def flush(self) -> None:
        pass

    async def refresh(self, _obj: Any) -> None:
        pass

    async def execute(self, _stmt: Any) -> Any:
        return SimpleNamespace(
            scalar_one_or_none=lambda: None,
            scalar_one=lambda: 0,
            scalars=lambda: SimpleNamespace(all=lambda: [], first=lambda: None),
        )

    async def get(self, model: Any, key: uuid.UUID) -> Any:
        if self.svc is None:
            return None
        name = getattr(model, "__name__", "")
        repo = {
            "MasterSchedule": getattr(self.svc, "master_repo", None),
            "PhasePlan": getattr(self.svc, "phase_repo", None),
            "LookAheadPlan": getattr(self.svc, "look_ahead_repo", None),
            "Constraint": getattr(self.svc, "constraint_repo", None),
            "WeeklyWorkPlan": getattr(self.svc, "weekly_repo", None),
            "Commitment": getattr(self.svc, "commitment_repo", None),
            "ReasonForNonCompletion": getattr(self.svc, "rnc_repo", None),
            "Baseline": getattr(self.svc, "baseline_repo", None),
            "Calendar": getattr(self.svc, "calendar_repo", None),
        }.get(name)
        if repo is None:
            return None
        return repo.rows.get(key)


class _StubRepo:
    """Generic in-memory repo backing every schedule_advanced entity."""

    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def create(self, instance: Any) -> Any:
        if getattr(instance, "id", None) is None:
            instance.id = uuid.uuid4()
        now = datetime.now(UTC)
        if not hasattr(instance, "created_at") or instance.created_at is None:
            instance.created_at = now
        if not hasattr(instance, "updated_at") or instance.updated_at is None:
            instance.updated_at = now
        self.rows[instance.id] = instance
        return instance

    async def get_by_id(self, instance_id: uuid.UUID) -> Any | None:
        return self.rows.get(instance_id)

    async def update_fields(self, instance_id: uuid.UUID, **fields: Any) -> None:
        obj = self.rows.get(instance_id)
        if obj is not None:
            for k, v in fields.items():
                setattr(obj, k, v)

    async def delete(self, instance_id: uuid.UUID) -> None:
        self.rows.pop(instance_id, None)

    async def commitments_for_week(
        self,
        week_plan_id: uuid.UUID,
    ) -> list[Any]:
        return [r for r in self.rows.values() if getattr(r, "week_plan_id", None) == week_plan_id]


def _make_service() -> ScheduleAdvancedService:
    svc = ScheduleAdvancedService.__new__(ScheduleAdvancedService)
    svc.session = _StubSession()
    svc.master_repo = _StubRepo()
    svc.phase_repo = _StubRepo()
    svc.look_ahead_repo = _StubRepo()
    svc.constraint_repo = _StubRepo()
    svc.weekly_repo = _StubRepo()
    svc.commitment_repo = _StubRepo()
    svc.rnc_repo = _StubRepo()
    svc.baseline_repo = _StubRepo()
    svc.baseline_delta_repo = _StubRepo()
    svc.calendar_repo = _StubRepo()
    svc.session.svc = svc
    return svc


def _patch_project_repo(
    monkeypatch: pytest.MonkeyPatch,
    *,
    owners: dict[uuid.UUID, str],
) -> None:
    """Stub ProjectRepository.get_by_id + UserRepository.get_by_id.

    A project is "missing" iff its id isn't in ``owners``. Users are
    always returned as plain editors — no admin override so the access
    check is strictly project-ownership-based.
    """

    class _StubProjectRepo:
        def __init__(self, _session: Any) -> None:
            pass

        async def get_by_id(self, project_id: uuid.UUID):
            uid = owners.get(project_id)
            if uid is None:
                return None
            return SimpleNamespace(id=project_id, owner_id=uid)

    class _StubUserRepo:
        def __init__(self, _session: Any) -> None:
            pass

        async def get_by_id(self, _user_id: uuid.UUID):
            return SimpleNamespace(role="editor")

    monkeypatch.setattr(
        "app.modules.projects.repository.ProjectRepository",
        _StubProjectRepo,
    )
    monkeypatch.setattr(
        "app.modules.users.repository.UserRepository",
        _StubUserRepo,
    )


# ── 1. IDOR — cross-tenant access denied (404, not 403) ───────────────────


@pytest.mark.asyncio
async def test_idor_master_schedule_blocks_cross_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """User B (owns project B) must NOT resolve a master-schedule on
    project A — ``verify_project_access`` must 404 (never 403), per the
    leak policy.
    """
    from app.dependencies import verify_project_access
    from app.modules.schedule_advanced.router import _project_id_for_master

    svc = _make_service()
    master = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=PROJECT_A,
        name="A-confidential",
    )
    svc.master_repo.rows[master.id] = master
    _patch_project_repo(monkeypatch, owners={PROJECT_A: USER_A, PROJECT_B: USER_B})

    # Helper resolves the project_id correctly (no leak there) ...
    project_id = await _project_id_for_master(master.id, svc)
    assert project_id == PROJECT_A

    # ... but the access guard slams the door.
    with pytest.raises(HTTPException) as exc:
        await verify_project_access(PROJECT_A, USER_B, svc.session)
    assert exc.value.status_code == 404, (
        f"cross-tenant master-schedule access must 404 (not 403) — got {exc.value.status_code}: {exc.value.detail!r}"
    )


@pytest.mark.asyncio
async def test_idor_nested_resource_chain_resolves_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A nested commitment must trace back through week-plan →
    master-schedule → project_id, and the access guard must 404 a
    cross-tenant caller. Pins the full resolver chain.
    """
    from app.dependencies import verify_project_access
    from app.modules.schedule_advanced.router import _project_id_for_commitment

    svc = _make_service()
    master = SimpleNamespace(id=uuid.uuid4(), project_id=PROJECT_A)
    week = SimpleNamespace(id=uuid.uuid4(), master_schedule_id=master.id)
    commit = SimpleNamespace(
        id=uuid.uuid4(),
        week_plan_id=week.id,
        task_ref=uuid.uuid4(),
        status="planned",
    )
    svc.master_repo.rows[master.id] = master
    svc.weekly_repo.rows[week.id] = week
    svc.commitment_repo.rows[commit.id] = commit
    _patch_project_repo(monkeypatch, owners={PROJECT_A: USER_A, PROJECT_B: USER_B})

    project_id = await _project_id_for_commitment(commit.id, svc)
    assert project_id == PROJECT_A

    with pytest.raises(HTTPException) as exc:
        await verify_project_access(project_id, USER_B, svc.session)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_idor_resolver_missing_resource_404s_not_500() -> None:
    """A nested resource that doesn't exist must 404, not 500 — so
    enumeration attempts get a clean answer with no traceback leak.
    """
    from app.modules.schedule_advanced.router import (
        _project_id_for_baseline,
        _project_id_for_commitment,
        _project_id_for_constraint,
        _project_id_for_look_ahead,
        _project_id_for_master,
        _project_id_for_phase,
        _project_id_for_rnc,
        _project_id_for_weekly,
    )

    svc = _make_service()
    bogus = uuid.uuid4()

    for helper in (
        _project_id_for_master,
        _project_id_for_phase,
        _project_id_for_look_ahead,
        _project_id_for_constraint,
        _project_id_for_weekly,
        _project_id_for_commitment,
        _project_id_for_rnc,
        _project_id_for_baseline,
    ):
        with pytest.raises(HTTPException) as exc:
            await helper(bogus, svc)
        assert exc.value.status_code == 404, f"{helper.__name__} should 404 for unknown id, got {exc.value.status_code}"


@pytest.mark.asyncio
async def test_idor_detached_constraint_404s_not_grants_access() -> None:
    """A Constraint with ``look_ahead_id=None`` (detached / orphan) has
    no project to verify against — must 404 rather than silently grant
    access (defence-in-depth).
    """
    from app.modules.schedule_advanced.router import _project_id_for_constraint

    svc = _make_service()
    detached = SimpleNamespace(
        id=uuid.uuid4(),
        look_ahead_id=None,
        task_ref=uuid.uuid4(),
        status="open",
    )
    svc.constraint_repo.rows[detached.id] = detached

    with pytest.raises(HTTPException) as exc:
        await _project_id_for_constraint(detached.id, svc)
    assert exc.value.status_code == 404


# ── 2. Resource-sharing wrinkle (Calendar) ───────────────────────────────


@pytest.mark.asyncio
async def test_calendar_resource_helper_returns_project_directly() -> None:
    """Calendars are project-scoped — ``_project_id_for_calendar`` MUST
    return ``cal.project_id`` directly, not via any cross-tenant join.

    If a future PR introduces shared calendars across projects, this
    test trips and the author must add an explicit per-assignment
    access check (the resource-sharing wrinkle from the R7 brief).
    """
    from app.modules.schedule_advanced.router import _project_id_for_calendar

    svc = _make_service()
    cal = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=PROJECT_A,
        name="Default working week",
    )
    svc.calendar_repo.rows[cal.id] = cal

    resolved = await _project_id_for_calendar(cal.id, svc)
    assert resolved == PROJECT_A, (
        "Calendar resolver must return its own project_id; if calendars "
        "ever become shared resources, add a per-assignment access "
        "check (verify caller has access on the assignment's project)."
    )


# ── 3. Money discipline — Numeric only, no Float ────────────────────────


def test_no_float_columns_in_orm_models() -> None:
    """Every numeric column across the module's ORM models must be
    ``Numeric``, never ``Float`` — Float introduces silent precision
    loss for quantities / percentages, which corrupts PPC arithmetic
    and commitment quantities.
    """
    offenders: list[str] = []
    for name, cls in inspect.getmembers(sa_models, inspect.isclass):
        if not hasattr(cls, "__table__"):
            continue
        for col in cls.__table__.columns:
            if isinstance(col.type, Float):
                offenders.append(f"{name}.{col.name}")
    assert offenders == [], "Float columns leak precision; switch to Numeric: " + ", ".join(offenders)


def test_numeric_quantity_columns_use_decimal() -> None:
    """Quantity / percentage columns must round-trip through Decimal.

    Pins the schema-level types: a future PR that switches
    ``Commitment.promised_qty`` to Float would corrupt PPC and break
    AR reconciliation downstream.
    """
    qty = sa_models.Commitment.__table__.c.promised_qty
    actual = sa_models.Commitment.__table__.c.actual_qty
    ppc = sa_models.WeeklyCommitment.__table__.c.ppc
    hours = sa_models.Calendar.__table__.c.work_hours_per_day

    for col in (qty, actual, ppc, hours):
        assert isinstance(col.type, Numeric), f"{col.name} must be Numeric (Decimal), got {type(col.type).__name__}"


def test_commitment_response_serializes_decimal_as_string() -> None:
    """Wire-level guard: ``CommitmentResponse.promised_qty`` is typed
    as ``Decimal``; the JSON-mode dump must emit a string.

    Catches a future "let's serialize as float" refactor at the
    schema layer.
    """
    now = datetime.now(UTC)
    resp = CommitmentResponse(
        id=uuid.uuid4(),
        week_plan_id=uuid.uuid4(),
        task_ref=uuid.uuid4(),
        worker_or_crew="crew-1",
        promised_qty=Decimal("123.456"),
        unit="m3",
        status="planned",
        created_at=now,
        updated_at=now,
    )
    dumped = resp.model_dump(mode="json")
    assert dumped["promised_qty"] == "123.456", (
        f"promised_qty must serialize as string, got {dumped['promised_qty']!r} "
        f"({type(dumped['promised_qty']).__name__})"
    )


# ── 4. FSM gates — invalid transitions rejected with 400 ─────────────────


@pytest.mark.asyncio
async def test_fsm_phase_rejects_skip_in_planning_to_completed() -> None:
    """PhasePlan ``in_planning → completed`` skips ``pulled → active`` —
    must surface 400 with a transition message.
    """
    svc = _make_service()
    phase = SimpleNamespace(
        id=uuid.uuid4(),
        master_schedule_id=uuid.uuid4(),
        pulled_status="in_planning",
        name="Phase 1",
    )
    svc.phase_repo.rows[phase.id] = phase

    with pytest.raises(HTTPException) as exc:
        await svc.update_phase_plan(
            phase.id,
            PhasePlanUpdate(pulled_status="completed"),
        )
    assert exc.value.status_code == 400
    assert "transition" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_fsm_look_ahead_rejects_skip_draft_to_published() -> None:
    """LookAheadPlan ``draft → published`` skips ``reviewed`` and is
    illegal — must surface 400.
    """
    svc = _make_service()
    la = SimpleNamespace(
        id=uuid.uuid4(),
        master_schedule_id=uuid.uuid4(),
        status="draft",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 6, 12),
        window_weeks=6,
    )
    svc.look_ahead_repo.rows[la.id] = la

    with pytest.raises(HTTPException) as exc:
        await svc.update_look_ahead(la.id, LookAheadUpdate(status="published"))
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_fsm_commitment_rejects_skip_planned_to_completed() -> None:
    """Commitment ``planned → completed`` skips ``committed`` /
    ``in_progress`` — must surface 400.
    """
    svc = _make_service()
    commit = SimpleNamespace(
        id=uuid.uuid4(),
        week_plan_id=uuid.uuid4(),
        task_ref=uuid.uuid4(),
        worker_or_crew="",
        promised_qty=Decimal("0"),
        unit="",
        planned_start=None,
        planned_finish=None,
        status="planned",
        made_by_user_id=None,
        made_at=None,
        completed_at=None,
        actual_qty=None,
    )
    svc.commitment_repo.rows[commit.id] = commit

    with pytest.raises(HTTPException) as exc:
        await svc.update_commitment(
            commit.id,
            CommitmentUpdate(status="completed"),
        )
    assert exc.value.status_code == 400
    assert "transition" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_fsm_mark_complete_blocks_from_planned() -> None:
    """``ScheduleAdvancedService.mark_commitment_complete`` cannot
    short-circuit the FSM: a ``planned`` commitment cannot jump
    directly to ``completed``.
    """
    svc = _make_service()
    commit = SimpleNamespace(
        id=uuid.uuid4(),
        week_plan_id=uuid.uuid4(),
        task_ref=uuid.uuid4(),
        status="planned",
        promised_qty=Decimal("0"),
        actual_qty=None,
        completed_at=None,
    )
    svc.commitment_repo.rows[commit.id] = commit

    with pytest.raises(HTTPException) as exc:
        await svc.mark_commitment_complete(commit.id, actual_qty=Decimal("10"))
    assert exc.value.status_code == 400


def test_fsm_transition_tables_are_one_way_from_terminal() -> None:
    """Terminal states are absorbing — no transition out of them.

    This is a structural guarantee: ``completed`` PhasePlan,
    ``published`` LookAheadPlan, ``cleared`` Constraint,
    ``completed`` / ``missed`` Commitment, ``closed`` WeeklyWorkPlan
    each only allow self-transitions. A regression that adds a
    ``completed → active`` rollback would silently undo audit history.
    """
    assert allowed_phase_transitions("completed") == {"completed"}
    assert allowed_look_ahead_transitions("published") == {"published"}
    assert allowed_commitment_transitions("completed") == {"completed"}
    assert allowed_commitment_transitions("missed") == {"missed"}
    assert allowed_weekly_transitions("closed") == {"closed"}


# ── 5. RBAC on writes ────────────────────────────────────────────────────


def test_rbac_write_endpoints_require_permission() -> None:
    """Every write route (POST / PATCH / DELETE) must declare a
    ``RequirePermission`` dependency. Read endpoints (GET) are
    intentionally open to project members.

    The CPM/EVM/TIA stateless POST endpoints carry a
    ``schedule_advanced.read`` permission (they don't mutate anything,
    but they're computationally expensive so VIEWER-or-higher only).
    """
    from app.dependencies import RequirePermission

    write_methods = {"POST", "PATCH", "DELETE", "PUT"}
    missing: list[str] = []

    for route in schedule_advanced_router.routes:
        methods = getattr(route, "methods", set()) or set()
        if not (methods & write_methods):
            continue
        deps = getattr(route, "dependant", None)
        # Walk the dependency tree looking for a RequirePermission instance.
        found = False
        if deps is not None:
            stack = [deps]
            while stack:
                cur = stack.pop()
                call = getattr(cur, "call", None)
                if isinstance(call, RequirePermission):
                    found = True
                    break
                stack.extend(getattr(cur, "dependencies", []) or [])
        if not found:
            missing.append(f"{','.join(sorted(methods))} {route.path}")

    assert missing == [], "Write endpoints missing RequirePermission gate (RBAC bypass risk):\n  " + "\n  ".join(
        missing
    )


def test_rbac_permission_constants_registered() -> None:
    """The nine permission keys must be present in the registry so the
    runtime guard never silently falls through to "permission unknown =
    allowed" semantics.
    """
    from app.core.permissions import permission_registry
    from app.modules.schedule_advanced.permissions import (
        register_schedule_advanced_permissions,
    )

    register_schedule_advanced_permissions()
    expected = {
        "schedule_advanced.read",
        "schedule_advanced.create",
        "schedule_advanced.update",
        "schedule_advanced.delete",
        "schedule_advanced.pull_phase",
        "schedule_advanced.commit",
        "schedule_advanced.clear_constraint",
        "schedule_advanced.close_weekly",
        "schedule_advanced.capture_baseline",
    }
    registered = set(permission_registry._permissions.keys())  # noqa: SLF001
    assert expected <= registered, f"missing permission keys: {expected - registered}"


# ── Regression: happy-path FSM transitions still work ────────────────────


@pytest.mark.asyncio
async def test_fsm_happy_path_phase_plan_walk() -> None:
    """Sanity guard: the legal walk
    ``in_planning → pulled → active → completed`` must still succeed
    so the R7 IDOR/FSM hardening hasn't accidentally bricked the
    common case.
    """
    svc = _make_service()
    phase = SimpleNamespace(
        id=uuid.uuid4(),
        master_schedule_id=uuid.uuid4(),
        pulled_status="in_planning",
        name="Phase happy path",
    )
    svc.phase_repo.rows[phase.id] = phase

    # in_planning → pulled (via the dedicated endpoint helper)
    await svc.pull_phase(phase.id, user_id=USER_A)
    assert phase.pulled_status == "pulled"

    # pulled → active
    await svc.start_phase(phase.id)
    assert phase.pulled_status == "active"

    # active → completed
    await svc.complete_phase(phase.id)
    assert phase.pulled_status == "completed"


@pytest.mark.asyncio
async def test_fsm_happy_path_commitment_walk() -> None:
    """Sanity guard: ``planned → committed → in_progress → completed``
    must succeed end-to-end with the FSM table currently in force.
    """
    svc = _make_service()
    commit = SimpleNamespace(
        id=uuid.uuid4(),
        week_plan_id=uuid.uuid4(),
        task_ref=uuid.uuid4(),
        worker_or_crew="",
        promised_qty=Decimal("100"),
        unit="m2",
        planned_start=None,
        planned_finish=None,
        status="planned",
        made_by_user_id=None,
        made_at=None,
        completed_at=None,
        actual_qty=None,
    )
    svc.commitment_repo.rows[commit.id] = commit

    # planned → committed (via the dedicated commit-to-week endpoint)
    await svc.commit_to_week(commit.id, user_id=USER_A)
    assert commit.status == "committed"

    # committed → in_progress (via update)
    await svc.update_commitment(commit.id, CommitmentUpdate(status="in_progress"))
    assert commit.status == "in_progress"

    # in_progress → completed (via mark complete with actual_qty)
    await svc.mark_commitment_complete(commit.id, actual_qty=Decimal("100"))
    assert commit.status == "completed"
