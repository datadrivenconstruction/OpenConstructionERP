# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The retention schedule routes keep the accrual lock the policy editor keeps.

Once a claim on a contract has left draft (and was not rejected), how the
contract holds retention is part of what that claim certified, and
``set_retention_policy`` refuses to move the ladder with 409
``retention_accrual_locked``. The engine reads the ladder from the contract's
retention schedules, the newest one carrying tiers, and the plain schedule
routes wrote those rows with no such check: a POST put a new ladder in force,
a PATCH rewrote the one certified claims were retained under, and a DELETE
removed it so later claims fell back to the flat rate.

Now, while the lock holds, a schedule's accrual rule is not added, changed or
removed through these routes either. The release rule and the notes stay
editable, a schedule that carries no accrual rule can still be added or
removed, and before any claim has gone out, or when the only one was
rejected, all three routes work as before. The tests call the route
functions, so what is asserted is what a request reaches.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

from app.modules.contracts import router as contracts_router
from app.modules.contracts.models import Contract, ProgressClaim, RetentionSchedule
from app.modules.contracts.schemas import RetentionScheduleCreate, RetentionScheduleUpdate
from app.modules.contracts.service import ContractsService
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

OWNER_ID = uuid.uuid4()
CERTIFIED_LADDER = {
    "tiers": [
        {"from_percent_complete": "0", "rate": "10"},
        {"from_percent_complete": "50", "rate": "5"},
    ]
}
NEW_LADDER = {"tiers": [{"from_percent_complete": "0", "rate": "3"}]}
RELEASE_EVENTS = {"events": [{"event": "practical_completion", "percent_of_held": "50"}]}


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email=f"sched-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
        await s.flush()
        yield s


async def _contract(s, claim_status: str | None) -> tuple[Contract, RetentionSchedule]:
    """An active contract with a tiered schedule and, unless None, one claim in ``claim_status``."""
    project = Project(id=uuid.uuid4(), name="Retention", owner_id=OWNER_ID, currency="USD", country_code="US")
    s.add(project)
    await s.flush()
    contract = Contract(
        id=uuid.uuid4(),
        code=f"C-{uuid.uuid4().hex[:8]}",
        title="Main works",
        project_id=project.id,
        currency="USD",
        total_value=Decimal("100000"),
        retention_percent=Decimal("10"),
        status="active",
    )
    s.add(contract)
    await s.flush()
    schedule = RetentionSchedule(
        id=uuid.uuid4(), contract_id=contract.id, accrual_rule=dict(CERTIFIED_LADDER), release_rule={}
    )
    s.add(schedule)
    if claim_status is not None:
        s.add(
            ProgressClaim(
                id=uuid.uuid4(),
                contract_id=contract.id,
                claim_number="PC-1",
                currency="USD",
                status=claim_status,
                gross_amount=Decimal("20000"),
                retention_amount=Decimal("2000"),
                net_due=Decimal("18000"),
            )
        )
    await s.flush()
    return contract, schedule


async def _create(s, contract: Contract, **fields):
    return await contracts_router.create_retention_schedule(
        data=RetentionScheduleCreate.model_validate({"contract_id": str(contract.id), **fields}),
        session=s,
        user_id=str(OWNER_ID),
        _perm=None,
    )


async def _update(s, schedule: RetentionSchedule, **fields):
    return await contracts_router.update_retention_schedule(
        schedule_id=schedule.id,
        data=RetentionScheduleUpdate.model_validate(fields),
        session=s,
        user_id=str(OWNER_ID),
        _perm=None,
    )


async def _delete(s, schedule_id: uuid.UUID) -> None:
    await contracts_router.delete_retention_schedule(
        schedule_id=schedule_id, session=s, user_id=str(OWNER_ID), _perm=None
    )


async def _schedules(s, contract: Contract) -> list[RetentionSchedule]:
    return list(
        (await s.execute(select(RetentionSchedule).where(RetentionSchedule.contract_id == contract.id))).scalars()
    )


