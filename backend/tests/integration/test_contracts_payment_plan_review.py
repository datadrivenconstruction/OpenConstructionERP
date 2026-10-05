# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Payment-plan billing kept honest, on a real database.

A contract is billed one way: by its payment plan or by measured progress,
never both, or the same work is billed twice. The schedule moves only what
is due on completion, and an instalment linked to a milestone that is already
complete does not wait for an announcement that will never come again. What
the client is told is due follows the invoice once there is one, and nothing
is overdue before anyone has billed it.
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
from app.modules.contracts.router import create_claim_line
from app.modules.contracts.schemas import AutoGenerateClaimRequest, ProgressClaimLineCreate
from app.modules.contracts.service import ContractsService
from app.modules.contracts.validators import register_contracts_validation_rules
from app.modules.finance.models import Invoice
from app.modules.finance.service import FinanceService
from app.modules.projects.models import Project
from app.modules.schedule.models import Activity, Schedule
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

OWNER_ID = uuid.uuid4()


@pytest.fixture(autouse=True)
def _no_detached_events(monkeypatch):
    from app.core import events

    monkeypatch.setattr(events.event_bus, "publish_detached", lambda *a, **k: None)


@pytest_asyncio.fixture
async def session():
    register_contracts_validation_rules()
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email=f"plan-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
        await s.flush()
        yield s


def _today() -> date:
    return datetime.now(UTC).date()


async def _project(session) -> Project:
    project = Project(id=uuid.uuid4(), name="Plan", owner_id=OWNER_ID, currency="USD", country_code="US")
    session.add(project)
    await session.flush()
    return project


