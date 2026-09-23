# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A generic bill update cannot move a locked bill's status or unlock it.

Status and lock mean this together. ``POST /boqs/{id}/lock`` approves a bill:
it sets ``is_locked``, records the approver and moves the status to ``final``.
``POST /boqs/{id}/unlock`` (admin or manager only) reverses both. On an
unlocked bill ``final`` without the lock is the editor's "in review" state:
"Submit for review" PATCHes ``status: final`` and "Request changes" PATCHes it
back to ``draft``, and that flow stays exactly as it is.

``PATCH /boqs/{id}`` could also move a LOCKED bill's status, to ``draft`` or to
``archived``, with nothing more than ``boq.update``. The bill then read as a
draft while every writer still refused it as locked, and the unlock endpoint's
role check and audit row were skipped. Now a status change on a locked bill is
refused with the same 409 as every other write to it. An echo of the current
status still passes, so a client that sends the whole header back is not
refused, and the other header fields keep working on a locked bill, as the lock
guard's docstring says they do.

``BOQUpdate`` has no ``is_locked`` field, and the last test holds that: a body
carrying ``is_locked: false`` leaves the bill locked.

Run:
    cd backend
    python -m pytest tests/modules/boq/test_a_locked_bill_keeps_its_status.py -v
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BOQ
from app.modules.boq.schemas import BOQUpdate
from app.modules.boq.service import BOQService
from app.modules.projects.models import Project
from tests._pg import transactional_session

LOCKED_DETAIL = "BOQ is locked and cannot be modified. Create a revision to make changes."


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    # FK triggers off so a project can be seeded without standing up a user row.
    async with transactional_session(disable_fks=True) as s:
        yield s


async def _seed_bill(session: AsyncSession, *, locked: bool) -> uuid.UUID:
    """A bill, locked the way the lock endpoint leaves it when ``locked``."""
    project = Project(
        name=f"Locked status {uuid.uuid4().hex[:6]}",
        currency="EUR",
        region="DACH",
        owner_id=uuid.uuid4(),
    )
    session.add(project)
    await session.flush()
    boq = BOQ(
        project_id=project.id,
        name="Approved estimate",
        status="final" if locked else "draft",
        is_locked=locked,
        metadata_={},
    )
    session.add(boq)
    await session.flush()
    boq_id = boq.id
    session.expunge(boq)
    return boq_id


async def _state(session: AsyncSession, boq_id: uuid.UUID) -> tuple[str, bool, str]:
    """(status, is_locked, name), straight from the table."""
    row = (await session.execute(select(BOQ.status, BOQ.is_locked, BOQ.name).where(BOQ.id == boq_id))).one()
    return row[0], row[1], row[2]


class TestALockedBill:
    @pytest.mark.parametrize("new_status", ["draft", "archived"])
    async def test_a_status_change_is_refused(self, session: AsyncSession, new_status: str) -> None:
        boq_id = await _seed_bill(session, locked=True)

        with pytest.raises(HTTPException) as exc:
            await BOQService(session).update_boq(boq_id, BOQUpdate(status=new_status))

        assert exc.value.status_code == 409
        assert exc.value.detail == LOCKED_DETAIL
        assert await _state(session, boq_id) == ("final", True, "Approved estimate")

    async def test_a_status_change_is_refused_with_the_rest_of_the_patch(self, session: AsyncSession) -> None:
        """Nothing of a refused body lands, not even the fields that alone would pass."""
        boq_id = await _seed_bill(session, locked=True)

        with pytest.raises(HTTPException) as exc:
            await BOQService(session).update_boq(boq_id, BOQUpdate(name="Renamed", status="draft"))

        assert exc.value.status_code == 409
        assert await _state(session, boq_id) == ("final", True, "Approved estimate")

    async def test_an_echo_of_the_current_status_passes(self, session: AsyncSession) -> None:
        """A client that sends the header back unchanged is not refused."""
        boq_id = await _seed_bill(session, locked=True)

        await BOQService(session).update_boq(boq_id, BOQUpdate(name="Renamed", status="final"))
        await session.flush()

        assert await _state(session, boq_id) == ("final", True, "Renamed")

    async def test_a_header_field_still_changes(self, session: AsyncSession) -> None:
        """The control: the lock guards the figures, not the bill's name."""
        boq_id = await _seed_bill(session, locked=True)

        await BOQService(session).update_boq(boq_id, BOQUpdate(name="Renamed"))
        await session.flush()

        assert await _state(session, boq_id) == ("final", True, "Renamed")

    async def test_a_body_that_says_unlocked_leaves_it_locked(self, session: AsyncSession) -> None:
        """No back door: the update schema has no lock field to write."""
        boq_id = await _seed_bill(session, locked=True)
        body = BOQUpdate.model_validate({"is_locked": False, "name": "Renamed"})

        await BOQService(session).update_boq(boq_id, body)
        await session.flush()

        assert await _state(session, boq_id) == ("final", True, "Renamed")


class TestAnUnlockedBill:
    async def test_submit_for_review_and_request_changes_still_work(self, session: AsyncSession) -> None:
        """The editor's review flow: draft to final and back, the lock untouched."""
        boq_id = await _seed_bill(session, locked=False)
        service = BOQService(session)

        await service.update_boq(boq_id, BOQUpdate(status="final"))
        await session.flush()
        assert await _state(session, boq_id) == ("final", False, "Approved estimate")

        await service.update_boq(boq_id, BOQUpdate(status="draft"))
        await session.flush()
        assert await _state(session, boq_id) == ("draft", False, "Approved estimate")

    async def test_an_unlocked_bill_can_still_be_archived(self, session: AsyncSession) -> None:
        boq_id = await _seed_bill(session, locked=False)

        await BOQService(session).update_boq(boq_id, BOQUpdate(status="archived"))
        await session.flush()

        assert await _state(session, boq_id) == ("archived", False, "Approved estimate")
