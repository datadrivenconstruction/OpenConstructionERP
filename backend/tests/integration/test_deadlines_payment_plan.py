# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Payment-plan reminders in the deadline register and sweep, on a real database.

Two sources read ``oe_contracts_milestone``: a reached instalment nobody has
claimed, and an owed instalment approaching or past its forecast due date.
Every negative assertion is paired with a sibling in the same project that
does surface, so a collector that returns nothing cannot pass.

The sweep sends a "due soon" reminder once per due date, to the project
managers, and heals forecasts older than their linked activity.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.modules.contracts.models import Contract, ContractMilestone, ProgressClaim
from app.modules.deadlines import service as deadlines_service
from app.modules.deadlines import sweeper
from app.modules.notifications.models import Notification
from app.modules.projects.models import Project
from app.modules.schedule.models import Activity, Schedule
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
TODAY = NOW.date()


def _day(offset: int) -> str:
    return (TODAY + timedelta(days=offset)).isoformat()


def _stamp(offset: int) -> str:
    return (NOW + timedelta(days=offset)).isoformat()


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        yield s


async def _owner(session) -> uuid.UUID:
    uid = uuid.uuid4()
    session.add(User(id=uid, email=f"plan-rem-{uid.hex[:8]}@test.io", hashed_password="x"))
    await session.flush()
    return uid


async def _contract(session, owner_id: uuid.UUID, *, status: str = "active", terms: dict | None = None) -> Contract:
    project = Project(id=uuid.uuid4(), name="Plan", owner_id=owner_id, currency="USD", country_code="US")
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
        terms=terms or {},
        status=status,
    )
    session.add(contract)
    await session.flush()
    return contract


async def _milestone(session, contract: Contract, **fields) -> ContractMilestone:
    m = ContractMilestone(
        id=uuid.uuid4(),
        contract_id=contract.id,
        code=f"M-{uuid.uuid4().hex[:4]}",
        name="Instalment",
        trigger="completion",
        **fields,
    )
    session.add(m)
    await session.flush()
    return m


async def _claim(session, contract: Contract, milestone: ContractMilestone, status: str) -> None:
    session.add(
        ProgressClaim(
            id=uuid.uuid4(),
            contract_id=contract.id,
            milestone_id=milestone.id,
            claim_number=f"PC-{uuid.uuid4().hex[:4]}",
            period_start="2026-09-01",
            period_end="2026-09-30",
            currency="USD",
            status=status,
        )
    )
    await session.flush()


async def _collect(session, module: str, project_id, approaching_days: int = 3):
    items = await deadlines_service._collect_all(
        session, [project_id], TODAY, approaching_days, module=module, for_sweep=True
    )
    return {it.entity_id: it for it in items}


# ── Claim not raised ────────────────────────────────────────────────────────


async def test_reached_instalment_without_a_live_claim_is_due_for_a_claim(session):
    owner = await _owner(session)
    contract = await _contract(session, owner)
    unclaimed = await _milestone(session, contract, status="reached", reached_at=_stamp(-10))
    rejected = await _milestone(session, contract, status="reached", reached_at=_stamp(-10))
    await _claim(session, contract, rejected, "rejected")
    claimed = await _milestone(session, contract, status="reached", reached_at=_stamp(-10))
    await _claim(session, contract, claimed, "draft")
    pending = await _milestone(session, contract, status="pending", reached_at=None, planned_date=_day(-30))

    rows = await _collect(session, "contracts_payment_plan_claim", contract.project_id)

    # Reached ten days ago, default window of seven: three days late.
    assert rows[str(unclaimed.id)].classification == "overdue"
    assert rows[str(unclaimed.id)].days_overdue == 3
    assert rows[str(unclaimed.id)].due_date == _day(-3)
    assert rows[str(unclaimed.id)].owner_user_id is None
    assert rows[str(unclaimed.id)].action_url == f"/contracts?highlight={contract.id}"
    # A rejected claim billed nothing, so the instalment is still unclaimed.
    assert str(rejected.id) in rows
    assert str(claimed.id) not in rows
    assert str(pending.id) not in rows


