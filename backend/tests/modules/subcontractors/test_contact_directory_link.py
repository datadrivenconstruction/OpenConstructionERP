# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A subcontractor contact person and a tender recipient resolve to the contacts directory.

Runs the service layer against PostgreSQL inside a rolled-back transaction.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.modules.subcontractors.models  # noqa: F401 - register metadata
import app.modules.tendering.models  # noqa: F401 - register metadata
from app.core.validation.engine import validation_engine
from app.modules.contacts.models import Contact
from app.modules.subcontractors.models import Subcontractor, SubcontractorContact
from app.modules.subcontractors.schemas import SubcontractorContactCreate, SubcontractorContactUpdate
from app.modules.subcontractors.service import SubcontractorService
from app.modules.tendering.models import TenderPackage
from app.modules.tendering.schemas import RecipientCreate
from app.modules.tendering.service import TenderingService
from tests._pg import transactional_session

TENANT_A = str(uuid.uuid4())
TENANT_B = str(uuid.uuid4())


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session(disable_fks=True) as sess:
        yield sess


async def _sub(session: AsyncSession, owner: str) -> Subcontractor:
    sub = Subcontractor(legal_name="ACME Subs", prequalification_status="approved", created_by=owner)
    session.add(sub)
    await session.flush()
    return sub


def _create(sub: Subcontractor, email: str | None, name: str = "Ana Lopez") -> SubcontractorContactCreate:
    return SubcontractorContactCreate(subcontractor_id=sub.id, name=name, email=email)


async def _count(session: AsyncSession, email: str) -> int:
    stmt = select(func.count()).select_from(Contact).where(func.lower(Contact.primary_email) == email.lower())
    return (await session.execute(stmt)).scalar_one()


@pytest.mark.asyncio
async def test_a_new_person_gets_a_tagged_natural_person_contact(session: AsyncSession) -> None:
    svc = SubcontractorService(session)
    row = await svc.create_contact(_create(await _sub(session, TENANT_A), "Ana@Acme.test"), tenant_id=TENANT_A)
    contact = await session.get(Contact, row.contact_id)
    assert contact is not None
    assert contact.party_kind == "natural_person"
    assert "subcontractor" in contact.module_tags
    assert contact.primary_email == "ana@acme.test"


@pytest.mark.asyncio
async def test_an_existing_contact_is_reused_case_insensitively_and_not_merged(session: AsyncSession) -> None:
    existing = Contact(contact_type="client", primary_email="Ana@Acme.test", tenant_id=TENANT_A, created_by=TENANT_A)
    other = Contact(contact_type="client", primary_email="bob@acme.test", tenant_id=TENANT_A, created_by=TENANT_A)
    session.add_all([existing, other])
    await session.flush()
    svc = SubcontractorService(session)
    row = await svc.create_contact(_create(await _sub(session, TENANT_A), "ana@ACME.test"), tenant_id=TENANT_A)
    assert row.contact_id == existing.id
    # Editing the email to another existing contact relinks, it never merges the two.
    row = await svc.update_contact(row.id, SubcontractorContactUpdate(email="bob@acme.test"), tenant_id=TENANT_A)
    assert row.contact_id == other.id
    assert await session.get(Contact, existing.id) is not None


@pytest.mark.asyncio
async def test_no_email_leaves_the_person_unlinked(session: AsyncSession) -> None:
    svc = SubcontractorService(session)
    row = await svc.create_contact(_create(await _sub(session, TENANT_A), None), tenant_id=TENANT_A)
    assert row.contact_id is None


@pytest.mark.asyncio
async def test_the_same_email_in_two_tenants_gives_two_contacts(session: AsyncSession) -> None:
    svc = SubcontractorService(session)
    a = await svc.create_contact(_create(await _sub(session, TENANT_A), "same@acme.test"), tenant_id=TENANT_A)
    b = await svc.create_contact(_create(await _sub(session, TENANT_B), "same@acme.test"), tenant_id=TENANT_B)
    assert a.contact_id != b.contact_id
    assert await _count(session, "same@acme.test") == 2


