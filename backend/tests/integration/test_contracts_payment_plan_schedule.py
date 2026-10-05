# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Payment-plan instalments that follow schedule activities, on a real database.

An instalment linked to an activity takes its forecast from the activity's
live finish (``Activity.end_date``), plus its lag and the client's payment
terms. The schedule reaching or reopening the activity moves the instalment,
and the plan view reads every forecast live.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.modules.contracts.models import Contract, ContractMilestone, ProgressClaim
from app.modules.contracts.router import contract_payment_plan, link_contract_milestone_activity
from app.modules.contracts.schemas import ContractMilestoneActivityLink
from app.modules.contracts.service import ContractsService
from app.modules.contracts.validators import register_contracts_validation_rules
from app.modules.projects.models import Project
from app.modules.schedule.models import Activity, Schedule
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

OWNER_ID = uuid.uuid4()


@pytest_asyncio.fixture
async def session():
    register_contracts_validation_rules()
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email=f"plan-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
        await s.flush()
        yield s


async def _project(session, **fields) -> Project:
    project = Project(id=uuid.uuid4(), name="Plan", owner_id=OWNER_ID, currency="USD", country_code="US", **fields)
    session.add(project)
    await session.flush()
    return project


async def _contract(session, project: Project, *, status: str = "active", payment_days: int | None = 30) -> Contract:
    terms: dict = {}
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
        retention_percent=Decimal("0"),
        terms=terms,
        status=status,
    )
    session.add(contract)
    await session.flush()
    return contract


async def _activity(
    session, project: Project, *, end: str = "2026-06-10", activity_type: str = "milestone"
) -> Activity:
    schedule = Schedule(id=uuid.uuid4(), project_id=project.id, name="Master")
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
    )
    session.add(activity)
    await session.flush()
    return activity


async def _milestone(session, contract: Contract, **fields) -> ContractMilestone:
    values = {
        "id": uuid.uuid4(),
        "contract_id": contract.id,
        "code": f"M{uuid.uuid4().hex[:4]}",
        "name": "Roof",
        "planned_date": "2026-06-01",
        "value": Decimal("30000"),
        "trigger": "completion",
        "status": "pending",
        "lag_days": 0,
    }
    values.update(fields)
    milestone = ContractMilestone(**values)
    session.add(milestone)
    await session.flush()
    return milestone


# ── Linking and forecasts ────────────────────────────────────────────────


async def test_linking_forecasts_from_the_activity_finish_lag_and_contract_terms(session) -> None:
    svc = ContractsService(session)
    project = await _project(session)
    contract = await _contract(session, project, payment_days=30)
    activity = await _activity(session, project, end="2026-06-10")
    milestone = await _milestone(session, contract, lag_days=5)

    linked, warnings = await svc.link_milestone_activity(milestone.id, activity.id)

    assert warnings == []
    assert linked.activity_id == activity.id
    assert linked.schedule_id == activity.schedule_id
    assert linked.forecast_reached_date == "2026-06-15"
    assert linked.forecast_due_date == "2026-07-15"
    assert linked.forecast_at


async def test_the_instalments_own_terms_win_over_the_contracts(session) -> None:
    svc = ContractsService(session)
    project = await _project(session)
    contract = await _contract(session, project, payment_days=30)
    activity = await _activity(session, project, end="2026-06-10")
    milestone = await _milestone(session, contract, payment_terms_days=14)

    linked, _ = await svc.link_milestone_activity(milestone.id, activity.id)

    assert linked.forecast_due_date == "2026-06-24"


async def test_an_activity_of_another_project_is_not_found(session) -> None:
    svc = ContractsService(session)
    project = await _project(session)
    elsewhere = await _project(session)
    contract = await _contract(session, project)
    foreign = await _activity(session, elsewhere)
    milestone = await _milestone(session, contract)

    with pytest.raises(HTTPException) as exc:
        await svc.link_milestone_activity(milestone.id, foreign.id)

    assert exc.value.status_code == 404
    await session.refresh(milestone)
    assert milestone.activity_id is None


