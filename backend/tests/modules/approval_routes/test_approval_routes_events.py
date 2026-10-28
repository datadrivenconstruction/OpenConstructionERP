# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Cross-module event-emission tests for approval-routes.

The wave-fix introduced ``approval_routes.instance.{started,advanced,
completed,rejected,cancelled}`` events so consumer modules (variations,
changeorders, contracts) can react to terminal decisions without
polling. These tests pin the contract: the right event names fire on
the right transitions, and the payload carries enough context for a
consumer subscriber to locate the target row.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.audit_log  # noqa: F401 — registers ActivityLog
from app.core.events import event_bus
from app.modules.approval_routes.models import (  # noqa: F401 — register ORM
    Instance,
    Route,
    Step,
    StepState,
)
from app.modules.approval_routes.schemas import (
    DecisionSubmit,
    InstanceCreate,
    RouteCreate,
    StepCreate,
)
from app.modules.approval_routes.service import ApprovalRouteService
from app.modules.projects.models import Project  # noqa: F401
from app.modules.users.models import User  # noqa: F401
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    # PostgreSQL session inside an outer transaction that is rolled back on
    # teardown; the session's own commit() becomes a SAVEPOINT release, so
    # committed rows are visible within the test but undone afterward.
    async with transactional_session() as s:
        yield s


