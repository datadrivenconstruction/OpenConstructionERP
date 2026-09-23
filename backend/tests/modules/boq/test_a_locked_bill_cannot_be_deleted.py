# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A locked bill cannot be deleted, like it cannot be edited.

Locking a bill is how an estimate is approved, and from then on its figures
change only through a revision. Every position and markup writer refuses a
locked bill with a 409, and so do snapshot restore and line duplicate. Deleting
the bill removes every one of those figures at once, and ``delete_boq`` did it
without reading the lock.

The refusal is paired with a control on the same fixture: the unlocked bill is
still deleted, so a green here cannot come from a guard that refuses everything.
The row checks read the table directly, so a refusal that raised after it had
already deleted would still show up.

Run:
    cd backend
    python -m pytest tests/modules/boq/test_a_locked_bill_cannot_be_deleted.py -v
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BOQ, Position
from app.modules.boq.schemas import PositionCreate
from app.modules.boq.service import BOQService
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

LOCKED_DETAIL = "BOQ is locked and cannot be modified. Create a revision to make changes."


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    # Foreign keys stay ON: deleting a bill removes its lines through the
    # database's ON DELETE CASCADE, and the control below has to see that
    # happen. The project therefore gets a real owner row.
    async with transactional_session() as s:
        yield s


async def _seed_bill(session: AsyncSession) -> uuid.UUID:
    """A bill with one priced line. Returns its id."""
    owner = User(
        email=f"locked-delete-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Estimator",
        role="admin",
    )
    session.add(owner)
    await session.flush()
    project = Project(
        name=f"Locked delete {uuid.uuid4().hex[:6]}",
        currency="EUR",
        region="DACH",
        owner_id=owner.id,
    )
    session.add(project)
    await session.flush()
    boq = BOQ(project_id=project.id, name="Approved estimate", status="draft", metadata_={})
    session.add(boq)
    await session.flush()
    await BOQService(session).add_position(
        PositionCreate(
            boq_id=boq.id,
            ordinal="1.1",
            description="Excavation",
            unit="m3",
            quantity=120,
            unit_rate=18.50,
        )
    )
    await session.flush()
    boq_id = boq.id
    session.expunge(boq)
    return boq_id


async def _lock(session: AsyncSession, boq_id: uuid.UUID) -> None:
    """Lock the bill the way the lock endpoint leaves it."""
    boq = await session.get(BOQ, boq_id)
    assert boq is not None
    boq.is_locked = True
    boq.status = "final"
    await session.flush()


async def _bill_rows(session: AsyncSession, boq_id: uuid.UUID) -> tuple[int, int]:
    """(bills with this id, lines of this bill), straight from the tables."""
    bills = (await session.execute(select(func.count(BOQ.id)).where(BOQ.id == boq_id))).scalar_one()
    lines = (await session.execute(select(func.count(Position.id)).where(Position.boq_id == boq_id))).scalar_one()
    return bills, lines


class TestDeletingABill:
    async def test_a_locked_bill_refuses_the_delete(self, session: AsyncSession) -> None:
        """The approved bill and its line are still there after the refusal."""
        boq_id = await _seed_bill(session)
        await _lock(session, boq_id)
        assert await _bill_rows(session, boq_id) == (1, 1)

        with pytest.raises(HTTPException) as exc:
            await BOQService(session).delete_boq(boq_id)

        assert exc.value.status_code == 409
        assert exc.value.detail == LOCKED_DETAIL
        assert await _bill_rows(session, boq_id) == (1, 1)

    async def test_an_unlocked_bill_is_still_deleted(self, session: AsyncSession) -> None:
        """The allowed case: the bill and its line are gone."""
        boq_id = await _seed_bill(session)
        assert await _bill_rows(session, boq_id) == (1, 1)

        await BOQService(session).delete_boq(boq_id)
        await session.flush()

        assert await _bill_rows(session, boq_id) == (0, 0)

    async def test_a_missing_bill_is_still_a_404(self, session: AsyncSession) -> None:
        """The guard sits after the lookup, so an unknown id answers as before."""
        with pytest.raises(HTTPException) as exc:
            await BOQService(session).delete_boq(uuid.uuid4())

        assert exc.value.status_code == 404
