"""An NCR's cost becomes one change order, however often the action is sent.

``POST /ncr/{id}/create-variation/`` minted a new change order on every call
and re-pointed the NCR at the newest one, so a double click or a retried
request left two change orders in the register carrying the same cost. It also
turned a void NCR, frozen like a closed one, into a change order. The RFI
handoff already returns the linked change order on a repeat call; this pins
the same behaviour for NCRs.

The route is called as a coroutine on a real PostgreSQL session (rolled back on
teardown) with the project owner as caller, so the project access check it runs
itself is the real one.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.changeorders.models import ChangeOrder
from app.modules.ncr.router import create_variation_from_ncr
from app.modules.ncr.schemas import NCRCreate
from app.modules.ncr.service import NCRService
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session() as s:
        yield s


async def _owner_and_project(session: AsyncSession) -> tuple[str, uuid.UUID]:
    user = User(email=f"ncr{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    session.add(user)
    await session.flush()
    project = Project(name="NCR project", owner_id=user.id, currency="EUR")
    session.add(project)
    await session.flush()
    return str(user.id), project.id


async def _ncr(session: AsyncSession, project_id: uuid.UUID, *, status: str = "corrective_action") -> uuid.UUID:
    ncr = await NCRService(session).create_ncr(
        NCRCreate(
            project_id=project_id,
            title="Honeycombing in slab S2",
            description="Voids at the column heads after stripping.",
            ncr_type="workmanship",
            severity="major",
            status=status,
            cost_impact="EUR 8400",
        )
    )
    return ncr.id


async def _raise_variation(session: AsyncSession, ncr_id: uuid.UUID, user_id: str) -> dict:
    return await create_variation_from_ncr(
        ncr_id=ncr_id, user_id=user_id, session=session, _perm=None, service=NCRService(session)
    )


async def _orders(session: AsyncSession, project_id: uuid.UUID) -> int:
    return int(
        await session.scalar(select(func.count()).select_from(ChangeOrder).where(ChangeOrder.project_id == project_id))
        or 0
    )


async def test_control_an_ncr_without_a_cost_is_still_refused(session: AsyncSession) -> None:
    user_id, project_id = await _owner_and_project(session)
    ncr = await NCRService(session).create_ncr(
        NCRCreate(
            project_id=project_id,
            title="Label missing",
            description="Batch label missing on delivery.",
            ncr_type="documentation",
            severity="minor",
        )
    )

    with pytest.raises(HTTPException) as exc:
        await _raise_variation(session, ncr.id, user_id)

    assert exc.value.status_code == 400
    assert await _orders(session, project_id) == 0


async def test_a_repeated_call_returns_the_same_change_order(session: AsyncSession) -> None:
    user_id, project_id = await _owner_and_project(session)
    ncr_id = await _ncr(session, project_id)

    first = await _raise_variation(session, ncr_id, user_id)
    second = await _raise_variation(session, ncr_id, user_id)

    assert second["change_order_id"] == first["change_order_id"]
    assert await _orders(session, project_id) == 1, "a second call minted another change order with the same cost"
    ncr = await NCRService(session).get_ncr(ncr_id)
    assert ncr.change_order_id == first["change_order_id"]


async def test_a_link_to_a_deleted_change_order_mints_a_new_one(session: AsyncSession) -> None:
    user_id, project_id = await _owner_and_project(session)
    ncr_id = await _ncr(session, project_id)
    first = await _raise_variation(session, ncr_id, user_id)
    order = await session.get(ChangeOrder, uuid.UUID(first["change_order_id"]))
    await session.delete(order)
    await session.flush()

    second = await _raise_variation(session, ncr_id, user_id)

    assert second["change_order_id"] != first["change_order_id"]
    assert await _orders(session, project_id) == 1


async def test_a_void_ncr_does_not_become_a_change_order(session: AsyncSession) -> None:
    user_id, project_id = await _owner_and_project(session)
    ncr_id = await _ncr(session, project_id, status="void")

    with pytest.raises(HTTPException) as exc:
        await _raise_variation(session, ncr_id, user_id)

    assert exc.value.status_code == 409
    assert "void" in exc.value.detail
    assert await _orders(session, project_id) == 0


async def test_a_closed_ncr_still_recovers_its_cost_once(session: AsyncSession) -> None:
    user_id, project_id = await _owner_and_project(session)
    ncr_id = await _ncr(session, project_id, status="closed")

    first = await _raise_variation(session, ncr_id, user_id)
    again = await _raise_variation(session, ncr_id, user_id)

    assert again["change_order_id"] == first["change_order_id"]
    assert await _orders(session, project_id) == 1
