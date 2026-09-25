# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A line written by hand moves the claim's own totals, or it is refused.

The inline line editor wrote the line and nothing else. The claim kept the
gross, retention and net it was generated with, the accounts receivable
invoice was booked from those stale figures, and every later claim read them
as what this one certified, so one correction typed on site walked forward
through the rest of the job.

Two rules, both tested here on PostgreSQL through the endpoints the editor
calls:

* a line write re-works the claim it belongs to, in the same transaction,
  including on a contract that retains at a flat rate;
* a claim that has left draft refuses the write. It used to accept it while
  submitted, which is the state where the payer is already reading the
  application the lines are supposed to add up to.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.modules.contracts.models import Contract, ContractLine, ProgressClaim
from app.modules.contracts.router import (
    create_claim_line,
    delete_claim_line,
    update_claim_line,
)
from app.modules.contracts.schemas import (
    AutoGenerateClaimRequest,
    ProgressClaimLineCreate,
    ProgressClaimLineUpdate,
)
from app.modules.contracts.service import ContractsService
from app.modules.contracts.validators import register_contracts_validation_rules
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _pay_application_rules() -> None:
    # Submitting a claim runs the pay_application gate, which refuses when the
    # rule set is not loaded; registering here keeps the file order-independent.
    register_contracts_validation_rules()


OWNER_ID = uuid.uuid4()


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email=f"lines-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
        await s.flush()
        yield s


async def _world(session, contract_type: str = "lump_sum"):
    project = Project(id=uuid.uuid4(), name="Lines", owner_id=OWNER_ID, currency="USD", country_code="US")
    session.add(project)
    await session.flush()
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
    )
    session.add(contract)
    await session.flush()
    lines = []
    for index, (code, value) in enumerate([("A", "60000"), ("B", "40000")]):
        line = ContractLine(
            id=uuid.uuid4(),
            contract_id=contract.id,
            code=code,
            description=f"Line {code}",
            quantity=Decimal("1"),
            unit_rate=Decimal(value),
            total_value=Decimal(value),
            order_index=index,
        )
        session.add(line)
        lines.append(line)
    await session.flush()
    return SimpleNamespace(project=project, contract=contract, a=lines[0], b=lines[1])


async def _claim(session, world, number: str, month: int) -> ProgressClaim:
    claim = ProgressClaim(
        id=uuid.uuid4(),
        contract_id=world.contract.id,
        claim_number=number,
        period_start=f"2026-{month:02d}-01",
        period_end=f"2026-{month:02d}-28",
        period_from=date(2026, month, 1),
        period_to=date(2026, month, 28),
        currency="USD",
        status="draft",
    )
    session.add(claim)
    await session.flush()
    return claim


async def test_a_line_corrected_by_hand_moves_the_claim_it_belongs_to(session) -> None:
    world = await _world(session)
    svc = ContractsService(session)
    march = await svc.auto_generate_claim_lines(
        (await _claim(session, world, "PC-1", 3)).id,
        AutoGenerateClaimRequest(completion={str(world.a.id): Decimal("40"), str(world.b.id): Decimal("40")}),
    )
    assert (march.gross_amount, march.retention_amount, march.net_due) == (
        Decimal("40000"),
        Decimal("4000"),
        Decimal("36000.0000"),
    )
    line_a = next(ln for ln in await svc.claim_line_repo.list_for_claim(march.id) if ln.contract_line_id == world.a.id)

    await update_claim_line(
        line_a.id,
        ProgressClaimLineUpdate(period_completed_value=Decimal("30000")),
        session,
        str(OWNER_ID),
    )
    await session.refresh(march)
    # 30,000 on A and 16,000 on B: the claim says so too, not just the line.
    assert (march.gross_amount, march.retention_amount, march.net_due) == (
        Decimal("46000"),
        Decimal("4600"),
        Decimal("41400.0000"),
    )

    # And what the next claim reads as previously certified is the corrected
    # figure, which is where the old behaviour did its lasting damage. March
    # goes out first: a draft is not a previous certificate.
    await svc.transition_claim(march.id, "submitted")
    april = await svc.auto_generate_claim_lines(
        (await _claim(session, world, "PC-2", 4)).id,
        AutoGenerateClaimRequest(completion={str(world.a.id): Decimal("60"), str(world.b.id): Decimal("60")}),
    )
    assert april.prior_claims_total == Decimal("41400")
    application = await svc.build_aia_application(april.id)
    assert application["summary"]["previous_certificates_total"] == Decimal("41400.00")
    assert application["summary"]["current_payment_due"] == april.net_due


