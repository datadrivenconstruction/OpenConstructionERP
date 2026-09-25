# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A due date typed as 16 October is stored as 16 October, on a real PostgreSQL.

The punch list's due date is a calendar day in a ``TIMESTAMPTZ`` column. The
API used to hand the column the naive ``datetime(2026, 10, 16)`` that Pydantic
makes of ``"2026-10-16"``, and asyncpg binds a naive value with
``astimezone(utc)``, which reads it in the server process's local zone. On a
server at UTC+2 the row held ``2026-10-15 22:00 UTC``, and a browser in Toronto
printed 15 October.

What is asserted is the stored instant itself, read back in UTC by the
database, so nothing in the application can reinterpret it on the way out.
This test is only discriminating on a machine that is not at UTC; on a UTC
runner the old code stored the right instant by coincidence. The zone-free
tests in ``tests/unit/test_a_date_only_field_keeps_its_day_in_every_zone.py``
pin the same rule everywhere.
"""

import uuid
from datetime import datetime

import pytest
from sqlalchemy import text

from app.modules.projects.models import Project
from app.modules.punchlist.models import PunchItem
from app.modules.punchlist.schemas import PunchItemCreate
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio


async def _a_project(session) -> uuid.UUID:
    owner = User(
        id=uuid.uuid4(),
        email=f"pm-{uuid.uuid4().hex[:12]}@example.com",
        hashed_password="x",
        full_name="Project Manager",
    )
    session.add(owner)
    await session.flush()
    project = Project(name="Due date zone", owner_id=owner.id)
    session.add(project)
    await session.flush()
    return project.id


async def _stored_utc(session, item_id: uuid.UUID) -> datetime:
    row = await session.execute(
        text("SELECT due_date AT TIME ZONE 'UTC' FROM oe_punchlist_item WHERE id = :id"),
        {"id": str(item_id)},
    )
    return row.scalar_one()


@pytest.mark.parametrize("typed", ["2026-10-16", datetime(2026, 10, 16)])
async def test_the_typed_day_is_stored_as_midnight_utc_of_that_day(pg_session, typed) -> None:
    project_id = await _a_project(pg_session)
    payload = PunchItemCreate(project_id=project_id, title="Cracked tile", due_date=typed)
    item = PunchItem(id=uuid.uuid4(), project_id=project_id, title=payload.title, due_date=payload.due_date)
    pg_session.add(item)
    await pg_session.flush()

    assert await _stored_utc(pg_session, item.id) == datetime(2026, 10, 16, 0, 0)


async def test_a_naive_value_written_straight_to_the_model_keeps_its_day(pg_session) -> None:
    # The seeders and the cross-module bridges build PunchItem directly, without
    # the API schema. The column itself has to keep the day.
    project_id = await _a_project(pg_session)
    item = PunchItem(id=uuid.uuid4(), project_id=project_id, title="Loose handrail", due_date=datetime(2026, 1, 26))
    pg_session.add(item)
    await pg_session.flush()

    assert await _stored_utc(pg_session, item.id) == datetime(2026, 1, 26, 0, 0)
