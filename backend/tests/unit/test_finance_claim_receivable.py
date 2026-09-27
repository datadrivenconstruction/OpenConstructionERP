# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Module tests for Gap E: certified claim → receivable invoice + withholding.

Runs against the real embedded PostgreSQL the suite boots, using the canonical
``transactional_session`` isolation primitive (one outer transaction rolled back
per test). Covers:

* receivable invoice auto-created from a certified claim, with claim lines
  mapped to invoice line items and multi-currency conversion to the project base;
* idempotency — certifying / invoicing the same claim twice yields one invoice;
* a not-yet-certified claim is rejected (400);
* a zero-net claim still produces a (zero) invoice;
* payment-with-withholding splits gross into cash + retainage, is idempotent on
  the idempotency key, links back to the source claim, and posts nothing to the
  cost spine (money the client pays is income, not a cost actual);
* a payment against a non-claim invoice still records (skips claim linkage).

The cost-spine sink (Gap B) is monkeypatched so these tests stay in the finance
lane and can assert that a receipt never reaches it.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.modules.contracts.models import (
    Contract,
    ContractLine,
    ProgressClaim,
    ProgressClaimLine,
)
from app.modules.finance.models import Invoice, Payment
from app.modules.finance.schemas import RecordClaimPaymentRequest
from app.modules.finance.service import FinanceService
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

OWNER_ID = uuid.uuid4()


@pytest_asyncio.fixture
async def session():
    """Transaction-isolated PG session with a user + USD project seeded."""
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email="owner@test.io", hashed_password="x", full_name="Owner"))
        await s.flush()
        yield s


# ── Seed helpers ─────────────────────────────────────────────────────────────


async def _make_project(s, *, currency: str = "USD", fx_rates: list[dict[str, str]] | None = None) -> Project:
    project = Project(
        id=uuid.uuid4(),
        name="Gap E Project",
        owner_id=OWNER_ID,
        currency=currency,
        status="active",
        fx_rates=fx_rates or [],
        metadata_={},
    )
    s.add(project)
    await s.flush()
    return project


async def _make_contract(
    s,
    project: Project,
    *,
    currency: str = "USD",
    counterparty_id: uuid.UUID | None = None,
    retention_percent: str = "5.00",
) -> Contract:
    contract = Contract(
        id=uuid.uuid4(),
        code=f"C-{uuid.uuid4().hex[:8]}",
        title="Main works",
        project_id=project.id,
        counterparty_id=counterparty_id,
        currency=currency,
        retention_percent=Decimal(retention_percent),
        status="active",
    )
    s.add(contract)
    await s.flush()
    return contract


async def _make_claim(
    s,
    contract: Contract,
    *,
    status: str = "certified",
    gross: str = "100000",
    retention: str = "5000",
    net: str = "95000",
    currency: str | None = None,
    n_lines: int = 0,
) -> ProgressClaim:
    claim = ProgressClaim(
        id=uuid.uuid4(),
        contract_id=contract.id,
        claim_number=f"PC-{uuid.uuid4().hex[:4]}",
        claim_date="2026-06-01",
        gross_amount=Decimal(gross),
        retention_amount=Decimal(retention),
        net_due=Decimal(net),
        currency=currency if currency is not None else contract.currency,
        status=status,
    )
    s.add(claim)
    await s.flush()
    if n_lines:
        per_line = Decimal(net) / Decimal(n_lines)
        for i in range(n_lines):
            cl = ContractLine(
                id=uuid.uuid4(),
                contract_id=contract.id,
                code=f"L{i}",
                description=f"Line {i}",
                total_value=per_line,
            )
            s.add(cl)
            await s.flush()
            s.add(
                ProgressClaimLine(
                    id=uuid.uuid4(),
                    progress_claim_id=claim.id,
                    contract_line_id=cl.id,
                    period_completed_qty=Decimal("1"),
                    period_completed_value=per_line,
                    period_completed_pct=Decimal("100"),
                    cumulative_completed_value=per_line,
                )
            )
        await s.flush()
    return claim


