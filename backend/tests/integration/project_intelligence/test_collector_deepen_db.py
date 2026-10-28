# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠DB-backed tests for the project_intelligence collector deepenings.

Covers the wave that made the Estimation Dashboard's zero-data widgets honest:

* scope coverage - real leaf-position count plus a scope baseline resolved
  from (in order) the project metadata, the earliest BOQ version snapshot, or
  the live count; the ``baseline_source`` flag reports which won.
* schedule health - ``progress_pct`` (mean actual) and
  ``baseline_adherence_pct`` (share of activities on or ahead of the planned
  time-elapsed progress) computed from real activity rows.
* validation aliases - ``rules_passed`` / ``rules_total`` / ``errors`` mirror
  the canonical report fields so the widget renders the real last run.
* PostgreSQL-correctness fixes - the tasks (varchar ``due_date`` vs DATE) and
  assemblies (boolean ``is_template`` vs integer) queries no longer raise on
  PostgreSQL and silently zero their whole domain.

All seeds land in an isolated PostgreSQL database rolled back on teardown.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

# Import the sibling ORM modules so their tables exist in Base.metadata.
import app.modules.assemblies.models  # noqa: F401
import app.modules.boq.models  # noqa: F401
import app.modules.projects.models  # noqa: F401
import app.modules.schedule.models  # noqa: F401
import app.modules.tasks.models  # noqa: F401
from app.modules.assemblies.models import Assembly
from app.modules.boq.models import BOQ, BOQSnapshot, Position
from app.modules.project_intelligence.collector import (
    _collect_assemblies,
    _collect_boq,
    _collect_schedule,
    _collect_tasks,
    _collect_validation,
    _count_snapshot_positions,
    _resolve_scope_baseline,
)
from app.modules.projects.models import Project
from app.modules.schedule.models import Activity, Schedule
from app.modules.tasks.models import Task
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Isolated PostgreSQL session, FK triggers off, rolled back on teardown."""
    async with transactional_session(disable_fks=True) as sess:
        yield sess


async def _make_project(session: AsyncSession, **kwargs) -> Project:
    project = Project(name=kwargs.pop("name", "Scope Tower"), owner_id=uuid.uuid4(), currency="EUR", **kwargs)
    session.add(project)
    await session.flush()
    return project


async def _make_boq_with_positions(session: AsyncSession, project: Project, leaf_count: int) -> BOQ:
    """Create one BOQ with one section header plus ``leaf_count`` priced leaves."""
    boq = BOQ(project_id=project.id, name="Main BOQ")
    session.add(boq)
    await session.flush()
    section = Position(
        boq_id=boq.id,
        parent_id=None,
        ordinal="01",
        description="Section",
        unit="",
        quantity="0",
        unit_rate="0",
        total="0",
    )
    session.add(section)
    await session.flush()
    for i in range(leaf_count):
        session.add(
            Position(
                boq_id=boq.id,
                parent_id=section.id,
                ordinal=f"01.{i:03d}",
                description=f"Item {i}",
                unit="m3",
                quantity="10",
                unit_rate="100",
                total="1000",
            )
        )
    await session.flush()
    return boq


# ── _count_snapshot_positions (pure) ───────────────────────────────────────


def test_count_snapshot_positions_flat() -> None:
    assert _count_snapshot_positions({"positions": [{"a": 1}, {"a": 2}, {"a": 3}]}) == 3


def test_count_snapshot_positions_nested_counts_only_leaves() -> None:
    data = {"positions": [{"children": [{"x": 1}, {"x": 2}]}, {"y": 1}]}
    assert _count_snapshot_positions(data) == 3


def test_count_snapshot_positions_garbage_is_zero() -> None:
    assert _count_snapshot_positions("nope") == 0
    assert _count_snapshot_positions({"nope": []}) == 0
    assert _count_snapshot_positions({}) == 0


# ── scope baseline resolution ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scope_baseline_falls_back_to_current(session: AsyncSession) -> None:
    """No metadata, no snapshot → baseline is the live count (source=current)."""
    project = await _make_project(session)
    boq = await _make_boq_with_positions(session, project, leaf_count=5)
    baseline, source = await _resolve_scope_baseline(session, str(project.id), [str(boq.id)], 5)
    assert baseline == 5
    assert source == "current"


@pytest.mark.asyncio
async def test_scope_baseline_from_earliest_snapshot(session: AsyncSession) -> None:
    """An earlier snapshot with fewer lines becomes the baseline (drift detected)."""
    project = await _make_project(session)
    boq = await _make_boq_with_positions(session, project, leaf_count=8)
    # Earliest snapshot froze the scope at 5 leaves.
    session.add(
        BOQSnapshot(
            boq_id=boq.id,
            name="Frozen estimate",
            snapshot_data={"positions": [{"o": i} for i in range(5)]},
        )
    )
    await session.flush()
    baseline, source = await _resolve_scope_baseline(session, str(project.id), [str(boq.id)], 8)
    assert baseline == 5
    assert source == "snapshot"


@pytest.mark.asyncio
async def test_scope_baseline_metadata_wins_over_snapshot(session: AsyncSession) -> None:
    """An explicit metadata baseline is authoritative over the snapshot."""
    project = await _make_project(session)
    project.metadata_ = {"project_intelligence": {"scope_baseline_positions": 12}}
    boq = await _make_boq_with_positions(session, project, leaf_count=8)
    session.add(BOQSnapshot(boq_id=boq.id, name="Snap", snapshot_data={"positions": [{"o": i} for i in range(5)]}))
    await session.flush()
    baseline, source = await _resolve_scope_baseline(session, str(project.id), [str(boq.id)], 8)
    assert baseline == 12
    assert source == "metadata"


@pytest.mark.asyncio
async def test_scope_baseline_capture_persists_into_metadata(session: AsyncSession) -> None:
    """Replicates the POST /scope-baseline/ write: freeze the live leaf count
    into the project metadata JSONB, then prove the collector now resolves it
    from metadata (source flips current -> metadata, drift becomes observable).

    The HTTP route itself is covered by test_scope_baseline_endpoint.py; this
    test pins the persistence + re-resolution contract the route depends on
    without standing up the full ASGI stack.
    """
    project = await _make_project(session)
    boq = await _make_boq_with_positions(session, project, leaf_count=5)
    await session.flush()

    # Before capture: baseline derives from the live count.
    before = await _collect_boq(session, str(project.id))
    assert before.position_count == 5
    assert before.baseline_source == "current"

    # Capture (the same JSONB merge the router performs).
    meta = dict(project.metadata_ or {})
    pi_meta = dict(meta.get("project_intelligence") or {})
    pi_meta["scope_baseline_positions"] = before.position_count
    pi_meta["scope_baseline_captured_at"] = datetime.now(UTC).isoformat()
    meta["project_intelligence"] = pi_meta
    project.metadata_ = meta
    await session.flush()

    # Now the project's scope grows (scope creep) - two more priced leaves
    # under the existing section header.
    from sqlalchemy import text as _text

    section_id = (
        await session.execute(
            _text("SELECT id FROM oe_boq_position WHERE boq_id = :b AND parent_id IS NULL"),
            {"b": str(boq.id)},
        )
    ).scalar()
    for i in range(5, 7):
        session.add(
            Position(
                boq_id=boq.id,
                parent_id=section_id,
                ordinal=f"01.{i:03d}",
                description=f"Extra {i}",
                unit="m3",
                quantity="10",
                unit_rate="100",
                total="1000",
            )
        )
    await session.flush()

    after = await _collect_boq(session, str(project.id))
    # 5 original leaves + 2 new = 7 current; baseline frozen at 5.
    assert after.position_count == 7
    assert after.baseline_position_count == 5
    assert after.baseline_source == "metadata"
    # Drift the widget renders: +2 since baseline (scope creep).
    assert after.position_count - after.baseline_position_count == 2


@pytest.mark.asyncio
async def test_collect_boq_exposes_position_and_baseline(session: AsyncSession) -> None:
    """End-to-end: _collect_boq fills position_count + baseline + source."""
    project = await _make_project(session)
    boq = await _make_boq_with_positions(session, project, leaf_count=6)
    session.add(BOQSnapshot(boq_id=boq.id, name="Snap", snapshot_data={"positions": [{"o": i} for i in range(4)]}))
    await session.flush()
    state = await _collect_boq(session, str(project.id))
    assert state.exists is True
    assert state.position_count == 6
    assert state.baseline_position_count == 4
    assert state.baseline_source == "snapshot"


# ── schedule health ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_schedule_health_on_pace_reads_high_adherence(session: AsyncSession) -> None:
    """Activities at/ahead of planned time-elapsed progress → high adherence."""
    project = await _make_project(session)
    # Data date halfway through a Jan-Dec span → planned ~50%.
    schedule = Schedule(
        project_id=project.id,
        name="Master",
        start_date="2026-01-01",
        end_date="2026-12-31",
        data_date="2026-07-01",
    )
    session.add(schedule)
    await session.flush()
    session.add_all(
        [
            Activity(
                schedule_id=schedule.id,
                name="A",
                start_date="2026-01-01",
                end_date="2026-12-31",
                progress_pct="60",  # ahead of ~50% planned
                status="in_progress",
            ),
            Activity(
                schedule_id=schedule.id,
                name="B",
                start_date="2026-01-01",
                end_date="2026-12-31",
                progress_pct="55",  # ahead of plan
                status="in_progress",
            ),
        ]
    )
    await session.flush()
    state = await _collect_schedule(session, str(project.id))
    assert state.exists is True
    assert state.activities_count == 2
    assert state.progress_pct == pytest.approx(57.5, abs=0.1)
    assert state.baseline_adherence_pct == 100.0


@pytest.mark.asyncio
async def test_schedule_health_behind_reads_low_adherence(session: AsyncSession) -> None:
    """Activities far behind planned progress → low adherence."""
    project = await _make_project(session)
    schedule = Schedule(
        project_id=project.id,
        name="Master",
        start_date="2026-01-01",
        end_date="2026-12-31",
        data_date="2026-10-01",  # ~75% planned
    )
    session.add(schedule)
    await session.flush()
    session.add_all(
        [
            Activity(
                schedule_id=schedule.id,
                name="A",
                start_date="2026-01-01",
                end_date="2026-12-31",
                progress_pct="20",  # way behind ~75% planned
                status="in_progress",
            ),
            Activity(
                schedule_id=schedule.id,
                name="B",
                start_date="2026-01-01",
                end_date="2026-12-31",
                progress_pct="10",
                status="in_progress",
            ),
        ]
    )
    await session.flush()
    state = await _collect_schedule(session, str(project.id))
    assert state.progress_pct == pytest.approx(15.0, abs=0.1)
    assert state.baseline_adherence_pct == 0.0


# ── validation aliases ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_validation_aliases_mirror_canonical(session: AsyncSession) -> None:
    """rules_passed / rules_total / errors mirror the report fields."""
    from app.modules.validation.models import ValidationReport

    project = await _make_project(session)
    session.add(
        ValidationReport(
            project_id=project.id,
            target_type="boq",
            target_id=str(uuid.uuid4()),
            rule_set="din276",
            status="warnings",
            error_count=2,
            warning_count=3,
            passed_count=10,
            total_rules=15,
        )
    )
    await session.flush()
    state = await _collect_validation(session, str(project.id))
    assert state.passed_rules == 10
    assert state.rules_passed == 10
    assert state.total_rules == 15
    assert state.rules_total == 15
    assert state.critical_errors == 2
    assert state.errors == 2


# ── PostgreSQL-correctness fixes ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_collect_tasks_overdue_does_not_raise_on_pg(session: AsyncSession) -> None:
    """The overdue query (varchar due_date vs ISO string) works on PostgreSQL.

    Previously ``due_date < date('now')`` compared varchar to DATE and raised
    InvalidDatetimeFormat, silently zeroing the tasks domain.
    """
    project = await _make_project(session)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    session.add_all(
        [
            Task(project_id=project.id, task_type="task", title="Overdue open", status="open", due_date=yesterday),
            Task(project_id=project.id, task_type="task", title="Future open", status="open", due_date=tomorrow),
            Task(
                project_id=project.id,
                task_type="task",
                title="Overdue done",
                status="completed",
                due_date=yesterday,
            ),
            Task(project_id=project.id, task_type="task", title="No due", status="open", due_date=None),
        ]
    )
    await session.flush()
    state = await _collect_tasks(session, str(project.id))
    assert state.total_tasks == 4
    assert state.open_tasks == 3  # three not-completed
    # Only the open task whose due_date is in the past and not completed.
    assert state.overdue_tasks == 1


@pytest.mark.asyncio
async def test_collect_assemblies_boolean_template_does_not_raise_on_pg(session: AsyncSession) -> None:
    """The is_template predicate is boolean (not = 1) so it works on PostgreSQL.

    Previously ``is_template = 1`` raised "operator does not exist:
    boolean = integer" on PostgreSQL, silently zeroing the assemblies domain.
    """
    project = await _make_project(session)
    other = await _make_project(session, name="Other")
    session.add_all(
        [
            Assembly(code="A-1", name="Project wall", unit="m2", is_template=False, project_id=project.id),
            Assembly(code="A-2", name="Global template", unit="m2", is_template=True, project_id=None),
            # An assembly owned by another project that is NOT a template must
            # not leak into this project's counts.
            Assembly(code="A-3", name="Other wall", unit="m2", is_template=False, project_id=other.id),
        ]
    )
    await session.flush()
    state = await _collect_assemblies(session, str(project.id))
    # project wall (1) + global template (1) are visible; other-project wall is not.
    assert state.total_assemblies == 2
    assert state.project_assemblies == 1
    assert state.template_assemblies == 1


def test_collect_uses_utc_now_import_guard() -> None:
    """Sanity: the collector module imports cleanly with the datetime symbols."""
    # datetime/UTC are used by the schedule-health 'today' fallback path.
    assert datetime.now(UTC).tzinfo is not None
