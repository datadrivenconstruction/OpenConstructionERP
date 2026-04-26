"""Unit tests for the 4D snapshot service (Section 6 / FR-6.5).

Goal: lock down the per-task status derivation
(``not_started``/``in_progress``/``completed``/``delayed``/``ahead_of_schedule``)
plus the multi-task aggregation contract.

Tests use an isolated temp SQLite per test (see
``feedback_test_isolation.md``) so we never touch ``backend/openestimate.db``.
The EAC predicate resolver is stubbed to a deterministic in-memory map.
"""

from __future__ import annotations

import tempfile
import uuid
from datetime import date
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.modules.schedule.models import (
    Activity,
    EacScheduleLink,
    Schedule,
)
from app.modules.schedule.service_4d import (
    STATUS_AHEAD,
    STATUS_COMPLETED,
    STATUS_DELAYED,
    STATUS_IN_PROGRESS,
    STATUS_NOT_STARTED,
    EacPredicateResolver,
    ScheduleSnapshotService,
    _derive_task_status,
)


PROJECT_ID = uuid.uuid4()


def _register_minimal_models() -> None:
    """Register the minimum set of model modules needed for the 4D tables.

    Keep this list narrow — pulling in every module bloats the test schema
    with irrelevant tables. We import only the FK-target chain rooted at
    ``oe_schedule_schedule.project_id``.
    """
    import app.modules.users.models  # noqa: F401  — projects.owner_id FK
    import app.modules.projects.models  # noqa: F401  — schedule.project_id FK
    import app.modules.schedule.models  # noqa: F401  — registers 4D tables


async def _seed_project(session: AsyncSession, project_id: uuid.UUID) -> None:
    """Insert a minimal Project + owner User row so the FK chain is satisfied."""
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner = User(
        email=f"owner-{uuid.uuid4().hex[:6]}@test.io",
        hashed_password="x",
        full_name="Owner",
    )
    session.add(owner)
    await session.flush()

    project = Project(id=project_id, name="4D Test Project", owner_id=owner.id)
    session.add(project)
    await session.flush()


@pytest_asyncio.fixture
async def session():
    """Per-test isolated SQLite — never the production DB."""
    tmp_db = Path(tempfile.mkdtemp()) / "snapshot.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)

    _register_minimal_models()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        await _seed_project(s, PROJECT_ID)
        await s.commit()
        yield s

    await engine.dispose()
    try:
        tmp_db.unlink(missing_ok=True)
        tmp_db.parent.rmdir()
    except OSError:
        pass


class _FixedResolver:
    """Stub resolver that returns pre-set element IDs per (rule_id, predicate)."""

    def __init__(self, mapping: dict[tuple[str | None, str | None], list[str]]):
        self._mapping = mapping

    async def resolve(
        self,
        *,
        rule_id: uuid.UUID | None,
        predicate_json: dict | None,
        model_version_id: uuid.UUID | None,
    ) -> list[str]:
        rid = str(rule_id) if rule_id else None
        # Hash the predicate by its sorted-keys repr.
        key_p = repr(sorted(predicate_json.items())) if predicate_json else None
        return list(self._mapping.get((rid, key_p), []))


def _make_activity(
    *,
    schedule_id: uuid.UUID,
    name: str,
    start: str,
    end: str,
    progress: float = 0.0,
    duration_days: int | None = None,
    wbs_code: str = "1",
) -> Activity:
    return Activity(
        schedule_id=schedule_id,
        name=name,
        wbs_code=wbs_code,
        start_date=start,
        end_date=end,
        duration_days=duration_days
        if duration_days is not None
        else (date.fromisoformat(end) - date.fromisoformat(start)).days,
        progress_pct=str(progress),
    )


# ── Pure status derivation tests (no DB) ──────────────────────────────────


def test_status_not_started_when_in_future():
    activity = _make_activity(
        schedule_id=uuid.uuid4(),
        name="Future task",
        start="2027-01-01",
        end="2027-01-31",
        progress=0.0,
    )
    assert _derive_task_status(activity, date(2026, 12, 1)) == STATUS_NOT_STARTED


def test_status_in_progress_when_spanning_as_of():
    activity = _make_activity(
        schedule_id=uuid.uuid4(),
        name="In-flight",
        start="2026-04-01",
        end="2026-05-31",
        progress=42.0,
    )
    assert _derive_task_status(activity, date(2026, 4, 20)) == STATUS_IN_PROGRESS


def test_status_completed_when_past_with_full_progress():
    activity = _make_activity(
        schedule_id=uuid.uuid4(),
        name="Done",
        start="2026-01-01",
        end="2026-01-31",
        progress=100.0,
    )
    # Snapshot taken after end_date → completed.
    assert _derive_task_status(activity, date(2026, 4, 1)) == STATUS_COMPLETED


