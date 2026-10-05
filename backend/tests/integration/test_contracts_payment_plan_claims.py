# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Claims raised from payment-plan instalments, on a real database.

An instalment that is reached becomes a draft claim for the instalment's
agreed amount. Its gross is not made of schedule-of-values lines, so it
records the ``milestone`` basis, and a line typed in by hand afterwards is a
breakdown that must not replace the agreed amount.

The first block pins how the bases that existed before this one behave when a
line is added by hand, so widening the set of fixed bases cannot move them:
a cost basis keeps its gross, a lines basis and a claim that records no basis
follow their lines.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.modules.contracts.models import (
    Contract,
    ContractLine,
    ContractMilestone,
    ProgressClaim,
    ProgressClaimLine,
)
from app.modules.contracts.schemas import AutoGenerateClaimRequest
from app.modules.contracts.service import ContractsService
from app.modules.contracts.validators import register_contracts_validation_rules
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

OWNER_ID = uuid.uuid4()
COST_OF_WORK = Decimal("50000")
HAND_LINE_VALUE = Decimal("1000")


@pytest_asyncio.fixture
async def session():
    register_contracts_validation_rules()
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email=f"plan-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
        await s.flush()
        yield s


async def _contract(session, *, contract_type: str = "lump_sum", status: str = "active") -> Contract:
    project = Project(id=uuid.uuid4(), name="Plan", owner_id=OWNER_ID, currency="USD", country_code="US")
    session.add(project)
    await session.flush()
    contract = Contract(
        id=uuid.uuid4(),
        code=f"C-{uuid.uuid4().hex[:8]}",
        title="Main works",
        project_id=project.id,
        contract_type=contract_type,
        currency="USD",
        total_value=Decimal("100000"),
        retention_percent=Decimal("10"),
        terms={"fee_percent": "0"},
        status=status,
    )
    session.add(contract)
    await session.flush()
    line = ContractLine(
        id=uuid.uuid4(),
        contract_id=contract.id,
        code="01",
        description="Line A",
        unit="m2",
        quantity=Decimal("1"),
        unit_rate=Decimal("100000"),
        total_value=Decimal("100000"),
        order_index=0,
    )
    session.add(line)
    await session.flush()
    contract.line = line  # type: ignore[attr-defined]
    return contract


async def _draft_claim(session, contract: Contract, *, gross_basis: str | None = None) -> ProgressClaim:
    claim = ProgressClaim(
        id=uuid.uuid4(),
        contract_id=contract.id,
        claim_number=f"PC-{uuid.uuid4().hex[:4]}",
        period_start="2026-03-01",
        period_end="2026-03-31",
        period_from=date(2026, 3, 1),
        period_to=date(2026, 3, 31),
        currency="USD",
        status="draft",
        gross_basis=gross_basis,
    )
    session.add(claim)
    await session.flush()
    return claim


async def _add_line_by_hand(session, svc: ContractsService, claim: ProgressClaim, line_id, value: Decimal) -> None:
    """What POST /progress-claim-lines/ does, minus the HTTP layer."""
    fields = {"progress_claim_id": claim.id, "contract_line_id": line_id, "period_completed_value": value}
    fields.update(await svc.claim_line_running_totals(claim, line_id, value))
    session.add(ProgressClaimLine(**fields))
    await session.flush()
    await svc.roll_claim_retention(claim.id, gross_follows_lines=True)


# ── Existing bases, pinned before the milestone basis joined them ────────


async def test_a_cost_basis_keeps_its_gross_when_a_line_is_added(session) -> None:
    svc = ContractsService(session)
    contract = await _contract(session, contract_type="cost_plus")
    claim = await _draft_claim(session, contract)
    await svc.auto_generate_claim_lines(claim.id, AutoGenerateClaimRequest(actual_costs_total=COST_OF_WORK))

    await _add_line_by_hand(session, svc, claim, contract.line.id, HAND_LINE_VALUE)

    await session.refresh(claim)
    assert claim.gross_basis == "cost"
    assert claim.gross_amount == COST_OF_WORK
    assert claim.retention_amount == Decimal("5000.0000")


@pytest.mark.parametrize("basis", ["lines", None])
async def test_a_lines_or_unrecorded_basis_follows_its_lines_on_cost_plus(session, basis) -> None:
    svc = ContractsService(session)
    contract = await _contract(session, contract_type="cost_plus")
    claim = await _draft_claim(session, contract, gross_basis=basis)
    await svc.claim_repo.update_fields(claim.id, gross_amount=COST_OF_WORK)

    await _add_line_by_hand(session, svc, claim, contract.line.id, HAND_LINE_VALUE)

    await session.refresh(claim)
    assert claim.gross_amount == HAND_LINE_VALUE


@pytest.mark.parametrize("basis", ["lines", None])
async def test_a_lines_or_unrecorded_basis_follows_its_lines_on_lump_sum(session, basis) -> None:
    svc = ContractsService(session)
    contract = await _contract(session, contract_type="lump_sum")
    claim = await _draft_claim(session, contract, gross_basis=basis)
    await svc.claim_repo.update_fields(claim.id, gross_amount=COST_OF_WORK)

    await _add_line_by_hand(session, svc, claim, contract.line.id, HAND_LINE_VALUE)

    await session.refresh(claim)
    assert claim.gross_amount == HAND_LINE_VALUE


# ── Claims raised from instalments ───────────────────────────────────────


