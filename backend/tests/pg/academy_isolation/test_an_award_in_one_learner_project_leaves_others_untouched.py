# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: an award in one learner's project leaves the others untouched (regression for E9).

Awarding a bid package fires a detached subscriber
(``_wave5_cross_module_subscribers._on_bid_package_awarded``) that drafts a
contract in its own session, outside the request that awarded. Detached code
is where a write can land in the wrong place unnoticed, so this pins what it
writes: a contract in the awarding learner's project, and nothing another
learner can see. The other learner's contracts, contacts and the subcontractor
directory read the same before and after, with the flag on and off.

The award has to draft its contract here, or an award that wrote nothing would
pass as "left the others untouched".

The subcontractor directory is install-wide, not per learner: its list has no
tenant filter. "Reads the same" there only says the award added nothing to it,
not that one learner cannot see another learner's subcontractors.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.dependencies import accessible_project_ids
from app.modules.bid_management.models import BidPackage
from app.modules.bid_management.schemas import BidderCreate
from app.modules.bid_management.service import BidManagementService
from app.modules.contacts.models import Contact
from app.modules.contacts.service import ContactService
from app.modules.contracts.models import Contract
from app.modules.notifications import _wave5_cross_module_subscribers as w5
from app.modules.subcontractors.models import Subcontractor
from app.modules.subcontractors.service import SubcontractorService
from tests.pg.academy_isolation.rows import make_project, make_user
from tests.pg.tender_award_fixtures import _NonCommittingSession

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]


async def _view_of(session, learner) -> dict[str, set]:
    """Everything the list endpoints would show ``learner``, as id sets."""
    projects = await accessible_project_ids(session, str(learner.id))
    assert projects is not None, "a learner is never an admin here"
    contracts = await session.execute(select(Contract.id).where(Contract.project_id.in_(projects)))
    contacts, _ = await ContactService(session).list_contacts(owner_id=str(learner.id), limit=500)
    subs, _ = await SubcontractorService(session).subs.list_all(limit=500, active_only=False)
    return {
        "contracts": set(contracts.scalars().all()),
        "contacts": {c.id for c in contacts},
        "subcontractors": {s.id for s in subs},
    }


async def _award(session, monkeypatch, package, bidder) -> None:
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


@pytest.mark.parametrize("academy_on", [True, False], ids=["academy_on", "academy_off"])
async def test_another_learners_lists_read_the_same_after_an_award(
    pg_session, academy, events, monkeypatch, academy_on: bool
) -> None:
    academy(academy_on)
    alice = await make_user(pg_session, name="Alice")
    bob = await make_user(pg_session, name="Bob")
    alice_project = await make_project(pg_session, alice, "Alice course project")
    bob_project = await make_project(pg_session, bob, "Bob course project")
    bob_contact = Contact(contact_type="client", company_name="Bob client", tenant_id=str(bob.id))
    pg_session.add(bob_contact)
    await pg_session.flush()
    pg_session.add(
        Contract(code="BOB-1", title="Bob own", project_id=bob_project.id, contract_type="lump_sum", currency="EUR")
    )

    contact = Contact(contact_type="subcontractor", company_name="Rheinbeton GmbH", tenant_id=str(alice.id))
    pg_session.add(contact)
    await pg_session.flush()
    sub = Subcontractor(legal_name="Rheinbeton GmbH", contact_id=contact.id)
    pg_session.add(sub)
    package = BidPackage(
        project_id=alice_project.id,
        code=f"BP-{uuid.uuid4().hex[:8]}",
        title="Concrete",
        currency="EUR",
        created_by=str(alice.id),
    )
    pg_session.add(package)
    await pg_session.flush()
    bidder = await BidManagementService(pg_session).create_bidder(
        BidderCreate(package_id=package.id, company_name="Rheinbeton", subcontractor_id=sub.id)
    )

    before = await _view_of(pg_session, bob)
    assert before["contacts"] == {bob_contact.id}
    alice_before = await _view_of(pg_session, alice)

    await _award(pg_session, monkeypatch, package, bidder)

    drafted = (
        (await pg_session.execute(select(Contract).where(Contract.project_id == alice_project.id))).scalars().all()
    )
    assert len(drafted) == 1, "the award drafted no contract, so this test proves nothing"
    assert str(drafted[0].created_by) == str(alice.id)
    assert await _view_of(pg_session, bob) == before
    assert (await _view_of(pg_session, alice))["contracts"] == alice_before["contracts"] | {drafted[0].id}
