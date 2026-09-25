# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A claim line entered as "% complete" bills that percent of its SoV line.

The line editor sends the percent and the value together, and a line typed as
a percent alone arrives with a value of zero. The endpoints stored the zero,
so a subcontractor at 30% on a 120,000 line was billed nothing. The percent is
to date, as on the generated lines, so the period bills that percent of the
line less what earlier claims billed on it.

A value typed by hand still wins: it is only worked out from the percent when
the value is empty, or when the percent is what changed.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio

from app.modules.contracts.models import Contract, ContractLine, ProgressClaim
from app.modules.contracts.router import create_claim_line, update_claim_line
from app.modules.contracts.schemas import ProgressClaimLineCreate, ProgressClaimLineUpdate
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

OWNER_ID = uuid.uuid4()


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email=f"pct-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
        await s.flush()
        yield s


async def _subcontract(session) -> tuple[Contract, ContractLine]:
    project = Project(id=uuid.uuid4(), name="Zagreb B", owner_id=OWNER_ID, currency="EUR", country_code="HR")
    session.add(project)
    await session.flush()
    contract = Contract(
        id=uuid.uuid4(),
        code=f"SC-{uuid.uuid4().hex[:8]}",
        title="Drywall",
        project_id=project.id,
        contract_type="lump_sum",
        counterparty_type="subcontractor",
        currency="EUR",
        total_value=Decimal("120000"),
        retention_percent=Decimal("5"),
        status="active",
    )
    session.add(contract)
    await session.flush()
    line = ContractLine(
        id=uuid.uuid4(),
        contract_id=contract.id,
        code="01",
        description="Drywall, block B",
        quantity=Decimal("1"),
        unit_rate=Decimal("120000"),
        total_value=Decimal("120000"),
        order_index=0,
    )
    session.add(line)
    await session.flush()
    return contract, line


async def _claim(session, contract: Contract, number: str, month: int) -> ProgressClaim:
    claim = ProgressClaim(
        id=uuid.uuid4(),
        contract_id=contract.id,
        claim_number=number,
        period_start=f"2026-{month:02d}-01",
        period_end=f"2026-{month:02d}-28",
        period_from=date(2026, month, 1),
        period_to=date(2026, month, 28),
        currency="EUR",
        status="draft",
    )
    session.add(claim)
    await session.flush()
    return claim


async def _add(session, claim: ProgressClaim, line: ContractLine, pct: str, value: str = "0"):
    return await create_claim_line(
        ProgressClaimLineCreate(
            progress_claim_id=claim.id,
            contract_line_id=line.id,
            period_completed_pct=Decimal(pct),
            period_completed_value=Decimal(value),
        ),
        session,
        str(OWNER_ID),
    )


async def test_thirty_percent_of_a_120000_line_bills_36000(session) -> None:
    contract, line = await _subcontract(session)
    claim = await _claim(session, contract, "PC-1", 3)

    written = await _add(session, claim, line, "30")

    assert written.period_completed_value == Decimal("36000")
    assert written.cumulative_completed_value == Decimal("36000")
    await session.refresh(claim)
    assert (claim.gross_amount, claim.retention_amount, claim.net_due) == (
        Decimal("36000"),
        Decimal("1800.0000"),
        Decimal("34200.0000"),
    )


async def test_the_percent_is_to_date_so_the_next_claim_bills_the_difference(session) -> None:
    contract, line = await _subcontract(session)
    await _add(session, await _claim(session, contract, "PC-1", 3), line, "30")

    april = await _add(session, await _claim(session, contract, "PC-2", 4), line, "50")

    assert april.prior_completed_value == Decimal("36000")
    assert april.period_completed_value == Decimal("24000")
    assert april.cumulative_completed_value == Decimal("60000")


async def test_changing_the_percent_moves_the_value_with_it(session) -> None:
    contract, line = await _subcontract(session)
    claim = await _claim(session, contract, "PC-1", 3)
    written = await _add(session, claim, line, "30")

    # The editor sends both fields back; only the percent was changed.
    edited = await update_claim_line(
        written.id,
        ProgressClaimLineUpdate(period_completed_pct=Decimal("40"), period_completed_value=Decimal("36000")),
        session,
        str(OWNER_ID),
    )

    assert edited.period_completed_value == Decimal("48000")
    await session.refresh(claim)
    assert claim.gross_amount == Decimal("48000")


async def test_a_value_typed_by_hand_still_wins(session) -> None:
    contract, line = await _subcontract(session)
    claim = await _claim(session, contract, "PC-1", 3)

    typed = await _add(session, claim, line, "30", value="30000")
    assert typed.period_completed_value == Decimal("30000")

    edited = await update_claim_line(
        typed.id,
        ProgressClaimLineUpdate(period_completed_pct=Decimal("30"), period_completed_value=Decimal("31000")),
        session,
        str(OWNER_ID),
    )
    assert edited.period_completed_value == Decimal("31000")
