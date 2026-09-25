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

These tests go through the production wiring: the registrars the app runs at
startup, a real bus and the real after-commit publishing, against a throwaway
database whose rows every subscriber session can see.
"""

from __future__ import annotations

import asyncio
import uuid
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
from app.core.events import EventBus
from app.modules.contacts.models import Contact
from app.modules.contracts.models import Contract, ProgressClaim
from app.modules.contracts.service import ContractsService
from app.modules.finance.models import Invoice
from app.modules.finance.service import FinanceService
from app.modules.projects.models import Project
from app.modules.subcontractors.models import Subcontractor
from app.modules.users.models import User
from tests._pg import isolated_engine

CERTIFIED = "contracts.claim.certified"

AGREEMENT_VALUE = Decimal("120000")
RETENTION_PCT = Decimal("5")
GROSS = Decimal("36000")
RETENTION = Decimal("1800")
NET = Decimal("34200")


class _World:
    """A throwaway database holding one EUR project, a subcontractor and a client."""

    def __init__(self, factory: async_sessionmaker[AsyncSession], project_id: uuid.UUID) -> None:
        self.factory = factory
        self.project_id = project_id
        self.sub_contact_id: uuid.UUID | None = None
        self.subcontractor_id: uuid.UUID | None = None
        self.client_contact_id: uuid.UUID | None = None

    async def contract(self, *, counterparty: str) -> uuid.UUID:
        async with self.factory() as session:
            contract = Contract(
                code=f"SC-{uuid.uuid4().hex[:8]}",
                title="Drywall subcontract" if counterparty == "subcontractor" else "Main contract",
                project_id=self.project_id,
                counterparty_type=counterparty,
                counterparty_id=self.subcontractor_id if counterparty == "subcontractor" else self.client_contact_id,
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


@pytest_asyncio.fixture
async def world(monkeypatch: pytest.MonkeyPatch):
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        # Subscribers open their own sessions by design; point them at the
        # throwaway database so they see the rows committed here.
        monkeypatch.setattr(finance_events, "async_session_factory", factory)
        monkeypatch.setattr(w5, "async_session_factory", factory)
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
            session.add(sub)
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
    for module in (core_events, contracts_service, finance_events, finance_service, w5):
        monkeypatch.setattr(module, "event_bus", bus)
    finance_events.register_finance_subscribers()
    w5.register_wave5_notification_subscribers()
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
