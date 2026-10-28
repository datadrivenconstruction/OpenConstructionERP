# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Feature 06 — submittal ↔ approval-routes wiring tests.

Pins the connective tissue:

1. ``SubmittalService.start_approval`` creates an ``Instance`` with
   ``target_kind='submittal'`` and moves the submittal out of draft, recording
   the instance id in metadata for deep-linking.
2. The engine's terminal decision events carry ``target_kind`` / ``target_id``
   / ``decided_by`` so a consumer subscriber can drive the FSM.
3. ``SubmittalService.apply_approval_decision`` (the body the subscriber calls)
   drives the existing, idempotent FSM: approve → ``approved`` (idempotent on a
   duplicate event), reject → ``rejected`` with the comment persisted.
4. The engine rejects a second pending workflow on the same submittal (409).
5. A project with NO configured route keeps the direct ``/approve`` path — the
   subscriber never fires because no instance exists.

These exercise the real service + engine objects on the same session, which is
how the feature behaves in production: ``start_approval`` and the FSM share the
request session, and the subscriber simply re-invokes
``apply_approval_decision`` from its own session on a committed row.
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
    RouteCreate,
    StepCreate,
)
from app.modules.approval_routes.service import ApprovalRouteService
from app.modules.projects.models import Project  # noqa: F401
from app.modules.submittals.models import Submittal  # noqa: F401
from app.modules.submittals.schemas import SubmittalCreate
from app.modules.submittals.service import SubmittalService
from app.modules.users.models import User  # noqa: F401
from tests._pg import transactional_session