def _patch_spine(monkeypatch) -> list[dict]:
    """Capture every ``post_actual_to_budget_line`` call instead of running it."""
    calls: list[dict] = []

    async def _fake_post(
        self,
        project_id,
        cost_line_id,
        cost_category,
        amount_base,
        currency,
        source_kind,
        source_ref,
        *,
        idempotency_key,
    ):  # noqa: ANN001, ANN002, ANN003, E501
        # Idempotent capture keyed on (source_kind, source_ref) — a replay of
        # the same posting must not double-record, mirroring the real sink.
        key = (source_kind, source_ref)
        if not any((c["source_kind"], c["source_ref"]) == key for c in calls):
            calls.append(
                {
                    "project_id": project_id,
                    "amount_base": amount_base,
                    "currency": currency,
                    "source_kind": source_kind,
                    "source_ref": source_ref,
                    "idempotency_key": idempotency_key,
                }
            )
        return object()

    from app.modules.costmodel.service import CostSpineService

    monkeypatch.setattr(CostSpineService, "post_actual_to_budget_line", _fake_post)
    return calls


# ── create_receivable_from_claim ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_receivable_invoice_from_claim_three_lines(session) -> None:
    project = await _make_project(session, currency="USD")
    contract = await _make_contract(session, project, currency="USD")
    claim = await _make_claim(session, contract, n_lines=3, net="90000", retention="4500", gross="94500")

    svc = FinanceService(session)
    invoice = await svc.create_receivable_from_claim(claim.id)

    assert invoice.invoice_direction == "receivable"
    assert invoice.status == "draft"
    assert invoice.source_claim_id == claim.id
    # Gross on the invoice; net is amount_total - retention_amount.
    assert Decimal(str(invoice.amount_total)) == Decimal("94500.00")
    assert Decimal(str(invoice.retention_amount)) == Decimal("4500.00")
    net = Decimal(str(invoice.amount_total)) - Decimal(str(invoice.retention_amount))
    assert net == Decimal("90000.00")
    assert invoice.currency_code == "USD"
    # 3 claim lines → 3 invoice line items (line breakdown sums to net work value).
    assert len(invoice.line_items) == 3
    line_total = sum(Decimal(str(li.amount)) for li in invoice.line_items)
    assert line_total == Decimal("90000.00")


@pytest.mark.asyncio
async def test_receivable_invoice_multi_currency_gbp_to_usd(session) -> None:
    # Project base USD; claim priced in GBP at 1.25 → net 10,000 GBP = 12,500 USD.
    project = await _make_project(session, currency="USD", fx_rates=[{"code": "GBP", "rate": "1.25"}])
    contract = await _make_contract(session, project, currency="GBP")
    claim = await _make_claim(session, contract, currency="GBP", gross="10500", retention="500", net="10000")

    svc = FinanceService(session)
    invoice = await svc.create_receivable_from_claim(claim.id)

    assert invoice.currency_code == "USD"
    # Gross 10,500 GBP * 1.25 = 13,125 USD; retention 500 GBP * 1.25 = 625 USD.
    assert Decimal(str(invoice.amount_total)) == Decimal("13125.00")
    assert Decimal(str(invoice.retention_amount)) == Decimal("625.00")
    net = Decimal(str(invoice.amount_total)) - Decimal(str(invoice.retention_amount))
    assert net == Decimal("12500.00")
    assert invoice.metadata_["claim_currency"] == "GBP"


@pytest.mark.asyncio
async def test_currency_mismatch_missing_fx_keeps_value(session) -> None:
    # Base USD, claim in GBP, but NO fx rate → value kept in its own units,
    # never zeroed (domain money rule).
    project = await _make_project(session, currency="USD", fx_rates=[])
    contract = await _make_contract(session, project, currency="GBP")
    claim = await _make_claim(session, contract, currency="GBP", gross="10500", retention="500", net="10000")

    svc = FinanceService(session)
    invoice = await svc.create_receivable_from_claim(claim.id)
    # Gross kept in GBP units (10,500), never zeroed by a missing rate.
    assert Decimal(str(invoice.amount_total)) == Decimal("10500.00")  # not 0