async def _milestone(session, contract: Contract, **fields) -> ContractMilestone:
    values = {
        "id": uuid.uuid4(),
        "contract_id": contract.id,
        "code": "M1",
        "name": "Frame complete",
        "planned_date": "2026-05-01",
        "value": Decimal("20000"),
        "trigger": "completion",
        "status": "reached",
        "reached_at": "2026-05-04T09:00:00+00:00",
    }
    values.update(fields)
    milestone = ContractMilestone(**values)
    session.add(milestone)
    await session.flush()
    return milestone


async def test_a_reached_instalment_raises_a_draft_claim_for_its_amount(session) -> None:
    svc = ContractsService(session)
    contract = await _contract(session)
    milestone = await _milestone(session, contract)

    claim = await svc.raise_claim_for_milestone(milestone.id)

    assert claim.status == "draft"
    assert claim.milestone_id == milestone.id
    assert claim.gross_basis == "milestone"
    assert claim.gross_amount == Decimal("20000")
    assert claim.retention_amount == Decimal("2000.0000")
    assert claim.net_due == Decimal("18000.0000")
    assert claim.period_end == datetime.now(UTC).date().isoformat()
    await session.refresh(milestone)
    assert milestone.status == "reached"


async def test_a_percent_instalment_bills_its_share_of_the_contract(session) -> None:
    svc = ContractsService(session)
    contract = await _contract(session)
    milestone = await _milestone(session, contract, value=None, percent_of_contract=Decimal("15"))

    claim = await svc.raise_claim_for_milestone(milestone.id)

    assert claim.gross_amount == Decimal("15000.0000")


async def test_the_period_runs_on_from_the_previous_claim(session) -> None:
    svc = ContractsService(session)
    contract = await _contract(session)
    await _draft_claim(session, contract)  # March
    milestone = await _milestone(session, contract)

    claim = await svc.raise_claim_for_milestone(milestone.id)

    assert (claim.period_start, claim.period_end) == ("2026-04-01", datetime.now(UTC).date().isoformat())


@pytest.mark.parametrize("status", ["pending", "invoiced", "paid"])
async def test_only_a_reached_instalment_is_claimed(session, status) -> None:
    svc = ContractsService(session)
    contract = await _contract(session)
    milestone = await _milestone(session, contract, status=status)

    with pytest.raises(HTTPException) as exc:
        await svc.raise_claim_for_milestone(milestone.id)

    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == "milestone_not_reached"


async def test_an_instalment_is_claimed_once_until_its_claim_is_rejected(session) -> None:
    svc = ContractsService(session)
    contract = await _contract(session)
    milestone = await _milestone(session, contract)
    first = await svc.raise_claim_for_milestone(milestone.id)

    with pytest.raises(HTTPException) as exc:
        await svc.raise_claim_for_milestone(milestone.id)
    assert exc.value.status_code == 409
    assert exc.value.detail["claim_id"] == str(first.id)

    await svc.transition_claim(first.id, "rejected")
    second = await svc.raise_claim_for_milestone(milestone.id)
    assert second.id != first.id


async def test_an_instalment_without_money_is_refused(session) -> None:
    svc = ContractsService(session)
    contract = await _contract(session)
    milestone = await _milestone(session, contract, value=None, percent_of_contract=None)

    with pytest.raises(HTTPException) as exc:
        await svc.raise_claim_for_milestone(milestone.id)

    assert exc.value.status_code == 422


async def test_an_instalment_claim_keeps_its_amount_when_a_line_is_added(session) -> None:
    # Lump sum, so without the basis the engine would measure the claim on
    # the schedule of values and bill the one thousand of the typed line.
    svc = ContractsService(session)
    contract = await _contract(session)
    milestone = await _milestone(session, contract)
    claim = await svc.raise_claim_for_milestone(milestone.id)

    await _add_line_by_hand(session, svc, claim, contract.line.id, HAND_LINE_VALUE)

    await session.refresh(claim)
    assert claim.gross_amount == Decimal("20000")
    assert claim.retention_amount == Decimal("2000.0000")


async def test_an_instalment_claim_is_not_rebuilt_from_the_schedule(session) -> None:
    svc = ContractsService(session)
    contract = await _contract(session)
    milestone = await _milestone(session, contract)
    claim = await svc.raise_claim_for_milestone(milestone.id)

    with pytest.raises(HTTPException) as exc:
        await svc.auto_generate_claim_lines(claim.id, AutoGenerateClaimRequest(completion={}))

    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == "instalment_claim_not_rebuilt"


async def test_certifying_and_paying_the_claim_moves_the_instalment(session) -> None:
    svc = ContractsService(session)
    contract = await _contract(session)
    milestone = await _milestone(session, contract)
    claim = await svc.raise_claim_for_milestone(milestone.id)
    # Straight to approved: the submission rules are not what this is about.
    await svc.claim_repo.update_fields(claim.id, status="approved")

    await svc.transition_claim(claim.id, "certified")
    await session.refresh(milestone)
    assert milestone.status == "invoiced"

    await svc.transition_claim(claim.id, "paid")
    await session.refresh(milestone)
    assert milestone.status == "paid"


async def test_a_claim_naming_another_contracts_milestone_moves_nothing(session) -> None:
    svc = ContractsService(session)
    contract = await _contract(session)
    other = await _contract(session)
    milestone = await _milestone(session, other)
    claim = await _draft_claim(session, contract)
    await svc.claim_repo.update_fields(claim.id, milestone_id=milestone.id, status="approved")

    await svc.transition_claim(claim.id, "certified")

    await session.refresh(milestone)
    assert milestone.status == "reached"
