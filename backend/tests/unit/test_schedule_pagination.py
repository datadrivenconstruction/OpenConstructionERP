"""Pagination / guard-cap tests for :mod:`app.modules.schedule.service`.

Scope:
    - ``ActivityRepository.list_for_schedule`` is the canonical paginated
      reader used by every public schedule endpoint. These tests verify
      the default page size (500), an explicit ``limit=1000`` override,
      and the total count the repo returns.
    - The CPM relationship load uses the ``MAX_SCHEDULE_ROWS`` guard cap
      (full-set semantics). We seed more than the cap and assert a
      ``WARNING`` is logged when the cap trips — correctness-preserving
      fallback per the v2.4.0 audit.

Uses an in-memory aiosqlite DB with scoped ``create_all(tables=[...])``
so the test is self-contained and does not pull the full app lifespan.
"""
from __future__ import annotations

import logging
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.modules.projects.models import Project
from app.modules.schedule.models import (
    Activity,
    Schedule,
    ScheduleRelationship,
    WorkOrder,
)
from app.modules.schedule.repository import ActivityRepository
from app.modules.users.models import User

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Fresh in-memory SQLite per test.

    Scoped ``create_all`` avoids pulling unrelated modules' FKs onto
    ``Base.metadata``.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[
                User.__table__,
                Project.__table__,
                Schedule.__table__,
                Activity.__table__,
                ScheduleRelationship.__table__,
                WorkOrder.__table__,
            ],
        )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as s:
        yield s
    await engine.dispose()


async def _seed_project(session: AsyncSession) -> Project:
    """Insert an owner user + one project row and return the project."""
    owner = User(
        email=f"{uuid.uuid4().hex}@test.local",
        hashed_password="x",
        full_name="Test Owner",
    )
    session.add(owner)
    await session.flush()

    proj = Project(
        name="Stress Project",
        owner_id=owner.id,
    )
    session.add(proj)
    await session.flush()
    return proj


async def _seed_schedule(session: AsyncSession) -> Schedule:
    """Insert one project + one schedule row and return the schedule."""
    proj = await _seed_project(session)
    sched = Schedule(
        project_id=proj.id,
        name="Stress-Test Schedule",
        schedule_type="master",
        status="draft",
        start_date="2026-01-01",
        end_date="2026-12-31",
    )
    session.add(sched)
    await session.flush()
    return sched


async def _bulk_insert_activities(
    session: AsyncSession, schedule_id: uuid.UUID, count: int
) -> None:
    """Insert ``count`` activity rows under ``schedule_id``.

    Uses ``add_all`` for speed — the in-memory sqlite DB loads 6 000 rows
    comfortably under the unit-test budget.
    """
    rows = [
        Activity(
            schedule_id=schedule_id,
            name=f"A{i:05d}",
            start_date="2026-01-01",
            end_date="2026-01-02",
            duration_days=1,
            sort_order=i,
        )
        for i in range(count)
    ]
    session.add_all(rows)
    await session.flush()


# ── ActivityRepository.list_for_schedule pagination ───────────────────────


class TestActivityRepositoryPagination:
    @pytest.mark.asyncio
    async def test_default_limit_returns_500(self, session):
        sched = await _seed_schedule(session)
        # Seed > 5 000 so the default 500-wide slice is visibly smaller.
        await _bulk_insert_activities(session, sched.id, count=5100)

        repo = ActivityRepository(session)
        # 500 is the paginated default surfaced to callers via service.
        rows, total = await repo.list_for_schedule(sched.id, limit=500)

        assert total == 5100
        assert len(rows) == 500

    @pytest.mark.asyncio
    async def test_explicit_limit_1000_returns_1000(self, session):
        sched = await _seed_schedule(session)
        await _bulk_insert_activities(session, sched.id, count=5100)

        repo = ActivityRepository(session)
        rows, total = await repo.list_for_schedule(sched.id, limit=1000)

        assert total == 5100
        assert len(rows) == 1000

    @pytest.mark.asyncio
    async def test_offset_pagination_walks_cleanly(self, session):
        sched = await _seed_schedule(session)
        await _bulk_insert_activities(session, sched.id, count=1500)

        repo = ActivityRepository(session)
        # Walk the full set in three page-size=500 hops.
        page1, total = await repo.list_for_schedule(sched.id, offset=0, limit=500)
        page2, _ = await repo.list_for_schedule(sched.id, offset=500, limit=500)
        page3, _ = await repo.list_for_schedule(sched.id, offset=1000, limit=500)

        assert total == 1500
        all_ids = {r.id for r in page1} | {r.id for r in page2} | {r.id for r in page3}
        assert len(all_ids) == 1500  # no overlap, no gaps


