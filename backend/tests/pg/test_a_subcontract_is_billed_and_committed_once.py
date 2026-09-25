# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A subcontract's money reaches finance once, in the right direction.

One scenario runs through every test: a 120,000 EUR subcontract with 5%
retention, and a first claim (or payment application) at 30% of it. That is a
gross of 36,000, retention of 1,800 and 34,200 due to the subcontractor.

What used to happen on the walk-through of a general contractor's project:
certifying the subcontractor's claim raised TWO receivables, one linked to the
claim and one not, while the claim page said nothing had been raised. The
subcontractor's bill is money we owe, so it is one payable, linked to the
claim, and raised however often the certification event is delivered.

Signing the same subcontract used to leave Committed at zero, and paying the
subcontractor never reached actual. Signing now commits the 120,000, paying
the first application moves its 36,000 gross from committed to actual, and the
1,800 retention is held from what we pay in both ledgers that report it.

These tests go through the production wiring: the registrars the app runs at
startup, a real bus and the real after-commit publishing, against a throwaway
database whose rows every subscriber session can see.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.core.events as core_events
import app.modules.contracts.service as contracts_service
import app.modules.finance.events as finance_events
import app.modules.finance.service as finance_service
import app.modules.notifications._wave5_cross_module_subscribers as w5
import app.modules.subcontractors.events as sub_events
import app.modules.subcontractors.service as sub_service
from app.core.events import EventBus
from app.modules.contacts.models import Contact
from app.modules.contracts.models import Contract, ProgressClaim
from app.modules.contracts.service import ContractsService
from app.modules.finance.cost_position import subcontract_open_commitment
from app.modules.finance.models import Invoice, Payment, ProjectBudget
from app.modules.finance.service import FinanceService
from app.modules.projects.models import Project
from app.modules.subcontractors.models import Certificate, RetentionLedger, Subcontractor
from app.modules.subcontractors.schemas import AgreementCreate, AgreementUpdate, PaymentApplicationCreate
from app.modules.subcontractors.service import SubcontractorService
from app.modules.users.models import User
from tests._pg import isolated_engine

CERTIFIED = "contracts.claim.certified"
SIGNED = "contracts.contract.signed"
CLAIM_PAID = "contracts.claim.paid"

AGREEMENT_VALUE = Decimal("120000")
RETENTION_PCT = Decimal("5")
GROSS = Decimal("36000")
RETENTION = Decimal("1800")
NET = Decimal("34200")
REMAINING = AGREEMENT_VALUE - GROSS


