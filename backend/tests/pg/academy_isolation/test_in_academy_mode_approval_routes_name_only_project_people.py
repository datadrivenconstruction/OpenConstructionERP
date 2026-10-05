# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: in academy mode approval routes and delegations name only project people.

A route step names its approver by user id, and an out-of-office delegation
names the delegate by user id. A route without a project was not checked
against anything and is listed to every project, a clone copied another
project's route without asking whether the caller may see it, and the SLA
monitor nudges the approver of a late step. On an academy box a learner could
therefore make another learner an approver of their work, read a route from
another learner's project by cloning it, hand their approvals to another
learner, and probe accounts through "Unknown delegate". In academy mode a
non-admin's route and delegation must name a project, every approver and
delegate must be in it, a clone's source must be visible to the caller, and
the SLA notifications carry the project for the backstop.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.core.academy_isolation import ROUTE_NEEDS_PROJECT, USER_NOT_IN_PROJECT
from app.modules.approval_routes import router as routes_router
from app.modules.approval_routes.models import Delegation, Route
from app.modules.approval_routes.schemas import (
    DelegationCreate,
    RouteCloneRequest,
    RouteCreate,
    RouteUpdate,
    StepCreate,
)
from app.modules.approval_routes.service import ApprovalRouteService
from tests.pg.academy_isolation.rows import add_member, make_project, make_user

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]


async def _setup(session):
    alice = await make_user(session, name="Alice")
    bob = await make_user(session, name="Bob")
    carol = await make_user(session, name="Carol")
    admin = await make_user(session, role="admin", name="Admin")
    project = await make_project(session, alice)
    bobs_project = await make_project(session, bob, name="Bob's course project")
    await add_member(session, project, carol)
    return project, bobs_project, alice, bob, carol, admin


def _route(project, *approvers) -> RouteCreate:
    return RouteCreate(
        project_id=project.id if project is not None else None,
        name=f"Route {uuid.uuid4().hex[:4]}",
        target_kind="submittal",
        steps=[StepCreate(ordinal=i + 1, approver_user_id=a.id) for i, a in enumerate(approvers)],
    )


async def _create(session, caller, payload):
    return await routes_router.create_route(
        payload=payload, session=session, user_id=str(caller.id), service=ApprovalRouteService(session)
    )


async def _delegate(session, caller, delegate, project):
    return await routes_router.create_delegation(
        payload=DelegationCreate(delegate_user_id=delegate.id, project_id=project.id if project else None),
        session=session,
        user_id=str(caller.id),
        service=ApprovalRouteService(session),
    )


def _refused(caught, error: str = USER_NOT_IN_PROJECT) -> None:
    assert caught.value.status_code == 422
    assert caught.value.detail["error"] == error


async def _routes(session) -> int:
    return (await session.execute(select(func.count(Route.id)))).scalar_one()


async def test_academy_on_an_approver_outside_the_project_is_422(pg_session, academy, events) -> None:
    academy(True)
    project, _bobs, alice, bob, carol, _admin = await _setup(pg_session)
    before = await _routes(pg_session)

    with pytest.raises(HTTPException) as on_create:
        await _create(pg_session, alice, _route(project, carol, bob))
    _refused(on_create)
    assert await _routes(pg_session) == before

    route = await _create(pg_session, alice, _route(project, carol))
    with pytest.raises(HTTPException) as on_update:
        await routes_router.update_route(
            route_id=route.id,
            payload=RouteUpdate(steps=[StepCreate(ordinal=1, approver_user_id=bob.id)]),
            session=pg_session,
            user_id=str(alice.id),
            service=ApprovalRouteService(pg_session),
        )
    _refused(on_update)


async def test_academy_on_a_learner_route_or_delegation_needs_a_project(pg_session, academy, events) -> None:
    academy(True)
    _project, _bobs, alice, _bob, carol, _admin = await _setup(pg_session)

    with pytest.raises(HTTPException) as on_route:
        await _create(pg_session, alice, _route(None, carol))
    _refused(on_route, ROUTE_NEEDS_PROJECT)
    with pytest.raises(HTTPException) as on_delegation:
        await _delegate(pg_session, alice, carol, None)
    _refused(on_delegation, ROUTE_NEEDS_PROJECT)


async def test_academy_on_a_delegate_outside_the_project_reads_like_a_missing_one(pg_session, academy, events) -> None:
    academy(True)
    project, _bobs, alice, bob, carol, _admin = await _setup(pg_session)

    for delegate in (bob, type("Nobody", (), {"id": uuid.uuid4()})()):
        with pytest.raises(HTTPException) as caught:
            await _delegate(pg_session, alice, delegate, project)
        _refused(caught)
    made = await _delegate(pg_session, alice, carol, project)
    assert made.delegate_user_id == carol.id
    count = await pg_session.execute(select(func.count(Delegation.id)).where(Delegation.delegator_user_id == alice.id))
    assert count.scalar_one() == 1


async def test_academy_on_another_learners_route_cannot_be_cloned(pg_session, academy, events) -> None:
    academy(True)
    project, bobs, alice, bob, _carol, _admin = await _setup(pg_session)
    bobs_route = await _create(pg_session, bob, _route(bobs, bob))

    with pytest.raises(HTTPException) as caught:
        await routes_router.clone_route(
            route_id=bobs_route.id,
            payload=RouteCloneRequest(project_id=project.id),
            session=pg_session,
            user_id=str(alice.id),
            service=ApprovalRouteService(pg_session),
        )
    assert caught.value.status_code == 404


async def test_academy_on_an_admin_keeps_tenant_wide_routes(pg_session, academy, events) -> None:
    academy(True)
    project, _bobs, alice, _bob, carol, admin = await _setup(pg_session)

    shared = await _create(pg_session, admin, _route(None, admin))
    assert shared.project_id is None
    own = await _create(pg_session, alice, _route(project, carol, alice))
    assert [s.approver_user_id for s in own.steps] == [carol.id, alice.id]


async def test_academy_off_unchanged(pg_session, academy, events) -> None:
    academy(False)
    project, bobs, alice, bob, carol, _admin = await _setup(pg_session)

    route = await _create(pg_session, alice, _route(project, bob))
    assert route.steps[0].approver_user_id == bob.id
    shared = await _create(pg_session, alice, _route(None, carol))
    assert shared.project_id is None
    made = await _delegate(pg_session, alice, bob, None)
    assert made.delegate_user_id == bob.id
    bobs_route = await _create(pg_session, bob, _route(bobs, bob))
    clone = await routes_router.clone_route(
        route_id=bobs_route.id,
        payload=RouteCloneRequest(project_id=project.id),
        session=pg_session,
        user_id=str(alice.id),
        service=ApprovalRouteService(pg_session),
    )
    assert clone.steps[0].approver_user_id == bob.id
