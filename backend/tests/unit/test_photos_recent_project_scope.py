# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Project scoping of the recent-photos feed (``PhotoService.recent_across_projects``).

The dashboard's site-photos card is project facing: clicking a photo selects
that project and opens its gallery. So when a project is selected the card
passes ``project_id`` and the feed has to answer for that project alone.

The filter is applied as an INTERSECTION with the set of projects the caller may
reach, never as a replacement for it. That distinction is the whole point of
these tests. A replacement would let any caller name any project id and receive
its site documentation, which is a read of data they cannot otherwise open; an
intersection can only ever return fewer rows than the unfiltered call, never
different ones.

The estate is built so the intersection has real work to do:

    owned        owner is the caller
    member       owned by a stranger, reachable only through a team membership
    unreachable  owned by a stranger, no membership for the caller

Without the middle one a broken implementation that replaced the accessible set
whenever the caller happened to own the named project would still pass.

Runs on the shared PostgreSQL unit database from ``tests/_pg.py``, inside an
outer transaction rolled back on teardown, which is what the neighbouring
service-level tests use. Foreign keys stay on: the accessible set is resolved
from real ``Project``, ``User``, ``Team`` and ``TeamMembership`` rows, and the
admin branch reads ``User.role`` off the persisted row.

Run:  python -m pytest tests/unit/test_photos_recent_project_scope.py -q
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.documents.models import ProjectPhoto
from app.modules.documents.service import PhotoService
from app.modules.projects.models import Project
from app.modules.teams.models import Team, TeamMembership
from app.modules.users.models import User
from tests._pg import transactional_session

#: Every photo gets its own caption. The feed de-duplicates by caption (demo
#: seeding shares one set of build-stage shots across projects), so photos that
#: happened to share a caption would be collapsed and a subset assertion would
#: then be measuring the de-duplicator rather than the scope filter.
_BASE_INSTANT = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)


@dataclass(frozen=True)
class Estate:
    """The seeded rows a scoping test needs.

    Attributes:
        caller: A non-admin user; owns ``owned`` and is a member of ``member``.
        admin: A user with role ``admin``, who reaches every project.
        owned: Project owned by ``caller``.
        member: Project owned by a stranger, reachable by ``caller`` via a team.
        unreachable: Project owned by a stranger with no route to ``caller``.
    """

    caller: User
    admin: User
    owned: Project
    member: Project
    unreachable: Project


