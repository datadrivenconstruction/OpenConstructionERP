# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: in academy mode a tender recipient links only the learner's own firm.

The second way an award names a counterparty: a tender award drafts its
contract with the directory subcontractor the winning bidder was invited as,
read from the package's distribution list. A recipient's ``subcontractor_id``
is a free string from the request, so on an academy box a learner could
invite, award and contract with another learner's firm. In academy mode a
recipient may link only a subcontractor the learner created; any other id,
including one that does not exist, is refused alike (404 ``Subcontractor not
found``). A recipient without a link is unchanged. An admin is not limited,
and nothing changes with the flag off.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.modules.subcontractors.models import Subcontractor
from app.modules.tendering.models import TenderPackage
from app.modules.tendering.schemas import RecipientCreate
from app.modules.tendering.service import TenderingService
from tests.pg.academy_isolation.rows import make_project, make_user

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]


async def _setup(session, *, actor_role: str = "manager"):
    alice = await make_user(session, name="Alice", role=actor_role)
    bob = await make_user(session, name="Bob")
    project = await make_project(session, alice)
    package = TenderPackage(project_id=project.id, name="Shell works", status="draft", metadata_={})
    mine = Subcontractor(legal_name="Alice Beton", created_by=str(alice.id))
    theirs = Subcontractor(legal_name="Bob Beton", created_by=str(bob.id))
    session.add_all([package, mine, theirs])
    await session.flush()
    return alice, package, mine, theirs


def _recipient(sub_id: object | None, name: str = "Beton") -> RecipientCreate:
    return RecipientCreate(
        company_name=name,
        email=f"{name.lower().replace(' ', '.')}@example.test",
        subcontractor_id=str(sub_id) if sub_id else None,
    )


async def test_academy_on_a_recipient_cannot_link_another_learners_firm(pg_session, academy, events) -> None:
    academy(True)
    alice, package, _mine, theirs = await _setup(pg_session)
    svc = TenderingService(pg_session)

    for sub_id in (theirs.id, uuid.uuid4(), "not-an-id"):
        with pytest.raises(HTTPException) as caught:
            await svc.add_recipient(package.id, _recipient(sub_id), actor_id=str(alice.id))
        assert (caught.value.status_code, caught.value.detail) == (404, "Subcontractor not found")
    assert await svc.list_recipients(package.id) == []


async def test_academy_on_own_firm_and_unlinked_recipients_still_work(pg_session, academy, events) -> None:
    academy(True)
    alice, package, mine, _theirs = await _setup(pg_session)
    svc = TenderingService(pg_session)

    linked = await svc.add_recipient(package.id, _recipient(mine.id, "Alice Beton"), actor_id=str(alice.id))
    plain = await svc.add_recipient(package.id, _recipient(None, "Walk In"), actor_id=str(alice.id))

    assert linked.subcontractor_id == str(mine.id)
    assert plain.subcontractor_id is None


async def test_academy_on_an_admin_is_not_limited(pg_session, academy, events) -> None:
    academy(True)
    admin, package, _mine, theirs = await _setup(pg_session, actor_role="admin")

    row = await TenderingService(pg_session).add_recipient(package.id, _recipient(theirs.id), actor_id=str(admin.id))

    assert row.subcontractor_id == str(theirs.id)


async def test_academy_off_unchanged(pg_session, academy, events) -> None:
    academy(False)
    alice, package, _mine, theirs = await _setup(pg_session)

    row = await TenderingService(pg_session).add_recipient(package.id, _recipient(theirs.id), actor_id=str(alice.id))

    assert row.subcontractor_id == str(theirs.id)
