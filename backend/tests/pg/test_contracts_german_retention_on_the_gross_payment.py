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

The gross basis needs the VAT rate the contract states for its invoices. A
German contract that states none is held on the net as before, and its X89
says the rate is missing; nothing assumes 19 %, because work between
contractors is often invoiced under reverse charge with no VAT at all.

A contract keeps one basis for its life. Retention accrues cumulatively, so
a contract moved to the gross after a claim was issued on the net would take
the difference on the work already billed out of its next payment: 7,262.94
on the second claim here. The basis is recorded on the contract as its first
claim is issued, and a contract with a claim out and nothing recorded stays
on the net.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio

from app.modules.boq.gaeb_exchange_router import preview_claim_gaeb_x89
from app.modules.contracts.country_defaults import NET_RETENTION_BASIS
from app.modules.contracts.models import Contract, ContractLine, ProgressClaim
from app.modules.contracts.schemas import AutoGenerateClaimRequest
from app.modules.contracts.service import RETENTION_BASIS_STAMP_KEY, ContractsService
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


_STATUSES = ("draft", "submitted", "approved", "certified")
_STORED = ("gross_amount", "retention_amount", "retention_held_to_date", "completed_stored_to_date", "net_due")


def _stored(claim: ProgressClaim) -> dict[str, Decimal | None]:
    return {name: None if getattr(claim, name) is None else D(str(getattr(claim, name))) for name in _STORED}


async def _certified_claim(
    session, contract: Contract, line: ContractLine, number: str, month: int, percent: str, *, upto: str = "certified"
):
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
    for target in ("submitted", "approved", "certified")[: _STATUSES.index(upto)]:
        claim = await svc.transition_claim(claim.id, target, actor_id=str(OWNER_ID))
    return claim


async def test_the_first_german_abschlagsrechnung_pays_409400_23(session) -> None:
    contract, line = await _contract(session, "DE", einvoice_vat="19")
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
    contract, line = await _contract(session, "DE", einvoice_vat="19")
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
    preview = await preview_claim_gaeb_x89(claim.id, str(OWNER_ID), session, vat_rate=None, invoice_type="deduction")
    assert "retention_basis_vat_not_stated" not in [w["code"] for w in preview["warnings"]]


async def test_a_german_contract_that_states_no_vat_rate_keeps_the_net_and_says_so(session) -> None:
    contract, line = await _contract(session, "DE")
    claim = await _certified_claim(session, contract, line, "AR-1", 3, "38.225979")

    # Ten percent of 382,259.79, the figure every such claim held before.
    assert D(claim.retention_amount) == D("38225.98")
    assert D(claim.net_due) == D("344033.81")

    preview = await preview_claim_gaeb_x89(claim.id, str(OWNER_ID), session, vat_rate=None, invoice_type="deduction")
    assert preview["figures"]["retention"] == "38225.98"
    codes = [w["code"] for w in preview["warnings"]]
    # The claim is out, so stating a rate now would not move the contract.
    assert "retention_basis_stays_net" in codes
    assert "retention_basis_vat_not_stated" not in codes
    assert "retention_vat_rate_differs" not in codes

    invoice = await FinanceService(session).create_receivable_from_claim(claim.id)
    # No rate stated, so no VAT is invented on the receivable.
    assert (D(invoice.tax_amount), D(invoice.retention_amount)) == (D("0"), D("38225.98"))


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


async def _issued_before_the_gross_basis(session, monkeypatch, contract, line, claims):
    """Build ``claims`` the way every claim was built before this release: on the net, nothing recorded."""
    real_basis = ContractsService.retention_basis

    async def _net_basis(self, _contract):
        return NET_RETENTION_BASIS

    monkeypatch.setattr(ContractsService, "retention_basis", _net_basis)
    built = [
        await _certified_claim(session, contract, line, number, month, percent, upto=upto)
        for number, month, percent, upto in claims
    ]
    monkeypatch.setattr(ContractsService, "retention_basis", real_basis)
    # No contract carried a recorded basis then, so none does here.
    contract.metadata_ = {k: v for k, v in (contract.metadata_ or {}).items() if k != RETENTION_BASIS_STAMP_KEY}
    await session.flush()
    return built


