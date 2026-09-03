# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""The daily diary seeder must run at boot, and must run once per project.

The seeder was written complete and then never referenced by anything, so the
module shipped with an empty register on every install while the code that
would have filled it sat in the tree looking finished. Nothing could see it: an
unreferenced seeder imports cleanly, passes lint, and a module with no rows
renders exactly as correctly as a module whose seeder was never written.

Two failures are pinned here rather than one, because wiring it introduces the
second. The seeder had no duplicate guard at all, and the boot backfill re-runs
the list on every start, so a naive wiring adds ninety days of diaries per
project per restart. The guard has to be per project as well: a table-wide count
would be satisfied by the first project seeded, or by one diary a real user
wrote, and every remaining project would stay empty.
"""

from __future__ import annotations

import inspect
import uuid

import pytest
from sqlalchemy import func, select

from app.core import demo_enrichment
from app.modules.daily_diary.models import DailyDiary, DiaryEntry
from app.modules.daily_diary.seed import seed_daily_diary_demo
from app.modules.projects.models import Project
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio


async def _make_project(session, name: str) -> uuid.UUID:
    """A diary needs nothing but a project, and a project needs an owner."""
    owner_id = uuid.uuid4()
    session.add(
        User(
            id=owner_id,
            email=f"{name.lower()}@example.test",
            hashed_password="x",
            full_name=f"{name} Owner",
            role="manager",
            locale="en",
            is_active=True,
            metadata_={},
        )
    )
    # Flushed on its own: the project's owner FK has no ORM relationship behind
    # it, so nothing orders the two inserts for us.
    await session.flush()
    project_id = uuid.uuid4()
    session.add(
        Project(
            id=project_id,
            name=name,
            description="Daily diary seed fixture",
            currency="EUR",
            status="active",
            owner_id=owner_id,
            metadata_={},
        )
    )
    await session.flush()
    return project_id


async def _count_diaries(session, project_id: uuid.UUID) -> int:
    stmt = select(func.count()).select_from(DailyDiary).where(DailyDiary.project_id == project_id)
    return (await session.execute(stmt)).scalar_one()


async def _count_entries(session, project_id: uuid.UUID) -> int:
    """Entries hang off their diary, not off the project.

    Counted through the join rather than through a project column the table
    does not have, which is also the shape the screen reads them in: an entry
    reachable only by a diary that belongs to another project is not on this
    project's register however many rows the table holds.
    """
    stmt = (
        select(func.count())
        .select_from(DiaryEntry)
        .join(DailyDiary, DailyDiary.id == DiaryEntry.diary_id)
        .where(DailyDiary.project_id == project_id)
    )
    return (await session.execute(stmt)).scalar_one()


async def test_seed_fills_the_register(pg_session) -> None:
    project_id = await _make_project(pg_session, "Diary One")

    await seed_daily_diary_demo(pg_session, [project_id])
    await pg_session.flush()

    diaries = await _count_diaries(pg_session, project_id)
    entries = await _count_entries(pg_session, project_id)
    # Three is the floor a screenshot needs; the seeder claims ninety days, so
    # assert against the claim rather than against the floor.
    assert diaries >= 30, f"expected a filled diary register, got {diaries} days"
    assert entries > 0, "diaries with no entries render as an empty register"


async def test_second_run_does_not_double_the_register(pg_session) -> None:
    project_id = await _make_project(pg_session, "Diary Twice")

    await seed_daily_diary_demo(pg_session, [project_id])
    await pg_session.flush()
    first = await _count_diaries(pg_session, project_id)
    first_entries = await _count_entries(pg_session, project_id)

    await seed_daily_diary_demo(pg_session, [project_id])
    await pg_session.flush()

    assert await _count_diaries(pg_session, project_id) == first
    assert await _count_entries(pg_session, project_id) == first_entries


async def test_guard_is_per_project_not_table_wide(pg_session) -> None:
    """A second project must still get its diaries after the first has them.

    This is the assertion a table-wide row count fails. It would pass the two
    tests above and leave every project after the first with an empty screen.
    """
    seeded_first = await _make_project(pg_session, "Diary Early")
    await seed_daily_diary_demo(pg_session, [seeded_first])
    await pg_session.flush()
    before = await _count_diaries(pg_session, seeded_first)

    seeded_late = await _make_project(pg_session, "Diary Late")
    await seed_daily_diary_demo(pg_session, [seeded_first, seeded_late])
    await pg_session.flush()

    assert await _count_diaries(pg_session, seeded_first) == before, "the already-seeded project was seeded again"
    assert await _count_diaries(pg_session, seeded_late) > 0, "the empty project was skipped by a table-wide guard"


async def test_the_seeder_is_wired_into_the_boot_backfill() -> None:
    """An unreferenced seeder is the bug this module actually shipped with.

    Read from the source of the function that owns the list, because the list is
    built inside it from local imports and cannot be inspected as a value.
    """
    source = inspect.getsource(demo_enrichment.enrich_projects)
    assert "seed_daily_diary_demo" in source, "the daily diary seeder is not called from the boot backfill"
    assert '"daily_diary"' in source, "the seeder runs but is not named, so its counters log as an unknown module"
