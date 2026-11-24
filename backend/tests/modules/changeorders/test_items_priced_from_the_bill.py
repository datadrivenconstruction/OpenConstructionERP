"""A change order item picked from a bill position is valued at its contract rate (PostgreSQL)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BOQ, Position
from app.modules.changeorders.schemas import ChangeOrderCreate, ChangeOrderItemCreate
from app.modules.changeorders.service import ChangeOrderService
from app.modules.changeorders.validators import register_changeorders_validation_rules
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    register_changeorders_validation_rules()
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession) -> uuid.UUID:
    user = User(email=f"cob-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", full_name="CO", role="admin")
    session.add(user)
    await session.flush()
    proj = Project(name=f"COB {uuid.uuid4().hex[:6]}", owner_id=user.id, currency="EUR")
    session.add(proj)
    await session.flush()
    return proj.id


async def _position(session: AsyncSession, project_id: uuid.UUID) -> Position:
    boq = BOQ(project_id=project_id, name="Bill")
    session.add(boq)
    await session.flush()
    pos = Position(
        boq_id=boq.id, ordinal="01.010", description="Wall", unit="m2", quantity="40", unit_rate="85.5", total="3420"
    )
    session.add(pos)
    await session.flush()
    return pos


@pytest.mark.asyncio
async def test_quantity_change_is_valued_at_the_contract_rate(session):
    pid = await _project(session)
    pos = await _position(session, pid)
    svc = ChangeOrderService(session)
    order = await svc.create_order(ChangeOrderCreate(project_id=pid, title="More wall"))
    item = await svc.add_item(
        order.id,
        ChangeOrderItemCreate(description="Wall", new_quantity="50", metadata={"boq_position_id": str(pos.id)}),
    )
    assert Decimal(item.original_quantity) == 40
    assert Decimal(item.original_rate) == Decimal("85.5")
    assert Decimal(item.new_rate) == Decimal("85.5")
    assert item.unit == "m2"
    assert Decimal(item.cost_delta) == Decimal("855.00")


@pytest.mark.asyncio
async def test_a_stated_new_rate_is_kept(session):
    pid = await _project(session)
    pos = await _position(session, pid)
    svc = ChangeOrderService(session)
    order = await svc.create_order(ChangeOrderCreate(project_id=pid, title="Star rate"))
    item = await svc.add_item(
        order.id,
        ChangeOrderItemCreate(
            description="Wall", new_quantity="40", new_rate="90", metadata={"boq_position_id": str(pos.id)}
        ),
    )
    assert Decimal(item.cost_delta) == Decimal("180.00")


@pytest.mark.asyncio
async def test_a_position_from_another_project_is_refused(session):
    pid = await _project(session)
    other = await _position(session, await _project(session))
    svc = ChangeOrderService(session)
    order = await svc.create_order(ChangeOrderCreate(project_id=pid, title="Wrong bill"))
    with pytest.raises(HTTPException) as exc:
        await svc.add_item(
            order.id,
            ChangeOrderItemCreate(description="Wall", new_quantity="5", metadata={"boq_position_id": str(other.id)}),
        )
    assert exc.value.detail["problem"] == "boq_position_not_in_project"
