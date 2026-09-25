# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A back-charge names a real party and a real source, and shows up as a deduction.

A back-charge used to carry the responsible party and its origin as free text
only, so nothing could ask "what does this subcontractor owe us back". These
tests pin the links: a back-charge can point at a subcontractor or a contact
(the text stays as a fallback label), and at the NCR or punch item it came
from; every link is checked against the project; and an agreed back-charge is
visible through :func:`pending_backcharges` as a pending deduction for that
subcontractor, per currency, net of what was already recovered and of other
parties' shares when the charge was apportioned.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contacts.models import Contact
from app.modules.cost_recovery.schemas import ApportionmentShareIn, BackChargeCreate, BackChargeUpdate
from app.modules.cost_recovery.service import (
    InvalidBackChargeLink,
    apportion_back_charge,
    create_back_charge,
    pending_backcharges,
    update_back_charge,
)
from app.modules.ncr.models import NCR
from app.modules.projects.models import Project
from app.modules.punchlist.models import PunchItem
from app.modules.subcontractors.models import Subcontractor
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession, currency: str = "EUR") -> uuid.UUID:
    user = User(
        email=f"bcl-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="BCL",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(name=f"BCL {uuid.uuid4().hex[:6]}", owner_id=user.id, currency=currency)
    session.add(proj)
    await session.flush()
    return proj.id


async def _sub(session: AsyncSession, *, contact_id: uuid.UUID | None = None) -> Subcontractor:
    sub = Subcontractor(legal_name=f"Drywall {uuid.uuid4().hex[:6]} GmbH", contact_id=contact_id)
    session.add(sub)
    await session.flush()
    return sub


async def _contact(session: AsyncSession) -> Contact:
    contact = Contact(contact_type="subcontractor", company_name=f"Tiles {uuid.uuid4().hex[:6]}")
    session.add(contact)
    await session.flush()
    return contact


async def _ncr(session: AsyncSession, project_id: uuid.UUID) -> NCR:
    ncr = NCR(
        project_id=project_id,
        ncr_number=f"NCR-{uuid.uuid4().hex[:4]}",
        title="Cracked screed level 2",
        description="Screed cracked across grid B",
        ncr_type="workmanship",
        severity="major",
        cost_impact="1250.50",
    )
    session.add(ncr)
    await session.flush()
    return ncr


async def _punch(session: AsyncSession, project_id: uuid.UUID) -> PunchItem:
    item = PunchItem(
        project_id=project_id,
        title="Damaged door frame",
        rework_cost="480.00",
        rework_cost_currency="EUR",
    )
    session.add(item)
    await session.flush()
    return item


async def _agree(session: AsyncSession, project_id: uuid.UUID, bc_id: uuid.UUID) -> None:
    await update_back_charge(session, project_id, bc_id, BackChargeUpdate(status="agreed"))


# --- party links ----------------------------------------------------------


@pytest.mark.asyncio
async def test_a_back_charge_links_to_a_subcontractor_and_keeps_a_label(session: AsyncSession) -> None:
    pid = await _project(session)
    sub = await _sub(session)

    bc = await create_back_charge(session, pid, BackChargeCreate(subcontractor_id=sub.id, gross_amount=Decimal("100")))

    assert bc.subcontractor_id == sub.id
    # A blank label is filled from the subcontractor so the ledger groups it
    # under a name rather than "unassigned".
    assert bc.responsible_party == sub.legal_name


@pytest.mark.asyncio
async def test_a_contact_of_a_subcontractor_resolves_to_the_subcontractor(session: AsyncSession) -> None:
    pid = await _project(session)
    contact = await _contact(session)
    sub = await _sub(session, contact_id=contact.id)

    bc = await create_back_charge(session, pid, BackChargeCreate(contact_id=contact.id, gross_amount=Decimal("100")))

    assert bc.contact_id == contact.id
    assert bc.subcontractor_id == sub.id


@pytest.mark.asyncio
async def test_an_unknown_subcontractor_is_refused(session: AsyncSession) -> None:
    pid = await _project(session)
    with pytest.raises(InvalidBackChargeLink):
        await create_back_charge(session, pid, BackChargeCreate(subcontractor_id=uuid.uuid4()))


@pytest.mark.asyncio
async def test_an_unknown_contact_is_refused(session: AsyncSession) -> None:
    pid = await _project(session)
    with pytest.raises(InvalidBackChargeLink):
        await create_back_charge(session, pid, BackChargeCreate(contact_id=uuid.uuid4()))


# --- source links ---------------------------------------------------------


@pytest.mark.asyncio
async def test_a_back_charge_from_a_punch_item_takes_its_rework_cost(session: AsyncSession) -> None:
    pid = await _project(session)
    punch = await _punch(session, pid)

    bc = await create_back_charge(session, pid, BackChargeCreate(punch_item_id=punch.id))

    assert bc.punch_item_id == punch.id
    assert bc.gross_amount == Decimal("480.00")
    assert bc.currency == "EUR"
    assert bc.description == "Damaged door frame"


@pytest.mark.asyncio
async def test_a_back_charge_from_an_ncr_takes_its_cost_impact(session: AsyncSession) -> None:
    pid = await _project(session)
    ncr = await _ncr(session, pid)

    bc = await create_back_charge(session, pid, BackChargeCreate(ncr_id=ncr.id))

    assert bc.ncr_id == ncr.id
    assert bc.gross_amount == Decimal("1250.50")
    assert bc.source_ref == ncr.ncr_number


@pytest.mark.asyncio
async def test_a_source_from_another_project_is_refused(session: AsyncSession) -> None:
    pid = await _project(session)
    other = await _project(session)
    ncr = await _ncr(session, other)
    punch = await _punch(session, other)

    with pytest.raises(InvalidBackChargeLink):
        await create_back_charge(session, pid, BackChargeCreate(ncr_id=ncr.id))
    with pytest.raises(InvalidBackChargeLink):
        await create_back_charge(session, pid, BackChargeCreate(punch_item_id=punch.id))


# --- pending deduction ----------------------------------------------------


@pytest.mark.asyncio
async def test_only_an_agreed_back_charge_is_a_pending_deduction(session: AsyncSession) -> None:
    pid = await _project(session)
    sub = await _sub(session)
    proposed = await create_back_charge(
        session, pid, BackChargeCreate(subcontractor_id=sub.id, gross_amount=Decimal("300"))
    )
    agreed = await create_back_charge(
        session, pid, BackChargeCreate(subcontractor_id=sub.id, gross_amount=Decimal("1000"))
    )
    await _agree(session, pid, agreed.id)
    await update_back_charge(session, pid, agreed.id, BackChargeUpdate(recovered_amount=Decimal("250")))

    pending = await pending_backcharges(session, sub.id)

    assert [p.back_charge_id for p in pending.items] == [agreed.id]
    assert pending.items[0].amount == Decimal("750.00")
    assert pending.totals == {"EUR": Decimal("750.00")}
    assert proposed.id not in {p.back_charge_id for p in pending.items}


@pytest.mark.asyncio
async def test_pending_deductions_never_sum_across_currencies(session: AsyncSession) -> None:
    pid = await _project(session)
    sub = await _sub(session)
    eur = await create_back_charge(session, pid, BackChargeCreate(subcontractor_id=sub.id, gross_amount=Decimal("100")))
    usd = await create_back_charge(
        session,
        pid,
        BackChargeCreate(subcontractor_id=sub.id, gross_amount=Decimal("40"), currency="USD"),
    )
    await _agree(session, pid, eur.id)
    await _agree(session, pid, usd.id)

    pending = await pending_backcharges(session, sub.id)

    assert pending.totals == {"EUR": Decimal("100.00"), "USD": Decimal("40.00")}


@pytest.mark.asyncio
async def test_pending_deductions_filter_by_project(session: AsyncSession) -> None:
    pid = await _project(session)
    other = await _project(session)
    sub = await _sub(session)
    here = await create_back_charge(session, pid, BackChargeCreate(subcontractor_id=sub.id, gross_amount=Decimal("10")))
    there = await create_back_charge(
        session, other, BackChargeCreate(subcontractor_id=sub.id, gross_amount=Decimal("20"))
    )
    await _agree(session, pid, here.id)
    await _agree(session, other, there.id)

    assert len((await pending_backcharges(session, sub.id)).items) == 2
    scoped = await pending_backcharges(session, sub.id, project_id=pid)
    assert [p.back_charge_id for p in scoped.items] == [here.id]


@pytest.mark.asyncio
async def test_an_apportioned_charge_deducts_only_this_subcontractors_share(session: AsyncSession) -> None:
    pid = await _project(session)
    sub = await _sub(session)
    bc = await create_back_charge(session, pid, BackChargeCreate(subcontractor_id=sub.id, gross_amount=Decimal("1000")))
    await _agree(session, pid, bc.id)
    await apportion_back_charge(
        session,
        pid,
        bc.id,
        [
            ApportionmentShareIn(party=sub.legal_name, share_pct=Decimal("0.6")),
            ApportionmentShareIn(party="Architect", share_pct=Decimal("0.4")),
        ],
    )

    pending = await pending_backcharges(session, sub.id)

    assert pending.items[0].apportioned is True
    assert pending.items[0].amount == Decimal("600.00")


@pytest.mark.asyncio
async def test_relinking_on_update_is_checked(session: AsyncSession) -> None:
    pid = await _project(session)
    bc = await create_back_charge(session, pid, BackChargeCreate(gross_amount=Decimal("10")))
    with pytest.raises(InvalidBackChargeLink):
        await update_back_charge(session, pid, bc.id, BackChargeUpdate(subcontractor_id=uuid.uuid4()))
    sub = await _sub(session)
    updated = await update_back_charge(session, pid, bc.id, BackChargeUpdate(subcontractor_id=sub.id))
    assert updated is not None and updated.subcontractor_id == sub.id


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1250.50", Decimal("1250.50")),
        ("EUR 8400", Decimal("8400")),
        ("8400 EUR", Decimal("8400")),
        ("8.400,00", None),
        ("about a week of rework", None),
        ("-10", None),
        ("", None),
    ],
)
def test_a_cost_impact_is_read_only_when_it_is_a_plain_figure(raw: str, expected: Decimal | None) -> None:
    from app.modules.cost_recovery.service import _parse_money

    assert _parse_money(raw) == expected


@pytest.mark.asyncio
async def test_a_cost_impact_in_another_currency_keeps_its_currency(session: AsyncSession) -> None:
    pid = await _project(session, currency="USD")
    ncr = await _ncr(session, pid)
    ncr.cost_impact = "EUR 8400"
    await session.flush()

    bc = await create_back_charge(session, pid, BackChargeCreate(ncr_id=ncr.id))

    assert bc.gross_amount == Decimal("8400")
    assert bc.currency == "EUR"


@pytest.mark.asyncio
async def test_a_charge_apportioned_under_its_own_label_is_still_pending(session: AsyncSession) -> None:
    pid = await _project(session)
    bc = await create_back_charge(
        session, pid, BackChargeCreate(responsible_party="Drywall Co", gross_amount=Decimal("500"))
    )
    sub = await _sub(session)
    await update_back_charge(session, pid, bc.id, BackChargeUpdate(subcontractor_id=sub.id))
    await _agree(session, pid, bc.id)
    await apportion_back_charge(session, pid, bc.id, [ApportionmentShareIn(party="Drywall Co", share_pct=Decimal("1"))])

    pending = await pending_backcharges(session, sub.id)

    assert [p.amount for p in pending.items] == [Decimal("500.00")]
