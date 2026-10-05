# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The invoice raised from a certified claim falls due on the agreed terms.

Without a due date the client portal can never call the bill overdue, and a
payment plan's reminders have nothing to count down to. An invoice whose
contract agreed no payment period keeps no due date rather than an invented
one.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio

from app.modules.contracts.models import Contract, ContractMilestone, ProgressClaim
from app.modules.finance.service import FinanceService
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

OWNER_ID = uuid.uuid4()


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email="owner@test.io", hashed_password="x", full_name="Owner"))
        await s.flush()
        yield s


async def _claim(s, *, terms: dict | None, milestone_terms: int | None = None, claim_date: str = "2026-06-01"):
    project = Project(id=uuid.uuid4(), name="Due dates", owner_id=OWNER_ID, currency="USD", status="active")
    s.add(project)
    await s.flush()
    contract = Contract(
        id=uuid.uuid4(),
        code=f"C-{uuid.uuid4().hex[:8]}",
        title="Main works",
        project_id=project.id,
        currency="USD",
        retention_percent=Decimal("0"),
        status="active",
        terms=terms or {},
    )
    s.add(contract)
    await s.flush()
    milestone_id = None
    if milestone_terms is not None:
        milestone = ContractMilestone(
            id=uuid.uuid4(),
            contract_id=contract.id,
            code="M1",
            name="Frame complete",
            trigger="completion",
            status="invoiced",
            payment_terms_days=milestone_terms,
        )
        s.add(milestone)
        await s.flush()
        milestone_id = milestone.id
    claim = ProgressClaim(
        id=uuid.uuid4(),
        contract_id=contract.id,
        claim_number=f"PC-{uuid.uuid4().hex[:4]}",
        claim_date=claim_date,
        gross_amount=Decimal("1000"),
        retention_amount=Decimal("0"),
        net_due=Decimal("1000"),
        currency="USD",
        status="certified",
        milestone_id=milestone_id,
    )
    s.add(claim)
    await s.flush()
    return claim


@pytest.mark.asyncio
async def test_the_contract_payment_period_counts_from_the_invoice_date(session) -> None:
    claim = await _claim(session, terms={"payment_terms": {"payment_period_days": 30}})
    invoice = await FinanceService(session).create_receivable_from_claim(claim.id)
    assert invoice.invoice_date == "2026-06-01"
    assert invoice.due_date == "2026-07-01"


@pytest.mark.asyncio
async def test_an_instalment_with_its_own_terms_uses_them(session) -> None:
    claim = await _claim(session, terms={"payment_terms": {"payment_period_days": 30}}, milestone_terms=7)
    invoice = await FinanceService(session).create_receivable_from_claim(claim.id)
    assert invoice.due_date == "2026-06-08"


@pytest.mark.asyncio
async def test_an_instalment_without_terms_falls_back_to_the_contract(session) -> None:
    claim = await _claim(session, terms={"payment_terms": {"payment_period_days": 14}}, milestone_terms=None)
    invoice = await FinanceService(session).create_receivable_from_claim(claim.id)
    assert invoice.due_date == "2026-06-15"


@pytest.mark.asyncio
async def test_no_agreed_period_leaves_no_due_date(session) -> None:
    claim = await _claim(session, terms=None)
    invoice = await FinanceService(session).create_receivable_from_claim(claim.id)
    assert invoice.due_date is None


@pytest.mark.asyncio
async def test_a_claim_without_a_date_gets_no_due_date(session) -> None:
    claim = await _claim(session, terms={"payment_terms": {"payment_period_days": 30}}, claim_date="")
    invoice = await FinanceService(session).create_receivable_from_claim(claim.id)
    assert invoice.due_date is None
