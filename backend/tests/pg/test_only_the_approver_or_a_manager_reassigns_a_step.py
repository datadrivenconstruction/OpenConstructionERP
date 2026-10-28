"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Who may hand a pending step to a stand-in, and to whom.

Reassigning makes the stand-in the sole decider of the step. Left open to any
caller, the person who started an approval could hand the step to an ally, or
have it handed to themselves, and the route's choice of approver would mean
nothing. So only whoever may decide the step now, or a manager of routes, can
hand it off, and never to the person who started the approval.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.approval_routes.schemas import InstanceCreate, RouteCreate, StepCreate
from app.modules.approval_routes.service import ApprovalRouteService
from app.modules.projects.models import Project
from app.modules.teams.models import Team, TeamMembership
from app.modules.users.models import User
from tests._pg import transactional_session

NOT_ALLOWED = "Only the current approver of this step or a manager can reassign it"
TO_STARTER = "A step cannot be reassigned to the person who started the approval"


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Per-test PostgreSQL session inside an outer transaction."""
    async with transactional_session() as s:
        yield s


async def _user(session: AsyncSession, role: str = "editor") -> uuid.UUID:
    user = User(
        email=f"re-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="hashed",
        full_name="Reassign Tester",
        role=role,
    )
    session.add(user)
    await session.flush()
    return user.id


async def _world(session: AsyncSession, step: dict) -> dict:
    """A project with a team, a pending one-step instance started by ``starter``, and the people around it."""
    owner = await _user(session, "admin")
    people = {name: await _user(session) for name in ("starter", "approver", "colleague", "stand_in")}
    project = Project(name=f"Reassign {uuid.uuid4().hex[:6]}", owner_id=owner)
    session.add(project)
    await session.flush()
    team = Team(project_id=project.id, name="Team")
    session.add(team)
    await session.flush()
    for user_id in people.values():
        session.add(TeamMembership(team_id=team.id, user_id=user_id))
    await session.flush()
    svc = ApprovalRouteService(session)
    if step.get("approver_user_id") == "approver":
        step = {**step, "approver_user_id": people["approver"]}
    route = await svc.create_route(
        RouteCreate(
            project_id=project.id,
            name=f"route-{uuid.uuid4().hex[:6]}",
            target_kind="contract",
            steps=[StepCreate(**{"ordinal": 1, "mode": "all", **step})],
        ),
        created_by=owner,
    )
    instance = await svc.start_instance(
        InstanceCreate(route_id=route.id, target_kind="contract", target_id=uuid.uuid4()),
        started_by=people["starter"],
    )
    return {"svc": svc, "instance": instance, "owner": owner, **people}


@pytest.mark.asyncio
async def test_the_starter_and_a_bystander_cannot_hand_the_step_to_anybody(session: AsyncSession) -> None:
    w = await _world(session, {"approver_user_id": "approver"})
    for actor in (w["starter"], w["colleague"], None):
        with pytest.raises(HTTPException) as exc:
            await w["svc"].reassign_current_step(w["instance"].id, to_user_id=w["stand_in"], actor_id=actor)
        assert exc.value.status_code == 403
        assert exc.value.detail == NOT_ALLOWED
    await session.refresh(w["instance"])
    assert w["instance"].current_assignee_user_id is None


@pytest.mark.asyncio
async def test_the_named_approver_hands_the_step_off_and_then_no_longer_can(session: AsyncSession) -> None:
    w = await _world(session, {"approver_user_id": "approver"})
    handed = await w["svc"].reassign_current_step(w["instance"].id, to_user_id=w["stand_in"], actor_id=w["approver"])
    assert handed.current_assignee_user_id == w["stand_in"]
    # The step has moved: the stand-in is the decider now, so the route's own approver is a bystander.
    with pytest.raises(HTTPException) as exc:
        await w["svc"].reassign_current_step(w["instance"].id, to_user_id=w["colleague"], actor_id=w["approver"])
    assert exc.value.status_code == 403
    again = await w["svc"].reassign_current_step(w["instance"].id, to_user_id=w["colleague"], actor_id=w["stand_in"])
    assert again.current_assignee_user_id == w["colleague"]


@pytest.mark.asyncio
async def test_nobody_hands_the_step_to_the_person_who_started_the_approval(session: AsyncSession) -> None:
    w = await _world(session, {"approver_user_id": "approver"})
    for actor, manage in ((w["approver"], False), (w["owner"], True)):
        with pytest.raises(HTTPException) as exc:
            await w["svc"].reassign_current_step(
                w["instance"].id, to_user_id=w["starter"], actor_id=actor, manage=manage
            )
        assert exc.value.status_code == 422
        assert exc.value.detail == TO_STARTER
    await session.refresh(w["instance"])
    assert w["instance"].current_assignee_user_id is None


@pytest.mark.asyncio
async def test_a_manager_hands_off_a_step_that_is_not_theirs(session: AsyncSession) -> None:
    w = await _world(session, {"approver_user_id": "approver"})
    handed = await w["svc"].reassign_current_step(
        w["instance"].id, to_user_id=w["stand_in"], actor_id=w["colleague"], manage=True
    )
    assert handed.current_assignee_user_id == w["stand_in"]


@pytest.mark.asyncio
async def test_a_role_step_is_handed_off_only_by_somebody_whose_role_would_decide_it(session: AsyncSession) -> None:
    # One decider is enough, so a hand-off to one stand-in is possible; an "all" step over a role needs every holder.
    w = await _world(session, {"approver_role": "manager", "mode": "any"})
    for role in ("editor", "viewer", None):
        with pytest.raises(HTTPException) as exc:
            await w["svc"].reassign_current_step(
                w["instance"].id, to_user_id=w["stand_in"], actor_id=w["colleague"], caller_role=role
            )
        assert exc.value.status_code == 403
        assert exc.value.detail == NOT_ALLOWED
    handed = await w["svc"].reassign_current_step(
        w["instance"].id, to_user_id=w["stand_in"], actor_id=w["colleague"], caller_role="manager"
    )
    assert handed.current_assignee_user_id == w["stand_in"]
