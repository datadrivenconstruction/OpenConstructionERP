# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: the negotiated award terms reach the contract, and a gated firm is not awarded.

Before, the tender award drafted every contract as a lump sum with empty
terms, valued at the lines sum. Now the award terms decide: the contract type
follows the final offer, a lump sum is spread over the lines pro rata, the
discount comes off, and retention, its cap and the payment discount land in
``Contract.terms``. A firm the directory blocks, or whose required certificate
lapsed, is refused at award (and a blocked one at invitation); a negotiated bid
needs its final offer, approved.

Worked examples (subcontractor award domain spec):

1. Unit prices 412,380.00, discount 3 % -> 400,008.60; retention 10 %, cap 5 %.
2. 120,000.00 + 98,450.00 + 50,000.00 revised to a lump sum of 255,000.00 ->
   113,987.71 + 93,517.41 + 47,494.88.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.modules.bid_management import events as bm_events
from app.modules.boq.models import BOQ, Position
from app.modules.contacts.models import Contact
from app.modules.contracts.models import Contract, ContractLine
from app.modules.projects.models import Project
from app.modules.subcontractors.models import Certificate, Subcontractor
from app.modules.tendering.award_schemas import AwardTermsIn, RoundIn
from app.modules.tendering.award_terms import AwardTermsService
from app.modules.tendering.models import TenderBid, TenderPackage
from app.modules.tendering.schemas import RecipientCreate
from app.modules.tendering.service import TenderingService
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio


class _NonCommittingSession:
    """The real session with ``commit`` demoted to ``flush``."""

    def __init__(self, inner) -> None:
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    async def commit(self) -> None:
        await self._inner.flush()

    async def close(self) -> None:
        return None

    async def __aenter__(self) -> _NonCommittingSession:
        return self

    async def __aexit__(self, *_exc) -> bool:
        return False


@pytest.fixture(autouse=True)
def _no_publish(monkeypatch):
    from app.core.events import event_bus

    monkeypatch.setattr(event_bus, "publish_detached", lambda *_a, **_kw: None)


async def _project(session, country: str | None = None) -> Project:
    owner = User(email=f"awt-{uuid.uuid4().hex[:8]}@example.test", hashed_password="x", full_name="Owner")
    session.add(owner)
    await session.flush()
    project = Project(name="Award terms", owner_id=owner.id, currency="EUR", country_code=country)
    session.add(project)
    await session.flush()
    return project


async def _package(session, project, rates: list[str], *, sub: Subcontractor | None = None, **bid_kw):
    boq = BOQ(project_id=project.id, name="Bill")
    session.add(boq)
    await session.flush()
    positions = []
    for i, _rate in enumerate(rates):
        pos = Position(boq_id=boq.id, ordinal=f"01.{i + 1:03d}", description=f"Line {i + 1}", unit="psch", quantity="1")
        session.add(pos)
        positions.append(pos)
    await session.flush()
    recipients = [{"email": "bids@drywall.test", "subcontractor_id": str(sub.id)}] if sub is not None else []
    package = TenderPackage(
        project_id=project.id, boq_id=boq.id, name="Drywall", status="evaluating", metadata_={"recipients": recipients}
    )
    session.add(package)
    await session.flush()
    bid = TenderBid(
        package_id=package.id,
        company_name="Drywall GmbH",
        contact_email="bids@drywall.test",
        total_amount=str(sum(D(r) for r in rates)),
        currency="EUR",
        status="submitted",
        line_items=[
            {"position_id": str(p.id), "description": p.description, "unit": "psch", "quantity": "1", "unit_rate": r}
            for p, r in zip(positions, rates, strict=True)
        ],
        **bid_kw,
    )
    session.add(bid)
    await session.flush()
    return package, bid


async def _award_and_draft(session, monkeypatch, package, bid) -> tuple[Contract, list[ContractLine]]:
    await TenderingService(session).apply_winner(package.id, bid.id)
    await session.flush()
    monkeypatch.setattr(bm_events, "async_session_factory", lambda: _NonCommittingSession(session))
    await bm_events._draft(package.id, bid.id, awarded_by=None)
    contract = (await session.execute(select(Contract).where(Contract.project_id == package.project_id))).scalar_one()
    lines = list(
        (
            await session.execute(
                select(ContractLine).where(ContractLine.contract_id == contract.id).order_by(ContractLine.order_index)
            )
        )
        .scalars()
        .all()
    )
    return contract, lines