async def test_claim_window_and_lag_come_from_the_contract(session):
    owner = await _owner(session)
    roomy = await _contract(session, owner, terms={"payment_plan": {"claim_within_days": 30}})
    tight = await _contract(session, owner)
    in_window = await _milestone(session, roomy, status="reached", reached_at=_stamp(-10))
    lagged = await _milestone(session, tight, status="reached", reached_at=_stamp(-10), lag_days=5)
    plain = await _milestone(session, tight, status="reached", reached_at=_stamp(-10))

    assert str(in_window.id) not in await _collect(session, "contracts_payment_plan_claim", roomy.project_id)
    rows = await _collect(session, "contracts_payment_plan_claim", tight.project_id)
    # Claimable five days after reaching, due seven days after that.
    assert rows[str(lagged.id)].classification == "approaching"
    assert rows[str(lagged.id)].due_date == _day(2)
    assert rows[str(plain.id)].classification == "overdue"


async def test_claim_reminder_skips_a_contract_not_in_force(session):
    owner = await _owner(session)
    draft = await _contract(session, owner, status="draft")
    live = await _contract(session, owner)
    on_draft = await _milestone(session, draft, status="reached", reached_at=_stamp(-20))
    on_live = await _milestone(session, live, status="reached", reached_at=_stamp(-20))

    assert str(on_draft.id) not in await _collect(session, "contracts_payment_plan_claim", draft.project_id)
    assert str(on_live.id) in await _collect(session, "contracts_payment_plan_claim", live.project_id)


# ── Instalment due ──────────────────────────────────────────────────────────


async def test_owed_instalments_surface_by_forecast_due_date(session):
    owner = await _owner(session)
    contract = await _contract(session, owner)
    late = await _milestone(session, contract, status="reached", reached_at=_stamp(-40), forecast_due_date=_day(-2))
    soon = await _milestone(session, contract, status="invoiced", reached_at=_stamp(-25), forecast_due_date=_day(5))
    paid = await _milestone(session, contract, status="paid", reached_at=_stamp(-40), forecast_due_date=_day(-2))
    pending = await _milestone(session, contract, status="pending", forecast_due_date=_day(-2))
    far = await _milestone(session, contract, status="invoiced", reached_at=_stamp(-5), forecast_due_date=_day(25))

    rows = await _collect(session, "contracts_payment_plan", contract.project_id, approaching_days=7)

    assert rows[str(late.id)].classification == "overdue"
    assert rows[str(soon.id)].classification == "approaching"
    assert rows[str(soon.id)].days_overdue == -5
    # Paid is settled; pending is not owed, whatever its forecast says.
    assert str(paid.id) not in rows
    assert str(pending.id) not in rows
    assert str(far.id) not in rows


async def test_instalment_reminder_reads_completed_contracts_and_the_project_filter(session):
    owner = await _owner(session)
    completed = await _contract(session, owner, status="completed")
    draft = await _contract(session, owner, status="draft")
    on_completed = await _milestone(session, completed, status="invoiced", forecast_due_date=_day(-1))
    on_draft = await _milestone(session, draft, status="invoiced", forecast_due_date=_day(-1))

    rows = await _collect(session, "contracts_payment_plan", completed.project_id)
    assert str(on_completed.id) in rows
    assert str(on_draft.id) not in rows
    # The other project's row stays out of this project's register.
    assert str(on_draft.id) not in await _collect(session, "contracts_payment_plan", draft.project_id)
    assert str(on_completed.id) not in await _collect(session, "contracts_payment_plan", draft.project_id)


# ── Sweep: due-soon reminders ───────────────────────────────────────────────


async def _approaching_rows(session, milestone: ContractMilestone) -> list[Notification]:
    stmt = select(Notification).where(
        Notification.entity_id == str(milestone.id),
        Notification.notification_type == sweeper.APPROACHING_TYPE,
    )
    return list((await session.execute(stmt)).scalars().all())


