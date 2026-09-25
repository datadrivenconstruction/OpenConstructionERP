"""An NCR's ``change_order_id`` must name a change order of the NCR's own project.

The column is a plain ``VARCHAR(36)`` with no foreign key, so the database
takes any string: a typo, an id from another project, a change order that was
never there. A database foreign key is not added (the column predates it on
running installs, the heal would add it ``NOT VALID`` over whatever strings
are already there, and the change orders table belongs to another module), so
the check lives in the service, on create and on update.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.changeorders.models import ChangeOrder
from app.modules.ncr.schemas import NCRCreate, NCRUpdate
from app.modules.ncr.service import NCRService
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession) -> uuid.UUID:
    user = User(email=f"ncrco{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    session.add(user)
    await session.flush()
    project = Project(name="NCR CO project", owner_id=user.id, currency="EUR")
    session.add(project)
    await session.flush()
    return project.id


async def _order(session: AsyncSession, project_id: uuid.UUID) -> str:
    order = ChangeOrder(project_id=project_id, code=f"CO-{uuid.uuid4().hex[:6]}", title="Rework")
    session.add(order)
    await session.flush()
    return str(order.id)


def _create(project_id: uuid.UUID, change_order_id: str | None) -> NCRCreate:
    return NCRCreate(
        project_id=project_id,
        title="Honeycombing in slab S2",
        description="Voids at the column heads after stripping.",
        ncr_type="workmanship",
        severity="major",
        change_order_id=change_order_id,
    )


async def test_a_change_order_of_the_same_project_is_accepted(session: AsyncSession) -> None:
    pid = await _project(session)
    order_id = await _order(session, pid)
    ncr = await NCRService(session).create_ncr(_create(pid, order_id))
    assert ncr.change_order_id == order_id


@pytest.mark.parametrize("which", ["other_project", "unknown", "not_a_uuid"])
async def test_a_foreign_or_unknown_change_order_is_refused_on_create(session: AsyncSession, which: str) -> None:
    pid = await _project(session)
    if which == "other_project":
        value = await _order(session, await _project(session))
    elif which == "unknown":
        value = str(uuid.uuid4())
    else:
        value = "CO-7"
    with pytest.raises(HTTPException) as exc:
        await NCRService(session).create_ncr(_create(pid, value))
    assert exc.value.status_code == 400


async def test_a_foreign_change_order_is_refused_on_update(session: AsyncSession) -> None:
    pid = await _project(session)
    svc = NCRService(session)
    ncr = await svc.create_ncr(_create(pid, None))
    foreign = await _order(session, await _project(session))
    with pytest.raises(HTTPException) as exc:
        await svc.update_ncr(ncr.id, NCRUpdate(change_order_id=foreign))
    assert exc.value.status_code == 400

    own = await _order(session, pid)
    updated = await svc.update_ncr(ncr.id, NCRUpdate(change_order_id=own))
    assert updated.change_order_id == own
