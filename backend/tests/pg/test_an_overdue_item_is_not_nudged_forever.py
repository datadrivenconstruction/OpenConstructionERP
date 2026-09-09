# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A due date that has passed stays passed, so the nudge needs a ceiling.

The sweep silenced an item only for :data:`sweeper.RENOTIFY_WINDOW_HOURS`
after its last nudge. That bounds the rate and not the total: an item nobody
resolves qualifies again on the next sweep, and the next, for as long as the
process runs. On the public demo, where the seeded items are overdue on
purpose and no one ever closes them, it sent the same reminders twice a day
until the mail host disabled outbound sending for the whole account.

The window was covered by nothing. ``test_deadlines_sweep_isolation.py``
exercises the same entry point four times and asserts only recipient routing
and savepoint isolation, so the sweep could have nudged once or a thousand
times and every one of those tests would still have passed.

**Time has to be moved on the rows, not on the caller.** ``sweep_overdue``
takes a ``now``, but ``Notification.created_at`` is filled by the database
clock, so passing a date months in the past makes every stored notification
newer than the cutoff and the sweep silences itself for the wrong reason. A
first draft of this test did exactly that and reported one nudge where it
expected three, which reads as the ceiling working and is nothing of the kind.
The sweeps here therefore run at wall-clock time and a day is simulated by
ageing the rows.

Both halves are pinned, because a ceiling with no floor is as wrong as a floor
with no ceiling: the early nudges must go out, and the ones past the ceiling
must not.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.modules.deadlines import sweeper
from app.modules.notifications.models import Notification
from app.modules.projects.models import Project
from app.modules.punchlist.models import PunchItem
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

_NOW = datetime.now(UTC)
_DUE = _NOW - timedelta(days=14)

# Comfortably past the window, so ageing the rows by this much makes the next
# sweep a fresh one as far as the rate limit is concerned and only the ceiling
# can stop it.
_A_DAY_LATER = timedelta(hours=sweeper.RENOTIFY_WINDOW_HOURS + 4)


async def _a_project_with_one_overdue_item(session) -> None:
    owner = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex[:12]}@example.com",
        hashed_password="x",
        full_name="Site Engineer",
    )
    session.add(owner)
    await session.flush()
    project = Project(name="Overdue forever", owner_id=owner.id)
    session.add(project)
    await session.flush()
    session.add(
        PunchItem(
            id=uuid.uuid4(),
            project_id=project.id,
            title="Nobody ever closes this",
            description="",
            status="open",
            due_date=_DUE,
            assigned_to=str(owner.id),
        )
    )
    await session.flush()


async def _nudge_count(session) -> int:
    rows = await session.execute(select(Notification).where(Notification.notification_type == sweeper.OVERDUE_TYPE))
    return len(list(rows.scalars().all()))


async def _age_every_nudge_by_a_day(session) -> None:
    """Move the stored nudges back past the window, the way a day would."""
    await session.execute(
        update(Notification)
        .where(Notification.notification_type == sweeper.OVERDUE_TYPE)
        .values(created_at=Notification.created_at - _A_DAY_LATER)
    )


async def test_the_same_overdue_item_stops_being_nudged_after_the_ceiling(pg_session):
    """Ten days of sweeps must not produce ten nudges for one unresolved item."""
    await _a_project_with_one_overdue_item(pg_session)

    for _ in range(10):
        await sweeper.sweep_overdue(pg_session, now=_NOW)
        await _age_every_nudge_by_a_day(pg_session)

    assert await _nudge_count(pg_session) == sweeper.MAX_OVERDUE_NUDGES, (
        "an item nobody resolves was nudged more times than the ceiling allows; "
        "this is the shape that mailed the demo accounts twice a day"
    )


async def test_the_early_nudges_still_go_out(pg_session):
    """The ceiling must not be mistaken for silence.

    Asserted separately because a guard that refuses everything satisfies the
    ceiling test on its own, and from a count alone the two failures look the
    same.
    """
    await _a_project_with_one_overdue_item(pg_session)

    await sweeper.sweep_overdue(pg_session, now=_NOW)
    assert await _nudge_count(pg_session) == 1

    await _age_every_nudge_by_a_day(pg_session)
    await sweeper.sweep_overdue(pg_session, now=_NOW)
    assert await _nudge_count(pg_session) == 2


async def test_a_second_sweep_inside_the_window_still_changes_nothing(pg_session):
    """The rate limit is unchanged; only the total is now bounded."""
    await _a_project_with_one_overdue_item(pg_session)

    await sweeper.sweep_overdue(pg_session, now=_NOW)
    await sweeper.sweep_overdue(pg_session, now=_NOW + timedelta(hours=1))

    assert await _nudge_count(pg_session) == 1
