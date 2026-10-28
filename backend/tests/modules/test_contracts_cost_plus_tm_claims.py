# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Cost-plus and T&M claims bill their own period, and the cap counts all billing.

Two defects, one on each contract type without a schedule of values:

* Net due was ``gross - retention - what earlier claims were paid``, although
  the costs and time entries on a claim are that period's. Every payment was
  taken off every later claim again.
* The T&M not-to-exceed cap was checked against what had been paid, so any
  claim still awaiting payment did not count towards it, and a contract could
  bill past its cap as long as the owner paid slowly.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.modules.contracts.models import Contract, ProgressClaim
from app.modules.contracts.service import ContractsService
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

OWNER_ID = uuid.uuid4()


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email=f"cptm-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
        await s.flush()
        yield s


async def _contract(s, contract_type: str, **terms) -> Contract:
    project = Project(id=uuid.uuid4(), name="CP/TM", owner_id=OWNER_ID, currency="USD", country_code="US")
    s.add(project)
    await s.flush()
    contract = Contract(
        id=uuid.uuid4(),
        code=f"C-{uuid.uuid4().hex[:8]}",
        title="Works",
        project_id=project.id,
        contract_type=contract_type,
        currency="USD",
        total_value=Decimal("100000"),
        retention_percent=Decimal("10"),
        status="active",
        terms=terms,
    )
    s.add(contract)
    await s.flush()
    return contract


async def _claim(s, contract: Contract, number: str, end: str, *, status: str = "draft", gross: str = "0"):
    amount = Decimal(gross)
    claim = ProgressClaim(
        id=uuid.uuid4(),
        contract_id=contract.id,
        claim_number=number,
        period_start=end[:8] + "01",
        period_end=end,
        currency="USD",
        status=status,
        gross_amount=amount,
        retention_amount=amount / 10,
        net_due=amount - amount / 10,
    )
    s.add(claim)
    await s.flush()
    return claim


async def test_a_cost_plus_claim_is_not_charged_again_for_what_was_paid(session) -> None:
    svc = ContractsService(session)
    contract = await _contract(session, "cost_plus")
    await _claim(session, contract, "PC-1", "2026-03-31", status="paid", gross="5000")
    april = await _claim(session, contract, "PC-2", "2026-04-30")

    april = await svc.auto_generate_claim_lines(april.id, SimpleNamespace(actual_costs_total=Decimal("2000")))
    assert april.gross_amount == Decimal("2000")
    assert april.retention_amount == Decimal("200.0000")
    # Used to be 1800 - 4500 floored to 0: the March payment taken off again.
    assert april.net_due == Decimal("1800.0000")
    # Prior claims is what March certified, as on every other contract type.
    assert april.prior_claims_total == Decimal("4500")
    # There is no schedule of values behind a cost-plus claim and so no
    # certificate snapshot: line 7 is rebuilt from the stored figures.
    assert await svc.previous_certificates(april) == (Decimal("4500"), "reconstructed")


async def test_the_tm_cap_counts_unpaid_claims_and_later_ones(session) -> None:
    svc = ContractsService(session)
    contract = await _contract(session, "tm", tm_nte_cap="10000")
    # Billed, not paid, and later in billing order than the claim generated.
    await _claim(session, contract, "PC-2", "2026-04-30", status="submitted", gross="9000")
    march = await _claim(session, contract, "PC-1", "2026-03-31")

    with pytest.raises(HTTPException) as refused:
        await svc.auto_generate_claim_lines(
            march.id,
            SimpleNamespace(time_entries_total=Decimal("1500"), material_entries_total=Decimal("0")),
        )
    assert refused.value.detail["error"] == "nte_cap_exceeded"

    # Within the cap it bills, net of retention only.
    march = await svc.auto_generate_claim_lines(
        march.id,
        SimpleNamespace(time_entries_total=Decimal("1000"), material_entries_total=Decimal("0")),
    )
    assert (march.gross_amount, march.net_due) == (Decimal("1000"), Decimal("900.0000"))


@pytest.mark.parametrize("status", ["rejected", "draft"])
async def test_a_claim_that_was_not_billed_does_not_use_up_the_cap(session, status: str) -> None:
    # A rejected claim was billed and taken back; a draft was never sent, and
    # counting it would let two drafts in progress block each other.
    svc = ContractsService(session)
    contract = await _contract(session, "tm", tm_nte_cap="10000")
    await _claim(session, contract, "PC-1", "2026-03-31", status=status, gross="9000")
    april = await _claim(session, contract, "PC-2", "2026-04-30")
    april = await svc.auto_generate_claim_lines(
        april.id,
        SimpleNamespace(time_entries_total=Decimal("5000"), material_entries_total=Decimal("0")),
    )
    assert april.gross_amount == Decimal("5000")
