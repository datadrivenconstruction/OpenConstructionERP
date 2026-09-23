# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A locked bill refuses a snapshot restore and a line duplicate, like every other writer.

Locking a bill is how an estimate is approved: ``POST /boqs/{id}/lock`` sets
``is_locked`` and the status to ``final``, and from then on the only way to
change the figures is a revision. ``BOQService._ensure_not_locked`` and its
one-column twin ``_ensure_boq_writable`` enforce that with a 409, and their
docstring asks every method that writes positions or markups to call one.

Two did not. ``restore_snapshot`` deletes every position and markup of the bill
and rebuilds them from the snapshot's JSON, so on an approved bill it silently
swapped the approved figures for older ones. ``duplicate_position`` deep-copies a
line and its subtree into the same bill, which adds money to it. Both sit behind
``boq.update`` and nothing in the router checks the lock either.

Each refusal below is paired with a control, so a green here cannot come from a
test that forgot how to lock a bill or from a guard that refuses everything:

* ``delete_position`` on the same locked bill already answers 409. That proves
  the lock the fixture sets is the lock the service reads.
* The same restore and duplicate on the unlocked bill still go through, and the
  restore still hands back the snapshot's lines.

The row checks read the table directly (``select`` on the columns), not through
the ORM identity map, so a refusal that raised after it had already written would
still show up.

Run:
    cd backend
    python -m pytest tests/modules/boq/test_a_locked_bill_refuses_restore_and_duplicate.py -v
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BOQ, BOQMarkup, Position
from app.modules.boq.schemas import PositionCreate
from app.modules.boq.service import BOQService
from app.modules.projects.models import Project
from tests._pg import transactional_session

LOCKED_DETAIL = "BOQ is locked and cannot be modified. Create a revision to make changes."


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    # FK triggers off so a project can be seeded without standing up a user row.
    async with transactional_session(disable_fks=True) as s:
        yield s


async def _seed_bill(session: AsyncSession) -> tuple[BOQ, Position, Position]:
    """A bill with two priced lines and one markup. Returns (bill, line 1, line 2)."""
    project = Project(
        name=f"Locked bill {uuid.uuid4().hex[:6]}",
        currency="EUR",
        region="DACH",
        owner_id=uuid.uuid4(),
    )
    session.add(project)
    await session.flush()

    boq = BOQ(project_id=project.id, name="Approved estimate", status="draft", metadata_={})
    session.add(boq)
    await session.flush()

    service = BOQService(session)
    first = await service.add_position(
        PositionCreate(
            boq_id=boq.id,
            ordinal="1.1",
            description="Excavation",
            unit="m3",
            quantity=120,
            unit_rate=18.50,
        )
    )
    second = await service.add_position(
        PositionCreate(
            boq_id=boq.id,
            ordinal="1.2",
            description="Blinding concrete",
            unit="m3",
            quantity=8,
            unit_rate=145,
        )
    )
    session.add(
        BOQMarkup(
            boq_id=boq.id,
            name="Site overhead",
            markup_type="percentage",
            category="overhead",
            percentage="10",
            fixed_amount="0",
            apply_to="direct_cost",
            sort_order=0,
            is_active=True,
        )
    )
    await session.flush()
    # The bill was built in this session, so its selectin collections were never
    # loaded and the first service read of ``boq.positions`` would lazy-load
    # outside the greenlet (MissingGreenlet). Drop it and read it back the way
    # the service does.
    boq_id = boq.id
    session.expunge(boq)
    loaded = await session.get(BOQ, boq_id)
    assert loaded is not None
    return loaded, first, second


async def _lock(session: AsyncSession, boq: BOQ) -> None:
    """Lock the bill the way the lock endpoint leaves it."""
    boq.is_locked = True
    boq.status = "final"
    await session.flush()