async def test_a_flat_retention_claim_follows_its_lines_too(session) -> None:
    # Cost-plus and T&M keep a flat rate, and that branch used to write a net
    # worked out from the gross the edit had just made wrong.
    world = await _world(session, "cost_plus")
    svc = ContractsService(session)
    claim = await _claim(session, world, "PC-1", 3)
    line = await create_claim_line(
        ProgressClaimLineCreate(
            progress_claim_id=claim.id,
            contract_line_id=world.a.id,
            period_completed_qty=Decimal("1"),
            period_completed_value=Decimal("10000"),
            period_completed_pct=Decimal("16.67"),
        ),
        session,
        str(OWNER_ID),
    )
    await session.refresh(claim)
    assert (claim.gross_amount, claim.retention_amount, claim.net_due) == (
        Decimal("10000"),
        Decimal("1000.0000"),
        Decimal("9000.0000"),
    )

    await update_claim_line(
        line.id, ProgressClaimLineUpdate(period_completed_value=Decimal("4000")), session, str(OWNER_ID)
    )
    await session.refresh(claim)
    assert (claim.gross_amount, claim.retention_amount, claim.net_due) == (
        Decimal("4000"),
        Decimal("400.0000"),
        Decimal("3600.0000"),
    )

    await delete_claim_line(line.id, session, str(OWNER_ID))
    await session.refresh(claim)
    assert (claim.gross_amount, claim.net_due) == (Decimal("0"), Decimal("0.0000"))


async def test_a_cost_plus_claim_with_no_lines_keeps_what_its_generator_worked_out(session) -> None:
    # The normal cost-plus shape: costs for the period, no schedule of values
    # behind them. There is nothing to add up, so the generator's figures stand.
    world = await _world(session, "cost_plus")
    svc = ContractsService(session)
    claim = await svc.auto_generate_claim_lines(
        (await _claim(session, world, "PC-1", 3)).id,
        SimpleNamespace(actual_costs_total=Decimal("2000")),
    )
    assert (claim.gross_amount, claim.retention_amount, claim.net_due) == (
        Decimal("2000"),
        Decimal("200.0000"),
        Decimal("1800.0000"),
    )
    claim = await svc.roll_claim_retention(claim.id)
    assert (claim.gross_amount, claim.retention_amount, claim.net_due) == (
        Decimal("2000"),
        Decimal("200.0000"),
        Decimal("1800.0000"),
    )


@pytest.mark.parametrize("status", ["submitted", "approved", "certified", "paid"])
async def test_a_claim_that_left_draft_refuses_a_line_write(session, status: str) -> None:
    world = await _world(session)
    svc = ContractsService(session)
    march = await svc.auto_generate_claim_lines(
        (await _claim(session, world, "PC-1", 3)).id,
        AutoGenerateClaimRequest(completion={str(world.a.id): Decimal("40")}),
    )
    line = next(ln for ln in await svc.claim_line_repo.list_for_claim(march.id) if ln.contract_line_id == world.a.id)
    await svc.claim_repo.update_fields(march.id, status=status)

    for call in (
        update_claim_line(
            line.id, ProgressClaimLineUpdate(period_completed_value=Decimal("1")), session, str(OWNER_ID)
        ),
        delete_claim_line(line.id, session, str(OWNER_ID)),
        create_claim_line(
            ProgressClaimLineCreate(
                progress_claim_id=march.id,
                contract_line_id=world.b.id,
                period_completed_qty=Decimal("1"),
                period_completed_value=Decimal("1000"),
                period_completed_pct=Decimal("2.5"),
            ),
            session,
            str(OWNER_ID),
        ),
    ):
        with pytest.raises(HTTPException) as refused:
            await call
        assert refused.value.status_code == 422
        assert refused.value.detail["error"] == "claim_not_editable"
        assert refused.value.detail["claim_status"] == status

    await session.refresh(march)
    assert march.gross_amount == Decimal("24000")
