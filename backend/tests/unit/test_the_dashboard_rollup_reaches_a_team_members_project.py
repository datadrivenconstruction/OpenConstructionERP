# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The dashboard rollup answers for every project the caller can open.

``accessible_projects`` in the dashboard service is the rollup's whole scope:
every widget aggregates over the list it returns and nothing else. It used to
filter a non-admin caller to ``Project.owner_id == caller``, while the access
rule the rest of the product enforces - ``verify_project_access`` and its
set-level twin ``accessible_project_ids`` in ``app.dependencies`` - lets a
caller reach a project they own *or* are a team member of. A manager added to
a project through a team could therefore open the project, its BOQ and its
schedule, and land on a dashboard reporting a project count of zero and empty
widgets: the rollup was quietly describing a subset of the estate the rest of
the product showed.

The estate is built so the two routes into the accessible set are separable:

    owned        owner is the caller
    member       owned by a stranger, reachable only through a team membership
    unreachable  owned by a stranger, no route for the caller
    archived     owned by the caller, but archived

Without ``member`` a filter that only honoured ownership passes every test
here; without ``unreachable`` a filter that dropped the ownership clause
altogether would pass too. Both directions are asserted.

Runs on the shared PostgreSQL unit database from ``tests/_pg.py``, inside an
outer transaction rolled back on teardown, the same way the neighbouring
service-level scope tests do. Foreign keys stay on: the accessible set is
resolved from real ``Project``, ``User``, ``Team`` and ``TeamMembership`` rows,
and the admin branch reads ``User.role`` off the persisted row.

Run:  python -m pytest tests/unit/test_the_dashboard_rollup_reaches_a_team_members_project.py -q
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.dashboard.service import accessible_projects
from app.modules.projects.models import Project
from app.modules.teams.models import Team, TeamMembership
from app.modules.users.models import User
from tests._pg import transactional_session


@dataclass(frozen=True)
class Estate:
    """The seeded rows a scoping test needs."""

    caller: User
    admin: User
    owned: Project
    member: Project
    unreachable: Project
    archived: Project


async def _make_user(session: AsyncSession, *, role: str = "manager") -> User:
    user = User(
        email=f"rollup-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="x",
        full_name="Rollup Caller",
        role=role,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _make_project(
    session: AsyncSession,
    owner_id: uuid.UUID,
    *,
    name: str,
    status: str = "active",
) -> Project:
    project = Project(name=name, owner_id=owner_id, currency="EUR", status=status)
    session.add(project)
    await session.flush()
    return project


async def _make_member(session: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Give ``user_id`` membership of ``project_id`` through a team.

    The accessible-set query reaches membership via ``Team.project_id`` joined
    to ``TeamMembership.team_id``, so a membership row without a team pointing
    at the project resolves to nothing.
    """
    team = Team(project_id=project_id, name="Site", metadata_={})
    session.add(team)
    await session.flush()
    session.add(TeamMembership(team_id=team.id, user_id=user_id, role="member"))
    await session.flush()


@pytest.fixture(autouse=True)
def _no_partner_pack(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the partner-pack axis off so membership is the only variable.

    The rollup is additionally scoped to the active partner pack, and a pack
    pinned on the machine running this suite would hide every fixture project
    from owner, member and admin alike, which reads as the same empty set the
    membership defect produces. That axis has its own suite in
    ``test_partner_pack_project_scope.py``; here it is switched off the way
    that suite switches it off.
    """
    monkeypatch.setattr("app.core.partner_pack.scope.active_pack_slug", lambda: None)


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session() as s:
        yield s


@pytest_asyncio.fixture
async def estate(session: AsyncSession) -> Estate:
    caller = await _make_user(session)
    admin = await _make_user(session, role="admin")
    stranger = await _make_user(session)

    owned = await _make_project(session, caller.id, name="Riverside Depot")
    member = await _make_project(session, stranger.id, name="Harbour Interchange")
    unreachable = await _make_project(session, stranger.id, name="Northgate Terminal")
    archived = await _make_project(session, caller.id, name="Old Quay", status="archived")
    await _make_member(session, member.id, caller.id)

    return Estate(
        caller=caller,
        admin=admin,
        owned=owned,
        member=member,
        unreachable=unreachable,
        archived=archived,
    )


async def _names(
    session: AsyncSession,
    user: User,
    *,
    requested_ids: list[uuid.UUID] | None = None,
) -> set[str]:
    rows = await accessible_projects(session, str(user.id), requested_ids=requested_ids)
    return {p.name for p in rows}


@pytest.mark.asyncio
async def test_a_team_member_sees_the_project_in_the_rollup(session: AsyncSession, estate: Estate) -> None:
    """Both routes into the accessible set, in one read.

    Asserting on the owned project alone would pass on the old owner-only
    filter; asserting membership alone would pass on a filter that lost the
    ownership clause. Set equality pins both, and keeps ``unreachable`` out.
    """
    assert await _names(session, estate.caller) == {estate.owned.name, estate.member.name}


@pytest.mark.asyncio
async def test_a_requested_id_narrows_to_the_reachable_subset(session: AsyncSession, estate: Estate) -> None:
    """``requested_ids`` is an intersection with the accessible set, for members too."""
    requested = [estate.owned.id, estate.member.id, estate.unreachable.id]

    assert await _names(session, estate.caller, requested_ids=requested) == {estate.owned.name, estate.member.name}


@pytest.mark.asyncio
async def test_naming_an_unreachable_project_returns_nothing(session: AsyncSession, estate: Estate) -> None:
    """The IDOR posture: a foreign id is dropped silently, never answered."""
    assert await _names(session, estate.caller, requested_ids=[estate.unreachable.id]) == set()


@pytest.mark.asyncio
async def test_an_archived_project_stays_out_however_it_is_reached(session: AsyncSession, estate: Estate) -> None:
    """Archived is excluded on the owner route, and the admin route agrees."""
    assert estate.archived.name not in await _names(session, estate.caller)
    assert estate.archived.name not in await _names(session, estate.admin)


@pytest.mark.asyncio
async def test_an_admin_sees_every_live_project(session: AsyncSession, estate: Estate) -> None:
    names = await _names(session, estate.admin)

    assert {estate.owned.name, estate.member.name, estate.unreachable.name} <= names


@pytest.mark.asyncio
async def test_a_caller_with_no_project_at_all_gets_an_empty_list(session: AsyncSession, estate: Estate) -> None:
    """No ownership and no membership is an empty rollup, not every project."""
    nobody = await _make_user(session)

    assert await accessible_projects(session, str(nobody.id)) == []


@pytest.mark.asyncio
async def test_a_malformed_caller_id_gets_an_empty_list(session: AsyncSession, estate: Estate) -> None:
    assert await accessible_projects(session, "not-a-uuid") == []