async def _position_rows(session: AsyncSession, boq_id: uuid.UUID) -> list[tuple[uuid.UUID, str]]:
    """(id, ordinal) of every line of the bill, straight from the table."""
    rows = await session.execute(
        select(Position.id, Position.ordinal).where(Position.boq_id == boq_id).order_by(Position.ordinal),
    )
    return [(r[0], r[1]) for r in rows.all()]


async def _markup_ids(session: AsyncSession, boq_id: uuid.UUID) -> list[uuid.UUID]:
    rows = await session.execute(select(BOQMarkup.id).where(BOQMarkup.boq_id == boq_id))
    return sorted(r[0] for r in rows.all())


class TestTheControl:
    async def test_deleting_a_line_of_a_locked_bill_is_refused(self, session: AsyncSession) -> None:
        """The guard that already works, on the lock this file sets."""
        boq, first, _second = await _seed_bill(session)
        await _lock(session, boq)
        before = await _position_rows(session, boq.id)

        with pytest.raises(HTTPException) as exc:
            await BOQService(session).delete_position(first.id)

        assert exc.value.status_code == 409
        assert exc.value.detail == LOCKED_DETAIL
        assert await _position_rows(session, boq.id) == before


class TestRestoringASnapshot:
    async def test_a_locked_bill_refuses_the_restore(self, session: AsyncSession) -> None:
        """Restore would drop every approved line and markup and rebuild older ones."""
        boq, _first, _second = await _seed_bill(session)
        service = BOQService(session)
        snapshot = await service.create_snapshot(boq.id, name="Before approval")
        await session.flush()
        await _lock(session, boq)
        lines_before = await _position_rows(session, boq.id)
        markups_before = await _markup_ids(session, boq.id)

        with pytest.raises(HTTPException) as exc:
            await service.restore_snapshot(boq.id, snapshot.id)

        assert exc.value.status_code == 409
        assert exc.value.detail == LOCKED_DETAIL
        # Same row ids, not just the same count: a restore recreates every line
        # under a fresh id, so an id that survived is a line nobody touched.
        assert await _position_rows(session, boq.id) == lines_before
        assert await _markup_ids(session, boq.id) == markups_before

    async def test_an_unlocked_bill_still_restores(self, session: AsyncSession) -> None:
        """The allowed case: the restore goes through and hands back the snapshot's lines."""
        boq, _first, second = await _seed_bill(session)
        service = BOQService(session)
        snapshot = await service.create_snapshot(boq.id, name="Two lines")
        await session.flush()
        await service.delete_position(second.id)
        await session.flush()
        assert [o for _i, o in await _position_rows(session, boq.id)] == ["1.1"]

        restored = await service.restore_snapshot(boq.id, snapshot.id)
        await session.flush()

        assert sorted(p.ordinal for p in restored.positions) == ["1.1", "1.2"]
        assert [o for _i, o in await _position_rows(session, boq.id)] == ["1.1", "1.2"]
        assert len(await _markup_ids(session, boq.id)) == 1


class TestDuplicatingALine:
    async def test_a_locked_bill_refuses_the_duplicate(self, session: AsyncSession) -> None:
        """A duplicate adds a priced line, so it adds money to an approved bill."""
        boq, first, _second = await _seed_bill(session)
        await _lock(session, boq)
        before = await _position_rows(session, boq.id)

        with pytest.raises(HTTPException) as exc:
            await BOQService(session).duplicate_position(first.id)

        assert exc.value.status_code == 409
        assert exc.value.detail == LOCKED_DETAIL
        assert await _position_rows(session, boq.id) == before

    async def test_an_unlocked_bill_still_duplicates(self, session: AsyncSession) -> None:
        """The allowed case: one more line, under a fresh ordinal."""
        boq, first, _second = await _seed_bill(session)

        copy = await BOQService(session).duplicate_position(first.id)
        await session.flush()

        count = (await session.execute(select(func.count(Position.id)).where(Position.boq_id == boq.id))).scalar_one()
        assert count == 3
        assert copy.boq_id == boq.id
        assert copy.id != first.id