@pytest.mark.asyncio
async def test_receivable_invoice_idempotency_same_claim_twice(session) -> None:
    project = await _make_project(session)
    contract = await _make_contract(session, project)
    claim = await _make_claim(session, contract)

    svc = FinanceService(session)
    first = await svc.create_receivable_from_claim(claim.id)
    second = await svc.create_receivable_from_claim(claim.id)
    assert first.id == second.id

    rows = (await session.execute(Invoice.__table__.select().where(Invoice.source_claim_id == claim.id))).fetchall()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_receivable_from_claim_not_certified_rejected(session) -> None:
    project = await _make_project(session)
    contract = await _make_contract(session, project)
    claim = await _make_claim(session, contract, status="approved")

    svc = FinanceService(session)
    with pytest.raises(HTTPException) as exc:
        await svc.create_receivable_from_claim(claim.id)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_receivable_from_claim_missing_claim_404(session) -> None:
    svc = FinanceService(session)
    with pytest.raises(HTTPException) as exc:
        await svc.create_receivable_from_claim(uuid.uuid4())
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_claim_with_zero_net_due(session) -> None:
    project = await _make_project(session)
    contract = await _make_contract(session, project)
    claim = await _make_claim(session, contract, gross="0", retention="0", net="0")

    svc = FinanceService(session)
    invoice = await svc.create_receivable_from_claim(claim.id)
    assert Decimal(str(invoice.amount_total)) == Decimal("0.00")
    assert invoice.source_claim_id == claim.id


@pytest.mark.asyncio
async def test_claim_invoice_lines_carry_the_schedule_description_unit_and_rate(session) -> None:
    """The invoice line is the schedule line, not a provenance sentence.

    Before this, every line read "Progress claim <n> line (contract line
    <uuid>)" with no unit and a zero unit price - unreadable to a person and
    rejected line by line by the e-invoice check (BR-23). The schedule of
    values already holds the description, the unit and, via value / quantity,
    the billed rate; the invoice inherits all three. The contract's
    ``metadata.einvoice`` (routing id, VAT treatment - handed over at award)
    reaches the invoice too instead of being dropped for provenance keys.
    """
    project = await _make_project(session, currency="EUR")
    contract = await _make_contract(session, project, currency="EUR")
    contract.metadata_ = {"einvoice": {"buyer_reference": "06-4300251-83", "vat_rate": "19"}}
    await session.flush()

    claim = ProgressClaim(
        id=uuid.uuid4(),
        contract_id=contract.id,
        claim_number="AZ-03",
        claim_date="2026-04-15",
        gross_amount=Decimal("82400"),
        retention_amount=Decimal("4120"),
        net_due=Decimal("78280"),
        currency="EUR",
        status="certified",
    )
    session.add(claim)
    await session.flush()
    sov = ContractLine(
        id=uuid.uuid4(),
        contract_id=contract.id,
        code="01.02",
        description="Rohbauarbeiten UG gem. Aufmaß",
        unit="m3",
        quantity=Decimal("120"),
        unit_rate=Decimal("2060"),
        total_value=Decimal("247200"),
    )
    session.add(sov)
    await session.flush()
    session.add(
        ProgressClaimLine(
            id=uuid.uuid4(),
            progress_claim_id=claim.id,
            contract_line_id=sov.id,
            period_completed_qty=Decimal("40"),
            period_completed_value=Decimal("82400"),
            period_completed_pct=Decimal("33.33"),
            cumulative_completed_value=Decimal("82400"),
        )
    )
    await session.flush()

    svc = FinanceService(session)
    invoice = await svc.create_receivable_from_claim(claim.id)

    [line] = invoice.line_items
    assert line.description == "01.02 Rohbauarbeiten UG gem. Aufmaß"
    assert str(sov.id) not in line.description
    assert line.unit == "m3"
    assert Decimal(str(line.quantity)) == Decimal("40")
    assert Decimal(str(line.unit_rate)) == Decimal("2060.0000")
    assert Decimal(str(line.amount)) == Decimal("82400.00")

    # The contract's e-invoice block survives beside the provenance keys.
    assert invoice.metadata_["einvoice"]["buyer_reference"] == "06-4300251-83"
    assert invoice.metadata_["source"] == "progress_claim"
    # VAT follows the contract's declared rate: 19% of the gross.
    assert Decimal(str(invoice.tax_amount)) == Decimal("15656.00")
    assert Decimal(str(invoice.amount_total)) == Decimal("98056.00")
    assert Decimal(str(invoice.amount_subtotal)) == Decimal("82400.00")


