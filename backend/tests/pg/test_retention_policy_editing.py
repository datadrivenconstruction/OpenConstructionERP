# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠What a person may change about how a contract holds retention, and when.

The accrual ladder decides money that has already been taken off the
contractor. A certified claim carries its own frozen figures and survives a
later edit, but the next draft claim does not: its retention is built on what
the earlier claims accrued, worked out under the rule as it stood. Move the
ladder underneath that and the contract stops explaining the amount it is
holding, with nothing able to say which rule produced which part of it.

So the ladder is editable only while every claim is a draft or was rejected,
and the words around it, the statute it cites and the notes beside it, are
editable for the life of the contract because they decide nothing. The screen
is told which is which before the person types, through ``locked_fields``,
rather than finding out when they save.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.modules.contracts.models import Contract, ContractLine, ProgressClaim
from app.modules.contracts.schemas import AutoGenerateClaimRequest, RetentionPolicyUpdate
from app.modules.contracts.service import ContractsService
from app.modules.contracts.validators import register_contracts_validation_rules
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

OWNER_ID = uuid.uuid4()


@pytest_asyncio.fixture
async def session():
    # The contracts rule set is registered by the module's startup hook, which
    # no test process runs, and an unregistered set makes the submission gate
    # answer 503 rather than check anything. See the helper in
    # tests/pg/test_claim_certificate_arithmetic.py.
    register_contracts_validation_rules()
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email=f"policy-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
        await s.flush()
        yield s


@pytest_asyncio.fixture
async def contract(session) -> Contract:
    project = Project(id=uuid.uuid4(), name="Policy", owner_id=OWNER_ID, currency="USD", country_code="US")
    session.add(project)
    await session.flush()
    row = Contract(
        id=uuid.uuid4(),
        code=f"C-{uuid.uuid4().hex[:8]}",
        title="Main works",
        project_id=project.id,
        contract_type="lump_sum",
        currency="USD",
        total_value=Decimal("100000"),
        original_contract_value=Decimal("100000"),
        retention_percent=Decimal("10"),
        status="active",
    )
    session.add(row)
    await session.flush()
    line = ContractLine(
        id=uuid.uuid4(),
        contract_id=row.id,
        code="A",
        description="Line A",
        quantity=Decimal("1"),
        unit_rate=Decimal("100000"),
        total_value=Decimal("100000"),
        order_index=0,
    )
    session.add(line)
    await session.flush()
    row.line = line  # type: ignore[attr-defined]
    return row


