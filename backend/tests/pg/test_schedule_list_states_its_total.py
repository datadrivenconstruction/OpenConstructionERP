"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠PG: the schedule list endpoints report the whole set, not just the page.

Both reads were capped and silent. ``GET /schedules/`` returned at most 50
rows and ``GET /schedules/{id}/activities/`` at most 1000, each as a bare
JSON array, so a client had no way to distinguish a complete list from a
truncated one. The repository was already running a ``count(*)`` to build
the page and the router discarded it.

The assertion that matters is ``total > len(items)``. Asserting only that a
``total`` field exists would pass against ``total=len(items)``, which is the
shape that states a wrong number out loud rather than staying quiet - the
census found three of those elsewhere in the tree, so it is not theoretical.

Real PostgreSQL because the count is a SQL aggregate over the filtered set,
and an in-memory stub would let the page length and the total agree by
construction.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from app.modules.projects.models import Project
from app.modules.schedule.models import Activity, Schedule
from app.modules.schedule.repository import ActivityRepository, ScheduleRepository
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio


# ── Seeding ────────────────────────────────────────────────────────────────


async def _seed_project(session) -> Project:
    """Insert an owner and a project to hang schedules from."""
    owner = User(email=f"total-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    session.add(owner)
    await session.flush()
    project = Project(name="Total project", owner_id=owner.id, currency="EUR")
    session.add(project)
    await session.flush()
    return project


async def _add_schedules(session, project: Project, count: int) -> None:
    for i in range(count):
        session.add(Schedule(project_id=project.id, name=f"Programme {i:03d}", status="active"))
    await session.flush()


async def _add_activities(session, schedule: Schedule, count: int) -> None:
    """Insert ``count`` activities, one calendar day each, back to back.

    The dates are required by the model, not decoration: a count over rows
    that could not exist would prove nothing about the count over rows that
    can.
    """
    start = date(2026, 3, 1)
    for i in range(count):
        day = start + timedelta(days=i)
        session.add(
            Activity(
                schedule_id=schedule.id,
                name=f"Activity {i:04d}",
                start_date=day.isoformat(),
                end_date=day.isoformat(),
                sort_order=i,
            )
        )
    await session.flush()


# ── Schedules ──────────────────────────────────────────────────────────────


async def test_schedule_page_reports_the_count_of_the_whole_set(pg_session) -> None:
    """A page of 10 out of 25 must say 25, not 10.

    This is the assertion the old bare-array response could not satisfy at
    all, and that a ``total=len(items)`` implementation would fail.
    """
    project = await _seed_project(pg_session)
    await _add_schedules(pg_session, project, 25)

    repo = ScheduleRepository(pg_session)
    items, total = await repo.list_for_project(project.id, offset=0, limit=10)

    assert len(items) == 10
    assert total == 25
    assert total > len(items), "a truncated page must be able to report that it is truncated"


async def test_schedule_total_is_stable_across_pages(pg_session) -> None:
    """The total describes the set, so it must not move as the caller walks it."""
    project = await _seed_project(pg_session)
    await _add_schedules(pg_session, project, 25)

    repo = ScheduleRepository(pg_session)
    totals = []
    for offset in (0, 10, 20):
        _, total = await repo.list_for_project(project.id, offset=offset, limit=10)
        totals.append(total)

    assert totals == [25, 25, 25]


async def test_schedule_total_counts_only_the_filtered_project(pg_session) -> None:
    """A count over the unfiltered table would pass the tests above and still lie."""
    mine = await _seed_project(pg_session)
    theirs = await _seed_project(pg_session)
    await _add_schedules(pg_session, mine, 7)
    await _add_schedules(pg_session, theirs, 11)

    repo = ScheduleRepository(pg_session)
    _, total = await repo.list_for_project(mine.id, offset=0, limit=50)

    assert total == 7


# ── Activities ─────────────────────────────────────────────────────────────


async def test_activity_page_reports_the_count_of_the_whole_schedule(pg_session) -> None:
    """The activity cap is 1000, so the truncation only shows on a big programme."""
    project = await _seed_project(pg_session)
    schedule = Schedule(project_id=project.id, name="Big programme", status="active")
    pg_session.add(schedule)
    await pg_session.flush()
    await _add_activities(pg_session, schedule, 120)

    repo = ActivityRepository(pg_session)
    items, total = await repo.list_for_schedule(schedule.id, offset=0, limit=50)

    assert len(items) == 50
    assert total == 120
    assert total > len(items)


async def test_activity_total_counts_only_this_schedule(pg_session) -> None:
    """Two schedules in one project must not pool their activity counts."""
    project = await _seed_project(pg_session)
    first = Schedule(project_id=project.id, name="First", status="active")
    second = Schedule(project_id=project.id, name="Second", status="active")
    pg_session.add_all([first, second])
    await pg_session.flush()
    await _add_activities(pg_session, first, 9)
    await _add_activities(pg_session, second, 4)

    repo = ActivityRepository(pg_session)
    _, total = await repo.list_for_schedule(first.id, offset=0, limit=1000)

    assert total == 9
