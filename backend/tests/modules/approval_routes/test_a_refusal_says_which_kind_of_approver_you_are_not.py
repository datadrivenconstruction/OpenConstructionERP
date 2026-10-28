# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The three ways this module refuses a decision each say something different.

``submit_decision`` answers 403 from two places and with three sentences,
because the first of them chooses between two of those sentences on whether
the instance currently names a stand-in:

    Not the assigned approver for this step
    Not the named approver for this step
    Caller role does not satisfy the approver role for this step

Only the status code was ever asserted, and a status code cannot tell those
apart. The distinction is the whole value of the message. "Named" means the
route itself picked somebody else, so the reader's answer is to ask the route
author. "Assigned" means the step was handed to a stand-in, so the reader's
answer is to ask the person holding it, and the person who used to be able to
decide is one of the people who will now read this. Swapping the two arms of
that conditional sends every reader to the wrong place, and the suite would
have stayed green, because both arms are 403.

The third sentence is not a variant of the other two. It comes from the
role-based branch, which is only reached when no user is entitled at all, and
it exists so somebody holding the decide permission cannot clear a gate the
route pinned to a higher role. A test that only exercised the pinned cases
would leave the branch that separates permission from role uncovered.

These are asserted as whole strings rather than by substring. "Not the" would
pass for either of the first two, which is exactly the confusion being
guarded against.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.approval_routes.schemas import (
    DecisionSubmit,
    InstanceCreate,
    RouteCreate,
    StepCreate,
)
from app.modules.approval_routes.service import ApprovalRouteService
from app.modules.projects.models import Project  # noqa: F401 — registers ORM
from app.modules.users.models import User  # noqa: F401 — registers ORM
from tests._pg import transactional_session

ASSIGNED = "Not the assigned approver for this step"
NAMED = "Not the named approver for this step"
WRONG_ROLE = "Caller role does not satisfy the approver role for this step"


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Per-test PostgreSQL session inside an outer transaction."""
    async with transactional_session() as s:
        yield s


async def _seed_project(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    user = User(
        email=f"ar-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="hashed",
        full_name="Approval Tester",
        role="admin",
    )
    session.add(user)
    await session.flush()
    project = Project(name=f"AR Project {uuid.uuid4().hex[:6]}", owner_id=user.id)
    session.add(project)
    await session.flush()
    return project.id, user.id


async def _add_user(session: AsyncSession, email_prefix: str = "u") -> uuid.UUID:
    user = User(
        email=f"{email_prefix}-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="hashed",
        full_name="Approver",
        role="editor",
    )
    session.add(user)
    await session.flush()
    return user.id


async def _one_step_route(
    svc: ApprovalRouteService,
    project_id: uuid.UUID,
    owner_id: uuid.UUID,
    step: StepCreate,
):
    """A started instance over a single-step route, and that step."""
    route = await svc.create_route(
        RouteCreate(
            project_id=project_id,
            name=f"route-{uuid.uuid4().hex[:6]}",
            target_kind="contract",
            steps=[step],
        ),
        created_by=owner_id,
    )
    steps = await svc.list_steps(route.id)
    instance = await svc.start_instance(
        InstanceCreate(route_id=route.id, target_kind="contract", target_id=uuid.uuid4()),
        started_by=owner_id,
    )
    return instance, steps[0]


@pytest.mark.asyncio
async def test_a_route_that_named_somebody_else_says_named(session: AsyncSession) -> None:
    """No stand-in in play, so the route itself is what excluded the reader."""
    svc = ApprovalRouteService(session)
    project_id, owner_id = await _seed_project(session)
    pinned = await _add_user(session, "pinned")
    outsider = await _add_user(session, "outsider")

    instance, step = await _one_step_route(
        svc, project_id, owner_id, StepCreate(ordinal=1, approver_user_id=pinned, mode="all")
    )

    with pytest.raises(HTTPException) as excinfo:
        await svc.submit_decision(
            instance.id,
            DecisionSubmit(step_id=step.id, decision="approved"),
            approver_id=outsider,
        )

    assert excinfo.value.status_code == 403
    assert excinfo.value.detail == NAMED


@pytest.mark.asyncio
async def test_a_step_handed_to_a_stand_in_says_assigned(session: AsyncSession) -> None:
    """The reassigned case, including for the approver the route did name.

    The person the route picked is refused here too, which is correct and is
    the reason the wording has to differ: they are not being told the route
    chose somebody else, they are being told the step has moved.
    """
    svc = ApprovalRouteService(session)
    project_id, owner_id = await _seed_project(session)
    pinned = await _add_user(session, "pinned")

    instance, step = await _one_step_route(
        svc, project_id, owner_id, StepCreate(ordinal=1, approver_user_id=pinned, mode="all")
    )
    # The stand-in is a second admin, because a hand-off is refused unless the
    # person receiving it can reach the route's project, and it never goes to
    # the person who started the approval (the owner here). The owner hands it
    # off as a manager: they are not the step's approver.
    stand_in = User(
        email=f"standin-{uuid.uuid4().hex[:8]}@example.com", hashed_password="hashed", full_name="S", role="admin"
    )
    session.add(stand_in)
    await session.flush()
    await svc.reassign_current_step(instance.id, to_user_id=stand_in.id, actor_id=owner_id, reason="away", manage=True)

    with pytest.raises(HTTPException) as excinfo:
        await svc.submit_decision(
            instance.id,
            DecisionSubmit(step_id=step.id, decision="approved"),
            approver_id=pinned,
        )

    assert excinfo.value.status_code == 403
    assert excinfo.value.detail == ASSIGNED, "a reassigned step refused its original approver as if it were unnamed"


@pytest.mark.asyncio
async def test_a_role_gate_refuses_the_role_and_not_the_person(session: AsyncSession) -> None:
    """The branch that separates holding the permission from holding the role."""
    svc = ApprovalRouteService(session)
    project_id, owner_id = await _seed_project(session)
    editor = await _add_user(session, "editor")

    instance, step = await _one_step_route(
        svc, project_id, owner_id, StepCreate(ordinal=1, approver_role="admin", mode="any")
    )

    with pytest.raises(HTTPException) as excinfo:
        await svc.submit_decision(
            instance.id,
            DecisionSubmit(step_id=step.id, decision="approved"),
            approver_id=editor,
            caller_role="editor",
        )

    assert excinfo.value.status_code == 403
    assert excinfo.value.detail == WRONG_ROLE


def test_the_three_sentences_are_three_sentences() -> None:
    """Guards the guard: three distinct messages, or the tests above prove less.

    If two of these were ever made identical, each test above would still pass
    while the reader lost the distinction the messages exist to draw.
    """
    assert len({ASSIGNED, NAMED, WRONG_ROLE}) == 3
