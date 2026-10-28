# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for approval acceleration (PostgreSQL, py3.12).

Covers one-tap reassignment and out-of-office delegation end to end against
real rows:

* a reassignment pins ``current_assignee_user_id`` so the stand-in becomes the
  sole eligible decider, notifies them, and the original approver is locked out;
* an active delegation lets the delegate decide on the approver's behalf;
* a revoked / expired delegation grants nothing;
* the per-step override clears when the instance advances to the next step;
* the step-cleared check reads the same entitlement the 403 gate enforces, in
  both directions: the stand-in's approval clears the step and an approval from
  someone that entitlement excludes does not;
* a stand-in's *rejection* ends the workflow instead of advancing it;
* a step that needs several distinct approvers is refused to a single
  stand-in, because pinning it would collapse the quorum the route author
  declared, while a step one approval clears stays reassignable.

The pure resolution rules are unit-tested separately in
``tests/unit/test_delegation_engine.py``; this file checks the service wiring.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.core.audit_log  # noqa: F401 - registers ActivityLog
from app.modules.approval_routes.models import Instance, StepState
from app.modules.approval_routes.schemas import (
    DecisionSubmit,
    InstanceCreate,
    RouteCreate,
    StepCreate,
)
from app.modules.approval_routes.service import ApprovalRouteService
from app.modules.notifications.models import Notification
from app.modules.projects.models import Project  # noqa: F401 - register ORM
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _user(session: AsyncSession, role: str = "editor") -> User:
    u = User(
        email=f"acc-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Acc",
        role=role,
    )
    session.add(u)
    await session.flush()
    return u


async def _project(session: AsyncSession, owner_id: uuid.UUID) -> uuid.UUID:
    proj = Project(name=f"Acc {uuid.uuid4().hex[:6]}", owner_id=owner_id)
    session.add(proj)
    await session.flush()
    return proj.id