class _World:
    """A throwaway database holding one EUR project, a subcontractor and a client."""

    def __init__(self, factory: async_sessionmaker[AsyncSession], project_id: uuid.UUID) -> None:
        self.factory = factory
        self.project_id = project_id
        self.sub_contact_id: uuid.UUID | None = None
        self.subcontractor_id: uuid.UUID | None = None
        self.client_contact_id: uuid.UUID | None = None

    async def contract(
        self,
        *,
        counterparty: str,
        counterparty_id: uuid.UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> uuid.UUID:
        async with self.factory() as session:
            contract = Contract(
                code=f"SC-{uuid.uuid4().hex[:8]}",
                title="Drywall subcontract" if counterparty == "subcontractor" else "Main contract",
                project_id=self.project_id,
                counterparty_type=counterparty,
                counterparty_id=counterparty_id
                or (self.subcontractor_id if counterparty == "subcontractor" else self.client_contact_id),
                metadata_=metadata or {},
                status="active",
                currency="EUR",
                total_value=AGREEMENT_VALUE,
                retention_percent=RETENTION_PCT,
            )
            session.add(contract)
            await session.commit()
            return contract.id

    async def approved_claim(self, contract_id: uuid.UUID) -> uuid.UUID:
        async with self.factory() as session:
            claim = ProgressClaim(
                contract_id=contract_id,
                claim_number="PC-0001",
                claim_date="2026-09-01",
                gross_amount=GROSS,
                retention_amount=RETENTION,
                net_due=NET,
                currency="EUR",
                status="approved",
            )
            session.add(claim)
            await session.commit()
            return claim.id

    async def invoices(self) -> list[Invoice]:
        async with self.factory() as session:
            rows = await session.execute(select(Invoice).where(Invoice.project_id == self.project_id))
            return list(rows.scalars().all())

    async def budget(self) -> tuple[Decimal, Decimal]:
        """``(committed, actual)`` on the project's budget row, read fresh."""
        async with self.factory() as session:
            row = (
                await session.execute(select(ProjectBudget).where(ProjectBudget.project_id == self.project_id))
            ).scalar_one()
            return _money(row.committed), _money(row.actual)

    async def payments(self, invoice_id: uuid.UUID) -> list[Payment]:
        async with self.factory() as session:
            rows = await session.execute(select(Payment).where(Payment.invoice_id == invoice_id))
            return list(rows.scalars().all())

    async def payable_retention(self) -> tuple[Decimal, Decimal]:
        """``(scheduled, held)`` on the payables side of the finance retention ledger."""
        async with self.factory() as session:
            ledger = await FinanceService(session).get_retention_ledger(self.project_id)
        assert all(t.direction == "payable" for t in ledger.totals), [t.direction for t in ledger.totals]
        payable = [t for t in ledger.totals if t.direction == "payable"]
        assert len(payable) == 1
        return payable[0].scheduled, payable[0].held_to_date


@pytest_asyncio.fixture
async def world(monkeypatch: pytest.MonkeyPatch):
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        # Subscribers open their own sessions by design; point them at the
        # throwaway database so they see the rows committed here.
        monkeypatch.setattr(finance_events, "async_session_factory", factory)
        monkeypatch.setattr(w5, "async_session_factory", factory)
        monkeypatch.setattr(sub_events, "async_session_factory", factory)
        async with factory() as session:
            user = User(
                email=f"sub-{uuid.uuid4().hex[:8]}@example.com",
                hashed_password="x",
                full_name="Site manager",
                role="admin",
            )
            session.add(user)
            await session.flush()
            project = Project(name=f"Zagreb GC {uuid.uuid4().hex[:6]}", owner_id=user.id, currency="EUR")
            sub_contact = Contact(contact_type="subcontractor", company_name="Suhi Zid d.o.o.")
            client_contact = Contact(contact_type="client", company_name="Investitor d.d.")
            session.add_all([project, sub_contact, client_contact])
            await session.flush()
            sub = Subcontractor(legal_name="Suhi Zid d.o.o.", contact_id=sub_contact.id, country="HR")
            budget = ProjectBudget(
                project_id=project.id,
                currency_code="EUR",
                original_budget=Decimal("500000"),
                revised_budget=Decimal("500000"),
            )
            session.add_all([sub, budget])
            await session.flush()
            # What a subcontractor must hold to be signed and paid.
            for cert_type in ("insurance", "license"):
                session.add(
                    Certificate(
                        subcontractor_id=sub.id,
                        cert_type=cert_type,
                        valid_until=date(2030, 12, 31),
                        status="valid",
                    )
                )
            await session.commit()
            w = _World(factory, project.id)
            w.sub_contact_id = sub_contact.id
            w.subcontractor_id = sub.id
            w.client_contact_id = client_contact.id
            yield w


@pytest.fixture
def production_bus(monkeypatch: pytest.MonkeyPatch) -> EventBus:
    """A fresh bus wired by the registrars the app runs at startup."""
    bus = EventBus()
    for module in (core_events, contracts_service, finance_events, finance_service, w5, sub_events, sub_service):
        monkeypatch.setattr(module, "event_bus", bus)
    finance_events.register_finance_subscribers()
    w5.register_wave5_notification_subscribers()
    sub_events.register_subcontractor_rating_subscribers()
    return bus


async def _drain(bus: EventBus) -> None:
    """Wait for every detached publish, including those they start in turn."""
    while bus._background_tasks:
        await asyncio.gather(*list(bus._background_tasks), return_exceptions=True)


async def _certify(world: _World, bus: EventBus, claim_id: uuid.UUID) -> None:
    """Certify the way the route does: transition, then the request commits."""
    async with world.factory() as session:
        await ContractsService(session).transition_claim(claim_id, "certified", actor_id=None)
        await session.commit()
    await _drain(bus)


def _money(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def test_one_subscriber_raises_the_claim_invoice(production_bus: EventBus) -> None:
    """Two writers on the certification raised two invoices for one claim."""
    assert production_bus.list_handlers(CERTIFIED) == {CERTIFIED: ["_on_claim_certified"]}
    handler = production_bus._handlers[CERTIFIED][0]
    assert handler.__module__ == "app.modules.finance.events"


@pytest.mark.asyncio
async def test_a_certified_subcontract_claim_is_one_linked_payable(world: _World, production_bus: EventBus) -> None:
    contract_id = await world.contract(counterparty="subcontractor")
    claim_id = await world.approved_claim(contract_id)

    await _certify(world, production_bus, claim_id)

    invoices = await world.invoices()
    assert len(invoices) == 1, [(i.invoice_number, i.invoice_direction) for i in invoices]
    invoice = invoices[0]
    assert invoice.invoice_direction == "payable"
    assert invoice.invoice_number == "INV-P-001"
    assert invoice.source_claim_id == claim_id
    assert invoice.contact_id == str(world.sub_contact_id)
    assert _money(invoice.amount_total) == GROSS
    assert _money(invoice.retention_amount) == RETENTION
    assert _money(invoice.amount_total) - _money(invoice.retention_amount) == NET

    # The claim page asks this route's service for the invoice; it must answer.
    async with world.factory() as session:
        found = await FinanceService(session).get_receivable_for_claim(claim_id)
        assert found is not None and found.id == invoice.id


@pytest.mark.asyncio
async def test_a_redelivered_certification_raises_nothing_more(world: _World, production_bus: EventBus) -> None:
    contract_id = await world.contract(counterparty="subcontractor")
    claim_id = await world.approved_claim(contract_id)
    await _certify(world, production_bus, claim_id)

    await production_bus.publish(CERTIFIED, {"claim_id": str(claim_id), "contract_id": str(contract_id)})
    await _drain(production_bus)

    assert len(await world.invoices()) == 1


@pytest.mark.asyncio
async def test_a_certified_client_claim_stays_a_receivable(world: _World, production_bus: EventBus) -> None:
    """The control: the same claim on the client contract is money owed to us."""
    contract_id = await world.contract(counterparty="client")
    claim_id = await world.approved_claim(contract_id)

    await _certify(world, production_bus, claim_id)

    invoices = await world.invoices()
    assert len(invoices) == 1
    assert invoices[0].invoice_direction == "receivable"
    assert invoices[0].invoice_number == "INV-R-001"
    assert invoices[0].source_claim_id == claim_id
    assert invoices[0].contact_id == str(world.client_contact_id)


# ── Commitment and actual ────────────────────────────────────────────────


async def _signed_subcontract(world: _World, bus: EventBus) -> uuid.UUID:
    """A subcontract signed the way the contracts module announces it."""
    contract_id = await world.contract(counterparty="subcontractor")
    await bus.publish(SIGNED, {"contract_id": str(contract_id), "project_id": str(world.project_id)})
    await _drain(bus)
    return contract_id


@pytest.mark.asyncio
async def test_signing_a_subcontract_commits_its_value_once(world: _World, production_bus: EventBus) -> None:
    contract_id = await _signed_subcontract(world, production_bus)
    await production_bus.publish(SIGNED, {"contract_id": str(contract_id)})
    await _drain(production_bus)
    assert await world.budget() == (AGREEMENT_VALUE, Decimal("0.00"))


@pytest.mark.asyncio
async def test_signing_a_client_contract_commits_nothing(world: _World, production_bus: EventBus) -> None:
    """The control: a contract with the client is income, not spend."""
    contract_id = await world.contract(counterparty="client")
    await production_bus.publish(SIGNED, {"contract_id": str(contract_id)})
    await _drain(production_bus)
    assert await world.budget() == (Decimal("0.00"), Decimal("0.00"))


@pytest.mark.asyncio
async def test_a_paid_subcontract_claim_moves_its_gross_from_committed_to_actual(
    world: _World, production_bus: EventBus
) -> None:
    contract_id = await _signed_subcontract(world, production_bus)
    claim_id = await world.approved_claim(contract_id)
    await _certify(world, production_bus, claim_id)

    async with world.factory() as session:
        await ContractsService(session).transition_claim(claim_id, "paid", actor_id=None)
        await session.commit()
    await _drain(production_bus)
    # A second delivery of the same payment moves nothing.
    await production_bus.publish(CLAIM_PAID, {"claim_id": str(claim_id), "contract_id": str(contract_id)})
    await _drain(production_bus)

    (invoice,) = await world.invoices()
    assert invoice.status == "paid"
    assert await world.budget() == (REMAINING, GROSS)
    (payment,) = await world.payments(invoice.id)
    assert _money(payment.amount) == NET
    assert _money(payment.withholding_amount) == RETENTION
    assert await world.payable_retention() == (RETENTION, RETENTION)


@pytest.mark.asyncio
async def test_a_pay_application_is_committed_billed_and_paid_once(world: _World, production_bus: EventBus) -> None:
    """The agreement path on the Subcontractors page, from signing to payment."""
    async with world.factory() as session:
        svc = SubcontractorService(session)
        agreement = await svc.create_agreement(
            AgreementCreate(
                subcontractor_id=world.subcontractor_id,
                project_id=world.project_id,
                title="Drywall, block B",
                total_value=AGREEMENT_VALUE,
                currency="EUR",
                retention_percent=RETENTION_PCT,
            )
        )
        await svc.update_agreement(agreement.id, AgreementUpdate(status="active"))
        await session.commit()
        agreement_id = agreement.id
    assert await world.budget() == (AGREEMENT_VALUE, Decimal("0.00"))

    async with world.factory() as session:
        svc = SubcontractorService(session)
        payment = await svc.submit_payment_application(
            PaymentApplicationCreate(agreement_id=agreement_id, gross_amount=GROSS, currency="EUR"),
            today=date(2026, 9, 30),
        )
        assert (_money(payment.gross_amount), _money(payment.retention_amount), _money(payment.net_amount)) == (
            GROSS,
            RETENTION,
            NET,
        )
        payment_id = payment.id
        await svc.approve_payment_application_foreman(payment_id, "foreman")
        await svc.approve_payment_application_finance(payment_id, "finance")
        await session.commit()
    await _drain(production_bus)

    (invoice,) = await world.invoices()
    assert invoice.invoice_direction == "payable"
    assert invoice.contact_id == str(world.sub_contact_id)
    assert (_money(invoice.amount_total), _money(invoice.retention_amount)) == (GROSS, RETENTION)
    async with world.factory() as session:
        accrued = (
            await session.execute(
                select(RetentionLedger.accrued_amount).where(RetentionLedger.payment_application_id == payment_id)
            )
        ).scalar_one()
    # The module's retention ledger and the payable hold the same retention.
    assert _money(accrued) == _money(invoice.retention_amount) == RETENTION
    assert await world.payable_retention() == (RETENTION, Decimal("0.00"))
    # Approved is billed, not yet spent.
    assert await world.budget() == (AGREEMENT_VALUE, Decimal("0.00"))

    async with world.factory() as session:
        await SubcontractorService(session).mark_paid(payment_id)
        await session.commit()
    await _drain(production_bus)

    (invoice,) = await world.invoices()
    assert invoice.status == "paid"
    assert await world.budget() == (REMAINING, GROSS)
    # The budget row carries what finance itself reports as still open.
    async with world.factory() as session:
        assert await subcontract_open_commitment(session, world.project_id) == {"EUR": REMAINING}
    (paid,) = await world.payments(invoice.id)
    assert (_money(paid.amount), _money(paid.withholding_amount)) == (NET, RETENTION)
    assert await world.payable_retention() == (RETENTION, RETENTION)


@pytest.mark.asyncio
async def test_a_paid_pay_application_reaches_the_5d_actual_once(world: _World, production_bus: EventBus) -> None:
    """The paid payable reaches the 5D cost model the way a supplier invoice does, and only once."""
    from app.modules.costmodel.models import BudgetLine

    await test_a_pay_application_is_committed_billed_and_paid_once(world, production_bus)

    async with world.factory() as session:
        lines = (
            (await session.execute(select(BudgetLine).where(BudgetLine.project_id == world.project_id))).scalars().all()
        )
    assert sum((Decimal(str(line.actual_amount)) for line in lines), Decimal("0")) == GROSS


@pytest.mark.asyncio
async def test_an_awarded_subcontract_bills_the_contact_the_award_resolved(
    world: _World, production_bus: EventBus
) -> None:
    """An award names the bidder in counterparty_id and the contact in metadata."""
    bidder_id = uuid.uuid4()
    contract_id = await world.contract(
        counterparty="subcontractor",
        counterparty_id=bidder_id,
        metadata={"counterparty_contact_id": str(world.sub_contact_id)},
    )
    claim_id = await world.approved_claim(contract_id)

    await _certify(world, production_bus, claim_id)

    (invoice,) = await world.invoices()
    assert invoice.invoice_direction == "payable"
    assert invoice.contact_id == str(world.sub_contact_id)


@pytest.mark.asyncio
async def test_an_unresolved_counterparty_is_left_blank_not_invented(world: _World, production_bus: EventBus) -> None:
    contract_id = await world.contract(
        counterparty="subcontractor",
        counterparty_id=uuid.uuid4(),
        metadata={"counterparty_contact_id": str(uuid.uuid4())},
    )
    claim_id = await world.approved_claim(contract_id)

    await _certify(world, production_bus, claim_id)

    (invoice,) = await world.invoices()
    assert invoice.contact_id is None


async def _linked_agreement(world: _World, contract_id: uuid.UUID | None, *, sign: bool) -> uuid.UUID:
    async with world.factory() as session:
        svc = SubcontractorService(session)
        agreement = await svc.create_agreement(
            AgreementCreate(
                subcontractor_id=world.subcontractor_id,
                project_id=world.project_id,
                title="Drywall, block B",
                total_value=AGREEMENT_VALUE,
                currency="EUR",
                retention_percent=RETENTION_PCT,
                contract_id=contract_id,
            )
        )
        if sign:
            await svc.update_agreement(agreement.id, AgreementUpdate(status="active"))
        await session.commit()
        return agreement.id


@pytest.mark.asyncio
async def test_a_contract_signed_before_its_agreement_commits_once(world: _World, production_bus: EventBus) -> None:
    contract_id = await _signed_subcontract(world, production_bus)
    assert await world.budget() == (AGREEMENT_VALUE, Decimal("0.00"))

    await _linked_agreement(world, contract_id, sign=True)

    assert await world.budget() == (AGREEMENT_VALUE, Decimal("0.00"))


@pytest.mark.asyncio
async def test_an_agreement_signed_before_its_contract_commits_once(world: _World, production_bus: EventBus) -> None:
    contract_id = await world.contract(counterparty="subcontractor")
    await _linked_agreement(world, contract_id, sign=True)
    assert await world.budget() == (AGREEMENT_VALUE, Decimal("0.00"))

    await production_bus.publish(SIGNED, {"contract_id": str(contract_id)})
    await _drain(production_bus)

    assert await world.budget() == (AGREEMENT_VALUE, Decimal("0.00"))


@pytest.mark.asyncio
async def test_a_linked_pair_draws_its_one_commitment_down(world: _World, production_bus: EventBus) -> None:
    """A claim paid on the linked contract takes its gross off the agreement's commitment."""
    contract_id = await _signed_subcontract(world, production_bus)
    await _linked_agreement(world, contract_id, sign=True)
    claim_id = await world.approved_claim(contract_id)
    await _certify(world, production_bus, claim_id)

    async with world.factory() as session:
        await ContractsService(session).transition_claim(claim_id, "paid", actor_id=None)
        await session.commit()
    await _drain(production_bus)

    assert await world.budget() == (REMAINING, GROSS)


@pytest.mark.asyncio
async def test_a_contract_links_to_one_agreement_only(world: _World, production_bus: EventBus) -> None:
    from fastapi import HTTPException

    contract_id = await world.contract(counterparty="subcontractor")
    await _linked_agreement(world, contract_id, sign=False)

    with pytest.raises(HTTPException) as exc:
        await _linked_agreement(world, contract_id, sign=False)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "subcontract_already_linked"


@pytest.mark.asyncio
async def test_an_agreement_cannot_link_the_client_contract(world: _World, production_bus: EventBus) -> None:
    from fastapi import HTTPException

    contract_id = await world.contract(counterparty="client")
    with pytest.raises(HTTPException) as exc:
        await _linked_agreement(world, contract_id, sign=False)
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "linked_contract_not_subcontract"


def _legacy_claim_invoice(project_id: uuid.UUID, claim_id: uuid.UUID, number: str) -> Invoice:
    """The shape the removed notifications subscriber wrote: unlinked, net_due as total."""
    return Invoice(
        project_id=project_id,
        invoice_direction="receivable",
        invoice_number=number,
        invoice_date="2026-09-30",
        currency_code="EUR",
        amount_subtotal=NET,
        tax_amount=Decimal("0"),
        retention_amount=RETENTION,
        amount_total=NET,
        status="draft",
        metadata_={"source": "contracts.claim.certified", "claim_id": str(claim_id), "claim_number": number[3:]},
    )


@pytest.mark.asyncio
async def test_the_duplicate_report_finds_the_old_second_invoice_and_changes_nothing(
    world: _World, production_bus: EventBus
) -> None:
    from scripts.report_duplicate_claim_invoices import find_duplicate_claim_invoices

    contract_id = await world.contract(counterparty="subcontractor")
    claim_id = await world.approved_claim(contract_id)
    await _certify(world, production_bus, claim_id)
    orphan_claim = uuid.uuid4()
    async with world.factory() as session:
        session.add(_legacy_claim_invoice(world.project_id, claim_id, "PC-PC-0001"))
        session.add(_legacy_claim_invoice(world.project_id, orphan_claim, "PC-PC-0009"))
        await session.commit()

    async with world.factory() as session:
        rows = await find_duplicate_claim_invoices(session)

    by_number = {row["invoice_number"]: row for row in rows}
    assert set(by_number) == {"PC-PC-0001", "PC-PC-0009"}
    assert by_number["PC-PC-0001"]["kind"] == "duplicate"
    assert by_number["PC-PC-0001"]["linked_invoice_number"] == "INV-P-001"
    assert by_number["PC-PC-0009"]["kind"] == "only_invoice"
    assert len(await world.invoices()) == 3


# ── The same subcontract written twice, unlinked ────────────────────────────


async def _unlinked_pair(world: _World, bus: EventBus) -> tuple[uuid.UUID, uuid.UUID]:
    """A signed subcontract in contracts and a signed agreement for it, nobody linked them."""
    contract_id = await _signed_subcontract(world, bus)
    agreement_id = await _linked_agreement(world, None, sign=True)
    return agreement_id, contract_id


async def _twins_and_warning(world: _World, agreement_id: uuid.UUID) -> tuple[list[dict[str, Any]], list[str]]:
    async with world.factory() as session:
        svc = SubcontractorService(session)
        twins = await svc.find_unlinked_twins(world.project_id)
        report = await svc.validate_agreement(agreement_id)
    warned = [
        r["message"]
        for r in report["results"]
        if r["rule_id"] == "subcontract.unlinked_contract_twin" and not r["passed"]
    ]
    return twins, warned


@pytest.mark.asyncio
async def test_an_unlinked_pair_is_reported_and_counted_twice_until_linked(
    world: _World, production_bus: EventBus
) -> None:
    agreement_id, contract_id = await _unlinked_pair(world, production_bus)
    # The double count the report exists for.
    assert await world.budget() == (2 * AGREEMENT_VALUE, Decimal("0.00"))

    twins, warned = await _twins_and_warning(world, agreement_id)
    assert [(t["agreement_id"], t["contract_id"], t["matched_on"]) for t in twins] == [
        (str(agreement_id), str(contract_id), "counterparty")
    ]
    assert twins[0]["value_close"] is True
    assert len(warned) == 1 and "twice" in warned[0]

    async with world.factory() as session:
        await SubcontractorService(session).update_agreement(agreement_id, AgreementUpdate(contract_id=contract_id))
        await session.commit()

    assert await world.budget() == (AGREEMENT_VALUE, Decimal("0.00"))
    assert await _twins_and_warning(world, agreement_id) == ([], [])


@pytest.mark.asyncio
async def test_a_pair_said_to_be_different_is_not_raised_again_and_not_merged(
    world: _World, production_bus: EventBus
) -> None:
    agreement_id, contract_id = await _unlinked_pair(world, production_bus)

    async with world.factory() as session:
        svc = SubcontractorService(session)
        await svc.dismiss_unlinked_twin(agreement_id, contract_id)
        await svc.dismiss_unlinked_twin(agreement_id, contract_id)
        await session.commit()

    assert await _twins_and_warning(world, agreement_id) == ([], [])
    # Two subcontracts, two commitments: nothing was merged behind the user's back.
    assert await world.budget() == (2 * AGREEMENT_VALUE, Decimal("0.00"))


@pytest.mark.asyncio
async def test_a_contract_in_another_currency_is_not_a_twin(world: _World, production_bus: EventBus) -> None:
    async with world.factory() as session:
        session.add(
            Contract(
                code="SC-USD",
                title="Drywall subcontract",
                project_id=world.project_id,
                counterparty_type="subcontractor",
                counterparty_id=world.subcontractor_id,
                status="active",
                currency="USD",
                total_value=AGREEMENT_VALUE,
                retention_percent=RETENTION_PCT,
            )
        )
        await session.commit()
    agreement_id = await _linked_agreement(world, None, sign=False)

    assert await _twins_and_warning(world, agreement_id) == ([], [])