async def test_a_date_trigger_links_but_keeps_its_contract_date(session) -> None:
    svc = ContractsService(session)
    project = await _project(session)
    contract = await _contract(session, project, payment_days=None)
    activity = await _activity(session, project, end="2026-09-01")
    milestone = await _milestone(session, contract, trigger="date")

    linked, warnings = await svc.link_milestone_activity(milestone.id, activity.id)

    assert warnings == ["date_trigger_ignores_schedule"]
    assert linked.forecast_reached_date == "2026-06-01"


async def test_unlinking_falls_back_to_the_contract_date(session) -> None:
    svc = ContractsService(session)
    project = await _project(session)
    contract = await _contract(session, project, payment_days=None)
    activity = await _activity(session, project, end="2026-08-20")
    milestone = await _milestone(session, contract)
    await svc.link_milestone_activity(milestone.id, activity.id)

    unlinked, _ = await svc.link_milestone_activity(milestone.id, None)

    assert unlinked.activity_id is None
    assert unlinked.schedule_id is None
    assert unlinked.forecast_reached_date == "2026-06-01"


async def test_a_moved_activity_moves_the_stored_forecast(session) -> None:
    svc = ContractsService(session)
    project = await _project(session)
    contract = await _contract(session, project, payment_days=None)
    activity = await _activity(session, project, end="2026-06-10")
    milestone = await _milestone(session, contract)
    await svc.link_milestone_activity(milestone.id, activity.id)

    activity.end_date = "2026-07-01"
    await session.flush()
    assert await svc.refresh_linked_forecasts(schedule_id=activity.schedule_id) == 1

    await session.refresh(milestone)
    assert milestone.forecast_reached_date == "2026-07-01"


async def test_a_deleted_activity_is_unlinked(session) -> None:
    svc = ContractsService(session)
    project = await _project(session)
    contract = await _contract(session, project, payment_days=None)
    activity = await _activity(session, project, end="2026-06-10")
    milestone = await _milestone(session, contract)
    await svc.link_milestone_activity(milestone.id, activity.id)

    await session.delete(activity)
    await session.flush()
    await svc.refresh_linked_forecasts(activity_id=activity.id)

    await session.refresh(milestone)
    assert milestone.activity_id is None
    assert milestone.forecast_reached_date == "2026-06-01"


# ── The schedule reaching and reopening a milestone ──────────────────────


async def test_reaching_the_activity_makes_the_instalment_claimable(session) -> None:
    svc = ContractsService(session)
    project = await _project(session)
    contract = await _contract(session, project, payment_days=10)
    activity = await _activity(session, project, end="2026-06-10")
    milestone = await _milestone(session, contract)
    await svc.link_milestone_activity(milestone.id, activity.id)

    moved = await svc.mark_milestones_reached(
        activity.id, project_id=project.id, reached_at="2026-06-08T16:00:00+00:00", actor_id=None
    )

    assert moved == 1
    await session.refresh(milestone)
    assert milestone.status == "reached"
    assert milestone.reached_by == "schedule"
    assert milestone.forecast_reached_date == "2026-06-08"
    assert milestone.forecast_due_date == "2026-06-18"


async def test_a_draft_contracts_instalment_does_not_move(session) -> None:
    svc = ContractsService(session)
    project = await _project(session)
    contract = await _contract(session, project, status="draft")
    activity = await _activity(session, project)
    milestone = await _milestone(session, contract)
    await svc.link_milestone_activity(milestone.id, activity.id)

    moved = await svc.mark_milestones_reached(activity.id, project_id=project.id, reached_at=None, actor_id="u1")

    assert moved == 0
    await session.refresh(milestone)
    assert milestone.status == "pending"


async def test_reopening_takes_back_an_unclaimed_instalment_only(session) -> None:
    svc = ContractsService(session)
    project = await _project(session)
    contract = await _contract(session, project)
    activity = await _activity(session, project)
    claimed = await _milestone(session, contract)
    unclaimed = await _milestone(session, contract)
    for m in (claimed, unclaimed):
        await svc.link_milestone_activity(m.id, activity.id)
    await svc.mark_milestones_reached(activity.id, project_id=project.id, reached_at=None, actor_id="u1")
    await svc.raise_claim_for_milestone(claimed.id)

    moved = await svc.reopen_milestones(activity.id, project_id=project.id)

    assert moved == 1
    await session.refresh(claimed)
    await session.refresh(unclaimed)
    assert claimed.status == "reached"
    assert unclaimed.status == "pending"
    assert unclaimed.reached_at is None