async def _contract(
    session, project: Project | None = None, *, status: str = "active", payment_days: int | None = None
) -> Contract:
    project = project or await _project(session)
    terms: dict = {"fee_percent": "0"}
    if payment_days is not None:
        terms["payment_terms"] = {"payment_period_days": payment_days}
    contract = Contract(
        id=uuid.uuid4(),
        code=f"C-{uuid.uuid4().hex[:8]}",
        title="Main works",
        project_id=project.id,
        contract_type="lump_sum",
        currency="USD",
        total_value=Decimal("100000"),
        retention_percent=Decimal("10"),
        terms=terms,
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


async def _activity(
    session,
    project_id: uuid.UUID,
    *,
    end: str = "2026-06-10",
    status: str = "not_started",
    activity_type: str = "milestone",
    metadata: dict | None = None,
) -> Activity:
    schedule = Schedule(id=uuid.uuid4(), project_id=project_id, name="Master")
    session.add(schedule)
    await session.flush()
    activity = Activity(
        id=uuid.uuid4(),
        schedule_id=schedule.id,
        name="Roof watertight",
        start_date=end,
        end_date=end,
        duration_days=0 if activity_type == "milestone" else 10,
        activity_type=activity_type,
        status=status,
        progress_pct="100" if status == "completed" else "0",
        metadata_=metadata or {},
    )
    session.add(activity)
    await session.flush()
    return activity


async def _milestone(session, contract: Contract, **fields) -> ContractMilestone:
    values = {
        "id": uuid.uuid4(),
        "contract_id": contract.id,
        "code": f"M{uuid.uuid4().hex[:4]}",
        "name": "Frame complete",
        "planned_date": "2026-05-01",
        "value": Decimal("20000"),
        "trigger": "completion",
        "status": "reached",
        "reached_at": "2026-05-04T09:00:00+00:00",
        "lag_days": 0,
    }
    values.update(fields)
    milestone = ContractMilestone(**values)
    session.add(milestone)
    await session.flush()
    return milestone


async def _draft_claim(session, contract: Contract, **fields) -> ProgressClaim:
    values = {
        "id": uuid.uuid4(),
        "contract_id": contract.id,
        "claim_number": f"PC-{uuid.uuid4().hex[:4]}",
        "period_start": "2026-03-01",
        "period_end": "2026-03-31",
        "period_from": date(2026, 3, 1),
        "period_to": date(2026, 3, 31),
        "currency": "USD",
        "status": "draft",
    }
    values.update(fields)
    claim = ProgressClaim(**values)
    session.add(claim)
    await session.flush()
    return claim


async def _invoice(session, contract: Contract, claim: ProgressClaim, *, due: str, status: str = "draft") -> Invoice:
    invoice = Invoice(
        id=uuid.uuid4(),
        project_id=contract.project_id,
        invoice_direction="receivable",
        invoice_number=f"INV-{uuid.uuid4().hex[:6]}",
        invoice_date="2026-05-10",
        due_date=due,
        currency_code="USD",
        status=status,
        source_claim_id=claim.id,
    )
    session.add(invoice)
    await session.flush()
    return invoice


# ── One billing mode per contract ────────────────────────────────────────


async def test_progress_is_not_generated_on_a_contract_its_plan_bills(session) -> None:
    svc = ContractsService(session)
    contract = await _contract(session)
    await svc.raise_claim_for_milestone((await _milestone(session, contract)).id)
    progress = await _draft_claim(session, contract)

    with pytest.raises(HTTPException) as exc:
        await svc.auto_generate_claim_lines(progress.id, AutoGenerateClaimRequest(completion={}))

    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == "contract_billed_by_payment_plan"


async def test_progress_is_not_populated_or_committed_on_a_contract_its_plan_bills(session) -> None:
    svc = ContractsService(session)
    contract = await _contract(session)
    await svc.raise_claim_for_milestone((await _milestone(session, contract)).id)
    progress = await _draft_claim(session, contract)

    for call in (
        lambda: svc.populate_claim_from_progress(progress.id),
        lambda: svc.commit_preview_to_claim(progress.id, []),
    ):
        with pytest.raises(HTTPException) as exc:
            await call()
        assert exc.value.status_code == 409
        assert exc.value.detail["error"] == "contract_billed_by_payment_plan"


async def test_a_line_typed_onto_a_progress_claim_is_refused_too(session) -> None:
    svc = ContractsService(session)
    contract = await _contract(session)
    await svc.raise_claim_for_milestone((await _milestone(session, contract)).id)
    progress = await _draft_claim(session, contract)

    with pytest.raises(HTTPException) as exc:
        await create_claim_line(
            ProgressClaimLineCreate(
                progress_claim_id=progress.id,
                contract_line_id=contract.line.id,
                period_completed_value=Decimal("1000"),
            ),
            session,
            str(OWNER_ID),
            None,
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == "contract_billed_by_payment_plan"


async def test_an_instalment_is_not_claimed_on_a_contract_progress_bills(session) -> None:
    svc = ContractsService(session)
    contract = await _contract(session)
    progress = await _draft_claim(session, contract)
    session.add(
        ProgressClaimLine(
            progress_claim_id=progress.id,
            contract_line_id=contract.line.id,
            period_completed_value=Decimal("1000"),
        )
    )
    await session.flush()
    milestone = await _milestone(session, contract)

    with pytest.raises(HTTPException) as exc:
        await svc.raise_claim_for_milestone(milestone.id)

    assert exc.value.status_code == 409
    assert exc.value.detail["error"] == "contract_billed_by_progress"


async def test_a_rejected_progress_claim_leaves_the_plan_free_to_bill(session) -> None:
    svc = ContractsService(session)
    contract = await _contract(session)
    await _draft_claim(session, contract, status="rejected", gross_basis="lines", gross_amount=Decimal("5000"))
    milestone = await _milestone(session, contract)

    claim = await svc.raise_claim_for_milestone(milestone.id)

    assert claim.milestone_id == milestone.id


# ── The schedule and what it may move ───────────────────────────────────


async def test_linking_a_milestone_already_complete_reaches_the_instalment(session) -> None:
    svc = ContractsService(session)
    contract = await _contract(session, payment_days=10)
    activity = await _activity(session, contract.project_id, end="2026-06-10", status="completed")
    milestone = await _milestone(session, contract, status="pending", reached_at=None)

    linked, _ = await svc.link_milestone_activity(milestone.id, activity.id)

    assert linked.status == "reached"
    assert linked.reached_by == "schedule"
    assert linked.reached_at[:10] == "2026-06-10"
    assert linked.forecast_due_date == "2026-06-20"


async def test_the_reached_day_is_the_one_the_schedule_announced(session) -> None:
    svc = ContractsService(session)
    contract = await _contract(session)
    activity = await _activity(
        session,
        contract.project_id,
        end="2026-06-10",
        status="completed",
        metadata={"milestone_reached_at": "2026-06-07T15:00:00+00:00"},
    )
    milestone = await _milestone(session, contract, status="pending", reached_at=None)

    linked, _ = await svc.link_milestone_activity(milestone.id, activity.id)

    assert linked.reached_at[:10] == "2026-06-07"


async def test_activating_the_contract_catches_up_on_a_completed_milestone(session) -> None:
    svc = ContractsService(session)
    contract = await _contract(session, status="draft")
    activity = await _activity(session, contract.project_id, end="2026-06-10")
    milestone = await _milestone(session, contract, status="pending", reached_at=None)
    await svc.link_milestone_activity(milestone.id, activity.id)
    # Completed and announced while the contract was a draft: that moved nothing.
    activity.status = "completed"
    activity.progress_pct = "100"
    await session.flush()
    assert await svc.mark_milestones_reached(activity.id, project_id=None, reached_at=None, actor_id=None) == 0

    await svc.transition_contract(contract.id, "active", actor_id=str(OWNER_ID))

    await session.refresh(milestone)
    assert milestone.status == "reached"
    assert milestone.reached_at[:10] == "2026-06-10"


async def test_the_plan_warns_of_a_completed_milestone_whose_instalment_waits(session) -> None:
    svc = ContractsService(session)
    contract = await _contract(session, status="draft")
    activity = await _activity(session, contract.project_id, status="completed")
    waiting = await _milestone(session, contract, status="pending", reached_at=None, name="Roof")
    await svc.link_milestone_activity(waiting.id, activity.id)

    plan = await svc.payment_plan(contract.id)

    finding = next(f for f in plan["findings"] if f["rule_id"] == "payment_plan.schedule_done_plan_pending")
    assert finding["element_ref"] == str(waiting.id)
    assert finding["severity"] == "warning"
    assert "Roof watertight" in finding["message"]
    assert "payment_plan." not in finding["message"]


@pytest.mark.parametrize("trigger", ["approval", "date"])
async def test_the_schedule_reaches_only_what_is_due_on_completion(session, trigger) -> None:
    svc = ContractsService(session)
    contract = await _contract(session)
    activity = await _activity(session, contract.project_id)
    milestone = await _milestone(session, contract, status="pending", reached_at=None, trigger=trigger)
    await svc.link_milestone_activity(milestone.id, activity.id)

    moved = await svc.mark_milestones_reached(activity.id, project_id=None, reached_at=None, actor_id=None)

    assert moved == 0
    await session.refresh(milestone)
    assert milestone.status == "pending"


@pytest.mark.parametrize("trigger", ["approval", "date"])
async def test_linking_a_completed_milestone_reaches_only_a_completion_instalment(session, trigger) -> None:
    svc = ContractsService(session)
    contract = await _contract(session)
    activity = await _activity(session, contract.project_id, status="completed")
    milestone = await _milestone(session, contract, status="pending", reached_at=None, trigger=trigger)

    linked, _ = await svc.link_milestone_activity(milestone.id, activity.id)

    assert linked.status == "pending"


async def test_reopening_leaves_an_instalment_a_person_marked_reached(session) -> None:
    svc = ContractsService(session)
    contract = await _contract(session)
    activity = await _activity(session, contract.project_id)
    by_hand = await _milestone(session, contract, reached_by=str(OWNER_ID))
    await svc.milestone_repo.update_fields(by_hand.id, activity_id=activity.id, schedule_id=activity.schedule_id)

    moved = await svc.reopen_milestones(activity.id, project_id=None)

    assert moved == 0
    await session.refresh(by_hand)
    assert by_hand.status == "reached"


async def test_reopening_leaves_an_approval_instalment_alone(session) -> None:
    svc = ContractsService(session)
    contract = await _contract(session)
    activity = await _activity(session, contract.project_id)
    approved = await _milestone(session, contract, trigger="approval", reached_by="schedule")
    await svc.milestone_repo.update_fields(approved.id, activity_id=activity.id, schedule_id=activity.schedule_id)

    assert await svc.reopen_milestones(activity.id, project_id=None) == 0
    await session.refresh(approved)
    assert approved.status == "reached"


async def test_a_task_is_refused_until_the_schedule_marks_it_a_milestone(session) -> None:
    svc = ContractsService(session)
    contract = await _contract(session)
    task = await _activity(session, contract.project_id, activity_type="task")
    milestone = await _milestone(session, contract, status="pending", reached_at=None)

    with pytest.raises(HTTPException) as exc:
        await svc.link_milestone_activity(milestone.id, task.id)

    assert exc.value.status_code == 422
    assert exc.value.detail["error"] == "activity_not_milestone"
    assert "milestone in the schedule first" in exc.value.detail["message"]
    await session.refresh(milestone)
    assert milestone.activity_id is None


# ── What the client is told is due ───────────────────────────────────────


async def test_nothing_is_overdue_before_it_is_billed(session) -> None:
    svc = ContractsService(session)
    contract = await _contract(session, payment_days=0)
    await _milestone(session, contract, reached_at="2026-05-01T00:00:00+00:00")

    plan = await svc.payment_plan(contract.id, today=date(2026, 9, 1), with_findings=False)

    assert plan["lines"][0]["client_status"] == "due"


async def test_a_raised_claim_without_an_invoice_is_not_overdue_either(session) -> None:
    svc = ContractsService(session)
    contract = await _contract(session, payment_days=0)
    milestone = await _milestone(session, contract, reached_at="2026-05-01T00:00:00+00:00")
    await svc.raise_claim_for_milestone(milestone.id)

    plan = await svc.payment_plan(contract.id, today=date(2026, 9, 1), with_findings=False)

    assert plan["lines"][0]["client_status"] == "due"


async def test_the_invoice_due_date_decides_when_it_falls_due(session) -> None:
    svc = ContractsService(session)
    contract = await _contract(session, payment_days=0)
    milestone = await _milestone(session, contract, reached_at="2026-05-01T00:00:00+00:00")
    claim = await svc.raise_claim_for_milestone(milestone.id)
    await _invoice(session, contract, claim, due="2026-06-30")

    before = await svc.payment_plan(contract.id, today=date(2026, 6, 20), with_findings=False)
    after = await svc.payment_plan(contract.id, today=date(2026, 7, 5), with_findings=False)

    assert before["lines"][0]["forecast_due_date"] == "2026-06-30"
    assert before["lines"][0]["client_status"] == "due"
    assert after["lines"][0]["client_status"] == "overdue"


async def test_a_cancelled_invoice_sets_no_due_date(session) -> None:
    svc = ContractsService(session)
    contract = await _contract(session, payment_days=0)
    milestone = await _milestone(session, contract, reached_at="2026-05-01T00:00:00+00:00")
    claim = await svc.raise_claim_for_milestone(milestone.id)
    await _invoice(session, contract, claim, due="2026-05-15", status="cancelled")

    plan = await svc.payment_plan(contract.id, today=date(2026, 9, 1), with_findings=False)

    assert plan["lines"][0]["forecast_due_date"] == "2026-05-01"
    assert plan["lines"][0]["client_status"] == "due"


# ── A claim on another contract's instalment ─────────────────────────────


async def test_another_contracts_claim_does_not_bill_the_instalment(session) -> None:
    svc = ContractsService(session)
    contract = await _contract(session)
    other = await _contract(session)
    milestone = await _milestone(session, contract)
    await _draft_claim(session, other, milestone_id=milestone.id)

    plan = await svc.payment_plan(contract.id, with_findings=False)
    assert plan["lines"][0]["claim_id"] is None

    claim = await svc.raise_claim_for_milestone(milestone.id)
    assert claim.contract_id == contract.id


async def test_the_invoice_ignores_terms_of_another_contracts_instalment(session) -> None:
    contract = await _contract(session, payment_days=30)
    other = await _contract(session)
    foreign = await _milestone(session, other, payment_terms_days=7)
    claim = await _draft_claim(
        session,
        contract,
        status="certified",
        claim_date="2026-06-01",
        gross_amount=Decimal("1000"),
        retention_amount=Decimal("0"),
        net_due=Decimal("1000"),
        milestone_id=foreign.id,
    )

    invoice = await FinanceService(session).create_receivable_from_claim(claim.id)

    assert invoice.due_date == "2026-07-01"


# ── The claim an instalment raises ───────────────────────────────────────


async def test_the_claim_period_ends_on_the_claim_date(session) -> None:
    svc = ContractsService(session)
    contract = await _contract(session)
    milestone = await _milestone(session, contract, reached_at="2026-05-04T09:00:00+00:00")

    claim = await svc.raise_claim_for_milestone(milestone.id)

    assert claim.period_end == claim.claim_date == _today().isoformat()


async def test_a_deposit_holds_no_retention(session) -> None:
    svc = ContractsService(session)
    contract = await _contract(session)
    deposit = await _milestone(session, contract, kind="deposit", value=Decimal("5000"))

    claim = await svc.raise_claim_for_milestone(deposit.id)

    assert claim.gross_amount == Decimal("5000")
    assert claim.retention_amount == Decimal("0")
    assert claim.net_due == Decimal("5000")


@pytest.mark.parametrize("kind", ["progress", "final"])
async def test_a_progress_or_final_instalment_holds_the_flat_rate(session, kind) -> None:
    svc = ContractsService(session)
    contract = await _contract(session)
    milestone = await _milestone(session, contract, kind=kind)

    claim = await svc.raise_claim_for_milestone(milestone.id)

    assert claim.retention_amount == Decimal("2000.0000")
    assert claim.net_due == Decimal("18000.0000")
