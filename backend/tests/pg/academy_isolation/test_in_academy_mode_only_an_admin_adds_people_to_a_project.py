# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: in academy mode only an admin adds people to a project.

Every learner owns their course project, and the owner may add members. A
member row is what every other academy gate counts as "in the project", so a
learner who could add another learner to their project would open every gate
at once: the response handed back the target's name and email, 404 against 409
answered whether an account exists, and the target saw the project in their own
list from then on. Learners never share a project, so in academy mode adding a
member is an admin's job, on the projects door (single and bulk) and on the
teams door alike. The refusal comes before the target is looked up, so an id
that names nobody gets the same answer as a real learner.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.config import get_settings
from app.core.academy_isolation import ADMIN_ADDS_MEMBERS
from app.modules.projects.member_schemas import AddProjectMemberRequest, BulkAddProjectMembersRequest
from app.modules.projects.router import add_project_member_endpoint, bulk_add_project_members_endpoint
from app.modules.projects.service import ProjectService
from app.modules.teams.models import Team, TeamMembership
from app.modules.teams.schemas import AddMemberRequest
from app.modules.teams.service import TeamService
from tests.pg.academy_isolation.rows import make_project, make_user, payload_of

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]


async def _setup(session):
    alice = await make_user(session, name="Alice")
    bob = await make_user(session, name="Bob", email=f"bob-{uuid.uuid4().hex[:6]}@academy.example")
    admin = await make_user(session, role="admin", name="Admin")
    project = await make_project(session, alice)
    team = Team(project_id=project.id, name="Site team")
    session.add(team)
    await session.flush()
    return project, team, alice, bob, admin


async def _memberships(session, user) -> int:
    return (
        await session.execute(select(func.count(TeamMembership.id)).where(TeamMembership.user_id == user.id))
    ).scalar_one()


async def _add_single(session, project, actor, target_id):
    return await add_project_member_endpoint(
        project_id=project.id,
        data=AddProjectMemberRequest(user_id=target_id),
        user_id=str(actor.id),
        payload=payload_of(actor),
        session=session,
        service=ProjectService(session, get_settings()),
    )


def _refused(caught) -> None:
    assert caught.value.status_code == 403
    assert caught.value.detail["error"] == ADMIN_ADDS_MEMBERS
    assert "@" not in str(caught.value.detail)


async def test_academy_on_an_owner_cannot_add_another_learner(pg_session, academy, events) -> None:
    academy(True)
    project, team, alice, bob, _admin = await _setup(pg_session)

    with pytest.raises(HTTPException) as single:
        await _add_single(pg_session, project, alice, bob.id)
    _refused(single)

    with pytest.raises(HTTPException) as bulk:
        await bulk_add_project_members_endpoint(
            project_id=project.id,
            data=BulkAddProjectMembersRequest(members=[AddProjectMemberRequest(user_id=bob.id)]),
            user_id=str(alice.id),
            payload=payload_of(alice),
            session=pg_session,
            service=ProjectService(pg_session, get_settings()),
        )
    _refused(bulk)

    with pytest.raises(HTTPException) as on_team:
        await TeamService(pg_session).add_member(team.id, AddMemberRequest(user_id=bob.id), actor_id=str(alice.id))
    _refused(on_team)

    assert await _memberships(pg_session, bob) == 0
    assert [name for name, _ in events if name == "teams.membership.added"] == []


async def test_academy_on_an_unknown_id_gets_the_same_answer(pg_session, academy, events) -> None:
    academy(True)
    project, team, alice, _bob, _admin = await _setup(pg_session)

    with pytest.raises(HTTPException) as single:
        await _add_single(pg_session, project, alice, uuid.uuid4())
    _refused(single)
    with pytest.raises(HTTPException) as on_team:
        await TeamService(pg_session).add_member(
            team.id, AddMemberRequest(user_id=uuid.uuid4()), actor_id=str(alice.id)
        )
    _refused(on_team)


async def test_academy_on_an_admin_still_adds_members(pg_session, academy, events) -> None:
    academy(True)
    project, team, _alice, bob, admin = await _setup(pg_session)
    carol = await make_user(pg_session, name="Carol")

    added = await _add_single(pg_session, project, admin, bob.id)
    assert added.user_id == bob.id
    await TeamService(pg_session).add_member(team.id, AddMemberRequest(user_id=carol.id), actor_id=str(admin.id))
    # A system call (no actor) such as a seeder is not a learner and is not refused.
    dave = await make_user(pg_session, name="Dave")
    await TeamService(pg_session).add_member(team.id, AddMemberRequest(user_id=dave.id), actor_id=None)

    assert await _memberships(pg_session, bob) == 1
    assert await _memberships(pg_session, carol) == 1
    assert await _memberships(pg_session, dave) == 1


async def test_academy_off_unchanged(pg_session, academy, events) -> None:
    academy(False)
    project, team, alice, bob, _admin = await _setup(pg_session)
    carol = await make_user(pg_session, name="Carol")

    added = await _add_single(pg_session, project, alice, bob.id)
    assert added.email == bob.email
    assert added.full_name == "Bob"
    with pytest.raises(HTTPException) as unknown:
        await _add_single(pg_session, project, alice, uuid.uuid4())
    assert unknown.value.status_code == 404
    await TeamService(pg_session).add_member(team.id, AddMemberRequest(user_id=carol.id), actor_id=str(alice.id))

    assert await _memberships(pg_session, bob) == 1
    assert await _memberships(pg_session, carol) == 1
