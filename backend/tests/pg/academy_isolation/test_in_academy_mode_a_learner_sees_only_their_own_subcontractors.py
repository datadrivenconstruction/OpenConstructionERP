# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: in academy mode a learner sees and edits only their own subcontractors.

The subcontractor directory is install-wide: the list, a single record, its
contact people, certificates, prequalifications and lien waivers carried no
tenant, owner or project filter, and any viewer could read them. On an academy
box that is every other learner's subcontractors, with legal name, tax id,
address and the contact people's names, emails and phones, and any editor could
change or block them. The table has no ``tenant_id``, so academy mode scopes a
non-admin to the rows they created (``created_by``): another learner's
subcontractor reads as missing (404) on every read and write keyed by it, and
the install-wide lists leave it out. An admin keeps the whole directory, and
with the flag off nothing changes.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.modules.subcontractors import router as sub_router
from app.modules.subcontractors.models import (
    Certificate,
    PrequalificationApplication,
    Subcontractor,
    SubcontractorContact,
)
from app.modules.subcontractors.schemas import (
    BlockRequest,
    CertificateCreate,
    SubcontractorContactCreate,
    SubcontractorContactUpdate,
    SubcontractorUpdate,
)
from tests.pg.academy_isolation.rows import make_user

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]


async def _setup(session):
    alice = await make_user(session, name="Alice")
    bob = await make_user(session, name="Bob")
    admin = await make_user(session, role="admin", name="Admin")
    mine = Subcontractor(legal_name="Alice Formwork Ltd", created_by=str(alice.id))
    theirs = Subcontractor(legal_name="Bob Steel GmbH", tax_id="DE123456789", created_by=str(bob.id))
    session.add_all([mine, theirs])
    await session.flush()
    person = SubcontractorContact(
        subcontractor_id=theirs.id, name="Bob Person", email="person@bobsteel.example", phone="+49 30 99"
    )
    cert = Certificate(subcontractor_id=theirs.id, cert_type="insurance", valid_until=date.today() + timedelta(days=10))
    prequal = PrequalificationApplication(subcontractor_id=theirs.id, status="submitted")
    session.add_all([person, cert, prequal])
    await session.flush()
    return alice, bob, admin, mine, theirs, person, cert, prequal


async def _list(session, caller) -> set:
    page = await sub_router.list_subcontractors(
        session=session,
        _user=str(caller.id),
        offset=0,
        limit=200,
        prequalification_status=None,
        trade_category=None,
        active_only=True,
        _perm=None,
    )
    return {item.id for item in page.items}


async def _expiring(session, caller) -> set:
    alerts = await sub_router.list_expiring_certificates(session=session, _user=str(caller.id), days=60, _perm=None)
    return {a.subcontractor_id for a in alerts}


async def _prequals(session, caller) -> set:
    rows = await sub_router.list_prequalifications(
        session=session, _user=str(caller.id), subcontractor_id=None, status_filter=None, _perm=None
    )
    return {r.subcontractor_id for r in rows}


def _missing(caught, detail: str) -> None:
    assert caught.value.status_code == 404
    assert caught.value.detail == detail


async def test_academy_on_another_learners_subcontractors_are_not_readable(pg_session, academy) -> None:
    academy(True)
    alice, _bob, _admin, mine, theirs, _person, _cert, _prequal = await _setup(pg_session)
    me = str(alice.id)

    assert theirs.id not in await _list(pg_session, alice)
    assert mine.id in await _list(pg_session, alice)
    assert theirs.id not in await _expiring(pg_session, alice)
    assert theirs.id not in await _prequals(pg_session, alice)

    reads = [
        sub_router.get_subcontractor(theirs.id, pg_session, me, None),
        sub_router.subcontractor_dashboard(theirs.id, pg_session, me, None),
        sub_router.subcontractor_award_eligibility(theirs.id, pg_session, me, None),
        sub_router.get_subcontractor_prequal(theirs.id, pg_session, me, None),
        sub_router.list_subcontractor_contacts(theirs.id, pg_session, me, None),
        sub_router.list_lien_waivers(theirs.id, pg_session, me, None),
        sub_router.list_certificates(session=pg_session, _user=me, subcontractor_id=theirs.id, _perm=None),
        sub_router.list_ratings(session=pg_session, _user=me, subcontractor_id=theirs.id, _perm=None),
        sub_router.list_prequalifications(
            session=pg_session, _user=me, subcontractor_id=theirs.id, status_filter=None, _perm=None
        ),
    ]
    for call in reads:
        with pytest.raises(HTTPException) as caught:
            await call
        _missing(caught, "Subcontractor not found")


