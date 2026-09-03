# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The diary seeder must skip the projects a person wrote, not the ones it wrote.

The demo installer lays down a handful of empty diary headers of its own
before the module seeder runs. The guard used to ask "does this project hold
a diary", which those headers answered for every project on the estate, so
the ninety-day register with entries, weather, photos and signatures was
written, tested and never once inserted. Nobody noticed because the screen
was not empty: it showed the installer's headers.

The distinction being gated is therefore between three kinds of row that all
look alike from a count: the installer's placeholder, this seeder's own work,
and a diary a user typed. Only the last may stop a project, and only the
first may be removed.

Against a real PostgreSQL schema because (project_id, diary_date) is unique,
and the reason the placeholders have to go rather than be written around is
that the ninety-day window lands on top of them.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

pytestmark = pytest.mark.asyncio

#: Anchor for the synthetic window, so the dates a test writes are predictable.
_BASE = datetime(2026, 8, 14, 8, 0, tzinfo=UTC)


async def _make_project(session, name: str, demo_id: str | None) -> uuid.UUID:
    """One project, created the way the installer creates one."""
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    email = "diary-guard@reference.example"
    owner = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if owner is None:
        owner = User(email=email, hashed_password="not-a-real-hash", full_name="Reference owner")
        session.add(owner)
        await session.flush()

    project = Project(
        name=name,
        owner_id=owner.id,
        country_code="GB",
        currency="GBP",
        metadata_={"demo_id": demo_id} if demo_id else {},
    )
    session.add(project)
    await session.flush()
    return uuid.UUID(str(project.id))


async def _add_diary(session, project_id: uuid.UUID, day: int, marks: dict) -> uuid.UUID:
    """A diary header carrying whatever marks the caller wants to impersonate."""
    from app.modules.daily_diary.models import DailyDiary

    row_id = uuid.uuid4()
    session.add(
        DailyDiary(
            id=row_id,
            project_id=project_id,
            diary_date=(_BASE - timedelta(days=day)).date().isoformat(),
            labour_count=12,
            equipment_count=3,
            status="closed",
            notes="Placeholder header.",
            weather_summary={"conditions": "clear", "temp_c": 18},
            metadata_=marks,
        )
    )
    await session.flush()
    return row_id


async def _diary_count(session, project_id: uuid.UUID) -> int:
    from app.modules.daily_diary.models import DailyDiary

    return int(
        (
            await session.execute(
                select(func.count()).select_from(DailyDiary).where(DailyDiary.project_id == project_id)
            )
        ).scalar_one()
    )


async def test_the_installers_placeholders_do_not_pass_for_a_seeded_project(pg_session) -> None:
    """The headers the installer wrote must not read as "the seed already ran"."""
    from app.modules.daily_diary.seed import seed_daily_diary_demo

    project_id = await _make_project(pg_session, "Diary guard installer rows", "guard-installer")
    # Three days inside the window the seeder is about to write, which is also
    # where the unique constraint would bite if they were left standing.
    for day in (5, 20, 60):
        await _add_diary(pg_session, project_id, day, {"project_id": str(project_id), "demo_id": "guard-installer"})
    assert await _diary_count(pg_session, project_id) == 3

    counts = await seed_daily_diary_demo(pg_session, [project_id], base_date=_BASE)

    assert counts.get("diaries", 0) > 0, "the seeder skipped a project holding only installer headers"
    assert await _diary_count(pg_session, project_id) == 90


async def test_the_placeholders_are_gone_rather_than_mixed_in(pg_session) -> None:
    """Every surviving row is the seeder's own, so the register has one author."""
    from app.modules.daily_diary.models import DailyDiary
    from app.modules.daily_diary.seed import seed_daily_diary_demo

    project_id = await _make_project(pg_session, "Diary guard placeholder removal", "guard-removal")
    for day in (2, 30):
        await _add_diary(pg_session, project_id, day, {"project_id": str(project_id), "demo_id": "guard-removal"})

    await seed_daily_diary_demo(pg_session, [project_id], base_date=_BASE)

    marks = (
        (await pg_session.execute(select(DailyDiary.metadata_).where(DailyDiary.project_id == project_id)))
        .scalars()
        .all()
    )
    assert marks, "no diary was written"
    assert all((m or {}).get("seed") for m in marks), "an installer placeholder survived the seeding"


async def test_a_diary_nobody_marked_still_stops_the_project(pg_session) -> None:
    """A real entry is the case the guard exists for, and it must still win."""
    from app.modules.daily_diary.seed import seed_daily_diary_demo

    project_id = await _make_project(pg_session, "Diary guard user row", "guard-user")
    await _add_diary(pg_session, project_id, 3, {})

    counts = await seed_daily_diary_demo(pg_session, [project_id], base_date=_BASE)

    assert counts.get("diaries", 0) == 0, "the seeder wrote over a diary it did not author"
    assert await _diary_count(pg_session, project_id) == 1, "a user's diary was removed"


async def test_a_project_the_seeder_skips_keeps_its_headers(pg_session) -> None:
    """Skipping a project must not leave it emptier than it was found."""
    from app.modules.daily_diary.models import DailyDiary
    from app.modules.daily_diary.seed import seed_daily_diary_demo

    project_id = await _make_project(pg_session, "Diary guard mixed rows", "guard-mixed")
    await _add_diary(pg_session, project_id, 4, {})
    kept = await _add_diary(pg_session, project_id, 9, {"project_id": str(project_id), "demo_id": "guard-mixed"})

    await seed_daily_diary_demo(pg_session, [project_id], base_date=_BASE)

    survivors = (
        (await pg_session.execute(select(DailyDiary.id).where(DailyDiary.project_id == project_id))).scalars().all()
    )
    assert kept in {uuid.UUID(str(row)) for row in survivors}, "a skipped project lost the installer's header"
    assert len(survivors) == 2


async def test_a_second_run_changes_nothing(pg_session) -> None:
    """The boot backfill re-runs this, so the second pass has to be a no-op."""
    from app.modules.daily_diary.seed import seed_daily_diary_demo

    project_id = await _make_project(pg_session, "Diary guard idempotency", "guard-twice")
    await _add_diary(pg_session, project_id, 7, {"project_id": str(project_id), "demo_id": "guard-twice"})

    await seed_daily_diary_demo(pg_session, [project_id], base_date=_BASE)
    first = await _diary_count(pg_session, project_id)

    counts = await seed_daily_diary_demo(pg_session, [project_id], base_date=_BASE)

    assert counts.get("diaries", 0) == 0
    assert await _diary_count(pg_session, project_id) == first
