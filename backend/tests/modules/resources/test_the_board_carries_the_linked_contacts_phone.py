# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The dispatcher board shows the linked contact's phone, read in one query for the whole roster."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.modules.projects.models  # noqa: F401
import app.modules.users.models  # noqa: F401
from app.database import Base
from app.modules.contacts.models import Contact
from app.modules.resources.models import Assignment, Resource
from app.modules.resources.schemas import BoardEntry, ResourceResponse
from app.modules.resources.service import ResourcesService


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(c, tables=[Contact.__table__, Resource.__table__, Assignment.__table__])
        )
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


TENANT = "tenant-a"


def _contact(phone: str | None, tenant: str = TENANT) -> Contact:
    return Contact(id=uuid.uuid4(), contact_type="employee", primary_phone=phone, tenant_id=tenant)


def _resource(code: str, contact_id: uuid.UUID | None) -> Resource:
    return Resource(id=uuid.uuid4(), code=code, name=code, resource_type="labor", contact_id=contact_id)


async def test_phone_comes_from_the_linked_contact_in_one_query(session) -> None:
    with_phone, without_phone = _contact(" +49 170 1234567 "), _contact(None)
    session.add_all([with_phone, without_phone])
    session.add_all(
        [
            _resource("R1", with_phone.id),
            _resource("R2", without_phone.id),
            _resource("R3", None),
            _resource("R4", with_phone.id),
        ]
    )
    await session.commit()

    contact_selects: list[str] = []

    def _count(conn, cursor, statement, *_):
        if "oe_contacts_contact" in statement:
            contact_selects.append(statement)

    event.listen(session.bind.sync_engine, "before_cursor_execute", _count)
    entries = await ResourcesService(session).board(
        datetime(2026, 11, 1, tzinfo=UTC), datetime(2026, 11, 8, tzinfo=UTC), tenant_id=TENANT
    )
    phones = {e["resource"].code: e["phone"] for e in entries}

    assert phones == {"R1": "+49 170 1234567", "R2": None, "R3": None, "R4": "+49 170 1234567"}
    assert len(contact_selects) == 1


async def test_a_contact_of_another_tenant_yields_no_phone(session) -> None:
    foreign = _contact("+1 555 0100", tenant="tenant-b")
    own = _contact("+1 555 0199")
    session.add_all([foreign, own, _resource("R1", foreign.id), _resource("R2", own.id)])
    await session.commit()
    window = (datetime(2026, 11, 1, tzinfo=UTC), datetime(2026, 11, 8, tzinfo=UTC))

    phones = {e["resource"].code: e["phone"] for e in await ResourcesService(session).board(*window, tenant_id=TENANT)}
    assert phones == {"R1": None, "R2": "+1 555 0199"}

    anonymous = await ResourcesService(session).board(*window, tenant_id=None)
    assert all(e["phone"] is None for e in anonymous)


def test_the_board_entry_exposes_an_optional_phone() -> None:
    assert BoardEntry.model_fields["phone"].default is None
    assert "phone" not in ResourceResponse.model_fields