@pytest.fixture(autouse=True)
def _isolate_event_bus():
    """Strip cross-session subscribers for the duration of each test.

    The submittal FSM publishes ``submittal.submitted`` / ``.reviewed`` /
    ``.approved`` which, in the live app, fan out to the vector indexer and
    notifications — each opening its own ``async_session_factory`` session.
    conftest shims ``publish_detached`` to run synchronously, so those
    cross-session writes execute inline outside a greenlet and raise
    ``MissingGreenlet`` in the unit harness (they are detached + greenlet-safe
    in production). We snapshot the bus, clear the handler maps that matter to
    these tests, and restore on teardown so the suite stays hermetic. The
    feature's own wiring is exercised directly via the service methods the
    subscriber calls, so dropping the bus subscribers does not reduce
    coverage of the connective tissue under test.
    """
    saved_handlers = {k: list(v) for k, v in event_bus._handlers.items()}
    saved_wildcards = list(event_bus._wildcard_handlers)
    event_bus._handlers.clear()
    event_bus._wildcard_handlers.clear()
    try:
        yield
    finally:
        event_bus._handlers.clear()
        for k, v in saved_handlers.items():
            event_bus._handlers[k] = v
        event_bus._wildcard_handlers[:] = saved_wildcards


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _seed(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    user = User(
        email=f"sub-appr-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Approver",
        role="manager",
    )
    session.add(user)
    await session.flush()
    proj = Project(name=f"Sub-Appr {uuid.uuid4().hex[:6]}", owner_id=user.id)
    session.add(proj)
    await session.flush()
    return proj.id, user.id


async def _make_submittal(
    svc: SubmittalService,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
) -> uuid.UUID:
    """Create a draft submittal and hand back its id, never the ORM row.

    ``start_approval`` writes the submittal through a bulk UPDATE and then
    expires the instance, which is correct - nothing may serve the stale cached
    values afterwards - but it turns any long-held row into a trap: the next
    plain attribute access is an implicit lazy load, and in async SQLAlchemy
    that is ``MissingGreenlet``, not a refresh. It took all four of these tests
    down on the 2026-09-22 nightly, each on a bare ``submittal_id`` read after
    the call. An id cannot go stale; re-read the row with ``get_submittal``
    wherever its fields are actually needed.
    """
    row = await svc.create_submittal(
        SubmittalCreate(
            project_id=project_id,
            title="Shop drawing — rebar",
            submittal_type="shop_drawing",
            status="draft",
        ),
        user_id=str(user_id),
    )
    return row.id


async def _make_route(
    engine: ApprovalRouteService,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    n_steps: int = 1,
) -> Route:
    steps = [StepCreate(ordinal=i + 1, approver_user_id=user_id, mode="all") for i in range(n_steps)]
    return await engine.create_route(
        RouteCreate(
            project_id=project_id,
            name="Submittal review",
            target_kind="submittal",
            steps=steps,
        ),
        created_by=user_id,
    )


def _capture() -> list[tuple[str, dict[str, Any]]]:
    captured: list[tuple[str, dict[str, Any]]] = []

    async def _handler(event: Any) -> None:
        captured.append((event.name, dict(event.data or {})))

    for n in (
        "approval_routes.instance.completed",
        "approval_routes.instance.rejected",
    ):
        event_bus.subscribe(n, _handler)
    return captured


@pytest.mark.asyncio
async def test_start_approval_creates_instance_and_submits(session: AsyncSession) -> None:
    project_id, user_id = await _seed(session)
    svc = SubmittalService(session)
    engine = ApprovalRouteService(session)
    submittal_id = await _make_submittal(svc, project_id, user_id)
    route = await _make_route(engine, project_id, user_id)

    instance = await svc.start_approval(submittal_id, route.id, started_by=str(user_id))

    assert instance.target_kind == "submittal"
    assert instance.target_id == submittal_id
    assert instance.status == "pending"

    # Draft submittal was moved into the review flow + instance id recorded.
    fresh = await svc.get_submittal(submittal_id)
    assert fresh.status == "submitted"
    assert (fresh.metadata_ or {}).get("approval_instance_id") == str(instance.id)

    # get_latest_approval returns the same instance.
    latest = await svc.get_latest_approval(submittal_id)
    assert latest is not None
    assert latest.id == instance.id


@pytest.mark.asyncio
async def test_second_workflow_rejected_409(session: AsyncSession) -> None:
    from fastapi import HTTPException

    project_id, user_id = await _seed(session)
    svc = SubmittalService(session)
    engine = ApprovalRouteService(session)
    submittal_id = await _make_submittal(svc, project_id, user_id)
    route = await _make_route(engine, project_id, user_id)

    await svc.start_approval(submittal_id, route.id, started_by=str(user_id))
    with pytest.raises(HTTPException) as exc:
        await svc.start_approval(submittal_id, route.id, started_by=str(user_id))
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_approval_decision_drives_fsm_to_approved(session: AsyncSession) -> None:
    project_id, user_id = await _seed(session)
    svc = SubmittalService(session)
    engine = ApprovalRouteService(session)
    submittal_id = await _make_submittal(svc, project_id, user_id)
    route = await _make_route(engine, project_id, user_id, n_steps=1)
    captured = _capture()

    instance = await svc.start_approval(submittal_id, route.id, started_by=str(user_id))
    steps = await engine.list_steps(route.id)

    # Approve the only step → instance completes, event carries decided_by.
    updated = await engine.submit_decision(
        instance.id,
        DecisionSubmit(step_id=steps[0].id, decision="approved", comment="LGTM"),
        approver_id=user_id,
    )
    assert updated.status == "approved"
    completed = [d for n, d in captured if n == "approval_routes.instance.completed"]
    assert completed, "expected a completed event"
    assert completed[0]["target_kind"] == "submittal"
    assert completed[0]["target_id"] == str(submittal_id)
    assert completed[0]["decided_by"] == str(user_id)

    # The subscriber body drives the submittal FSM.
    result = await svc.apply_approval_decision(
        submittal_id,
        decision="approved",
        decided_by=str(user_id),
        comment="LGTM",
    )
    assert result is not None
    assert result.status == "approved"

    # Idempotent: a duplicate event does not error or double-approve.
    again = await svc.apply_approval_decision(
        submittal_id,
        decision="approved",
        decided_by=str(user_id),
        comment="LGTM",
    )
    assert again is None or again.status == "approved"


@pytest.mark.asyncio
async def test_approval_rejection_drives_fsm_to_rejected(session: AsyncSession) -> None:
    project_id, user_id = await _seed(session)
    svc = SubmittalService(session)
    engine = ApprovalRouteService(session)
    submittal_id = await _make_submittal(svc, project_id, user_id)
    route = await _make_route(engine, project_id, user_id, n_steps=2)
    captured = _capture()

    instance = await svc.start_approval(submittal_id, route.id, started_by=str(user_id))
    steps = await engine.list_steps(route.id)

    # Reject step 2-of-2 source (the first step rejection short-circuits).
    rejected_inst = await engine.submit_decision(
        instance.id,
        DecisionSubmit(step_id=steps[0].id, decision="rejected", comment="missing dims"),
        approver_id=user_id,
    )
    assert rejected_inst.status == "rejected"
    rejected = [d for n, d in captured if n == "approval_routes.instance.rejected"]
    assert rejected and rejected[0]["target_kind"] == "submittal"

    result = await svc.apply_approval_decision(
        submittal_id,
        decision="rejected",
        decided_by=str(user_id),
        comment="missing dims",
    )
    assert result is not None
    assert result.status == "rejected"
    assert (result.metadata_ or {}).get("review_notes") == "missing dims"


@pytest.mark.asyncio
async def test_no_route_keeps_direct_path(session: AsyncSession) -> None:
    """A project with no configured route keeps today's direct approve path."""
    project_id, user_id = await _seed(session)
    svc = SubmittalService(session)
    submittal_id = await _make_submittal(svc, project_id, user_id)

    # No instance exists → get_latest_approval is None and direct approve works.
    assert await svc.get_latest_approval(submittal_id) is None
    await svc.submit_submittal(submittal_id)
    approved = await svc.approve_submittal(submittal_id, approver_id=str(user_id))
    assert approved.status == "approved"