async def test_a_claim_issued_on_the_net_keeps_its_figures_once_retention_is_measured_on_the_gross(
    session, monkeypatch
) -> None:
    """Claims issued before the gross basis are not restated by reading them or by moving them on.

    The contract already states 19 % for its invoices. AR-1 was certified
    and AR-2 submitted while every claim was held on the net.
    """
    contract, line = await _contract(session, "DE", einvoice_vat="19")
    certified, submitted = await _issued_before_the_gross_basis(
        session,
        monkeypatch,
        contract,
        line,
        [("AR-1", 3, "38.225979", "certified"), ("AR-2", 4, "45", "submitted")],
    )

    before = {c.id: _stored(c) for c in (certified, submitted)}
    assert before[certified.id]["retention_amount"] == D("38225.98")
    assert before[certified.id]["net_due"] == D("344033.81")
    assert before[submitted.id]["retention_amount"] == D("6774.02")

    # Every place that reads the certified claim as money.
    svc = ContractsService(session)
    assert D(str((await svc.retention_summary(contract))["accrued"])) == D("38225.98")
    await svc.claim_rule_context(certified)
    sheet = await svc.build_payment_application(certified.id)
    assert sheet["lines"][0]["retainage"] == D("38225.98")
    preview = await preview_claim_gaeb_x89(
        certified.id, str(OWNER_ID), session, vat_rate=None, invoice_type="deduction"
    )
    assert preview["figures"]["retention"] == "38225.98"
    assert preview["figures"]["payable"] == "416663.17"
    assert "retention_basis_stays_net" in [w["code"] for w in preview["warnings"]]
    invoice = await FinanceService(session).create_receivable_from_claim(certified.id)
    assert D(invoice.retention_amount) == D("38225.98")

    # A claim already submitted is approved and certified as it was issued.
    for target in ("approved", "certified"):
        await svc.transition_claim(submitted.id, target, actor_id=str(OWNER_ID))

    for claim in (certified, submitted):
        await session.refresh(claim)
        assert _stored(claim) == before[claim.id], claim.claim_number


async def test_a_contract_with_a_claim_issued_on_the_net_stays_on_the_net(session, monkeypatch) -> None:
    """The upgrade, with nobody touching the contract: the next claim does not catch up the first.

    Moved to the gross, AR-2 held 21,274.02: its own 14,011.08 and 7,262.94
    for the work AR-1 had already billed. On the net it holds what is left
    under the ceiling, five percent of 1,000,000.00 less AR-1's 38,225.98.
    """
    contract, line = await _contract(session, "DE", einvoice_vat="19")
    await _issued_before_the_gross_basis(session, monkeypatch, contract, line, [("AR-1", 3, "38.225979", "certified")])
    svc = ContractsService(session)
    assert RETENTION_BASIS_STAMP_KEY not in contract.metadata_

    summary = await svc.retention_summary(contract)
    assert (summary["retention_basis"], summary["retention_basis_vat_percent"]) == ("net", None)
    assert summary["retention_basis_reason"] == "claims_issued_on_net"

    second = await _certified_claim(session, contract, line, "AR-2", 4, "50")
    assert D(second.gross_amount) == D("117740.21")
    assert D(second.retention_amount) == D("11774.02")
    assert D(second.retention_held_to_date) == D("50000.00")
    assert D(second.net_due) == D("117740.21") - D("11774.02")

    # Issuing it recorded what the contract was already on.
    await session.refresh(contract)
    assert contract.metadata_[RETENTION_BASIS_STAMP_KEY] == "net"
    summary = await svc.retention_summary(contract)
    assert D(str(summary["accrued"])) == D("50000.00")
    assert summary["retention_basis_reason"] == "claims_issued_on_net"