async def _add_member(session: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Add ``user_id`` to ``project_id``'s default team.

    A reassignment target must belong to the route's project (the service now
    enforces the same owner / team-member / admin rule ``verify_project_access``
    applies to the caller), so a plain stand-in is enrolled as a project member
    before it can be pinned to a step.
    """
    from app.modules.projects.member_schemas import AddProjectMemberRequest
    from app.modules.projects.member_service import add_project_member

    await add_project_member(session, project_id, AddProjectMemberRequest(user_id=user_id))


async def _route_instance(
    session: AsyncSession,
    svc: ApprovalRouteService,
    project_id: uuid.UUID,
    owner_id: uuid.UUID,
    steps: list[StepCreate],
) -> Instance:
    route = await svc.create_route(
        RouteCreate(
            project_id=project_id,
            name="Acc route",
            target_kind="variation",
            steps=steps,
        ),
        created_by=owner_id,
    )
    return await svc.start_instance(
        InstanceCreate(route_id=route.id, target_kind="variation", target_id=uuid.uuid4()),
        started_by=owner_id,
    )


@pytest.mark.asyncio
async def test_reassign_pins_assignee_and_locks_out_original(session: AsyncSession) -> None:
    svc = ApprovalRouteService(session)
    owner = await _user(session, role="admin")
    project_id = await _project(session, owner.id)
    approver_a = await _user(session)
    stand_in_b = await _user(session)
    await _add_member(session, project_id, stand_in_b.id)

    inst = await _route_instance(
        session,
        svc,
        project_id,
        owner.id,
        [StepCreate(ordinal=1, approver_user_id=approver_a.id, mode="all")],
    )
    step = (await svc.list_steps((await svc.get_instance(inst.id)).route_id))[0]

    reassigned = await svc.reassign_current_step(
        inst.id, to_user_id=stand_in_b.id, actor_id=owner.id, reason="on leave", manage=True
    )
    assert reassigned.current_assignee_user_id == stand_in_b.id

    # The new assignee got an actionable notification.
    notifs = (
        (
            await session.execute(
                select(Notification).where(
                    Notification.user_id == stand_in_b.id,
                    Notification.notification_type == "approval_reassigned",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(notifs) == 1
    assert notifs[0].entity_id == str(inst.id)

    # The original approver is now locked out of the override step.
    with pytest.raises(HTTPException) as exc:
        await svc.submit_decision(
            inst.id,
            DecisionSubmit(step_id=step.id, decision="approved"),
            approver_id=approver_a.id,
        )
    assert exc.value.status_code == 403

    # The pinned stand-in clears it.
    done = await svc.submit_decision(
        inst.id,
        DecisionSubmit(step_id=step.id, decision="approved"),
        approver_id=stand_in_b.id,
    )
    assert done.status == "approved"


@pytest.mark.asyncio
async def test_active_delegation_lets_delegate_decide(session: AsyncSession) -> None:
    svc = ApprovalRouteService(session)
    owner = await _user(session, role="admin")
    project_id = await _project(session, owner.id)
    approver_a = await _user(session)
    delegate_b = await _user(session)
    stranger_c = await _user(session)

    # A hands their approvals to B (blanket, open-ended).
    await svc.create_delegation(
        delegator_id=approver_a.id,
        delegate_id=delegate_b.id,
        project_id=None,
        starts_at=None,
        ends_at=None,
        reason="out of office",
        created_by=approver_a.id,
    )

    inst = await _route_instance(
        session,
        svc,
        project_id,
        owner.id,
        [StepCreate(ordinal=1, approver_user_id=approver_a.id, mode="all")],
    )
    step = (await svc.list_steps((await svc.get_instance(inst.id)).route_id))[0]

    # A stranger still cannot decide.
    with pytest.raises(HTTPException) as exc:
        await svc.submit_decision(
            inst.id,
            DecisionSubmit(step_id=step.id, decision="approved"),
            approver_id=stranger_c.id,
        )
    assert exc.value.status_code == 403

    # The delegate may decide on A's behalf.
    done = await svc.submit_decision(
        inst.id,
        DecisionSubmit(step_id=step.id, decision="approved"),
        approver_id=delegate_b.id,
    )
    assert done.status == "approved"


@pytest.mark.asyncio
async def test_revoked_delegation_grants_nothing(session: AsyncSession) -> None:
    svc = ApprovalRouteService(session)
    owner = await _user(session, role="admin")
    project_id = await _project(session, owner.id)
    approver_a = await _user(session)
    delegate_b = await _user(session)

    d = await svc.create_delegation(
        delegator_id=approver_a.id,
        delegate_id=delegate_b.id,
        project_id=None,
        starts_at=None,
        ends_at=None,
        reason=None,
        created_by=approver_a.id,
    )
    await svc.revoke_delegation(d.id, actor_id=approver_a.id)

    inst = await _route_instance(
        session,
        svc,
        project_id,
        owner.id,
        [StepCreate(ordinal=1, approver_user_id=approver_a.id, mode="all")],
    )
    step = (await svc.list_steps((await svc.get_instance(inst.id)).route_id))[0]

    with pytest.raises(HTTPException) as exc:
        await svc.submit_decision(
            inst.id,
            DecisionSubmit(step_id=step.id, decision="approved"),
            approver_id=delegate_b.id,
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_expired_delegation_grants_nothing(session: AsyncSession) -> None:
    svc = ApprovalRouteService(session)
    owner = await _user(session, role="admin")
    project_id = await _project(session, owner.id)
    approver_a = await _user(session)
    delegate_b = await _user(session)

    # Window already closed.
    await svc.create_delegation(
        delegator_id=approver_a.id,
        delegate_id=delegate_b.id,
        project_id=None,
        starts_at=datetime.now(UTC) - timedelta(days=10),
        ends_at=datetime.now(UTC) - timedelta(days=1),
        reason=None,
        created_by=approver_a.id,
    )

    inst = await _route_instance(
        session,
        svc,
        project_id,
        owner.id,
        [StepCreate(ordinal=1, approver_user_id=approver_a.id, mode="all")],
    )
    step = (await svc.list_steps((await svc.get_instance(inst.id)).route_id))[0]

    with pytest.raises(HTTPException) as exc:
        await svc.submit_decision(
            inst.id,
            DecisionSubmit(step_id=step.id, decision="approved"),
            approver_id=delegate_b.id,
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_override_clears_when_instance_advances(session: AsyncSession) -> None:
    svc = ApprovalRouteService(session)
    owner = await _user(session, role="admin")
    project_id = await _project(session, owner.id)
    approver_a = await _user(session)
    stand_in_b = await _user(session)
    approver_c = await _user(session)
    await _add_member(session, project_id, stand_in_b.id)

    inst = await _route_instance(
        session,
        svc,
        project_id,
        owner.id,
        [
            StepCreate(ordinal=1, approver_user_id=approver_a.id, mode="all"),
            StepCreate(ordinal=2, approver_user_id=approver_c.id, mode="all"),
        ],
    )
    route_id = (await svc.get_instance(inst.id)).route_id
    steps = await svc.list_steps(route_id)

    # Reassign step 1 to B, B clears it -> instance advances to step 2.
    await svc.reassign_current_step(inst.id, to_user_id=stand_in_b.id, actor_id=owner.id, reason=None, manage=True)
    advanced = await svc.submit_decision(
        inst.id,
        DecisionSubmit(step_id=steps[0].id, decision="approved"),
        approver_id=stand_in_b.id,
    )
    assert advanced.status == "pending"
    assert advanced.current_step_ordinal == 2
    # The per-step override is gone; step 2 starts with its own approver.
    assert advanced.current_assignee_user_id is None

    # B (the step-1 stand-in) has no standing on step 2.
    with pytest.raises(HTTPException) as exc:
        await svc.submit_decision(
            inst.id,
            DecisionSubmit(step_id=steps[1].id, decision="approved"),
            approver_id=stand_in_b.id,
        )
    assert exc.value.status_code == 403

    # The real step-2 approver clears it.
    done = await svc.submit_decision(
        inst.id,
        DecisionSubmit(step_id=steps[1].id, decision="approved"),
        approver_id=approver_c.id,
    )
    assert done.status == "approved"


@pytest.mark.asyncio
async def test_reassignment_refuses_a_gate_that_needs_several_approvers(session: AsyncSession) -> None:
    """A multi-approver gate cannot be handed to one stand-in; a single-approver gate can.

    A reassignment pins exactly one person, so handing it a step that needs
    several distinct approvers would collapse the quorum the route author
    declared - a weaker gate than the template says. The refusal is read in
    both directions: it must fire for a gate that needs more than one approval
    and must not fire for a gate one approval clears, so a blanket refusal
    fails this test as surely as a missing one.
    """
    svc = ApprovalRouteService(session)
    owner = await _user(session, role="admin")
    project_id = await _project(session, owner.id)
    approver_a = await _user(session)
    stand_in_b = await _user(session)
    await _add_member(session, project_id, stand_in_b.id)

    # Refused: the author declared a population of three.
    quorum = await _route_instance(
        session,
        svc,
        project_id,
        owner.id,
        [StepCreate(ordinal=1, approver_role="manager", mode="all", required_approver_count=3)],
    )
    with pytest.raises(HTTPException) as exc:
        await svc.reassign_current_step(
            quorum.id, to_user_id=stand_in_b.id, actor_id=owner.id, reason=None, manage=True
        )
    assert exc.value.status_code == 422
    assert "3 approvals" in exc.value.detail
    # The refusal left the instance alone instead of half-applying.
    assert (await svc.get_instance(quorum.id)).current_assignee_user_id is None

    # Refused: no declared count, so the "all" fallback still wants two.
    implicit = await _route_instance(
        session,
        svc,
        project_id,
        owner.id,
        [StepCreate(ordinal=1, approver_role="manager", mode="all")],
    )
    with pytest.raises(HTTPException) as exc:
        await svc.reassign_current_step(
            implicit.id, to_user_id=stand_in_b.id, actor_id=owner.id, reason=None, manage=True
        )
    assert exc.value.status_code == 422
    assert "2 approvals" in exc.value.detail

    # Allowed: a role gate that one approval clears.
    any_gate = await _route_instance(
        session,
        svc,
        project_id,
        owner.id,
        [StepCreate(ordinal=1, approver_role="manager", mode="any")],
    )
    handed_any = await svc.reassign_current_step(
        any_gate.id, to_user_id=stand_in_b.id, actor_id=owner.id, reason=None, manage=True
    )
    assert handed_any.current_assignee_user_id == stand_in_b.id

    # Allowed: a step the template already pins to one named approver.
    named = await _route_instance(
        session,
        svc,
        project_id,
        owner.id,
        [StepCreate(ordinal=1, approver_user_id=approver_a.id, mode="all")],
    )
    handed_named = await svc.reassign_current_step(
        named.id, to_user_id=stand_in_b.id, actor_id=owner.id, reason=None, manage=True
    )
    assert handed_named.current_assignee_user_id == stand_in_b.id


@pytest.mark.asyncio
async def test_reassigned_role_gate_clears_for_its_stand_in_only(session: AsyncSession) -> None:
    """A reassignment decides the step, and only for the person it named.

    Three readings, so the test fails whichever way the advance check drifts:

    1. an untouched ``all`` role gate with no declared count still wants two
       distinct approvers, so one manager's approval leaves it pending;
    2. on a gate one approval can clear, handed to B, an approval from outside
       the hand-off does not clear it - honouring an override is not the same
       as honouring any approval that happens to be on file;
    3. the same state plus B's own approval does clear it, so what changed the
       verdict is who approved and not how many did.

    Readings 2 and 3 use an ``any`` gate because a gate needing several
    approvers can no longer be handed to a stand-in at all (see
    ``test_reassignment_refuses_a_gate_that_needs_several_approvers``). The
    approval from outside the hand-off is written directly: ``submit_decision``
    answers such a caller with 403, so no public path produces one, and that
    403 is the boundary this check has to agree with.
    """
    svc = ApprovalRouteService(session)
    owner = await _user(session, role="admin")
    project_id = await _project(session, owner.id)
    manager_x = await _user(session, role="manager")
    stand_in_b = await _user(session)
    await _add_member(session, project_id, stand_in_b.id)

    # (1) An untouched role gate still needs a second distinct approver.
    strict = await _route_instance(
        session,
        svc,
        project_id,
        owner.id,
        [StepCreate(ordinal=1, approver_role="manager", mode="all")],
    )
    strict_step = (await svc.list_steps((await svc.get_instance(strict.id)).route_id))[0]
    open_still = await svc.submit_decision(
        strict.id,
        DecisionSubmit(step_id=strict_step.id, decision="approved"),
        approver_id=manager_x.id,
        caller_role="manager",
    )
    assert open_still.status == "pending"
    assert open_still.current_step_ordinal == 1

    # (2) A gate one approval clears, handed to B: X's approval is now an
    # approval from someone the service would refuse, so it cannot clear it.
    inst = await _route_instance(
        session,
        svc,
        project_id,
        owner.id,
        [StepCreate(ordinal=1, approver_role="manager", mode="any")],
    )
    step = (await svc.list_steps((await svc.get_instance(inst.id)).route_id))[0]
    await svc.reassign_current_step(inst.id, to_user_id=stand_in_b.id, actor_id=owner.id, reason=None, manage=True)
    instance = await svc.get_instance(inst.id)
    now = datetime.now(UTC)
    entitled = await svc.entitled_deciders(instance, step, now=now)
    assert entitled == {stand_in_b.id}

    session.add(
        StepState(
            instance_id=inst.id,
            step_id=step.id,
            approver_user_id=manager_x.id,
            decision="approved",
            decided_at=now,
        )
    )
    await session.flush()
    assert await svc._maybe_advance(instance, step, entitled_deciders=entitled) is None
    assert (await svc.get_instance(inst.id)).status == "pending"

    # (3) The named stand-in clears that very same step.
    done = await svc.submit_decision(
        inst.id,
        DecisionSubmit(step_id=step.id, decision="approved"),
        approver_id=stand_in_b.id,
    )
    assert done.status == "approved"


@pytest.mark.asyncio
async def test_delegated_step_clears_only_for_an_entitled_decider(session: AsyncSession) -> None:
    """The advance check reads the delegation, not the mere count of approvals.

    A stranger's approval row is written directly: ``submit_decision`` answers
    such a caller with 403, so no public path can produce one, and that 403 is
    exactly the boundary the advance check must agree with. The row must not
    clear the step; the delegate's approval must.
    """
    svc = ApprovalRouteService(session)
    owner = await _user(session, role="admin")
    project_id = await _project(session, owner.id)
    approver_a = await _user(session)
    delegate_b = await _user(session)
    stranger_c = await _user(session)

    await svc.create_delegation(
        delegator_id=approver_a.id,
        delegate_id=delegate_b.id,
        project_id=None,
        starts_at=None,
        ends_at=None,
        reason="out of office",
        created_by=approver_a.id,
    )

    inst = await _route_instance(
        session,
        svc,
        project_id,
        owner.id,
        [StepCreate(ordinal=1, approver_user_id=approver_a.id, mode="all")],
    )
    instance = await svc.get_instance(inst.id)
    step = (await svc.list_steps(instance.route_id))[0]

    now = datetime.now(UTC)
    entitled = await svc.entitled_deciders(instance, step, now=now)
    assert entitled == {approver_a.id, delegate_b.id}
    assert stranger_c.id not in entitled

    session.add(
        StepState(
            instance_id=inst.id,
            step_id=step.id,
            approver_user_id=stranger_c.id,
            decision="approved",
            decided_at=now,
        )
    )
    await session.flush()
    assert await svc._maybe_advance(instance, step, entitled_deciders=entitled) is None

    done = await svc.submit_decision(
        inst.id,
        DecisionSubmit(step_id=step.id, decision="approved"),
        approver_id=delegate_b.id,
    )
    assert done.status == "approved"


@pytest.mark.asyncio
async def test_stand_in_rejection_ends_the_workflow(session: AsyncSession) -> None:
    """A stand-in's rejection is terminal on both hand-off paths.

    A rejection never reaches the advance check - it finalises the instance on
    the spot - so this pins that the reassignment and delegation paths reject
    as decisively as they approve, and that the workflow neither advances nor
    stays open afterwards.
    """
    svc = ApprovalRouteService(session)
    owner = await _user(session, role="admin")
    project_id = await _project(session, owner.id)

    # Reassignment path: the pinned stand-in rejects.
    approver_a = await _user(session)
    stand_in_b = await _user(session)
    approver_c = await _user(session)
    await _add_member(session, project_id, stand_in_b.id)
    reassigned = await _route_instance(
        session,
        svc,
        project_id,
        owner.id,
        [
            StepCreate(ordinal=1, approver_user_id=approver_a.id, mode="all"),
            StepCreate(ordinal=2, approver_user_id=approver_c.id, mode="all"),
        ],
    )
    steps = await svc.list_steps((await svc.get_instance(reassigned.id)).route_id)
    await svc.reassign_current_step(
        reassigned.id, to_user_id=stand_in_b.id, actor_id=owner.id, reason=None, manage=True
    )
    refused = await svc.submit_decision(
        reassigned.id,
        DecisionSubmit(step_id=steps[0].id, decision="rejected", comment="scope unclear"),
        approver_id=stand_in_b.id,
    )
    assert refused.status == "rejected"
    assert refused.current_step_ordinal == 1
    assert refused.completed_at is not None
    assert refused.current_assignee_user_id is None

    # The original approver cannot reopen what the stand-in closed.
    with pytest.raises(HTTPException) as exc:
        await svc.submit_decision(
            reassigned.id,
            DecisionSubmit(step_id=steps[0].id, decision="approved"),
            approver_id=approver_a.id,
        )
    assert exc.value.status_code == 409

    # Delegation path: the out-of-office delegate rejects.
    approver_d = await _user(session)
    delegate_e = await _user(session)
    await svc.create_delegation(
        delegator_id=approver_d.id,
        delegate_id=delegate_e.id,
        project_id=None,
        starts_at=None,
        ends_at=None,
        reason=None,
        created_by=approver_d.id,
    )
    delegated = await _route_instance(
        session,
        svc,
        project_id,
        owner.id,
        [
            StepCreate(ordinal=1, approver_user_id=approver_d.id, mode="all"),
            StepCreate(ordinal=2, approver_user_id=approver_c.id, mode="all"),
        ],
    )
    delegated_steps = await svc.list_steps((await svc.get_instance(delegated.id)).route_id)
    closed = await svc.submit_decision(
        delegated.id,
        DecisionSubmit(step_id=delegated_steps[0].id, decision="rejected"),
        approver_id=delegate_e.id,
    )
    assert closed.status == "rejected"
    assert closed.current_step_ordinal == 1


@pytest.mark.asyncio
async def test_cannot_delegate_to_self(session: AsyncSession) -> None:
    svc = ApprovalRouteService(session)
    a = await _user(session)
    with pytest.raises(HTTPException) as exc:
        await svc.create_delegation(
            delegator_id=a.id,
            delegate_id=a.id,
            project_id=None,
            starts_at=None,
            ends_at=None,
            reason=None,
            created_by=a.id,
        )
    assert exc.value.status_code == 422