async def _ladder_in_force(s, contract: Contract) -> list[tuple[Decimal, Decimal]]:
    policy = await ContractsService(s).retention_policy(contract)
    return [(Decimal(str(t.from_percent_complete)), Decimal(str(t.rate))) for t in policy.tiers]


CERTIFIED_TIERS = [(Decimal("0"), Decimal("10")), (Decimal("50"), Decimal("5"))]
LOCKING = ["submitted", "approved", "certified", "paid"]


def _assert_locked(refused: pytest.ExceptionInfo[HTTPException]) -> None:
    assert refused.value.status_code == 409
    assert refused.value.detail["error"] == "retention_accrual_locked"
    assert refused.value.detail["claim_number"] == "PC-1"
    assert refused.value.detail["locked_fields"] == ["accrual_rule"]


# ── Refused while a claim has gone out ──────────────────────────────────


@pytest.mark.parametrize("claim_status", LOCKING)
async def test_a_new_ladder_is_not_put_in_force(session, claim_status: str) -> None:
    contract, _ = await _contract(session, claim_status)

    with pytest.raises(HTTPException) as refused:
        await _create(session, contract, accrual_rule=NEW_LADDER)

    _assert_locked(refused)
    assert len(await _schedules(session, contract)) == 1
    assert await _ladder_in_force(session, contract) == CERTIFIED_TIERS


@pytest.mark.parametrize("claim_status", LOCKING)
async def test_the_certified_ladder_is_not_rewritten(session, claim_status: str) -> None:
    contract, schedule = await _contract(session, claim_status)

    with pytest.raises(HTTPException) as refused:
        await _update(session, schedule, accrual_rule=NEW_LADDER)

    _assert_locked(refused)
    await session.refresh(schedule)
    assert schedule.accrual_rule == CERTIFIED_LADDER


@pytest.mark.parametrize("claim_status", LOCKING)
async def test_the_certified_ladder_is_not_deleted(session, claim_status: str) -> None:
    contract, schedule = await _contract(session, claim_status)

    with pytest.raises(HTTPException) as refused:
        await _delete(session, schedule.id)

    _assert_locked(refused)
    assert await _ladder_in_force(session, contract) == CERTIFIED_TIERS


# ── Still open while the lock holds ─────────────────────────────────────


async def test_the_release_rule_and_notes_stay_editable(session) -> None:
    contract, schedule = await _contract(session, "certified")

    # Sending the accrual rule it already has is not a change to it.
    response = await _update(
        session, schedule, accrual_rule=CERTIFIED_LADDER, release_rule=RELEASE_EVENTS, notes="Per clause 14.3"
    )

    assert response.release_rule == RELEASE_EVENTS
    assert response.notes == "Per clause 14.3"
    assert await _ladder_in_force(session, contract) == CERTIFIED_TIERS


async def test_a_schedule_without_an_accrual_rule_can_be_added_and_removed(session) -> None:
    contract, _ = await _contract(session, "certified")

    created = await _create(session, contract, release_rule=RELEASE_EVENTS)
    assert await _ladder_in_force(session, contract) == CERTIFIED_TIERS

    await _delete(session, created.id)
    assert len(await _schedules(session, contract)) == 1


# ── Open before any claim has gone out ──────────────────────────────────


@pytest.mark.parametrize("claim_status", [None, "draft", "rejected"])
async def test_nothing_is_locked_before_a_claim_goes_out(session, claim_status: str | None) -> None:
    contract, schedule = await _contract(session, claim_status)

    await _update(session, schedule, accrual_rule=NEW_LADDER)
    assert await _ladder_in_force(session, contract) == [(Decimal("0"), Decimal("3"))]

    created = await _create(session, contract, accrual_rule=CERTIFIED_LADDER)
    await _delete(session, created.id)
    await _delete(session, schedule.id)
    assert await _schedules(session, contract) == []
