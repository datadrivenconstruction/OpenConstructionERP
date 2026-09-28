# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""One row the sweep cannot write must not silence the sweep.

Found in production, not by reading: a single punch item held an
``owner_user_id`` that parses as a UUID and names nobody. The sweeper decided
who to notify with a format check, so it took that id as the recipient instead
of falling through to the project managers, and the insert broke the
notification foreign key. The failed flush left the session rollback-only, so
every later item in the same pass raised ``PendingRollbackError`` rather than
doing its work - on every tick, forever. Overdue deadlines stopped reaching
anyone on any project, and the only outward sign was the log.

Two independent guarantees are pinned here because the defect needed both to
be missing. The first stops that id from being chosen at all. The second is the
one that matters when the next unwritable row arrives for a reason nobody
predicted: whatever it is, the rows behind it still get their notification.

Same root as the false "Unassigned" in the register: a value that parses is not
a party that exists. See ``test_deadlines_party_resolution.py``.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.modules.deadlines import service as deadlines_service
from app.modules.deadlines import sweeper
from app.modules.notifications.models import Notification
from app.modules.projects.models import Project
from app.modules.punchlist.models import PunchItem
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

# A fixed clock a fortnight past the due date, so the rows below land as overdue
# whatever day the suite runs.
_NOW = datetime(2026, 3, 15, 9, 0, tzinfo=UTC)
_DUE = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


async def _a_user(session, full_name: str) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex[:12]}@example.com",
        hashed_password="x",
        full_name=full_name,
    )
    session.add(user)
    await session.flush()
    return user


async def _a_project(session) -> tuple[uuid.UUID, uuid.UUID]:
    """A project and the id of the manager the sweep must fall back to."""
    manager = await _a_user(session, "Project Manager")
    project = Project(name="Deadline sweep isolation", owner_id=manager.id)
    session.add(project)
    await session.flush()
    return project.id, manager.id


def _punch_item(project_id: uuid.UUID, assigned_to: str | None, title: str) -> PunchItem:
    return PunchItem(
        id=uuid.uuid4(),
        project_id=project_id,
        title=title,
        description="",
        status="open",
        due_date=_DUE,
        assigned_to=assigned_to,
    )


async def _overdue_notifications(session) -> list[Notification]:
    rows = await session.execute(select(Notification).where(Notification.notification_type == sweeper.OVERDUE_TYPE))
    return list(rows.scalars().all())


async def test_an_owner_id_naming_nobody_falls_through_to_the_managers(pg_session):
    """The production row, reproduced.

    A well-formed id that no user is behind is exactly the case the managers
    fallback exists for. Choosing it as the recipient is both a lost
    notification and the foreign key violation that poisons the pass.
    """
    project_id, manager_id = await _a_project(pg_session)
    ghost = uuid.uuid4()
    pg_session.add(_punch_item(project_id, str(ghost), title="Held by nobody"))
    await pg_session.flush()

    actioned = await sweeper.sweep_overdue(pg_session, now=_NOW)

    assert actioned == 1, "the overdue item raised no nudge at all"
    notifications = await _overdue_notifications(pg_session)
    assert [n.user_id for n in notifications] == [manager_id]


async def test_a_real_owner_is_still_notified_directly(pg_session):
    """The existence check must not cost the ordinary case its direct nudge."""
    project_id, manager_id = await _a_project(pg_session)
    holder = await _a_user(pg_session, "Site Engineer")
    pg_session.add(_punch_item(project_id, str(holder.id), title="Held by a teammate"))
    await pg_session.flush()

    actioned = await sweeper.sweep_overdue(pg_session, now=_NOW)

    assert actioned == 1
    notifications = await _overdue_notifications(pg_session)
    assert [n.user_id for n in notifications] == [holder.id]
    assert manager_id not in {n.user_id for n in notifications}