async def _claim(session, contract: Contract, number: str, month: int) -> ProgressClaim:
    claim = ProgressClaim(
        id=uuid.uuid4(),
        contract_id=contract.id,
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


def _ladder(*steps: tuple[str, str]) -> list[dict[str, Decimal]]:
    return [{"from_percent_complete": Decimal(at), "rate": Decimal(rate)} for at, rate in steps]


async def test_a_contract_with_no_schedule_reports_its_own_flat_rate(session, contract) -> None:
    svc = ContractsService(session)
    view = await svc.retention_policy_view(contract)

    # Nothing has been written, so the contract's own percentage is standing
    # in for a policy, and the view says so rather than inventing a ladder.
    assert view["retention_schedule_id"] is None
    assert view["source"] == "contract.retention_percent"
    assert view["tiers"] == [{"from_percent_complete": Decimal("0"), "rate": Decimal("10")}]
    assert view["tier_mode"] == "prospective"
    assert view["accrual_locked"] is False
    assert view["locked_fields"] == []


async def test_the_ladder_can_be_written_while_every_claim_is_a_draft(session, contract) -> None:
    svc = ContractsService(session)
    await _claim(session, contract, "PC-1", 3)

    view = await svc.set_retention_policy(
        contract,
        RetentionPolicyUpdate(
            tiers=_ladder(("0", "10"), ("50", "5")),
            tier_mode="recompute",
            cap_percent_of_contract_sum=Decimal("5"),
            statute_reference="Tex. Prop. Code 53.101",
            effective_date=date(2026, 3, 1),
            notes="Half rate after half the job",
        ),
    )
    assert view["retention_schedule_id"] is not None
    assert view["tiers"] == [
        {"from_percent_complete": Decimal("0"), "rate": Decimal("10")},
        {"from_percent_complete": Decimal("50"), "rate": Decimal("5")},
    ]
    assert view["tier_mode"] == "recompute"
    assert view["cap_percent_of_contract_sum"] == Decimal("5")
    assert view["statute_reference"] == "Tex. Prop. Code 53.101"
    assert view["effective_date"] == "2026-03-01"
    assert view["accrual_locked"] is False

    # And it is the policy the engine applies, not just a row: a claim at 60%
    # complete retains at the second tier rather than the contract's 10.
    claim = await svc.auto_generate_claim_lines(
        (await _claim(session, contract, "PC-2", 4)).id,
        AutoGenerateClaimRequest(completion={str(contract.line.id): Decimal("60")}),
    )
    assert claim.retention_held_to_date == Decimal("3000.0000")


async def test_the_ladder_is_refused_once_a_claim_has_left_draft(session, contract) -> None:
    svc = ContractsService(session)
    await svc.set_retention_policy(contract, RetentionPolicyUpdate(tiers=_ladder(("0", "10"))))
    claim = await svc.auto_generate_claim_lines(
        (await _claim(session, contract, "PC-1", 3)).id,
        AutoGenerateClaimRequest(completion={str(contract.line.id): Decimal("40")}),
    )
    await svc.claim_repo.update_fields(claim.id, status="submitted")

    with pytest.raises(HTTPException) as refused:
        await svc.set_retention_policy(contract, RetentionPolicyUpdate(tiers=_ladder(("0", "5"))))
    assert refused.value.status_code == 409
    detail = refused.value.detail
    assert detail["error"] == "retention_accrual_locked"
    # The refusal names the claim that did the locking, because "locked" with
    # no claim named is a dead end for whoever is holding the contract.
    assert detail["claim_number"] == "PC-1"
    assert detail["claim_status"] == "submitted"
    assert detail["locked_fields"] == ["tiers"]

    # The ladder on disk did not move.
    assert (await svc.retention_policy_view(contract))["tiers"] == [
        {"from_percent_complete": Decimal("0"), "rate": Decimal("10")}
    ]

    # The words around it are not money and stay editable.
    view = await svc.set_retention_policy(
        contract,
        RetentionPolicyUpdate(statute_reference="Cal. Civ. Code 8812", notes="Agreed at the pre-con"),
    )
    assert view["statute_reference"] == "Cal. Civ. Code 8812"
    assert view["accrual_locked"] is True
    assert view["locked_by_claim"]["claim_number"] == "PC-1"
    assert view["locked_fields"] == [
        "tiers",
        "tier_mode",
        "stored_materials_rate",
        "cap_percent_of_contract_sum",
        "effective_date",
    ]


async def test_a_rejected_claim_locks_nothing(session, contract) -> None:
    # A rejected claim was taken back. It counts as nothing certified
    # everywhere else in this module and it can return to draft, so it must
    # not freeze the contract's rule on its way out.
    svc = ContractsService(session)
    claim = await svc.auto_generate_claim_lines(
        (await _claim(session, contract, "PC-1", 3)).id,
        AutoGenerateClaimRequest(completion={str(contract.line.id): Decimal("40")}),
    )
    for target in ("submitted", "rejected"):
        claim = await svc.transition_claim(claim.id, target, actor_id=str(OWNER_ID))

    view = await svc.set_retention_policy(contract, RetentionPolicyUpdate(tiers=_ladder(("0", "7.5"))))
    assert view["accrual_locked"] is False
    assert view["tiers"] == [{"from_percent_complete": Decimal("0"), "rate": Decimal("7.5")}]


async def test_a_ladder_nobody_could_apply_is_refused_where_it_is_written(session, contract) -> None:
    # The engine answers 422 on an unreadable policy on every claim it touches.
    # Catching it here means one refusal at the moment somebody typed it,
    # rather than a contract that cannot produce a payment application.
    svc = ContractsService(session)
    with pytest.raises(HTTPException) as refused:
        await svc.set_retention_policy(contract, RetentionPolicyUpdate(tiers=_ladder(("20", "5"))))
    assert refused.value.status_code == 422
    assert refused.value.detail["error"] == "retention_policy_unreadable"
    # Nothing was stored, so the contract still answers with its flat rate.
    assert (await svc.retention_policy_view(contract))["source"] == "contract.retention_percent"