# ── The plan view ────────────────────────────────────────────────────────


async def test_the_plan_reads_forecasts_live_and_reports_its_findings(session) -> None:
    svc = ContractsService(session)
    project = await _project(session)
    contract = await _contract(session, project, payment_days=30)
    activity = await _activity(session, project, end="2026-06-10")
    linked = await _milestone(session, contract, code="M1")
    unlinked = await _milestone(session, contract, code="M2", planned_date="2026-08-01", value=Decimal("20000"))
    await svc.link_milestone_activity(linked.id, activity.id)
    # The schedule slips without telling anyone; the plan still sees it.
    activity.end_date = "2026-06-20"
    await session.flush()

    plan = await svc.payment_plan(contract.id, today=date(2026, 6, 1))

    assert plan["scheduled_total"] == Decimal("50000")
    assert plan["percent_scheduled"] == Decimal("50.00")
    assert plan["default_payment_terms_days"] == 30
    by_code = {line["code"]: line for line in plan["lines"]}
    assert by_code["M1"]["forecast_reached_date"] == "2026-06-20"
    assert by_code["M1"]["days_moved"] == 19
    assert by_code["M1"]["client_status"] == "upcoming"
    assert by_code["M1"]["activity_name"] == "Roof watertight"
    assert by_code["M2"]["days_moved"] == 0
    rules = {(f["rule_id"], f["element_ref"]) for f in plan["findings"]}
    assert ("payment_plan.percent_sum", str(contract.id)) in rules
    assert ("payment_plan.completion_trigger_linked", str(unlinked.id)) in rules
    assert ("payment_plan.completion_trigger_linked", str(linked.id)) not in rules


async def test_the_plan_names_the_claim_billing_each_instalment(session) -> None:
    svc = ContractsService(session)
    project = await _project(session)
    contract = await _contract(session, project, payment_days=0)
    milestone = await _milestone(session, contract, status="reached", reached_at="2026-05-01T00:00:00+00:00")
    claim = await svc.raise_claim_for_milestone(milestone.id)

    plan = await svc.payment_plan(contract.id, today=date(2026, 5, 10))

    line = plan["lines"][0]
    assert line["claim_id"] == claim.id
    assert line["claim_status"] == "draft"
    # Claimed but not invoiced: nobody has billed the client yet.
    assert line["client_status"] == "due"


async def test_the_routes_answer_in_their_declared_shapes(session) -> None:
    project = await _project(session, subdivision_code="US-CA")
    contract = await _contract(session, project)
    activity = await _activity(session, project)
    milestone = await _milestone(session, contract, kind="deposit", value=Decimal("5000"))

    linked = await link_contract_milestone_activity(
        milestone.id, ContractMilestoneActivityLink(activity_id=activity.id), session, str(OWNER_ID)
    )
    assert linked.activity_id == activity.id
    assert linked.warnings == []

    plan = await contract_payment_plan(contract.id, session, str(OWNER_ID))
    dumped = plan.model_dump(mode="json")
    # Money goes out as strings, like the rest of the module.
    assert isinstance(dumped["contract_total"], str)
    assert Decimal(dumped["contract_total"]) == Decimal("100000")
    assert Decimal(dumped["lines"][0]["amount"]) == Decimal("5000")
    deposit = next(f for f in dumped["findings"] if f["rule_id"] == "payment_plan.consumer_deposit_cap")
    # 10 percent or 1000 dollars, the lesser; California's statute, unverified.
    assert deposit["severity"] == "warning"
    assert deposit["details"]["reference"] == "Cal. Bus. & Prof. Code 7159.5(a)(3)"
    assert deposit["details"]["source_url"].startswith("https://leginfo.legislature.ca.gov/")


async def test_a_rejected_claim_does_not_count_as_billing_the_instalment(session) -> None:
    svc = ContractsService(session)
    project = await _project(session)
    contract = await _contract(session, project)
    milestone = await _milestone(session, contract, status="reached")
    session.add(
        ProgressClaim(
            id=uuid.uuid4(),
            contract_id=contract.id,
            claim_number="PC-R",
            currency="USD",
            status="rejected",
            milestone_id=milestone.id,
        )
    )
    await session.flush()

    plan = await svc.payment_plan(contract.id)

    assert plan["lines"][0]["claim_id"] is None
