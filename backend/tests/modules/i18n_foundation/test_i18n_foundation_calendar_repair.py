# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠``v3303`` run against a real database, not just its decision rule.

The seed file fix reaches new installs only - ``seed.py`` returns early once
the table has rows - so the Saudi calendar shipped as ``[0, 1, 2, 3, 4]`` stays
in every database that has already seeded. ``v3303_work_calendar_iso_weekdays``
is the repair, and ``tests/unit/test_work_calendar_weekdays_are_iso.py`` proves
its decision rule shape by shape without a database.

This is the other half: the statement actually running. A repair whose rule is
right and whose UPDATE writes the text ``"[7, 1, 2, 3, 4]"`` into a JSON column,
or fails to bind at all, is still a broken repair, and no amount of testing the
rule would say so.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.i18n_foundation.models import WorkCalendar
from tests.modules.i18n_foundation.conftest import make_calendar

_MIGRATION = Path(__file__).resolve().parents[3] / "alembic" / "versions" / "v3303_work_calendar_iso_weekdays.py"

# A year no seed data uses, so these rows cannot collide with a seeded
# (country_code, year) - the pair is unique - whatever the test database was
# populated with before this test ran.
_YEAR = "2044"


def _migration() -> Any:
    """Side-load the revision; ``alembic/versions`` is not a package."""
    spec = importlib.util.spec_from_file_location("v3303_work_calendar_iso_weekdays", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _run_repair(session: AsyncSession) -> tuple[int, int, list[str]]:
    """Run the revision's repair over the session's own connection."""
    module = _migration()
    return await session.run_sync(lambda sync_session: module._repair_rows(sync_session.connection()))


async def _stored(session: AsyncSession, country_code: str) -> list[int]:
    """Read a calendar back from the database, ignoring anything cached."""
    session.expire_all()
    result = await session.execute(
        select(WorkCalendar).where(WorkCalendar.country_code == country_code, WorkCalendar.year == _YEAR)
    )
    return result.scalar_one().work_days


async def test_the_seeded_saudi_week_becomes_sunday_to_thursday(session: AsyncSession) -> None:
    """The row an existing install still carries is rewritten in place."""
    await make_calendar(session, country_code="SA", year=_YEAR, work_days=[0, 1, 2, 3, 4])

    _, repaired, _ = await _run_repair(session)

    assert repaired >= 1
    stored = await _stored(session, "SA")
    # A list, not the text of one: this is the JSON round-trip the rule tests
    # cannot see.
    assert stored == [7, 1, 2, 3, 4]
    assert all(isinstance(day, int) for day in stored)


async def test_a_correct_calendar_is_left_exactly_as_it_was(session: AsyncSession) -> None:
    """A deployment that edited its calendars keeps what it edited them to."""
    await make_calendar(session, country_code="DE", year=_YEAR, work_days=[1, 2, 3, 4, 5])
    await make_calendar(session, country_code="AE", year=_YEAR, work_days=[7, 1, 2, 3, 4])

    await _run_repair(session)

    assert await _stored(session, "DE") == [1, 2, 3, 4, 5]
    assert await _stored(session, "AE") == [7, 1, 2, 3, 4]


async def test_another_country_with_the_same_broken_week_is_reported_not_rewritten(
    session: AsyncSession,
) -> None:
    """Only the shipped row is repaired; anything else is named for a human.

    Two zero-based conventions are live in this platform, so ``[0, 1, 2, 3, 4]``
    on a row we never shipped does not say which week was meant.
    """
    await make_calendar(session, country_code="QA", year=_YEAR, work_days=[0, 1, 2, 3, 4])

    _, _, warnings = await _run_repair(session)

    assert any(warning.startswith("QA:") for warning in warnings), warnings
    assert await _stored(session, "QA") == [0, 1, 2, 3, 4]


async def test_running_the_upgrade_twice_repairs_nothing_the_second_time(session: AsyncSession) -> None:
    """Idempotent on the data itself, so a re-run cannot double-apply.

    The predicate is the stored value, not a version marker, which is what
    makes a partially migrated database safe to run this against.
    """
    await make_calendar(session, country_code="SA", year=_YEAR, work_days=[0, 1, 2, 3, 4])

    _, first, _ = await _run_repair(session)
    inspected, second, _ = await _run_repair(session)

    assert first >= 1
    assert second == 0
    assert inspected >= 1, "the repair inspected no rows at all, so it proved nothing"
    assert await _stored(session, "SA") == [7, 1, 2, 3, 4]
