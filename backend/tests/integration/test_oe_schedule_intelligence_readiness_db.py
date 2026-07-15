# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""DB-backed integration tests for the E1 Readiness (Watch) workflow.

Drives ``service.evaluate_readiness`` / ``list_readiness`` end-to-end against a
real PostgreSQL database (the session template carries every module's schema),
so the readiness engine, its repository, the ``schedule_advanced`` constraint
feed, and the best-effort CPM-float join are all proven to integrate.

FK triggers are disabled (``disable_fks=True``) so we can stand up a minimal
``master_schedule → look_ahead → constraint`` chain (plus an optional
``schedule_activity`` for the float path) against synthetic project ids without
the full projects/users graph.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

# Import models so their tables are registered in Base.metadata.
import app.modules.schedule_intelligence.models  # noqa: F401
from app.modules.schedule.models import Activity, Schedule
from app.modules.schedule_advanced.models import Constraint, LookAheadPlan, MasterSchedule
from app.modules.schedule_intelligence import service
from app.modules.schedule_intelligence.enums import ReadinessClass
from tests._pg import transactional_session

TODAY = date(2026, 7, 15)


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session(disable_fks=True) as sess:
        yield sess


async def _make_look_ahead(session: AsyncSession, project_id: uuid.UUID) -> LookAheadPlan:
    """Create a master schedule + look-ahead owned by ``project_id``."""
    master = MasterSchedule(project_id=project_id, name="Master")
    session.add(master)
    await session.flush()
    la = LookAheadPlan(
        master_schedule_id=master.id,
        period_start=date(2026, 7, 13),
        period_end=date(2026, 8, 24),
    )
    session.add(la)
    await session.flush()
    return la


async def _add_constraint(
    session: AsyncSession,
    la_id: uuid.UUID,
    task_ref: uuid.UUID,
    status: str,
    *,
    ctype: str = "material",
    target: date | None = None,
) -> Constraint:
    c = Constraint(
        look_ahead_id=la_id,
        task_ref=task_ref,
        constraint_type=ctype,
        status=status,
        target_clear_date=target,
    )
    session.add(c)
    await session.flush()
    return c


# ─────────────────────────────────────────────────────────────────────────────
# Persist + classify through the real DB
# ─────────────────────────────────────────────────────────────────────────────
async def test_evaluate_persists_snapshot_and_classifies(session: AsyncSession) -> None:
    project_id = uuid.uuid4()
    la = await _make_look_ahead(session, project_id)

    ready_task = uuid.uuid4()
    blocked_task = uuid.uuid4()
    await _add_constraint(session, la.id, ready_task, "cleared")
    await _add_constraint(session, la.id, blocked_task, "cannot_clear", ctype="permit")

    run_id, rows = await service.evaluate_readiness(session, project_id, la.id, today=TODAY)

    assert run_id and len(run_id) == 64
    by_ref = {r.activity_ref: r for r in rows}
    assert by_ref[str(ready_task)].classification == ReadinessClass.READY.value
    assert by_ref[str(blocked_task)].classification == ReadinessClass.BLOCKED.value
    # Snapshot carries the run stamp + a confidence band, uniformly.
    assert all(r.evaluation_run_id == run_id for r in rows)
    assert all(r.confidence_band for r in rows)
    # The blocked row names its binding constraint (P4).
    assert by_ref[str(blocked_task)].binding_constraint_ref is not None


async def test_get_latest_run_returns_snapshot(session: AsyncSession) -> None:
    project_id = uuid.uuid4()
    la = await _make_look_ahead(session, project_id)
    await _add_constraint(session, la.id, uuid.uuid4(), "open")

    run_id, _ = await service.evaluate_readiness(session, project_id, la.id, today=TODAY)
    latest_id, latest_rows = await service.list_readiness(session, project_id, look_ahead_id=la.id)

    assert latest_id == run_id
    assert len(latest_rows) == 1
    assert latest_rows[0].classification == ReadinessClass.AT_RISK.value


async def test_reevaluate_identical_inputs_is_idempotent(session: AsyncSession) -> None:
    project_id = uuid.uuid4()
    la = await _make_look_ahead(session, project_id)
    await _add_constraint(session, la.id, uuid.uuid4(), "open")

    run1, rows1 = await service.evaluate_readiness(session, project_id, la.id, today=TODAY)
    run2, rows2 = await service.evaluate_readiness(session, project_id, la.id, today=TODAY)

    # Same digest, same rows — no duplicate snapshot written.
    assert run1 == run2
    assert {r.id for r in rows1} == {r.id for r in rows2}


async def test_changed_inputs_produce_a_new_run(session: AsyncSession) -> None:
    project_id = uuid.uuid4()
    la = await _make_look_ahead(session, project_id)
    task = uuid.uuid4()
    c = await _add_constraint(session, la.id, task, "open")

    run1, _ = await service.evaluate_readiness(session, project_id, la.id, today=TODAY)

    # Escalate the constraint → different canonical inputs → new run.
    c.status = "cannot_clear"
    await session.flush()
    run2, rows2 = await service.evaluate_readiness(session, project_id, la.id, today=TODAY)

    assert run1 != run2
    latest_id, latest_rows = await service.list_readiness(session, project_id, look_ahead_id=la.id)
    assert latest_id == run2
    assert latest_rows[0].classification == ReadinessClass.BLOCKED.value


async def test_foreign_look_ahead_is_404(session: AsyncSession) -> None:
    owner = uuid.uuid4()
    other = uuid.uuid4()
    la = await _make_look_ahead(session, owner)
    await _add_constraint(session, la.id, uuid.uuid4(), "open")

    with pytest.raises(HTTPException) as exc:
        await service.evaluate_readiness(session, other, la.id, today=TODAY)
    assert exc.value.status_code == 404


async def test_missing_look_ahead_is_404(session: AsyncSession) -> None:
    with pytest.raises(HTTPException) as exc:
        await service.evaluate_readiness(session, uuid.uuid4(), uuid.uuid4(), today=TODAY)
    assert exc.value.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# Best-effort CPM float join + float-burn across runs
# ─────────────────────────────────────────────────────────────────────────────
async def test_float_join_enriches_and_burn_detected_across_runs(session: AsyncSession) -> None:
    project_id = uuid.uuid4()
    la = await _make_look_ahead(session, project_id)

    # The constraint's task_ref doubles as a schedule-activity id (the MVP's
    # best-effort join point). First run: float 10, clean → READY.
    task = uuid.uuid4()
    sched = Schedule(project_id=project_id, name="S")
    session.add(sched)
    await session.flush()
    act = Activity(
        id=task,
        schedule_id=sched.id,
        name="Pour slab",
        start_date="2026-08-01",
        end_date="2026-08-05",
        total_float=10,
        is_critical=False,
    )
    session.add(act)
    await session.flush()
    await _add_constraint(session, la.id, task, "cleared")

    _run1, rows1 = await service.evaluate_readiness(session, project_id, la.id, today=TODAY)
    assert rows1[0].total_float_days == 10
    assert rows1[0].classification == ReadinessClass.READY.value
    assert rows1[0].float_burn_days is None  # first snapshot, no prior

    # Float burns down to 1 → thin float, and a burn of 9 vs the prior run.
    act.total_float = 1
    await session.flush()
    _run2, rows2 = await service.evaluate_readiness(session, project_id, la.id, today=TODAY)
    assert rows2[0].total_float_days == 1
    assert rows2[0].float_burn_days == 9
    assert rows2[0].classification == ReadinessClass.AT_RISK.value
