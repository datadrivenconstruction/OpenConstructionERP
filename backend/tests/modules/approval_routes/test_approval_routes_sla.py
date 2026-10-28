# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for the approval-SLA breach monitor (PostgreSQL, py3.12).

Exercises :func:`app.modules.approval_routes.sla_monitor.check_sla_breaches`
end to end against real rows: a pending instance whose current step is past its
``sla_hours`` gets a single overdue notification, dedup suppresses repeats
inside the window, and a healthy step or a step with no SLA is left alone.
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
from app.modules.approval_routes.models import Instance, Step
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
        email=f"sla-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="SLA",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(name=f"SLA {uuid.uuid4().hex[:6]}", owner_id=user.id)
    session.add(proj)
    await session.flush()
    return proj.id, user.id


async def _new_approver(session: AsyncSession) -> User:
    approver = User(
        email=f"appr-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="x",
        full_name="Ap",
        role="editor",
    )
    session.add(approver)
    await session.flush()
    return approver


async def _make_instance(
    session: AsyncSession,
    svc: ApprovalRouteService,
    project_id: uuid.UUID,
    owner_id: uuid.UUID,
    approver_id: uuid.UUID,
    *,
    sla_hours: int | None,
    age_hours: float,
) -> uuid.UUID:
    """Create a single-step route + instance, set the step SLA, backdate start."""
    route = await svc.create_route(
        RouteCreate(
            project_id=project_id,
            name="SLA route",
            target_kind="variation",
            steps=[StepCreate(ordinal=1, approver_user_id=approver_id, mode="all")],
        ),
        created_by=owner_id,
    )
    steps = await svc.list_steps(route.id)
    step = await session.get(Step, steps[0].id)
    step.sla_hours = sla_hours
    await session.flush()

    inst = await svc.start_instance(
        InstanceCreate(route_id=route.id, target_kind="variation", target_id=uuid.uuid4()),
        started_by=owner_id,
    )
    row = await session.get(Instance, inst.id)
    row.started_at = datetime.now(UTC) - timedelta(hours=age_hours)
    await session.flush()
    return row.id


@pytest.mark.asyncio
async def test_overdue_step_creates_single_notification(session: AsyncSession) -> None:
    svc = ApprovalRouteService(session)
    project_id, owner_id = await _seed(session)
    approver = await _new_approver(session)

    inst_id = await _make_instance(session, svc, project_id, owner_id, approver.id, sla_hours=1, age_hours=100)

    now = datetime.now(UTC)
    actioned = await sla_monitor.check_sla_breaches(session, now=now)
    assert actioned == 1

    notifs = (
        (
            await session.execute(
                select(Notification).where(
                    Notification.user_id == approver.id,
                    Notification.notification_type == "approval_overdue",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(notifs) == 1
    n = notifs[0]
    assert n.entity_type == "approval_instance"
    assert n.entity_id == str(inst_id)
    assert (n.metadata_ or {}).get("step_ordinal") == 1

    # Dedup: a second sweep inside the renotify window does not re-notify.
    actioned2 = await sla_monitor.check_sla_breaches(session, now=now + timedelta(minutes=30))
    assert actioned2 == 0
    all_overdue = (
        (await session.execute(select(Notification).where(Notification.notification_type == "approval_overdue")))
        .scalars()
        .all()
    )
    assert len(all_overdue) == 1


@pytest.mark.asyncio
async def test_healthy_step_is_not_flagged(session: AsyncSession) -> None:
    svc = ApprovalRouteService(session)
    project_id, owner_id = await _seed(session)
    approver = await _new_approver(session)

    # 48h SLA, only 1h old -> comfortably within budget.
    await _make_instance(session, svc, project_id, owner_id, approver.id, sla_hours=48, age_hours=1)

    actioned = await sla_monitor.check_sla_breaches(session, now=datetime.now(UTC))
    assert actioned == 0


@pytest.mark.asyncio
async def test_step_without_sla_is_ignored(session: AsyncSession) -> None:
    svc = ApprovalRouteService(session)
    project_id, owner_id = await _seed(session)
    approver = await _new_approver(session)

    # No sla_hours on the step at all, even though it is long overdue.
    await _make_instance(session, svc, project_id, owner_id, approver.id, sla_hours=None, age_hours=100)

    actioned = await sla_monitor.check_sla_breaches(session, now=datetime.now(UTC))
    assert actioned == 0