async def test_a_deactivated_owner_falls_through_to_the_managers(pg_session):
    """A row that exists but is switched off is not somebody to remind.

    Measured on the showcase: a deactivated external account kept collecting
    overdue reminders every day for items it would never touch again.
    """
    project_id, manager_id = await _a_project(pg_session)
    gone = await _a_user(pg_session, "Former Subcontractor")
    gone.is_active = False
    pg_session.add(_punch_item(project_id, str(gone.id), title="Held by a departed account"))
    await pg_session.flush()

    actioned = await sweeper.sweep_overdue(pg_session, now=_NOW)

    assert actioned == 1
    notifications = await _overdue_notifications(pg_session)
    assert [n.user_id for n in notifications] == [manager_id]


async def test_with_no_active_owner_or_manager_nobody_is_nudged(pg_session):
    """The fallback must not reach for a deactivated manager either."""
    project_id, manager_id = await _a_project(pg_session)
    manager = await pg_session.get(User, manager_id)
    manager.is_active = False
    gone = await _a_user(pg_session, "Former Subcontractor")
    gone.is_active = False
    pg_session.add(_punch_item(project_id, str(gone.id), title="Nobody left to tell"))
    await pg_session.flush()

    assert await sweeper.sweep_overdue(pg_session, now=_NOW) == 0
    assert await _overdue_notifications(pg_session) == []


async def test_one_unwritable_row_does_not_silence_the_rest_of_the_sweep(pg_session, monkeypatch):
    """The guarantee the docstring used to claim and the code did not provide.

    The recipient is forced to an id nobody is behind for whichever item the
    sweep happens to reach first, so the test does not depend on the order the
    collectors return. Catching the exception is not what makes the second item
    work - the savepoint is. Without it the failed flush leaves the session
    rollback-only and the very next statement raises, which is how one row took
    every project's notifications down with it.
    """
    project_id, _manager_id = await _a_project(pg_session)
    holder = await _a_user(pg_session, "Site Engineer")
    pg_session.add_all(
        [
            _punch_item(project_id, str(holder.id), title="First"),
            _punch_item(project_id, str(holder.id), title="Second"),
        ],
    )
    await pg_session.flush()

    overdue = await deadlines_service.collect_overdue_for_sweep(pg_session, now=_NOW)
    assert len(overdue) == 2, "both punch items must reach the sweep, or this proves nothing"

    ghost = uuid.uuid4()
    resolve = sweeper._overdue_recipients
    reached: list[str] = []

    async def _first_row_cannot_be_written(session, item):
        reached.append(item.title)
        if len(reached) == 1:
            return [ghost]
        return await resolve(session, item)

    monkeypatch.setattr(sweeper, "_overdue_recipients", _first_row_cannot_be_written)

    actioned = await sweeper.sweep_overdue(pg_session, now=_NOW)

    assert len(reached) == 2, "the sweep stopped before it reached the second item"
    assert actioned == 1, "the item behind the unwritable one was never notified"
    notifications = await _overdue_notifications(pg_session)
    assert [n.user_id for n in notifications] == [holder.id]
    assert ghost not in {n.user_id for n in notifications}


async def test_the_session_survives_the_pass_it_could_not_complete(pg_session, monkeypatch):
    """The caller owns the transaction, so the sweep must hand it back usable.

    ``_run_once`` commits after the sweep. A pass that leaves the session
    rollback-only turns one unwritable row into a lost commit for everything the
    pass did manage to write.
    """
    project_id, _manager_id = await _a_project(pg_session)
    pg_session.add(_punch_item(project_id, str(uuid.uuid4()), title="Held by nobody"))
    await pg_session.flush()

    ghost = uuid.uuid4()

    async def _nobody_can_be_written(session, item):
        return [ghost]

    monkeypatch.setattr(sweeper, "_overdue_recipients", _nobody_can_be_written)

    assert await sweeper.sweep_overdue(pg_session, now=_NOW) == 0

    # Not decoration: this is the statement that raised PendingRollbackError.
    assert await _overdue_notifications(pg_session) == []
