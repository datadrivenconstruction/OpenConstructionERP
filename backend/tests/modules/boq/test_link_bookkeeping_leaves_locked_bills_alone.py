# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Keeping a linked code's group in order never writes into a locked bill.

A code is shared across the project (issue #127). Its master line owns the
definition, the other lines are instances, and three writers keep the group in
order by rewriting ``link_role`` and ``link_group_id`` on lines of OTHER bills:

* deleting the master promotes the oldest surviving line to master, or turns a
  lone survivor back into a plain line;
* unlinking the master does the same;
* linking a new line to a code whose owner is a plain line promotes that owner
  to master, or gives a group member its master role back.

None of that is money, but a locked bill is approved as it stands and should
not change at all, so each writer now leaves a locked bill's lines alone:

* promotion goes to the oldest survivor in a bill that is NOT locked, and a
  lone survivor in a locked bill is left as it is;
* a new link that would have to rewrite the owner's line in a locked bill is
  refused with a 409 that names the bill, before anything is written. Linking
  to an owner that is already the master writes nothing into its bill, so that
  still works.

Each refusal or skip has an unlocked control on the same fixture, and the row
checks read the table directly.

Run:
    cd backend
    python -m pytest tests/modules/boq/test_link_bookkeeping_leaves_locked_bills_alone.py -v
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BOQ, Position
from app.modules.boq.schemas import PositionCreate
from app.modules.boq.service import BOQService
from app.modules.projects.models import Project
from tests._pg import transactional_session

_T0 = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    # FK triggers off so a project can be seeded without standing up a user row.
    async with transactional_session(disable_fks=True) as s:
        yield s


async def _bills(session: AsyncSession, *names: str) -> list[uuid.UUID]:
    project = Project(
        name=f"Link bookkeeping {uuid.uuid4().hex[:6]}",
        currency="EUR",
        region="DACH",
        owner_id=uuid.uuid4(),
    )
    session.add(project)
    await session.flush()
    ids = []
    for name in names:
        boq = BOQ(project_id=project.id, name=name, status="draft", metadata_={})
        session.add(boq)
        await session.flush()
        ids.append(boq.id)
        session.expunge(boq)
    return ids


async def _lock(session: AsyncSession, boq_id: uuid.UUID) -> None:
    """Lock a bill the way the lock endpoint leaves it, without loading it."""
    await session.execute(update(BOQ).where(BOQ.id == boq_id).values(is_locked=True, status="final"))
    await session.flush()


async def _add(session: AsyncSession, boq_id: uuid.UUID, **fields: Any) -> Position:
    return await BOQService(session).add_position(PositionCreate(boq_id=boq_id, unit="m3", **fields))


async def _owner(session: AsyncSession, boq_id: uuid.UUID) -> Position:
    """The line that owns code 0040, a plain line with a price."""
    return await _add(
        session,
        boq_id,
        ordinal="0040",
        description="RC wall C30/37",
        quantity=10,
        unit_rate=185,
        reference_code="0040",
    )


async def _link(session: AsyncSession, boq_id: uuid.UUID, quantity: int = 1) -> Position:
    return await _add(session, boq_id, ordinal="0040", quantity=quantity, reference_code="0040", link_mode="link")


async def _link_state(session: AsyncSession, position_id: uuid.UUID) -> tuple[Any, ...]:
    """(link_role, link_group_id, reference_code, version), straight from the table."""
    row = (
        await session.execute(
            select(Position.link_role, Position.link_group_id, Position.reference_code, Position.version).where(
                Position.id == position_id
            )
        )
    ).one()
    return tuple(row)


async def _line_count(session: AsyncSession, boq_id: uuid.UUID) -> int:
    return (await session.execute(select(func.count(Position.id)).where(Position.boq_id == boq_id))).scalar_one()


# ── Deleting or unlinking the master ────────────────────────────────────────


class TestPromotingASurvivor:
    async def _group(self, session: AsyncSession) -> dict[str, Any]:
        """Master in the working bill, the OLDEST instance in a locked bill, a
        younger one in an open bill."""
        editing, locked, open_ = await _bills(session, "Working estimate", "Approved estimate", "Second draft")
        master = await _owner(session, editing)
        oldest = await _link(session, locked)
        younger = await _link(session, open_)
        await session.flush()
        # Explicit and strictly increasing: promotion picks the oldest, and two
        # rows written in one burst can share a clock tick on some platforms.
        for minutes, position_id in enumerate((master.id, oldest.id, younger.id)):
            await session.execute(
                update(Position).where(Position.id == position_id).values(created_at=_T0 + timedelta(minutes=minutes))
            )
        await _lock(session, locked)
        return {"master": master.id, "oldest": oldest.id, "younger": younger.id, "locked": locked}

    async def test_deleting_the_master_promotes_the_oldest_unlocked_survivor(self, session: AsyncSession) -> None:
        group = await self._group(session)
        oldest_before = await _link_state(session, group["oldest"])

        await BOQService(session).delete_position(group["master"])
        await session.flush()

        assert await _link_state(session, group["oldest"]) == oldest_before
        role, group_id, _code, _version = await _link_state(session, group["younger"])
        assert role == "master"
        assert group_id == oldest_before[1]

    async def test_unlinking_the_master_promotes_the_oldest_unlocked_survivor(self, session: AsyncSession) -> None:
        group = await self._group(session)
        oldest_before = await _link_state(session, group["oldest"])

        await BOQService(session).unlink_position(group["master"])
        await session.flush()

        assert await _link_state(session, group["oldest"]) == oldest_before
        assert (await _link_state(session, group["younger"]))[0] == "master"

    async def test_a_lone_survivor_in_a_locked_bill_is_left_as_it_is(self, session: AsyncSession) -> None:
        editing, locked = await _bills(session, "Working estimate", "Approved estimate")
        master = await _owner(session, editing)
        survivor = await _link(session, locked)
        await session.flush()
        await _lock(session, locked)
        before = await _link_state(session, survivor.id)

        await BOQService(session).delete_position(master.id)
        await session.flush()

        assert await _link_state(session, survivor.id) == before

    async def test_a_lone_survivor_in_an_open_bill_still_becomes_a_plain_line(self, session: AsyncSession) -> None:
        """The control: the collapse still happens where the bill may change."""
        editing, open_ = await _bills(session, "Working estimate", "Second draft")
        master = await _owner(session, editing)
        survivor = await _link(session, open_)
        await session.flush()

        await BOQService(session).delete_position(master.id)
        await session.flush()

        role, group_id, _code, _version = await _link_state(session, survivor.id)
        assert role is None
        assert group_id is None


# ── Linking a new line to a code owned in a locked bill ─────────────────────


class TestLinkingToALockedOwner:
    async def test_a_plain_owner_in_a_locked_bill_refuses_the_link(self, session: AsyncSession) -> None:
        """The owner would have to become the master: refused, nothing written."""
        locked, editing = await _bills(session, "Approved estimate", "Working estimate")
        owner = await _owner(session, locked)
        await session.flush()
        await _lock(session, locked)
        owner_before = await _link_state(session, owner.id)
        lines_before = await _line_count(session, editing)

        with pytest.raises(HTTPException) as exc:
            await _link(session, editing, quantity=4)

        assert exc.value.status_code == 409
        assert "'0040'" in exc.value.detail
        assert "'Approved estimate'" in exc.value.detail
        assert await _link_state(session, owner.id) == owner_before
        assert await _line_count(session, editing) == lines_before

    async def test_a_plain_owner_in_an_open_bill_still_links(self, session: AsyncSession) -> None:
        """The control: the owner is promoted and the new line joins its group."""
        open_, editing = await _bills(session, "Second draft", "Working estimate")
        owner = await _owner(session, open_)

        linked = await _link(session, editing, quantity=4)
        await session.flush()

        role, group_id, _code, _version = await _link_state(session, owner.id)
        assert role == "master"
        assert linked.link_role == "instance"
        assert linked.link_group_id == group_id

    async def test_an_owner_already_master_in_a_locked_bill_still_links(self, session: AsyncSession) -> None:
        """Joining an existing group writes nothing into the owner's bill."""
        locked, first, second = await _bills(session, "Approved estimate", "Working estimate", "Second draft")
        owner = await _owner(session, locked)
        await _link(session, first)
        await session.flush()
        await _lock(session, locked)
        owner_before = await _link_state(session, owner.id)
        assert owner_before[0] == "master"

        linked = await _link(session, second, quantity=4)
        await session.flush()

        assert await _link_state(session, owner.id) == owner_before
        assert linked.link_role == "instance"
        assert linked.link_group_id == owner_before[1]

    async def test_a_copy_of_a_locked_owner_is_still_allowed(self, session: AsyncSession) -> None:
        """A copy writes nothing into the owner's line either."""
        locked, editing = await _bills(session, "Approved estimate", "Working estimate")
        owner = await _owner(session, locked)
        await session.flush()
        await _lock(session, locked)
        owner_before = await _link_state(session, owner.id)

        copy = await _add(session, editing, ordinal="0040", quantity=2, reference_code="0040", link_mode="copy")
        await session.flush()

        assert await _link_state(session, owner.id) == owner_before
        assert copy.link_role is None
        assert copy.description == "RC wall C30/37"