@pytest.mark.asyncio
async def test_value_only_claim_line_becomes_a_lump_sum(session) -> None:
    """Percent-complete billing without a measured quantity: 1 psch at the value."""
    project = await _make_project(session, currency="EUR")
    contract = await _make_contract(session, project, currency="EUR")
    claim = ProgressClaim(
        id=uuid.uuid4(),
        contract_id=contract.id,
        claim_number="AZ-04",
        claim_date="2026-05-15",
        gross_amount=Decimal("5000"),
        retention_amount=Decimal("0"),
        net_due=Decimal("5000"),
        currency="EUR",
        status="certified",
    )
    session.add(claim)
    await session.flush()
    sov = ContractLine(
        id=uuid.uuid4(),
        contract_id=contract.id,
        code="02.01",
        description="Baustelleneinrichtung",
        unit=None,
        total_value=Decimal("15000"),
    )
    session.add(sov)
    await session.flush()
    session.add(
        ProgressClaimLine(
            id=uuid.uuid4(),
            progress_claim_id=claim.id,
            contract_line_id=sov.id,
            period_completed_qty=Decimal("0"),
            period_completed_value=Decimal("5000"),
            period_completed_pct=Decimal("33.33"),
            cumulative_completed_value=Decimal("5000"),
        )
    )
    await session.flush()

    svc = FinanceService(session)
    invoice = await svc.create_receivable_from_claim(claim.id)

    [line] = invoice.line_items
    assert line.description == "02.01 Baustelleneinrichtung"
    assert line.unit == "psch"
    assert Decimal(str(line.quantity)) == Decimal("1")
    assert Decimal(str(line.unit_rate)) == Decimal("5000.00")
    # No einvoice block on the contract: no VAT invented, no einvoice key.
    assert Decimal(str(invoice.tax_amount)) == Decimal("0.00")
    assert "einvoice" not in invoice.metadata_


@pytest.mark.asyncio
async def test_claim_certified_event_triggers_invoice_creation(session, monkeypatch) -> None:
    # Exercise the subscriber's core call (the service method it delegates to)
    # — the event-bus → session plumbing is covered separately; here we assert
    # the certified claim materialises into AR.
    project = await _make_project(session)
    contract = await _make_contract(session, project)
    claim = await _make_claim(session, contract)

    svc = FinanceService(session)
    invoice = await svc.create_receivable_from_claim(claim.id, actor_id=str(OWNER_ID))
    assert invoice is not None
    assert invoice.source_claim_id == claim.id
    # get_receivable_for_claim convenience lookup resolves the same row.
    looked_up = await svc.get_receivable_for_claim(claim.id)
    assert looked_up is not None and looked_up.id == invoice.id


# ── record_payment_with_withholding ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_payment_with_withholding_derives_from_invoice(session, monkeypatch) -> None:
    calls = _patch_spine(monkeypatch)
    project = await _make_project(session)
    contract = await _make_contract(session, project)
    claim = await _make_claim(session, contract, gross="100000", retention="5000", net="95000")

    svc = FinanceService(session)
    invoice = await svc.create_receivable_from_claim(claim.id)

    # Pay the whole invoice; withholding derived from invoice.retention_amount.
    payment = await svc.record_payment_with_withholding(
        invoice.id,
        RecordClaimPaymentRequest(payment_date="2026-06-10"),
    )
    # Gross settled = amount_total (100000) since amount omitted; held = 5000;
    # cash paid = 95000 (the certified net).
    assert Decimal(str(payment.withholding_amount)) == Decimal("5000.00")
    assert Decimal(str(payment.amount)) == Decimal("95000.00")
    assert payment.source_claim_id == claim.id

    # The client paying us is income: nothing reaches the cost spine.
    assert calls == []


