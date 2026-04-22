"""Event publication tests for :mod:`app.modules.schedule.service`.

Scope:
    Verifies the canonical ``schedule.*`` events emitted by the mutation
    methods (activity create/update/delete) and the critical-path
    recomputation path. Each test subscribes an in-memory handler to the
    relevant event name, drives the service method, and asserts the
    payload carries at least ``activity_id``, ``schedule_id`` and
    ``project_id`` per the v2.4.0 event contract.

Pattern mirrors :file:`tests/unit/test_events_hooks.py`: we isolate a
fresh ``EventBus`` instance by patching ``event_bus`` on the service
module so the global singleton is untouched between tests.
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.events import EventBus
from app.database import Base
from app.modules.projects.models import Project
from app.modules.schedule.models import (
    Activity,
    Schedule,
    ScheduleRelationship,
    WorkOrder,
)
from app.modules.schedule.schemas import ActivityCreate, ActivityUpdate
from app.modules.schedule.service import ScheduleService
from app.modules.users.models import User

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncSession:
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


@pytest.fixture
def isolated_bus(monkeypatch):
    """Swap the service module's ``event_bus`` for a fresh, isolated bus.

    Keeps test handlers out of the global singleton so there's no cross-
    test pollution from other modules that subscribe at import time.
    """
    fresh = EventBus()

    from app.modules.schedule import service as schedule_service

    monkeypatch.setattr(schedule_service.event_bus, "publish", fresh.publish)
    # _safe_publish is a thin wrapper around event_bus.publish — the
    # monkeypatch above intercepts it at the right layer.
    yield fresh
    fresh.clear()


async def _seed_schedule(session: AsyncSession) -> tuple[Project, Schedule]:
    owner = User(
        email=f"{uuid.uuid4().hex}@test.local",
        hashed_password="x",
        full_name="Test Owner",
    )
    session.add(owner)
    await session.flush()

    project = Project(name="Event Test Project", owner_id=owner.id)
    session.add(project)
    await session.flush()

    sched = Schedule(
        project_id=project.id,
        name="Event Test Schedule",
        schedule_type="master",
        status="draft",
        start_date="2026-01-01",
        end_date="2026-12-31",
    )
    session.add(sched)
    await session.flush()
    return project, sched


# ── Activity lifecycle events ─────────────────────────────────────────────


class TestActivityLifecycleEvents:
    @pytest.mark.asyncio
    async def test_create_activity_emits_canonical_event(
        self, session, isolated_bus
    ):
        received: list[Any] = []

        @isolated_bus.on("schedule.activity.created")
        async def handler(event):
            received.append(event)

        project, sched = await _seed_schedule(session)
        service = ScheduleService(session)
        sched_id = sched.id
        project_id = project.id
        payload = ActivityCreate(
            schedule_id=sched_id,
            name="dig-footing",
            start_date="2026-02-01",
            end_date="2026-02-05",
            wbs_code="01.01",
        )

        await service.create_activity(payload)

        assert len(received) == 1
        event = received[0]
        assert event.name == "schedule.activity.created"
        assert event.data["schedule_id"] == str(sched_id)
        assert event.data["project_id"] == str(project_id)
        # activity_id should be a valid UUID string.
        uuid.UUID(event.data["activity_id"])

    @pytest.mark.asyncio
    async def test_update_activity_emits_canonical_event(
        self, session, isolated_bus
    ):
        received: list[Any] = []

        @isolated_bus.on("schedule.activity.updated")
        async def handler(event):
            received.append(event)

        project, sched = await _seed_schedule(session)
        service = ScheduleService(session)
        created = await service.create_activity(
            ActivityCreate(
                schedule_id=sched.id,
                name="pour-slab",
                start_date="2026-03-01",
                end_date="2026-03-10",
            )
        )
        activity_id = created.id
        # Snapshot ids before the service call — update_activity internally
        # triggers expire_all(), after which reading sched.id / project.id
        # on the test side would require another await.
        sched_id = sched.id
        project_id = project.id

        received.clear()  # drop the create event — we only assert on update here.

        await service.update_activity(
            activity_id,
            ActivityUpdate(progress_pct=50.0),
        )

        assert len(received) == 1
        event = received[0]
        assert event.name == "schedule.activity.updated"
        assert event.data["activity_id"] == str(activity_id)
        assert event.data["schedule_id"] == str(sched_id)
        assert event.data["project_id"] == str(project_id)

    @pytest.mark.asyncio
    async def test_delete_activity_emits_canonical_event(
        self, session, isolated_bus
    ):
        received: list[Any] = []

        @isolated_bus.on("schedule.activity.deleted")
        async def handler(event):
            received.append(event)

        project, sched = await _seed_schedule(session)
        service = ScheduleService(session)
        created = await service.create_activity(
            ActivityCreate(
                schedule_id=sched.id,
                name="finishes",
                start_date="2026-06-01",
                end_date="2026-06-15",
            )
        )
        activity_id = created.id
        # Snapshot before delete — the service's expire_all() would
        # otherwise force a re-await to read sched.id / project.id.
        sched_id = sched.id
        project_id = project.id

        await service.delete_activity(activity_id)

        assert len(received) == 1
        event = received[0]
        assert event.name == "schedule.activity.deleted"
        assert event.data["activity_id"] == str(activity_id)
        assert event.data["schedule_id"] == str(sched_id)
        assert event.data["project_id"] == str(project_id)


# ── Critical-path recompute event ─────────────────────────────────────────


class TestCriticalPathEvent:
    @pytest.mark.asyncio
    async def test_critical_path_recomputed_event(self, session, isolated_bus):
        received: list[Any] = []

        @isolated_bus.on("schedule.critical_path.recomputed")
        async def handler(event):
            received.append(event)

        project, sched = await _seed_schedule(session)
        service = ScheduleService(session)

        # Seed a trivial 2-activity chain so CPM has something to chew on.
        a1 = await service.create_activity(
            ActivityCreate(
                schedule_id=sched.id,
                name="A",
                start_date="2026-01-01",
                end_date="2026-01-02",
                duration_days=1,
            )
        )
        a2 = await service.create_activity(
            ActivityCreate(
                schedule_id=sched.id,
                name="B",
                start_date="2026-01-02",
                end_date="2026-01-03",
                duration_days=1,
            )
        )
        # Link A → B so the forward/backward pass has a real edge.
        session.add(
            ScheduleRelationship(
                schedule_id=sched.id,
                predecessor_id=a1.id,
                successor_id=a2.id,
                relationship_type="FS",
                lag_days=0,
            )
        )
        await session.flush()

        # Snapshot ids — the service calls expire_all() while persisting
        # CPM metadata, which would otherwise invalidate `sched` / project.
        sched_id = sched.id
        project_id = project.id

        await service.calculate_critical_path(sched_id)

        assert len(received) == 1
        event = received[0]
        assert event.name == "schedule.critical_path.recomputed"
        # Flat payload per the v2.4.0 event contract.
        assert event.data["schedule_id"] == str(sched_id)
        assert event.data["project_id"] == str(project_id)
        # activity_id is present (empty-string, since the recompute is
        # schedule-scoped) — but the key itself MUST exist for the
        # downstream JSON-serialisable contract.
        assert "activity_id" in event.data