async def test_a_new_german_contract_is_on_the_gross_from_its_first_claim_and_says_so(session) -> None:
    contract, line = await _contract(session, "DE", einvoice_vat="19")
    svc = ContractsService(session)
    summary = await svc.retention_summary(contract)
    assert (summary["retention_basis"], summary["retention_basis_reason"]) == ("gross", "vat_stated")
    assert D(str(summary["retention_basis_vat_percent"])) == D("19")

    claim = await _certified_claim(session, contract, line, "AR-1", 3, "38.225979")
    assert D(claim.retention_amount) == D("45488.92")
    await session.refresh(contract)
    assert contract.metadata_[RETENTION_BASIS_STAMP_KEY] == "gross"
    # Its own issued claim does not send it back to the net.
    summary = await svc.retention_summary(contract)
    assert (summary["retention_basis"], summary["retention_basis_reason"]) == ("gross", "vat_stated")
    second = await _certified_claim(session, contract, line, "AR-2", 4, "90")
    assert D(second.retention_amount) == D("14011.08")


async def test_a_contract_with_only_drafts_moves_to_the_gross_when_the_first_is_issued(session, monkeypatch) -> None:
    """Drafts raised on the net are worked out again as the first of them leaves."""
    contract, line = await _contract(session, "DE", einvoice_vat="19")
    first, second = await _issued_before_the_gross_basis(
        session,
        monkeypatch,
        contract,
        line,
        [("AR-1", 3, "38.225979", "draft"), ("AR-2", 4, "40", "draft")],
    )
    assert D(first.retention_amount) == D("38225.98")
    # Two drafts side by side each measure the schedule alone: 400,000.00 at ten percent.
    assert D(second.retention_amount) == D("40000.00")

    svc = ContractsService(session)
    assert (await svc.retention_summary(contract))["retention_basis_reason"] == "vat_stated"
    first = await svc.transition_claim(first.id, "submitted", actor_id=str(OWNER_ID))
    assert D(first.retention_amount) == D("45488.92")
    assert D(first.net_due) == D("382259.79") - D("45488.92")
    await session.refresh(second)
    assert second.status == "draft"
    assert D(second.retention_amount) == D("47600.00")
    await session.refresh(contract)
    assert contract.metadata_[RETENTION_BASIS_STAMP_KEY] == "gross"


async def test_stating_the_vat_rate_after_a_claim_is_out_does_not_move_the_contract(session) -> None:
    """A contract that stated no rate issued on the net; the rate arriving later changes no payment."""
    contract, line = await _contract(session, "DE")
    svc = ContractsService(session)
    assert (await svc.retention_summary(contract))["retention_basis_reason"] == "vat_not_stated"
    await _certified_claim(session, contract, line, "AR-1", 3, "38.225979")
    await session.refresh(contract)
    assert contract.metadata_[RETENTION_BASIS_STAMP_KEY] == "net"

    contract.metadata_ = {**contract.metadata_, "einvoice": {"vat_rate": "19"}}
    await session.flush()
    second = await _certified_claim(session, contract, line, "AR-2", 4, "50")
    assert D(second.retention_amount) == D("11774.02")
    summary = await svc.retention_summary(contract)
    assert (summary["retention_basis"], summary["retention_basis_reason"]) == ("net", "claims_issued_on_net")


@pytest.mark.parametrize("country", ["GB", "US", "FR"])
async def test_a_net_basis_country_says_its_retention_is_on_the_net(session, country: str) -> None:
    contract, _line = await _contract(session, country, einvoice_vat="20")
    summary = await ContractsService(session).retention_summary(contract)
    assert (summary["retention_basis"], summary["retention_basis_reason"]) == ("net", "country_net")