def test_status_delayed_when_past_end_with_partial_progress():
    activity = _make_activity(
        schedule_id=uuid.uuid4(),
        name="Slipped",
        start="2026-01-01",
        end="2026-02-28",
        progress=50.0,
    )
    # Past end_date but progress < 100 → delayed.
    assert _derive_task_status(activity, date(2026, 4, 1)) == STATUS_DELAYED


def test_status_ahead_of_schedule_when_done_before_planned_end():
    activity = _make_activity(
        schedule_id=uuid.uuid4(),
        name="Early bird",
        start="2026-04-01",
        end="2026-12-31",
        progress=100.0,
    )
    # Hit 100% but as_of is earlier than planned end_date → ahead.
    assert _derive_task_status(activity, date(2026, 4, 20)) == STATUS_AHEAD


# ── Multi-task aggregation via the snapshot service ──────────────────────


@pytest.mark.asyncio
async def test_snapshot_aggregates_multiple_tasks_with_priority(session: AsyncSession):
    schedule = Schedule(project_id=PROJECT_ID, name="MultiAgg")
    session.add(schedule)
    await session.flush()

    a1 = _make_activity(
        schedule_id=schedule.id,
        name="Done early",
        start="2026-04-01",
        end="2026-04-10",
        progress=100.0,
    )
    a2 = _make_activity(
        schedule_id=schedule.id,
        name="Slipped",
        start="2026-01-01",
        end="2026-02-01",
        progress=20.0,
    )
    a3 = _make_activity(
        schedule_id=schedule.id,
        name="Future",
        start="2027-01-01",
        end="2027-02-01",
        progress=0.0,
    )
    session.add_all([a1, a2, a3])
    await session.flush()

    # Three links — overlapping element sets so priority logic kicks in.
    pred_a = {"selector": "kind:walls"}
    pred_b = {"selector": "kind:slabs"}
    pred_c = {"selector": "kind:doors"}

    link1 = EacScheduleLink(task_id=a1.id, predicate_json=pred_a, mode="partial_match")
    link2 = EacScheduleLink(task_id=a2.id, predicate_json=pred_b, mode="partial_match")
    link3 = EacScheduleLink(task_id=a3.id, predicate_json=pred_c, mode="partial_match")
    session.add_all([link1, link2, link3])
    await session.flush()

    resolver = _FixedResolver(
        {
            (None, repr(sorted(pred_a.items()))): ["E1", "E2"],
            # E2 also linked to delayed task → delayed should win.
            (None, repr(sorted(pred_b.items()))): ["E2", "E3"],
            (None, repr(sorted(pred_c.items()))): ["E4"],
        }
    )

    service = ScheduleSnapshotService(session, resolver=resolver)
    statuses = await service.snapshot(
        schedule.id, date(2026, 4, 5), model_version_id=None
    )

    # Task1 hit 100% but the snapshot is taken before its planned end_date
    # (as_of=2026-04-05 < end=2026-04-10) → ahead_of_schedule per FR-6.5.
    assert statuses["E1"] == STATUS_AHEAD
    # E2 is reachable from both task1 (ahead) and task2 (delayed).
    # Delayed has higher priority — E2 must end up delayed.
    assert statuses["E2"] == STATUS_DELAYED
    assert statuses["E3"] == STATUS_DELAYED
    assert statuses["E4"] == STATUS_NOT_STARTED


@pytest.mark.asyncio
async def test_snapshot_skips_excluded_links(session: AsyncSession):
    schedule = Schedule(project_id=PROJECT_ID, name="Excluded")
    session.add(schedule)
    await session.flush()

    activity = _make_activity(
        schedule_id=schedule.id,
        name="Some task",
        start="2026-01-01",
        end="2026-12-31",
        progress=20.0,
    )
    session.add(activity)
    await session.flush()

    pred = {"selector": "anything"}
    excluded = EacScheduleLink(
        task_id=activity.id, predicate_json=pred, mode="excluded"
    )
    session.add(excluded)
    await session.flush()

    resolver = _FixedResolver(
        {(None, repr(sorted(pred.items()))): ["E_should_not_appear"]}
    )
    service = ScheduleSnapshotService(session, resolver=resolver)
    statuses = await service.snapshot(
        schedule.id, date(2026, 4, 1), model_version_id=None
    )

    assert statuses == {}


@pytest.mark.asyncio
async def test_snapshot_empty_for_unknown_schedule(session: AsyncSession):
    service = ScheduleSnapshotService(session, resolver=_FixedResolver({}))
    statuses = await service.snapshot(
        uuid.uuid4(), date(2026, 4, 1), model_version_id=None
    )
    assert statuses == {}
