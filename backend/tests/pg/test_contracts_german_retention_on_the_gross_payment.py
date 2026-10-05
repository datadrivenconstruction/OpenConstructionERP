# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A German claim holds its Sicherheitseinbehalt on the payment with VAT in it, end to end.

§ 17 Abs. 6 Nr. 1 VOB/B lets the client cut "jeweils die Zahlung um höchstens
10 v. H.", and leaves the USt out of that only for a § 13b UStG invoice that
carries none. The security sum it stops at is five percent of the
Auftragssumme "inkl. Umsatzsteuer" (VHB Bund, Formblatt 214 Nr. 4).

The first Abschlagsrechnung bills 382,259.79 net on a 1,000,000.00 contract
at ten percent retention capped at five: 454,889.15 with 19 % USt, 45,488.92
held, 409,400.23 to pay. The claim used to hold 38,225.98, ten percent of the
net, and its X89 asked the client for 416,663.17.

Four places read the claim's retention as money and must agree: the claim
itself, the ceiling, the GAEB X89 invoice and the finance receivable. A UK,
US and French contract built the same way keeps ten percent of the net.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio

from app.modules.boq.gaeb_exchange_router import preview_claim_gaeb_x89
from app.modules.contracts.models import Contract, ContractLine, ProgressClaim
from app.modules.contracts.schemas import AutoGenerateClaimRequest
from app.modules.contracts.service import ContractsService
from app.modules.contracts.validators import register_contracts_validation_rules
from app.modules.finance.service import FinanceService
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

OWNER_ID = uuid.uuid4()
D = Decimal


@pytest_asyncio.fixture
async def session():
    register_contracts_validation_rules()
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email=f"de-ret-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
        await s.flush()
        yield s


async def _contract(session, country: str, *, einvoice_vat: str | None = None) -> tuple[Contract, ContractLine]:
    project = Project(id=uuid.uuid4(), name="Kita Nord", owner_id=OWNER_ID, currency="EUR", country_code=country)
    session.add(project)
    await session.flush()
    contract = Contract(
        id=uuid.uuid4(),
        code=f"C-{uuid.uuid4().hex[:8]}",
        title="Rohbau",
        project_id=project.id,
        contract_type="lump_sum",
        currency="EUR",
        total_value=D("1000000"),
        original_contract_value=D("1000000"),
        retention_percent=D("10"),
        status="active",
        terms={"payment_terms": {"retention_cap_percent": "5"}},
        metadata_={"einvoice": {"vat_rate": einvoice_vat}} if einvoice_vat is not None else {},
    )
    session.add(contract)
    await session.flush()
    line = ContractLine(
        id=uuid.uuid4(),
        contract_id=contract.id,
        code="01.01",
        description="Rohbauarbeiten",
        quantity=D("1"),
        unit_rate=D("1000000"),
        total_value=D("1000000"),
        metadata_={},
    )
    session.add(line)
    await session.flush()
    return contract, line


async def _certified_claim(session, contract: Contract, line: ContractLine, number: str, month: int, percent: str):
    claim = ProgressClaim(
        id=uuid.uuid4(),
        contract_id=contract.id,
        claim_number=number,
        period_start=f"2026-{month:02d}-01",
        period_end=f"2026-{month:02d}-28",
        claim_date=f"2026-{month:02d}-28",
        period_from=date(2026, month, 1),
        period_to=date(2026, month, 28),
        status="draft",
        currency="EUR",
    )
    session.add(claim)
    await session.flush()
    svc = ContractsService(session)
    claim = await svc.auto_generate_claim_lines(
        claim.id, AutoGenerateClaimRequest(completion={str(line.id): D(percent)})
    )
    for target in ("submitted", "approved", "certified"):
        claim = await svc.transition_claim(claim.id, target, actor_id=str(OWNER_ID))
    return claim


async def test_the_first_german_abschlagsrechnung_pays_409400_23(session) -> None:
    contract, line = await _contract(session, "DE")
    claim = await _certified_claim(session, contract, line, "AR-1", 3, "38.225979")

    # The claim: ten percent of 454,889.15, not of 382,259.79.
    assert D(claim.gross_amount) == D("382259.79")
    assert D(claim.retention_amount) == D("45488.92")
    assert D(claim.retention_held_to_date) == D("45488.92")
    assert D(claim.net_due) == D("382259.79") - D("45488.92")

    # The X89 asks for the gross less that retention, VAT still on the net.
    preview = await preview_claim_gaeb_x89(claim.id, str(OWNER_ID), session, vat_rate=None, invoice_type="deduction")
    figures = preview["figures"]
    assert (figures["net"], figures["vat_amount"], figures["gross"]) == ("382259.79", "72629.36", "454889.15")
    assert figures["retention"] == "45488.92"
    assert figures["payable"] == "409400.23"
    assert all(w["code"] != "retention_vat_rate_differs" for w in preview["warnings"])

    # The receivable collects the same: the USt is booked with it, and the
    # payment withholds the claim's own retention once.
    invoice = await FinanceService(session).create_receivable_from_claim(claim.id)
    assert D(invoice.amount_subtotal) == D("382259.79")
    assert D(invoice.tax_amount) == D("72629.36")
    assert D(invoice.amount_total) == D("454889.15")
    assert D(invoice.retention_amount) == D("45488.92")
    assert D(invoice.amount_total) - D(invoice.retention_amount) == D("409400.23")


async def test_the_german_ceiling_is_five_percent_of_the_contract_sum_with_vat(session) -> None:
    contract, line = await _contract(session, "DE")
    await _certified_claim(session, contract, line, "AR-1", 3, "38.225979")
    second = await _certified_claim(session, contract, line, "AR-2", 4, "90")

    # 5 % of 1,190,000.00 is 59,500.00; the first claim held 45,488.92.
    assert D(second.retention_amount) == D("14011.08")
    assert D(second.retention_held_to_date) == D("59500.00")
    summary = await ContractsService(session).retention_summary(contract)
    assert D(str(summary["accrued"])) == D("59500.00")


async def test_a_reverse_charge_contract_is_measured_without_vat(session) -> None:
    """The contract states 0 % for its invoices: § 13b UStG, so § 17 Abs. 6 Nr. 1 Satz 2 VOB/B."""
    contract, line = await _contract(session, "DE", einvoice_vat="0")
    claim = await _certified_claim(session, contract, line, "AR-1", 3, "38.225979")
    assert D(claim.retention_amount) == D("38225.98")


@pytest.mark.parametrize("country", ["GB", "US", "FR"])
async def test_a_net_basis_country_still_holds_ten_percent_of_the_net(session, country: str) -> None:
    contract, line = await _contract(session, country)
    claim = await _certified_claim(session, contract, line, "PC-1", 3, "38.225979")
    assert D(claim.retention_amount) == D("38225.98")
    assert D(claim.retention_held_to_date) == D("38225.98")
    assert D(claim.net_due) == D("344033.81")

    preview = await preview_claim_gaeb_x89(claim.id, str(OWNER_ID), session, vat_rate=None, invoice_type="deduction")
    assert preview["figures"]["retention"] == "38225.98"
    assert D(preview["figures"]["payable"]) == D(preview["figures"]["gross"]) - D("38225.98")

    invoice = await FinanceService(session).create_receivable_from_claim(claim.id)
    # No VAT agreed on the contract, so none booked, exactly as before.
    assert (D(invoice.tax_amount), D(invoice.retention_amount)) == (D("0"), D("38225.98"))