async def test_sweep_reminds_the_managers_once_per_due_date(session):
    owner = await _owner(session)
    contract = await _contract(session, owner)
    soon = await _milestone(session, contract, status="invoiced", reached_at=_stamp(-25), forecast_due_date=_day(5))
    far = await _milestone(session, contract, status="invoiced", reached_at=_stamp(-5), forecast_due_date=_day(25))

    await sweeper.sweep_overdue(session, now=NOW)
    first = await _approaching_rows(session, soon)
    assert [n.user_id for n in first] == [owner]
    assert first[0].metadata_["module"] == "contracts_payment_plan"
    assert first[0].metadata_["due_date"] == _day(5)
    assert first[0].title_key == "notifications.deadline.approaching.title"
    assert await _approaching_rows(session, far) == []

    await sweeper.sweep_overdue(session, now=NOW)
    assert len(await _approaching_rows(session, soon)) == 1

    # The forecast moved: the new date earns its own reminder.
    soon.forecast_due_date = _day(6)
    await session.flush()
    await sweeper.sweep_overdue(session, now=NOW)
    assert sorted(n.metadata_["due_date"] for n in await _approaching_rows(session, soon)) == [_day(5), _day(6)]


async def test_sweep_stops_reminding_after_the_ceiling(session):
    owner = await _owner(session)
    contract = await _contract(session, owner)
    slipping = await _milestone(session, contract, status="invoiced", forecast_due_date=_day(1))

    for offset in range(1, sweeper.MAX_APPROACHING_REMINDERS + 3):
        slipping.forecast_due_date = _day(offset)
        await session.flush()
        await sweeper.sweep_overdue(session, now=NOW)

    assert len(await _approaching_rows(session, slipping)) == sweeper.MAX_APPROACHING_REMINDERS


async def test_overdue_claim_nudges_the_project_managers(session):
    owner = await _owner(session)
    contract = await _contract(session, owner)
    unclaimed = await _milestone(session, contract, status="reached", reached_at=_stamp(-10))

    await sweeper.sweep_overdue(session, now=NOW)

    rows = (
        (
            await session.execute(
                select(Notification).where(
                    Notification.entity_id == str(unclaimed.id),
                    Notification.notification_type == sweeper.OVERDUE_TYPE,
                )
            )
        )
        .scalars()
        .all()
    )
    assert [(n.user_id, n.metadata_["module"]) for n in rows] == [(owner, "contracts_payment_plan_claim")]


# ── Sweep: forecast self-heal ───────────────────────────────────────────────


async def test_heal_recomputes_only_forecasts_older_than_their_activity(session):
    owner = await _owner(session)
    contract = await _contract(session, owner)
    schedule = Schedule(id=uuid.uuid4(), project_id=contract.project_id, name="Master")
    session.add(schedule)
    await session.flush()
    activity = Activity(
        id=uuid.uuid4(),
        schedule_id=schedule.id,
        name="Roof complete",
        start_date="2026-11-20",
        end_date="2026-11-20",
        activity_type="milestone",
    )
    session.add(activity)
    await session.flush()

    never = await _milestone(
        session, contract, status="pending", activity_id=activity.id, schedule_id=schedule.id, forecast_at=None
    )
    fresh_stamp = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    fresh = await _milestone(
        session,
        contract,
        status="pending",
        activity_id=activity.id,
        schedule_id=schedule.id,
        forecast_at=fresh_stamp,
        forecast_reached_date="2000-01-01",
    )

    # Stamped before the activity was last edited: the announcement was lost.
    behind = await _milestone(
        session,
        contract,
        status="pending",
        activity_id=activity.id,
        schedule_id=schedule.id,
        forecast_at="2020-01-01T00:00:00+00:00",
        forecast_reached_date="2000-01-01",
    )

    healed = await deadlines_service.heal_stale_plan_forecasts(session)

    assert healed == 2
    await session.refresh(never)
    await session.refresh(fresh)
    await session.refresh(behind)
    assert never.forecast_reached_date == "2026-11-20"
    assert never.forecast_at is not None
    assert behind.forecast_reached_date == "2026-11-20"
    assert behind.forecast_at != "2020-01-01T00:00:00+00:00"
    # Stamped after the activity's last edit: left exactly as it was.
    assert fresh.forecast_reached_date == "2000-01-01"
    assert fresh.forecast_at == fresh_stamp
