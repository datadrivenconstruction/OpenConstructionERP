# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: in academy mode a bidder links only the learner's own firm.

A bidder may point at a directory subcontractor and a contact, and an award
turns those links into the drafted contract's counterparty. Both ids come
from the request body and were only checked to exist, so on an academy box a
learner could bid, award and contract with another learner's firm. In academy
mode a learner's bidder may link only a subcontractor they created and a
contact in their own address book; any other id reads exactly like one that
does not exist (400 ``Subcontractor not found`` / ``Contact not found``), so
the award can only ever name the learner's own party. An admin is not limited,
and nothing changes with the flag off.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.modules.bid_management.models import BidPackage
from app.modules.bid_management.schemas import BidderCreate, BidderUpdate
from app.modules.bid_management.service import BidManagementService
from app.modules.contacts.models import Contact
from app.modules.contracts.models import Contract
from app.modules.notifications import _wave5_cross_module_subscribers as w5
from app.modules.subcontractors.models import Subcontractor
from tests.pg.academy_isolation.rows import make_project, make_user
from tests.pg.tender_award_fixtures import _NonCommittingSession

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]


async def _firm(session, owner, name: str) -> tuple[Subcontractor, Contact]:
    contact = Contact(contact_type="subcontractor", company_name=name, tenant_id=str(owner.id))
    session.add(contact)
    await session.flush()
    sub = Subcontractor(legal_name=name, contact_id=contact.id, created_by=str(owner.id))
    session.add(sub)
    await session.flush()
    return sub, contact


async def _setup(session, *, actor_role: str = "manager"):
    alice = await make_user(session, name="Alice", role=actor_role)
    bob = await make_user(session, name="Bob")
    project = await make_project(session, alice)
    package = BidPackage(
        project_id=project.id,
        code=f"BP-{uuid.uuid4().hex[:8]}",
        title="Concrete",
        currency="EUR",
        created_by=str(alice.id),
    )
    session.add(package)
    await session.flush()
    mine = await _firm(session, alice, "Alice Beton")
    theirs = await _firm(session, bob, "Bob Beton")
    return alice, package, mine, theirs


async def _award(session, monkeypatch, package, bidder) -> Contract:
    monkeypatch.setattr(w5, "async_session_factory", lambda: _NonCommittingSession(session))
    await w5._on_bid_package_awarded(
        w5.Event(
            name="bid_management.package.awarded",
            data={
                "package_id": str(package.id),
                "project_id": str(package.project_id),
                "awarded_bidder_id": str(bidder.id),
                "awarded_amount": "95000.00",
                "currency": "EUR",
            },
            source_module="bid_management",
        )
    )
    return (await session.execute(select(Contract).where(Contract.project_id == package.project_id))).scalar_one()


def _not_found(caught, what: str) -> None:
    assert caught.value.status_code == 400
    assert caught.value.detail == f"{what} not found"


async def test_academy_on_a_bidder_cannot_link_another_learners_firm(pg_session, academy, events) -> None:
    academy(True)
    alice, package, (my_sub, _my_contact), (their_sub, their_contact) = await _setup(pg_session)
    svc = BidManagementService(pg_session)

    with pytest.raises(HTTPException) as by_sub:
        await svc.create_bidder(
            BidderCreate(package_id=package.id, company_name="Bob Beton", subcontractor_id=their_sub.id),
            actor_id=str(alice.id),
        )
    _not_found(by_sub, "Subcontractor")
    with pytest.raises(HTTPException) as by_contact:
        await svc.create_bidder(
            BidderCreate(package_id=package.id, company_name="Bob Beton", contact_id=their_contact.id),
            actor_id=str(alice.id),
        )
    _not_found(by_contact, "Contact")
    with pytest.raises(HTTPException) as mixed:
        await svc.create_bidder(
            BidderCreate(
                package_id=package.id, company_name="Mixed", subcontractor_id=my_sub.id, contact_id=their_contact.id
            ),
            actor_id=str(alice.id),
        )
    _not_found(mixed, "Contact")

    bidder = await svc.create_bidder(
        BidderCreate(package_id=package.id, company_name="Alice Beton", subcontractor_id=my_sub.id),
        actor_id=str(alice.id),
    )
    with pytest.raises(HTTPException) as moved:
        await svc.update_bidder(bidder.id, BidderUpdate(subcontractor_id=their_sub.id), actor_id=str(alice.id))
    _not_found(moved, "Subcontractor")
    await pg_session.refresh(bidder)
    assert bidder.subcontractor_id == my_sub.id


async def test_academy_on_the_award_names_the_learners_own_firm(pg_session, academy, events, monkeypatch) -> None:
    academy(True)
    alice, package, (my_sub, my_contact), _theirs = await _setup(pg_session)

    bidder = await BidManagementService(pg_session).create_bidder(
        BidderCreate(package_id=package.id, company_name="Alice Beton", subcontractor_id=my_sub.id),
        actor_id=str(alice.id),
    )
    assert bidder.contact_id == my_contact.id
    contract = await _award(pg_session, monkeypatch, package, bidder)

    assert contract.counterparty_id == my_sub.id
    assert contract.metadata_["counterparty_contact_id"] == str(my_contact.id)


async def test_academy_on_an_admin_is_not_limited(pg_session, academy, events) -> None:
    academy(True)
    admin, package, _mine, (their_sub, their_contact) = await _setup(pg_session, actor_role="admin")

    bidder = await BidManagementService(pg_session).create_bidder(
        BidderCreate(package_id=package.id, company_name="Bob Beton", subcontractor_id=their_sub.id),
        actor_id=str(admin.id),
    )

    assert (bidder.subcontractor_id, bidder.contact_id) == (their_sub.id, their_contact.id)


async def test_academy_off_unchanged(pg_session, academy, events, monkeypatch) -> None:
    academy(False)
    alice, package, _mine, (their_sub, their_contact) = await _setup(pg_session)

    bidder = await BidManagementService(pg_session).create_bidder(
        BidderCreate(package_id=package.id, company_name="Bob Beton", subcontractor_id=their_sub.id),
        actor_id=str(alice.id),
    )
    assert bidder.contact_id == their_contact.id
    contract = await _award(pg_session, monkeypatch, package, bidder)

    assert contract.counterparty_id == their_sub.id