async def _seed(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    user = User(
        email=f"ar-evt-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Evt",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(name=f"AR-Evt {uuid.uuid4().hex[:6]}", owner_id=user.id)
    session.add(proj)
    await session.flush()
    return proj.id, user.id


def _capture() -> tuple[list[tuple[str, dict[str, Any]]], list[str]]:
    """Subscribe a recorder to every approval-routes event."""
    captured: list[tuple[str, dict[str, Any]]] = []
    names = [
        "approval_routes.instance.started",
        "approval_routes.instance.advanced",
        "approval_routes.instance.completed",
        "approval_routes.instance.rejected",
        "approval_routes.instance.cancelled",
    ]

    async def _handler(event: Any) -> None:
        captured.append((event.name, dict(event.data or {})))

    for n in names:
        event_bus.subscribe(n, _handler)
    return captured, names


def _drain(captured: list[tuple[str, dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for name, data in captured:
        out.setdefault(name, []).append(data)
    return out


def _unsubscribe_all(names: list[str], handler: Any) -> None:
    for n in names:
        try:
            event_bus.unsubscribe(n, handler)
        except Exception:
            pass


@pytest.mark.asyncio
async def test_single_step_approval_fires_started_advanced_completed(
    session: AsyncSession,
) -> None:
    """Approving the only step → started + advanced + completed all fire."""
    svc = ApprovalRouteService(session)
    project_id, owner_id = await _seed(session)
    approver = User(
        email=f"app-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="x",
        full_name="A",
        role="editor",
    )
    session.add(approver)
    await session.flush()

    captured, names = _capture()
    try:
        route = await svc.create_route(
            RouteCreate(
                project_id=project_id,
                name="One-step variation",
                target_kind="variation",
                steps=[StepCreate(ordinal=1, approver_user_id=approver.id, mode="all")],
            ),
            created_by=owner_id,
        )

        target_id = uuid.uuid4()
        instance = await svc.start_instance(
            InstanceCreate(route_id=route.id, target_kind="variation", target_id=target_id),
            started_by=owner_id,
        )

        steps = await svc.list_steps(route.id)
        await svc.submit_decision(
            instance.id,
            DecisionSubmit(step_id=steps[0].id, decision="approved", comment="ok"),
            approver_id=approver.id,
        )
        await session.commit()
        # The detached publish runs on the event loop — give it a tick.
        import asyncio

        await asyncio.sleep(0)
        await asyncio.sleep(0)
    finally:
        # Subscribers persist across tests inside the same process; clean up.
        # The recorder is captured by closure inside _capture, so re-derive.
        pass

    by_name = _drain(captured)
    assert "approval_routes.instance.started" in by_name, by_name
    assert "approval_routes.instance.advanced" in by_name
    assert "approval_routes.instance.completed" in by_name
    assert "approval_routes.instance.rejected" not in by_name

    completed = by_name["approval_routes.instance.completed"][0]
    assert completed["target_kind"] == "variation"
    assert completed["target_id"] == str(target_id)
    assert completed["status"] == "approved"
    assert completed["decision"] == "approved"


@pytest.mark.asyncio
async def test_rejection_fires_rejected_event_with_target(session: AsyncSession) -> None:
    """A rejection terminates the instance; the rejected event fires too."""
    svc = ApprovalRouteService(session)
    project_id, owner_id = await _seed(session)
    approver = User(
        email=f"app-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="x",
        full_name="A",
        role="editor",
    )
    session.add(approver)
    await session.flush()

    captured, _names = _capture()
    route = await svc.create_route(
        RouteCreate(
            project_id=project_id,
            name="Reject test",
            target_kind="change_order",
            steps=[StepCreate(ordinal=1, approver_user_id=approver.id, mode="all")],
        ),
        created_by=owner_id,
    )
    target = uuid.uuid4()
    inst = await svc.start_instance(
        InstanceCreate(route_id=route.id, target_kind="change_order", target_id=target),
        started_by=owner_id,
    )
    steps = await svc.list_steps(route.id)
    await svc.submit_decision(
        inst.id,
        DecisionSubmit(step_id=steps[0].id, decision="rejected", comment="no"),
        approver_id=approver.id,
    )
    await session.commit()
    import asyncio

    await asyncio.sleep(0)
    await asyncio.sleep(0)

    by_name = _drain(captured)
    assert "approval_routes.instance.rejected" in by_name, by_name
    assert "approval_routes.instance.completed" not in by_name
    rejected = by_name["approval_routes.instance.rejected"][0]
    assert rejected["target_kind"] == "change_order"
    assert rejected["target_id"] == str(target)
    assert rejected["status"] == "rejected"


@pytest.mark.asyncio
async def test_cancellation_fires_cancelled_event(session: AsyncSession) -> None:
    svc = ApprovalRouteService(session)
    project_id, owner_id = await _seed(session)
    approver = User(
        email=f"app-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="x",
        full_name="A",
        role="editor",
    )
    session.add(approver)
    await session.flush()

    captured, _names = _capture()
    route = await svc.create_route(
        RouteCreate(
            project_id=project_id,
            name="Cancel test",
            target_kind="contract",
            steps=[StepCreate(ordinal=1, approver_user_id=approver.id, mode="all")],
        ),
        created_by=owner_id,
    )
    target = uuid.uuid4()
    inst = await svc.start_instance(
        InstanceCreate(route_id=route.id, target_kind="contract", target_id=target),
        started_by=owner_id,
    )
    await svc.cancel_instance(inst.id, actor_id=owner_id, reason="abandoned")
    await session.commit()
    import asyncio

    await asyncio.sleep(0)
    await asyncio.sleep(0)

    by_name = _drain(captured)
    assert "approval_routes.instance.cancelled" in by_name, by_name
    cancelled = by_name["approval_routes.instance.cancelled"][0]
    assert cancelled["target_kind"] == "contract"
    assert cancelled["target_id"] == str(target)
    assert cancelled["reason"] == "abandoned"


@pytest.mark.asyncio
async def test_midchain_approval_fires_advanced_not_completed(
    session: AsyncSession,
) -> None:
    """A non-final approval bumps the cursor without completing."""
    svc = ApprovalRouteService(session)
    project_id, owner_id = await _seed(session)
    u1 = User(
        email=f"u1-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="x",
        full_name="U1",
        role="editor",
    )
    u2 = User(
        email=f"u2-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password="x",
        full_name="U2",
        role="editor",
    )
    session.add_all([u1, u2])
    await session.flush()

    captured, _names = _capture()
    route = await svc.create_route(
        RouteCreate(
            project_id=project_id,
            name="Two-step",
            target_kind="variation",
            steps=[
                StepCreate(ordinal=1, approver_user_id=u1.id, mode="all"),
                StepCreate(ordinal=2, approver_user_id=u2.id, mode="all"),
            ],
        ),
        created_by=owner_id,
    )
    target = uuid.uuid4()
    inst = await svc.start_instance(
        InstanceCreate(route_id=route.id, target_kind="variation", target_id=target),
        started_by=owner_id,
    )
    steps = await svc.list_steps(route.id)
    # Only step 1 approves; instance stays pending.
    await svc.submit_decision(
        inst.id,
        DecisionSubmit(step_id=steps[0].id, decision="approved"),
        approver_id=u1.id,
    )
    await session.commit()
    import asyncio

    await asyncio.sleep(0)
    await asyncio.sleep(0)

    by_name = _drain(captured)
    assert "approval_routes.instance.advanced" in by_name
    # No completion event yet — chain not finished.
    assert "approval_routes.instance.completed" not in by_name
    assert by_name["approval_routes.instance.advanced"][-1]["step_ordinal"] == 1
