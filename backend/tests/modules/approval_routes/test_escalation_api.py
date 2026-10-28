# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for approval-SLA escalation depth (#17, PostgreSQL, py3.12).

Exercises the escalation service end to end against real rows: a breached step
past its grace window escalates up the route's approver chain to the next
authority, the verdict surfaces severity / level / next target, a step still
within the grace window or with no SLA does not escalate, an authority who can
already decide the step through an out-of-office delegation is stepped over
rather than escalated to, and the background monitor walks the ladder one
target per sweep without ever escalating to the same authority twice.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.audit_log  # noqa: F401 - registers ActivityLog
from app.modules.approval_routes import sla_monitor
from app.modules.approval_routes.escalation_service import evaluate_escalation
from app.modules.approval_routes.models import Instance, Route, Step
from app.modules.approval_routes.schemas import InstanceCreate, RouteCreate, StepCreate
from app.modules.approval_routes.service import ApprovalRouteService
from app.modules.notifications.models import Notification
from app.modules.projects.models import Project  # noqa: F401 - register ORM
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _seed(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    user = User(
        email=f"esc-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="ESC",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(name=f"ESC {uuid.uuid4().hex[:6]}", owner_id=user.id)
    session.add(proj)
    await session.flush()
    return proj.id, user.id


async def _approver(session: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"appr-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="x",
        full_name="Ap",
        role="editor",
    )
    session.add(user)
    await session.flush()
    return user.id


async def _make_ladder(
    session: AsyncSession,
    svc: ApprovalRouteService,
    project_id: uuid.UUID,
    owner_id: uuid.UUID,
    approver_ids: list[uuid.UUID],
    *,
    sla_hours: int | None,
    age_hours: float,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Create an N-step route (step 1 holds, the rest are the chain) + instance.

    Step 1 carries the SLA and is the current step; the later steps' approvers
    form the escalation ladder. The instance start is backdated by ``age_hours``.
    Returns ``(instance_id, route_id)``.
    """
    route = await svc.create_route(
        RouteCreate(
            project_id=project_id,
            name="Escalation route",
            target_kind="variation",
            steps=[StepCreate(ordinal=i + 1, approver_user_id=aid, mode="all") for i, aid in enumerate(approver_ids)],
        ),
        created_by=owner_id,
    )
    steps = await svc.list_steps(route.id)
    first = await session.get(Step, steps[0].id)
    first.sla_hours = sla_hours
    await session.flush()

    inst = await svc.start_instance(
        InstanceCreate(route_id=route.id, target_kind="variation", target_id=uuid.uuid4()),
        started_by=owner_id,
    )
    row = await session.get(Instance, inst.id)
    row.started_at = datetime.now(UTC) - timedelta(hours=age_hours)
    await session.flush()
    return row.id, route.id


async def _evaluate(session: AsyncSession, instance_id: uuid.UUID, route_id: uuid.UUID, *, now: datetime):
    instance = await session.get(Instance, instance_id)
    route = await session.get(Route, route_id)
    return await evaluate_escalation(session, instance, route, now=now)


@pytest.mark.asyncio
async def test_escalates_to_next_authority_past_grace(session: AsyncSession) -> None:
    """A long-overdue step escalates to the next approver, critical, level 1."""
    svc = ApprovalRouteService(session)
    project_id, owner_id = await _seed(session)
    holder = await _approver(session)
    second = await _approver(session)
    third = await _approver(session)

    inst_id, route_id = await _make_ladder(
        session, svc, project_id, owner_id, [holder, second, third], sla_hours=1, age_hours=100
    )

    view = await _evaluate(session, inst_id, route_id, now=datetime.now(UTC))
    assert view.has_sla is True
    assert view.should_escalate is True
    assert view.next_target == str(second)
    assert view.level == 1
    assert view.severity == "critical"
    assert view.chain_length == 2
    assert view.current_holder == str(holder)


@pytest.mark.asyncio
async def test_escalation_steps_over_an_entitled_delegate(session: AsyncSession) -> None:
    """An authority who can already decide the step is not an escalation target.

    The same ladder is read in both directions: with no delegation the stuck
    step escalates to the next authority, and once that authority holds an
    active delegation from the step's approver - which lets them decide the
    step today - the escalation goes past them to the one above. A chain that
    excluded nobody would fail the second half; one that excluded everybody
    would fail the first.
    """
    svc = ApprovalRouteService(session)
    project_id, owner_id = await _seed(session)
    holder = await _approver(session)
    second = await _approver(session)
    third = await _approver(session)

    # No delegation: the ladder escalates to the next authority up.
    plain_id, plain_route = await _make_ladder(
        session, svc, project_id, owner_id, [holder, second, third], sla_hours=1, age_hours=100
    )
    plain = await _evaluate(session, plain_id, plain_route, now=datetime.now(UTC))
    assert plain.should_escalate is True
    assert plain.next_target == str(second)
    assert plain.chain_length == 2
    assert plain.current_holder == str(holder)

    # The step's approver goes out of office and delegates to that same next
    # authority, who can now decide the step; escalating to them would hand
    # them what they already hold.
    await svc.create_delegation(
        delegator_id=holder,
        delegate_id=second,
        project_id=None,
        starts_at=None,
        ends_at=None,
        reason="out of office",
        created_by=holder,
    )
    delegated_id, delegated_route = await _make_ladder(
        session, svc, project_id, owner_id, [holder, second, third], sla_hours=1, age_hours=100
    )
    delegated = await _evaluate(session, delegated_id, delegated_route, now=datetime.now(UTC))
    assert delegated.should_escalate is True
    assert delegated.next_target == str(third)
    assert delegated.chain_length == 1
    # The delegate is who the step waits on now, and who a breach nudge reaches.
    assert delegated.current_holder == str(second)


@pytest.mark.asyncio
async def test_within_grace_does_not_escalate(session: AsyncSession) -> None:
    """Breached but inside the grace window: no escalation, severity 'late'."""
    svc = ApprovalRouteService(session)
    project_id, owner_id = await _seed(session)
    holder = await _approver(session)
    second = await _approver(session)

    # SLA 48h, age 50h: breached (overdue 2h) but grace is 2x SLA = 96h.
    inst_id, route_id = await _make_ladder(
        session, svc, project_id, owner_id, [holder, second], sla_hours=48, age_hours=50
    )

    view = await _evaluate(session, inst_id, route_id, now=datetime.now(UTC))
    assert view.has_sla is True
    assert view.should_escalate is False
    assert view.reason == "within_window"
    assert view.severity == "late"


@pytest.mark.asyncio
async def test_step_without_sla_is_idle(session: AsyncSession) -> None:
    """A current step with no SLA has no escalation clock."""
    svc = ApprovalRouteService(session)
    project_id, owner_id = await _seed(session)
    holder = await _approver(session)
    second = await _approver(session)

    inst_id, route_id = await _make_ladder(
        session, svc, project_id, owner_id, [holder, second], sla_hours=None, age_hours=100
    )

    view = await _evaluate(session, inst_id, route_id, now=datetime.now(UTC))
    assert view.has_sla is False
    assert view.should_escalate is False
    assert view.severity == "on_time"


@pytest.mark.asyncio
async def test_monitor_walks_the_ladder_once_per_target(session: AsyncSession) -> None:
    """The sweep escalates to the next un-notified authority, never repeating one."""
    svc = ApprovalRouteService(session)
    project_id, owner_id = await _seed(session)
    holder = await _approver(session)
    second = await _approver(session)
    third = await _approver(session)

    inst_id, _route_id = await _make_ladder(
        session, svc, project_id, owner_id, [holder, second, third], sla_hours=1, age_hours=100
    )

    base = datetime.now(UTC)
    # First sweep: escalate to the second approver (level 1).
    await sla_monitor.check_sla_breaches(session, now=base)
    # Second sweep: the second is already escalated, so move to the third.
    await sla_monitor.check_sla_breaches(session, now=base + timedelta(hours=1))
    # Third sweep: the chain is exhausted, so nothing new is escalated.
    await sla_monitor.check_sla_breaches(session, now=base + timedelta(hours=2))

    escalations = (
        (
            await session.execute(
                select(Notification).where(
                    Notification.entity_type == "approval_instance",
                    Notification.entity_id == str(inst_id),
                    Notification.notification_type == "approval_escalated",
                )
            )
        )
        .scalars()
        .all()
    )
    recipients = {n.user_id for n in escalations}
    assert recipients == {second, third}
    levels = sorted((n.metadata_ or {}).get("level") for n in escalations)
    assert levels == [1, 2]