async def _make_user(session: AsyncSession, *, role: str = "editor") -> User:
    """Persist a user with an explicit role.

    Args:
        session: Async session.
        role: Stored on the row. The service reads the role from the database,
            not from a token payload, so an admin case needs a real row.

    Returns:
        The persisted user.
    """
    user = User(
        email=f"photos-{uuid.uuid4().hex[:10]}@example.com",
        hashed_password="x",
        full_name="Photo Caller",
        role=role,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _make_project(session: AsyncSession, owner_id: uuid.UUID, *, name: str) -> Project:
    """Persist a project owned by ``owner_id``."""
    project = Project(name=name, owner_id=owner_id, currency="EUR")
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


async def _make_photo(session: AsyncSession, project_id: uuid.UUID, *, caption: str, offset: int) -> ProjectPhoto:
    """Persist one photo with a unique caption and a distinct capture instant."""
    photo = ProjectPhoto(
        project_id=project_id,
        filename=f"{caption.lower().replace(' ', '-')}.jpg",
        file_path=f"/photos/{uuid.uuid4().hex}.jpg",
        caption=caption,
        taken_at=_BASE_INSTANT - timedelta(hours=offset),
        category="site",
    )
    session.add(photo)
    await session.flush()
    return photo


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """A rolled-back session on the shared PostgreSQL unit database."""
    async with transactional_session() as s:
        yield s


@pytest_asyncio.fixture
async def estate(session: AsyncSession) -> Estate:
    """Three projects, six photos, one caller who may reach exactly two of them."""
    caller = await _make_user(session)
    admin = await _make_user(session, role="admin")
    stranger = await _make_user(session)

    owned = await _make_project(session, caller.id, name="Riverside Depot")
    member = await _make_project(session, stranger.id, name="Harbour Interchange")
    unreachable = await _make_project(session, stranger.id, name="Northgate Terminal")
    await _make_member(session, member.id, caller.id)

    offset = 0
    for project, prefix in ((owned, "Depot"), (member, "Interchange"), (unreachable, "Terminal")):
        for shot in ("formwork", "rebar"):
            await _make_photo(session, project.id, caption=f"{prefix} {shot}", offset=offset)
            offset += 1

    return Estate(caller=caller, admin=admin, owned=owned, member=member, unreachable=unreachable)


async def _project_names(
    session: AsyncSession,
    user: User,
    *,
    project_id: uuid.UUID | None = None,
) -> set[str]:
    """Return the set of project names the feed answers with for ``user``."""
    rows = await PhotoService(session).recent_across_projects(str(user.id), project_id=project_id)
    return {name for _, name in rows}


async def _photo_ids(
    session: AsyncSession,
    user: User,
    *,
    project_id: uuid.UUID | None = None,
) -> set[str]:
    """Return the set of photo ids the feed answers with, compared as text.

    The ``GUID`` column is ``VARCHAR(36)`` while the migrations declare a native
    uuid, so which Python type a query hands back is not something a test should
    have an opinion about. Both sides of every comparison here are strings.
    """
    rows = await PhotoService(session).recent_across_projects(str(user.id), project_id=project_id)
    return {str(photo.id) for photo, _ in rows}


@pytest.mark.asyncio
async def test_without_project_id_the_feed_spans_every_accessible_project(
    session: AsyncSession,
    estate: Estate,
) -> None:
    """No ``project_id`` keeps the pre-existing behaviour: everything reachable.

    Both reachable projects have to appear. Asserting on the owned one alone
    would pass even if membership never resolved, and the intersection tests
    below would then be narrowing a set that was only ever one project wide.
    """
    names = await _project_names(session, estate.caller)

    assert names == {estate.owned.name, estate.member.name}


@pytest.mark.asyncio
async def test_project_id_for_a_reachable_project_narrows_to_that_project(
    session: AsyncSession,
    estate: Estate,
) -> None:
    """A reachable id narrows the feed to that one project, however it is reached.

    Run for both routes into the accessible set - ownership and team membership -
    because a filter that only worked for projects the caller owns would drop the
    membership half silently.
    """
    for project in (estate.owned, estate.member):
        names = await _project_names(session, estate.caller, project_id=project.id)

        assert names == {project.name}


@pytest.mark.asyncio
async def test_project_id_for_an_unreachable_project_returns_nothing(
    session: AsyncSession,
    estate: Estate,
) -> None:
    """Naming a project the caller cannot open returns no rows, not its photos.

    This is the case the intersection exists for. A caller who is neither owner
    nor member must not be able to widen their own scope by naming an id, and
    the answer is an empty feed rather than an error, so the assertion is on the
    returned rows.

    The count query is not decoration: an empty answer only means something once
    it is established there was something to leak.
    """
    stored = await session.execute(
        select(func.count()).select_from(ProjectPhoto).where(ProjectPhoto.project_id == estate.unreachable.id)
    )
    assert stored.scalar_one() > 0, "the unreachable project must hold photos for this test to mean anything"

    rows = await PhotoService(session).recent_across_projects(
        str(estate.caller.id),
        project_id=estate.unreachable.id,
    )

    assert rows == []


@pytest.mark.asyncio
async def test_admin_is_narrowed_by_project_id_rather_than_ignoring_it(
    session: AsyncSession,
    estate: Estate,
) -> None:
    """An admin reaches every project, so an id narrows rather than being dropped.

    The id used is the one the ordinary caller cannot reach, which shows the
    filter is not a denylist: the same argument that yields nothing above yields
    that project's photos here, because the accessible set it intersects with is
    different.

    Note what this case cannot tell apart. For an admin the accessible set is
    every project, so intersecting with it and replacing it produce the same
    answer. Both readings agree here and only one of them is right in general -
    the unreachable case above is what separates them.
    """
    names = await _project_names(session, estate.admin, project_id=estate.unreachable.id)

    assert names == {estate.unreachable.name}


@pytest.mark.asyncio
async def test_project_id_that_exists_nowhere_returns_nothing(
    session: AsyncSession,
    estate: Estate,
) -> None:
    """An id belonging to no project yields an empty feed for anyone.

    Including the admin, whose accessible set is every project that exists: an
    id that is in none of them intersects to nothing there too.
    """
    absent = uuid.uuid4()

    assert await _photo_ids(session, estate.caller, project_id=absent) == set()
    assert await _photo_ids(session, estate.admin, project_id=absent) == set()


@pytest.mark.asyncio
async def test_the_filtered_feed_is_a_subset_of_the_unfiltered_one(
    session: AsyncSession,
    estate: Estate,
) -> None:
    """The property the word "intersection" actually names.

    Filtering may remove photos from the answer and may never introduce one, so
    for any id the filtered result is a subset of the unfiltered result. Stated
    as a relation between two calls rather than as a restatement of the fixture,
    so it keeps holding when the estate changes.

    Asserted on a reachable id, and non-emptiness is asserted first: a subset
    claim is vacuously true of an empty set, which is exactly the answer the
    unreachable cases give.
    """
    unfiltered = await _photo_ids(session, estate.caller)
    filtered = await _photo_ids(session, estate.caller, project_id=estate.owned.id)

    assert filtered, "a reachable project with photos must contribute rows"
    assert filtered <= unfiltered