@pytest.mark.asyncio
async def test_payment_with_explicit_amount_and_withholding(session, monkeypatch) -> None:
    _patch_spine(monkeypatch)
    project = await _make_project(session)
    contract = await _make_contract(session, project)
    claim = await _make_claim(session, contract)
    svc = FinanceService(session)
    invoice = await svc.create_receivable_from_claim(claim.id)

    payment = await svc.record_payment_with_withholding(
        invoice.id,
        RecordClaimPaymentRequest(
            payment_date="2026-06-10",
            amount="80000",
            withholding_amount="4000",
            withholding_release_date="2027-01-01",
        ),
    )
    assert Decimal(str(payment.amount)) == Decimal("80000.00")
    assert Decimal(str(payment.withholding_amount)) == Decimal("4000.00")
    assert payment.withholding_release_date == "2027-01-01"


@pytest.mark.asyncio
async def test_payment_idempotency_key_deduplication(session, monkeypatch) -> None:
    calls = _patch_spine(monkeypatch)
    project = await _make_project(session)
    contract = await _make_contract(session, project)
    claim = await _make_claim(session, contract)
    svc = FinanceService(session)
    invoice = await svc.create_receivable_from_claim(claim.id)

    p1 = await svc.record_payment_with_withholding(
        invoice.id,
        RecordClaimPaymentRequest(payment_date="2026-06-10", idempotency_key="K1"),
    )
    p2 = await svc.record_payment_with_withholding(
        invoice.id,
        RecordClaimPaymentRequest(payment_date="2026-06-10", idempotency_key="K1"),
    )
    assert p1.id == p2.id
    rows = (await session.execute(Payment.__table__.select().where(Payment.invoice_id == invoice.id))).fetchall()
    assert len(rows) == 1
    # Neither call posts the receipt to the cost spine.
    assert calls == []


@pytest.mark.asyncio
async def test_payment_without_claim_link_skips_claim_linkage(session, monkeypatch) -> None:
    # A plain (non-claim) receivable invoice still records a payment; the
    # payment simply carries no source_claim_id.
    _patch_spine(monkeypatch)
    project = await _make_project(session)
    invoice = Invoice(
        id=uuid.uuid4(),
        project_id=project.id,
        invoice_direction="receivable",
        invoice_number="INV-R-999",
        invoice_date="2026-06-01",
        currency_code="USD",
        amount_subtotal=Decimal("1000"),
        tax_amount=Decimal("0"),
        retention_amount=Decimal("0"),
        amount_total=Decimal("1000"),
        status="draft",
        metadata_={},
    )
    session.add(invoice)
    await session.flush()

    svc = FinanceService(session)
    payment = await svc.record_payment_with_withholding(
        invoice.id, RecordClaimPaymentRequest(payment_date="2026-06-10")
    )
    assert payment.source_claim_id is None
    assert Decimal(str(payment.withholding_amount)) == Decimal("0.00")
    assert Decimal(str(payment.amount)) == Decimal("1000.00")


@pytest.mark.asyncio
async def test_withholding_release_date_round_trips(session, monkeypatch) -> None:
    _patch_spine(monkeypatch)
    project = await _make_project(session)
    contract = await _make_contract(session, project)
    claim = await _make_claim(session, contract)
    svc = FinanceService(session)
    invoice = await svc.create_receivable_from_claim(claim.id)

    payment = await svc.record_payment_with_withholding(
        invoice.id,
        RecordClaimPaymentRequest(payment_date="2026-06-10", withholding_release_date="2027-03-31"),
    )
    reloaded = await session.get(Payment, payment.id)
    assert reloaded.withholding_release_date == "2027-03-31"


@pytest.mark.asyncio
async def test_existing_payable_invoices_unaffected(session) -> None:
    # Regression: an ordinary payable invoice carries no source_claim_id and is
    # not picked up by the claim lookup.
    project = await _make_project(session)
    invoice = Invoice(
        id=uuid.uuid4(),
        project_id=project.id,
        invoice_direction="payable",
        invoice_number="INV-P-001",
        invoice_date="2026-06-01",
        currency_code="USD",
        amount_subtotal=Decimal("500"),
        tax_amount=Decimal("0"),
        retention_amount=Decimal("0"),
        amount_total=Decimal("500"),
        status="draft",
        metadata_={},
    )
    session.add(invoice)
    await session.flush()
    assert invoice.source_claim_id is None

    svc = FinanceService(session)
    assert await svc.get_receivable_for_claim(uuid.uuid4()) is None