@pytest.mark.asyncio
async def test_the_backfill_is_idempotent_and_dry_by_default(session: AsyncSession) -> None:
    from scripts.backfill_subcontractor_contact_links import backfill

    sub = await _sub(session, TENANT_A)
    session.add_all(
        [
            SubcontractorContact(subcontractor_id=sub.id, name="One", email="Backfill@Acme.test"),
            SubcontractorContact(subcontractor_id=sub.id, name="Two", email="backfill@acme.test"),
            SubcontractorContact(subcontractor_id=sub.id, name="Three", email=None),
        ]
    )
    await session.flush()

    dry = await backfill(session, apply=False)
    assert (dry["created"], dry["linked_existing"], dry["no_email"]) == (1, 1, 1)
    assert await _count(session, "backfill@acme.test") == 0

    first = await backfill(session, apply=True)
    assert first["created"] == 1
    assert await _count(session, "backfill@acme.test") == 1
    second = await backfill(session, apply=True)
    assert (second["created"], second["linked_existing"]) == (0, 0)
    assert await _count(session, "backfill@acme.test") == 1
    linked = (
        (await session.execute(select(SubcontractorContact.contact_id).where(SubcontractorContact.email.is_not(None))))
        .scalars()
        .all()
    )
    assert len(set(linked)) == 1 and None not in linked


async def _package(session: AsyncSession) -> TenderPackage:
    package = TenderPackage(project_id=uuid.uuid4(), name="Facade", description="")
    session.add(package)
    await session.flush()
    return package


def _firm(owner: str) -> Contact:
    return Contact(contact_type="subcontractor", primary_email="bids@firm.test", tenant_id=owner, created_by=owner)


@pytest.mark.asyncio
async def test_a_recipient_links_to_the_existing_contact(session: AsyncSession) -> None:
    contact = _firm(TENANT_A)
    session.add(contact)
    await session.flush()
    svc = TenderingService(session)
    by_email = await svc.add_recipient(
        (await _package(session)).id, RecipientCreate(company_name="Firm", email="BIDS@firm.test"), tenant_id=TENANT_A
    )
    assert by_email.contact_id == str(contact.id)
    explicit = await svc.add_recipient(
        (await _package(session)).id,
        RecipientCreate(company_name="Firm", email="x@firm.test", contact_id=contact.id),
        tenant_id=TENANT_A,
    )
    assert explicit.contact_id == str(contact.id)


@pytest.mark.asyncio
async def test_a_recipient_cannot_name_another_tenants_contact(session: AsyncSession) -> None:
    contact = _firm(TENANT_A)
    session.add(contact)
    await session.flush()
    package = await _package(session)
    svc = TenderingService(session)
    with pytest.raises(HTTPException) as err:
        await svc.add_recipient(
            package.id,
            RecipientCreate(company_name="Firm", email="bids@firm.test", contact_id=contact.id),
            tenant_id=TENANT_B,
        )
    assert err.value.status_code == 404
    unlinked = await svc.add_recipient(
        package.id, RecipientCreate(company_name="Firm", email="bids@firm.test"), tenant_id=TENANT_B
    )
    assert unlinked.contact_id is None


@pytest.mark.asyncio
async def test_the_rule_warns_about_an_unlinked_contact_person() -> None:
    async def run(names: list[str]):
        return await validation_engine.validate(
            data={"id": "ag-1", "title": "Drywall", "unlinked_contacts": names},
            rule_sets=["subcontract"],
            target_type="subcontract_agreement",
            target_id="ag-1",
            metadata={"locale": "en"},
        )

    report = await run(["Ana Lopez"])
    (warning,) = [r for r in report.warnings if r.rule_id == "subcontract.contact_linked"]
    assert "Ana Lopez" in warning.message
    clean = await run([])
    assert not [r for r in clean.warnings if r.rule_id == "subcontract.contact_linked"]
