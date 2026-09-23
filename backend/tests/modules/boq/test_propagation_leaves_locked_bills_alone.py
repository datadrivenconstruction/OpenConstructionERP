# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A shared definition edit reaches every bill of the project except a locked one.

A code is shared across the project, not the bill. Editing a linked master line
(issue #127), a sub-line of a linked master (#132) or a coded resource on its
first carrier (#133) rewrites rate and total on the matching lines of every
other bill in the project. The edited line's own bill passes the lock guard, but
the other bills were never asked, so an approved bill's money changed under it
without anyone touching it.

The rule now: propagation skips a locked bill, and the edit's response says how
many lines it left and in which locked bills, so the editor can tell the
estimator rather than let the approved bill silently drift out of step with the
definition. Every test here has a second, unlocked bill that must still take
the change, so a green cannot come from a propagation that stopped working
altogether. Row checks read the table directly, past the identity map.

Run:
    cd backend
    python -m pytest tests/modules/boq/test_propagation_leaves_locked_bills_alone.py -v
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest_asyncio
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BOQ, Position
from app.modules.boq.schemas import PositionCreate, PositionUpdate
from app.modules.boq.service import BOQService
from app.modules.projects.models import Project
from tests._pg import transactional_session

_T0 = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    # FK triggers off so a project can be seeded without standing up a user row.
    async with transactional_session(disable_fks=True) as s:
        yield s


async def _project_with_bills(session: AsyncSession) -> dict[str, uuid.UUID]:
    """A project with three bills: the one being edited, a locked one, an open one."""
    project = Project(
        name=f"Shared codes {uuid.uuid4().hex[:6]}",
        currency="EUR",
        region="DACH",
        owner_id=uuid.uuid4(),
    )
    session.add(project)
    await session.flush()
    ids: dict[str, uuid.UUID] = {"project": project.id}
    for key, name in (("editing", "Working estimate"), ("locked", "Approved estimate"), ("open", "Second draft")):
        boq = BOQ(project_id=project.id, name=name, status="draft", metadata_={})
        session.add(boq)
        await session.flush()
        ids[key] = boq.id
        session.expunge(boq)
    return ids


async def _lock(session: AsyncSession, boq_id: uuid.UUID) -> None:
    """Lock a bill the way the lock endpoint leaves it, without loading it."""
    await session.execute(update(BOQ).where(BOQ.id == boq_id).values(is_locked=True, status="final"))
    await session.flush()


async def _stored(session: AsyncSession, position_id: uuid.UUID) -> tuple[Any, ...]:
    """What the database holds for a line's money and definition."""
    row = (
        await session.execute(
            select(
                Position.description, Position.unit_rate, Position.total, Position.version, Position.metadata_
            ).where(Position.id == position_id)
        )
    ).one()
    return tuple(row)


async def _add(session: AsyncSession, boq_id: uuid.UUID, **fields: Any) -> Position:
    return await BOQService(session).add_position(PositionCreate(boq_id=boq_id, **fields))


async def _child_of(session: AsyncSession, parent_id: uuid.UUID) -> uuid.UUID:
    row = (await session.execute(select(Position.id).where(Position.parent_id == parent_id))).one()
    return row[0]


def _info(position: Position) -> dict[str, Any]:
    return getattr(position, "_link_propagation_info", None) or {}


# ── Issue #127: a linked master line ────────────────────────────────────────


class TestALinkedMasterLine:
    async def _linked(self, session: AsyncSession) -> dict[str, Any]:
        bills = await _project_with_bills(session)
        master = await _add(
            session,
            bills["editing"],
            ordinal="0040",
            description="RC wall C30/37",
            unit="m3",
            quantity=10,
            unit_rate=185,
            reference_code="0040",
        )
        in_locked = await _add(
            session, bills["locked"], ordinal="0040", unit="m3", quantity=4, reference_code="0040", link_mode="link"
        )
        in_open = await _add(
            session, bills["open"], ordinal="0040", unit="m3", quantity=7, reference_code="0040", link_mode="link"
        )
        await session.flush()
        assert in_locked.link_role == "instance" and in_open.link_role == "instance"
        return {**bills, "master": master.id, "in_locked": in_locked.id, "in_open": in_open.id}

    async def test_the_locked_bill_keeps_its_line_and_the_open_one_takes_the_edit(self, session: AsyncSession) -> None:
        linked = await self._linked(session)
        await _lock(session, linked["locked"])
        locked_before = await _stored(session, linked["in_locked"])

        edited = await BOQService(session).update_position(
            linked["master"], PositionUpdate(description="RC wall C35/45", unit_rate=Decimal("200"))
        )
        await session.flush()

        assert await _stored(session, linked["in_locked"]) == locked_before
        description, rate, total, _version, _meta = await _stored(session, linked["in_open"])
        assert description == "RC wall C35/45"
        assert Decimal(str(rate)) == Decimal("200")
        assert Decimal(str(total)) == Decimal("1400")
        info = _info(edited)
        assert info["propagated_to"] == 1
        assert info["locked_skipped"] == 1
        assert info["locked_boqs"] == [{"id": str(linked["locked"]), "name": "Approved estimate"}]

    async def test_a_skip_is_reported_even_when_nothing_else_changed(self, session: AsyncSession) -> None:
        """Every instance locked: the count of written lines is 0, the notice is not lost."""
        linked = await self._linked(session)
        await _lock(session, linked["locked"])
        await _lock(session, linked["open"])
        locked_before = await _stored(session, linked["in_locked"])

        edited = await BOQService(session).update_position(linked["master"], PositionUpdate(unit_rate=Decimal("200")))
        await session.flush()

        assert await _stored(session, linked["in_locked"]) == locked_before
        info = _info(edited)
        assert info["propagated_to"] == 0
        assert info["locked_skipped"] == 2
        assert [b["name"] for b in info["locked_boqs"]] == ["Approved estimate", "Second draft"]

    async def test_with_no_bill_locked_nothing_is_skipped(self, session: AsyncSession) -> None:
        """The control: both instances take the edit and the notice stays empty."""
        linked = await self._linked(session)

        edited = await BOQService(session).update_position(linked["master"], PositionUpdate(unit_rate=Decimal("200")))
        await session.flush()

        for key in ("in_locked", "in_open"):
            assert Decimal(str((await _stored(session, linked[key]))[1])) == Decimal("200")
        info = _info(edited)
        assert info["propagated_to"] == 2
        assert info.get("locked_skipped", 0) == 0
        assert info.get("locked_boqs", []) == []


# ── Issue #132: a sub-line of a linked master ───────────────────────────────


class TestASubLineOfALinkedMaster:
    async def test_the_locked_bill_keeps_its_sub_line(self, session: AsyncSession) -> None:
        bills = await _project_with_bills(session)
        master = await _add(
            session,
            bills["editing"],
            ordinal="MC1",
            description="Partida master",
            unit="m3",
            quantity=10,
            unit_rate=185,
            reference_code="MCODE",
        )
        master_child = await _add(
            session,
            bills["editing"],
            ordinal="MC1.1",
            description="Old sub-line",
            unit="kg",
            quantity=120,
            unit_rate=Decimal("1.85"),
            parent_id=master.id,
        )
        in_locked = await _add(
            session, bills["locked"], ordinal="MC1", unit="m3", quantity=4, reference_code="MCODE", link_mode="link"
        )
        in_open = await _add(
            session, bills["open"], ordinal="MC1", unit="m3", quantity=7, reference_code="MCODE", link_mode="link"
        )
        await session.flush()
        locked_child = await _child_of(session, in_locked.id)
        open_child = await _child_of(session, in_open.id)
        await _lock(session, bills["locked"])
        locked_before = await _stored(session, locked_child)

        edited = await BOQService(session).update_position(
            master_child.id, PositionUpdate(description="NEW sub-line", unit_rate=Decimal("2"))
        )
        await session.flush()

        assert await _stored(session, locked_child) == locked_before
        description, rate, _total, _version, _meta = await _stored(session, open_child)
        assert description == "NEW sub-line"
        assert Decimal(str(rate)) == Decimal("2")
        info = _info(edited)
        assert info["propagated_to"] == 1
        assert info["locked_skipped"] == 1
        assert info["locked_boqs"] == [{"id": str(bills["locked"]), "name": "Approved estimate"}]


# ── Issue #133: a coded resource on its first carrier ───────────────────────


def _res(code: str, qty: str, rate: str) -> dict[str, Any]:
    return {
        "code": code,
        "name": f"Resource {code}",
        "type": "material",
        "unit": "m3",
        "quantity": qty,
        "unit_rate": rate,
        "total": str(Decimal(qty) * Decimal(rate)),
    }


def _carrier(boq_id: uuid.UUID, n: int, qty: str, resources: list[dict[str, Any]]) -> Position:
    rate = sum((Decimal(r["quantity"]) * Decimal(r["unit_rate"]) for r in resources), Decimal("0"))
    return Position(
        boq_id=boq_id,
        ordinal=f"01.{n:03d}",
        description=f"Line {n}",
        unit="m3",
        quantity=qty,
        unit_rate=str(rate),
        total=str(rate * Decimal(qty)),
        metadata_={"resources": resources},
        sort_order=n,
        # Explicit and strictly increasing: the oldest carrier of a code owns it.
        created_at=_T0 + timedelta(minutes=n),
    )


class TestASharedResource:
    async def test_the_locked_bill_keeps_its_resource_rate(self, session: AsyncSession) -> None:
        bills = await _project_with_bills(session)
        master = _carrier(bills["editing"], 1, "1", [_res("SHR-100", "1", "100")])
        in_locked = _carrier(bills["locked"], 2, "2", [_res("SHR-100", "2", "100")])
        in_open = _carrier(bills["open"], 3, "3", [_res("SHR-100", "1", "100")])
        session.add_all([master, in_locked, in_open])
        await session.flush()
        ids = {"master": master.id, "in_locked": in_locked.id, "in_open": in_open.id}
        await _lock(session, bills["locked"])
        locked_before = await _stored(session, ids["in_locked"])
        sent = [{**_res("SHR-100", "1", "120"), "quantity": 1.0, "unit_rate": 120.0, "total": 120.0}]

        edited = await BOQService(session).update_position(ids["master"], PositionUpdate(metadata={"resources": sent}))
        await session.flush()

        assert await _stored(session, ids["in_locked"]) == locked_before
        _description, rate, total, _version, meta = await _stored(session, ids["in_open"])
        assert Decimal(str(meta["resources"][0]["unit_rate"])) == Decimal("120")
        assert Decimal(str(rate)) == Decimal("120")
        assert Decimal(str(total)) == Decimal("360")
        info = _info(edited)
        assert info["resource_propagated_to"] == 1
        assert info["locked_skipped"] == 1
        assert info["locked_boqs"] == [{"id": str(bills["locked"]), "name": "Approved estimate"}]
