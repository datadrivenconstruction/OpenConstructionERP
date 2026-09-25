# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The invoice raised from a certified claim carries the claim's retention.

A client claim billed from a schedule of values at 10 % retention: 40 % of a
60 000 line is 24 000 gross, 2 400 held, 21 600 due. The invoice keeps the
gross in its subtotal and total and the 2 400 beside it, so the claim invoice
card's net collectible (total less retention) is the 21 600 the certificate
says is due, not the gross. The card used to print the subtotal (P-39); it
now subtracts retention, and this pins that the retention is there to
subtract.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio

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


@pytest_asyncio.fixture
async def session():
    register_contracts_validation_rules()
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email=f"claim-inv-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
        await s.flush()
        yield s


async def test_the_invoice_from_a_certified_claim_holds_its_retention(session) -> None:
    project = Project(id=uuid.uuid4(), name="Works", owner_id=OWNER_ID, currency="EUR", country_code="DE")
    session.add(project)
    await session.flush()
    contract = Contract(
        id=uuid.uuid4(),
        code=f"C-{uuid.uuid4().hex[:8]}",
        title="Main works",
        project_id=project.id,
        contract_type="lump_sum",
        currency="EUR",
        total_value=Decimal("60000"),
        original_contract_value=Decimal("60000"),
        retention_percent=Decimal("10"),
        status="active",
        terms={},
    )
    session.add(contract)
    await session.flush()
    line = ContractLine(
        id=uuid.uuid4(),
        contract_id=contract.id,
        code="A",
        description="Line A",
        quantity=Decimal("10"),
        unit_rate=Decimal("6000"),
        total_value=Decimal("60000"),
        metadata_={},
    )
    claim = ProgressClaim(
        id=uuid.uuid4(),
        contract_id=contract.id,
        claim_number="PC-1",
        period_start="2026-03-01",
        period_end="2026-03-28",
        period_from=date(2026, 3, 1),
        period_to=date(2026, 3, 28),
        status="draft",
        currency="EUR",
    )
    session.add_all([line, claim])
    await session.flush()

    svc = ContractsService(session)
    claim = await svc.auto_generate_claim_lines(
        claim.id, AutoGenerateClaimRequest(completion={str(line.id): Decimal("40")})
    )
    for target in ("submitted", "approved", "certified"):
        claim = await svc.transition_claim(claim.id, target, actor_id=str(OWNER_ID))

    invoice = await FinanceService(session).create_receivable_from_claim(claim.id)

    assert invoice.invoice_direction == "receivable"
    assert (Decimal(invoice.amount_subtotal), Decimal(invoice.retention_amount)) == (Decimal("24000"), Decimal("2400"))
    collectible = Decimal(invoice.amount_total) - Decimal(invoice.retention_amount)
    assert collectible == Decimal(claim.net_due) == Decimal("21600")