async def test_a_revised_lump_sum_becomes_a_lump_sum_contract_spread_over_the_lines(pg_session, monkeypatch):
    project = await _project(pg_session)
    package, bid = await _package(pg_session, project, ["120000.00", "98450.00", "50000.00"])
    svc = AwardTermsService(pg_session)
    await svc.save_terms(package.id, AwardTermsIn(bid_id=bid.id, lump_sum=D("255000.00")), None)

    contract, lines = await _award_and_draft(pg_session, monkeypatch, package, bid)

    assert contract.contract_type == "lump_sum"
    assert contract.total_value == D("255000.00")
    assert [ln.total_value for ln in lines] == [D("113987.71"), D("93517.41"), D("47494.88")]
    assert [ln.unit_rate for ln in lines] == [D("120000.00"), D("98450.00"), D("50000.00")]
    assert contract.terms["award_terms"]["offer_total"] == "255000.00"


async def test_a_unit_price_award_takes_its_discount_retention_and_payment_discount(pg_session, monkeypatch):
    project = await _project(pg_session)
    package, bid = await _package(pg_session, project, ["200000.00", "150000.00", "62380.00"])
    terms = AwardTermsIn(
        bid_id=bid.id,
        discount_percent=D("3"),
        retention_percent=D("10"),
        retention_cap_percent=D("5"),
        payment_discount_percent=D("2"),
        payment_discount_days=14,
    )
    preview = await AwardTermsService(pg_session).preview(package.id, terms)
    assert preview.contract_sum == D("400008.60")
    assert preview.retention_cap_amount == D("20000.43")
    assert preview.can_award
    await AwardTermsService(pg_session).save_terms(package.id, terms, None)

    contract, lines = await _award_and_draft(pg_session, monkeypatch, package, bid)

    assert contract.contract_type == "unit_price"
    assert contract.total_value == D("400008.60")
    assert sum(ln.total_value for ln in lines) == D("400008.60")
    assert contract.retention_percent == D("10.00")
    assert contract.terms["payment_terms"] == {
        "retention_cap_percent": "5.0000",
        "payment_discount_percent": "2.0000",
        "payment_discount_days": 14,
    }


async def test_a_bid_submitted_as_a_lump_sum_drafts_a_lump_sum_contract(pg_session, monkeypatch):
    project = await _project(pg_session)
    package, bid = await _package(pg_session, project, ["100.00", "300.00"], metadata_={"pricing_mode": "lump_sum"})
    bid.total_amount = "200.00"
    await pg_session.flush()

    contract, lines = await _award_and_draft(pg_session, monkeypatch, package, bid)

    assert contract.contract_type == "lump_sum"
    assert [ln.total_value for ln in lines] == [D("50.00"), D("150.00")]


async def _directory_firm(session, *, blocked: bool = False) -> Subcontractor:
    contact = Contact(contact_type="subcontractor", company_name="Drywall GmbH", primary_email="bids@drywall.test")
    session.add(contact)
    await session.flush()
    sub = Subcontractor(legal_name="Drywall GmbH", contact_id=contact.id, is_blocked=blocked)
    session.add(sub)
    await session.flush()
    return sub


async def test_a_blocked_firm_is_neither_invited_nor_awarded(pg_session):
    project = await _project(pg_session)
    sub = await _directory_firm(pg_session, blocked=True)
    package, bid = await _package(pg_session, project, ["1000.00"], sub=sub)

    with pytest.raises(HTTPException) as invited:
        await TenderingService(pg_session).add_recipient(
            package.id, RecipientCreate(company_name="Other", email="other@drywall.test", subcontractor_id=str(sub.id))
        )
    assert invited.value.status_code == 409
    assert invited.value.detail["code"] == "award.bidder_blocked"

    with pytest.raises(HTTPException) as awarded:
        await TenderingService(pg_session).apply_winner(package.id, bid.id)
    assert awarded.value.status_code == 409
    assert awarded.value.detail["code"] == "award.bidder_blocked"
    assert awarded.value.detail["gate"]["subcontractor_id"] == str(sub.id)