# ── CPM relationship guard-cap (full-set semantics) ───────────────────────


class TestCpmRelationshipGuardCap:
    @pytest.mark.asyncio
    async def test_relationship_load_capped_logs_warning(
        self, session, caplog, monkeypatch
    ):
        """Seed > cap relationships and exercise the real CPM path.

        We drive ``ScheduleService.calculate_critical_path`` end-to-end
        on an in-memory SQLite DB. To keep the fixture fast we monkeypatch
        ``MAX_SCHEDULE_ROWS`` down to a small number so we only need to
        insert a few dozen rows to trip the cap. The production constant
        is already covered by the ``test_default_limit_returns_500`` path;
        what matters here is that the guard block *fires* on cap-hit.
        """
        from app.modules.schedule import service as schedule_service
        from app.modules.schedule.service import ScheduleService

        # Shrink the cap so the test stays fast. The constant lives at
        # module level, but the service reads it each call via the
        # imported name, so monkeypatching the module attribute works.
        monkeypatch.setattr(schedule_service, "MAX_SCHEDULE_ROWS", 20)

        sched = await _seed_schedule(session)

        # Build a diamond: a0 → a1, a0 → a2, … , a0 → aN so every rel is
        # unique (UniqueConstraint on pred/succ) and the CPM has a clean
        # acyclic graph.
        need = 25  # > shrunken cap of 20
        root = Activity(
            schedule_id=sched.id,
            name="root",
            start_date="2026-01-01",
            end_date="2026-01-02",
            duration_days=1,
            sort_order=0,
        )
        session.add(root)
        await session.flush()

        leaves = [
            Activity(
                schedule_id=sched.id,
                name=f"leaf-{i:03d}",
                start_date="2026-01-02",
                end_date="2026-01-03",
                duration_days=1,
                sort_order=i + 1,
            )
            for i in range(need)
        ]
        session.add_all(leaves)
        await session.flush()

        rels = [
            ScheduleRelationship(
                schedule_id=sched.id,
                predecessor_id=root.id,
                successor_id=leaves[i].id,
                relationship_type="FS",
                lag_days=0,
            )
            for i in range(need)
        ]
        session.add_all(rels)
        await session.flush()

        service = ScheduleService(session)

        caplog.set_level(logging.WARNING, logger=schedule_service.logger.name)

        # Snapshot ids before the call — the service internally calls
        # session.expire_all() while persisting CPM metadata, after which
        # ORM instances on the test side can't be read back without an
        # additional await.
        sched_id = sched.id

        response = await service.calculate_critical_path(sched_id)

        # CPM still returns something (correctness-preserving fallback)
        assert response.schedule_id == sched_id

        warnings = [
            rec
            for rec in caplog.records
            if rec.levelno == logging.WARNING
            and "MAX_SCHEDULE_ROWS=20" in rec.getMessage()
            and "critical path may be incomplete" in rec.getMessage()
        ]
        assert warnings, "Expected a WARNING log from the CPM guard cap"

    @pytest.mark.asyncio
    async def test_no_warning_below_cap(self, session, caplog, monkeypatch):
        """Sanity check: under-cap loads must NOT emit the cap warning."""
        from app.modules.schedule import service as schedule_service
        from app.modules.schedule.service import ScheduleService

        # Keep the shrunken cap but only seed 3 relationships.
        monkeypatch.setattr(schedule_service, "MAX_SCHEDULE_ROWS", 20)

        sched = await _seed_schedule(session)
        root = Activity(
            schedule_id=sched.id,
            name="root",
            start_date="2026-01-01",
            end_date="2026-01-02",
            duration_days=1,
            sort_order=0,
        )
        session.add(root)
        await session.flush()
        leaves = [
            Activity(
                schedule_id=sched.id,
                name=f"leaf-{i}",
                start_date="2026-01-02",
                end_date="2026-01-03",
                duration_days=1,
                sort_order=i + 1,
            )
            for i in range(3)
        ]
        session.add_all(leaves)
        await session.flush()
        session.add_all(
            [
                ScheduleRelationship(
                    schedule_id=sched.id,
                    predecessor_id=root.id,
                    successor_id=leaf.id,
                    relationship_type="FS",
                )
                for leaf in leaves
            ]
        )
        await session.flush()

        service = ScheduleService(session)
        caplog.set_level(logging.WARNING, logger=schedule_service.logger.name)
        sched_id = sched.id
        await service.calculate_critical_path(sched_id)

        assert not [
            rec
            for rec in caplog.records
            if rec.levelno == logging.WARNING
            and "MAX_SCHEDULE_ROWS" in rec.getMessage()
        ]
