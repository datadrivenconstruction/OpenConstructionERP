# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A progress claim that has left draft is not deleted, and its lines stay.

``ProgressClaimLine.progress_claim_id`` cascades, so deleting a claim deletes
its breakdown with it. The claim line routes already refuse to add, change or
remove a line once the claim has left draft. The claim's own delete route did
not: it called the repository directly and would remove a certified or paid
claim, lines and all. A later claim's certificate sums its previous
applications and its column D from the claims before it, so it would then be
worked out as if the deleted one had never been issued.

A draft claim still deletes. It has gone nowhere, and the retention release
comment on the model already treats deleting a draft claim as ordinary.

Every read-back is a fresh SELECT rather than ``session.get``, so a row still
held in the identity map cannot answer for one the database has removed.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import func, select

from app.modules.contracts.models import Contract, ContractLine, ProgressClaim, ProgressClaimLine
from app.modules.contracts.service import ContractsService
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

OWNER_ID = uuid.uuid4()

#: Every status past draft. A rejected claim is reopened to draft before it
#: can be changed, so it is refused here too.
PAST_DRAFT = ("submitted", "approved", "certified", "paid", "rejected")


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email=f"claimdel-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
        await s.flush()
        yield s


async def _claim_with_a_line(session, *, status: str) -> tuple[ProgressClaim, ContractLine]:
    project = Project(id=uuid.uuid4(), name="Claims", owner_id=OWNER_ID, currency="USD", country_code="US")
    session.add(project)
    await session.flush()
    contract = Contract(
        id=uuid.uuid4(),
        code=f"C-{uuid.uuid4().hex[:8]}",
        title="Main works",
        project_id=project.id,
        contract_type="lump_sum",
        currency="USD",
        total_value=Decimal("100000"),
        retention_percent=Decimal("10"),
        status="active",
    )
    session.add(contract)
    await session.flush()
    line = ContractLine(
        id=uuid.uuid4(),
        contract_id=contract.id,
        code="1",
        description="Line 1",
        unit="m2",
        quantity=Decimal("100"),
        unit_rate=Decimal("1000"),
        total_value=Decimal("100000"),
        order_index=1,
    )
    session.add(line)
    await session.flush()
    claim = ProgressClaim(
        id=uuid.uuid4(),
        contract_id=contract.id,
        claim_number="PC-1",
        period_start="2026-03-01",
        period_end="2026-03-31",
        period_from=date(2026, 3, 1),
        period_to=date(2026, 3, 31),
        currency="USD",
        gross_amount=Decimal("25000"),
        retention_amount=Decimal("2500"),
        net_due=Decimal("22500"),
        status=status,
    )
    session.add(claim)
    await session.flush()
    session.add(
        ProgressClaimLine(
            id=uuid.uuid4(),
            progress_claim_id=claim.id,
            contract_line_id=line.id,
            period_completed_qty=Decimal("25"),
            period_completed_value=Decimal("25000"),
            period_completed_pct=Decimal("25"),
            prior_completed_value=Decimal("0"),
            cumulative_completed_value=Decimal("25000"),
        )
    )
    await session.flush()
    return claim, line


async def _claims_with_id(session, claim_id: uuid.UUID) -> int:
    stmt = select(func.count()).select_from(ProgressClaim).where(ProgressClaim.id == claim_id)
    return (await session.execute(stmt)).scalar_one()


async def _lines_of_claim(session, claim_id: uuid.UUID) -> int:
    stmt = select(func.count()).select_from(ProgressClaimLine).where(ProgressClaimLine.progress_claim_id == claim_id)
    return (await session.execute(stmt)).scalar_one()


@pytest.mark.parametrize("claim_status", PAST_DRAFT)
async def test_a_claim_past_draft_is_refused_and_keeps_its_lines(session, claim_status: str) -> None:
    svc = ContractsService(session)
    claim, _line = await _claim_with_a_line(session, status=claim_status)

    refused: HTTPException | None = None
    try:
        await svc.delete_progress_claim(claim.id)
    except HTTPException as exc:
        refused = exc

    # Before the guard both read 0: the claim and its breakdown were gone.
    assert await _claims_with_id(session, claim.id) == 1
    assert await _lines_of_claim(session, claim.id) == 1
    assert refused is not None
    # The same refusal the claim line routes give for the same claim.
    assert refused.status_code == 422
    assert refused.detail["error"] == "claim_not_editable"
    assert refused.detail["claim_status"] == claim_status


async def test_a_draft_claim_still_deletes_with_its_lines(session) -> None:
    """The control. A draft has gone nowhere, so removing it is ordinary."""
    svc = ContractsService(session)
    claim, line = await _claim_with_a_line(session, status="draft")

    await svc.delete_progress_claim(claim.id)

    assert await _claims_with_id(session, claim.id) == 0
    assert await _lines_of_claim(session, claim.id) == 0
    # The schedule line it billed on is the contract's, not the claim's.
    lines = select(func.count()).select_from(ContractLine).where(ContractLine.id == line.id)
    assert (await session.execute(lines)).scalar_one() == 1


async def test_a_claim_that_is_not_there_is_a_404(session) -> None:
    svc = ContractsService(session)
    with pytest.raises(HTTPException) as caught:
        await svc.delete_progress_claim(uuid.uuid4())
    assert caught.value.status_code == 404