async def test_the_pack_names_the_certificates_and_a_lapsed_one_refuses_the_award(pg_session):
    project = await _project(pg_session, country="DE")
    sub = await _directory_firm(pg_session)
    yesterday = date.today() - timedelta(days=1)
    pg_session.add(Certificate(subcontractor_id=sub.id, cert_type="construction_tax_exemption", valid_until=yesterday))
    await pg_session.flush()
    package, bid = await _package(pg_session, project, ["50000.00"], sub=sub)

    preview = await AwardTermsService(pg_session).preview(package.id, None, bid_id=bid.id)
    assert "construction_tax_exemption" in preview.gate.required_types
    assert preview.gate.requirements_source == "pack"
    rules = {r.rule_id for r in preview.blockers} | {r.rule_id for r in preview.warnings}
    assert "award.evidence_expired" in {r.rule_id for r in preview.blockers}
    assert "award.evidence_missing" in rules
    assert not preview.can_award

    with pytest.raises(HTTPException) as awarded:
        await TenderingService(pg_session).apply_winner(package.id, bid.id)
    assert awarded.value.detail["code"] == "award.evidence_expired"


async def test_a_missing_certificate_warns_and_the_award_goes_ahead(pg_session):
    project = await _project(pg_session, country="DE")
    sub = await _directory_firm(pg_session)
    package, bid = await _package(pg_session, project, ["50000.00"], sub=sub)

    preview = await AwardTermsService(pg_session).preview(package.id, None, bid_id=bid.id)
    assert preview.blockers == []
    assert {r.rule_id for r in preview.warnings} == {"award.evidence_missing"}
    await TenderingService(pg_session).apply_winner(package.id, bid.id)


async def test_a_negotiated_bid_is_awarded_on_its_approved_final_offer(pg_session, monkeypatch):
    project = await _project(pg_session)
    package, bid = await _package(pg_session, project, ["120000.00", "98450.00", "50000.00"])
    svc = AwardTermsService(pg_session)
    first = await svc.add_round(package.id, bid.id, RoundIn(pricing_mode="lump_sum", lump_sum=D("260000.00")), None)
    second = await svc.add_round(package.id, bid.id, RoundIn(pricing_mode="lump_sum", lump_sum=D("255000.00")), None)
    assert (first.round_no, second.round_no) == (1, 2)

    with pytest.raises(HTTPException) as no_final:
        await TenderingService(pg_session).apply_winner(package.id, bid.id)
    assert no_final.value.detail["code"] == "award.final_offer_required"

    await svc.mark_final(package.id, second.id)
    with pytest.raises(HTTPException) as unapproved:
        await TenderingService(pg_session).apply_winner(package.id, bid.id)
    assert unapproved.value.detail["code"] == "award.final_offer_not_approved"

    approved = await svc.approve_round(package.id, second.id, str(uuid.uuid4()))
    assert approved.approved_at is not None
    assert approved.contract_sum == D("255000.00")

    contract, lines = await _award_and_draft(pg_session, monkeypatch, package, bid)
    assert contract.contract_type == "lump_sum"
    assert contract.total_value == D("255000.00")
    assert [ln.total_value for ln in lines] == [D("113987.71"), D("93517.41"), D("47494.88")]
    assert contract.terms["award_terms"]["round_no"] == 2

    # Decided: the terms and rounds are kept as they were.
    with pytest.raises(HTTPException) as frozen:
        await svc.add_round(package.id, bid.id, RoundIn(), None)
    assert frozen.value.status_code == 409


async def test_a_contract_edited_after_the_award_is_flagged(pg_session, monkeypatch):
    project = await _project(pg_session)
    package, bid = await _package(pg_session, project, ["120000.00", "98450.00", "50000.00"])
    svc = AwardTermsService(pg_session)
    await svc.save_terms(package.id, AwardTermsIn(bid_id=bid.id, lump_sum=D("255000.00")), None)
    contract, _lines = await _award_and_draft(pg_session, monkeypatch, package, bid)

    clean = await svc.get(package.id)
    assert clean.contract_id == contract.id
    assert clean.preview is not None
    assert [r.rule_id for r in clean.preview.blockers] == []

    contract.total_value = D("256000.00")
    await pg_session.flush()
    flagged = await svc.get(package.id)
    assert {r.rule_id for r in flagged.preview.blockers} == {
        "award.contract_sum_mismatch",
        "award.lump_sum_lines_reconcile",
    }