async def test_academy_on_another_learners_subcontractors_are_not_writable(pg_session, academy) -> None:
    academy(True)
    alice, _bob, _admin, _mine, theirs, person, cert, prequal = await _setup(pg_session)
    me = str(alice.id)

    with pytest.raises(HTTPException) as caught:
        await sub_router.update_subcontractor(theirs.id, SubcontractorUpdate(legal_name="Taken"), pg_session, me, None)
    _missing(caught, "Subcontractor not found")
    with pytest.raises(HTTPException) as caught:
        await sub_router.block_subcontractor_endpoint(theirs.id, BlockRequest(reason="x"), me, pg_session, None)
    _missing(caught, "Subcontractor not found")
    with pytest.raises(HTTPException) as caught:
        await sub_router.delete_subcontractor(theirs.id, pg_session, me, None)
    _missing(caught, "Subcontractor not found")
    with pytest.raises(HTTPException) as caught:
        await sub_router.create_subcontractor_contact(
            SubcontractorContactCreate(subcontractor_id=theirs.id, name="Spy"), pg_session, me, None
        )
    _missing(caught, "Subcontractor not found")
    with pytest.raises(HTTPException) as caught:
        await sub_router.update_subcontractor_contact(
            person.id, SubcontractorContactUpdate(email="spy@x.example"), pg_session, me, None
        )
    _missing(caught, "Contact not found")
    with pytest.raises(HTTPException) as caught:
        await sub_router.create_certificate(
            CertificateCreate(subcontractor_id=theirs.id, cert_type="license"), pg_session, me, None
        )
    _missing(caught, "Subcontractor not found")
    with pytest.raises(HTTPException) as caught:
        await sub_router.delete_certificate(cert.id, pg_session, me, None)
    _missing(caught, "Certificate not found")
    with pytest.raises(HTTPException) as absent:
        await sub_router.submit_prequalification(uuid.uuid4(), pg_session, me, None)
    with pytest.raises(HTTPException) as caught:
        await sub_router.submit_prequalification(prequal.id, pg_session, me, None)
    _missing(caught, absent.value.detail)

    await pg_session.refresh(theirs)
    await pg_session.refresh(person)
    assert theirs.legal_name == "Bob Steel GmbH"
    assert not theirs.is_blocked
    assert person.email == "person@bobsteel.example"
    assert (await pg_session.execute(select(Certificate.id).where(Certificate.id == cert.id))).first() is not None


async def test_academy_on_own_rows_and_an_admin_still_work(pg_session, academy) -> None:
    academy(True)
    alice, _bob, admin, mine, theirs, _person, _cert, _prequal = await _setup(pg_session)
    me = str(alice.id)

    got = await sub_router.get_subcontractor(mine.id, pg_session, me, None)
    assert got.legal_name == "Alice Formwork Ltd"
    await sub_router.update_subcontractor(mine.id, SubcontractorUpdate(trade_name="AF"), pg_session, me, None)
    contact = await sub_router.create_subcontractor_contact(
        SubcontractorContactCreate(subcontractor_id=mine.id, name="Site lead"), pg_session, me, None
    )
    assert [c.id for c in await sub_router.list_subcontractor_contacts(mine.id, pg_session, me, None)] == [contact.id]

    assert {mine.id, theirs.id} <= await _list(pg_session, admin)
    assert theirs.id in await _expiring(pg_session, admin)
    assert theirs.id in await _prequals(pg_session, admin)
    seen = await sub_router.get_subcontractor(theirs.id, pg_session, str(admin.id), None)
    assert seen.tax_id == "DE123456789"


async def test_academy_off_unchanged(pg_session, academy) -> None:
    academy(False)
    alice, _bob, _admin, mine, theirs, person, _cert, _prequal = await _setup(pg_session)
    me = str(alice.id)

    assert {mine.id, theirs.id} <= await _list(pg_session, alice)
    assert theirs.id in await _expiring(pg_session, alice)
    assert theirs.id in await _prequals(pg_session, alice)
    seen = await sub_router.get_subcontractor(theirs.id, pg_session, me, None)
    assert seen.tax_id == "DE123456789"
    contacts = await sub_router.list_subcontractor_contacts(theirs.id, pg_session, me, None)
    assert [c.email for c in contacts] == [person.email]
