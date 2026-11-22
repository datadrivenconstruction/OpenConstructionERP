# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A grant is one of two layers, and both have to answer yes.

ADR 006, stage 3, the application arm. The database arm is
``test_a_grant_opens_exactly_the_project_it_names.py``; this file is about the
guard every project-scoped route already calls -
:func:`app.dependencies.verify_project_access` - and its set-level companion
:func:`app.dependencies.accessible_project_ids`.

The two layers are a company layer and a person layer, and the claim is that they
are AND'd rather than OR'd:

* a team membership alone stops opening a project whose company never invited the
  caller's company in. That is the hole the ``project_frameworks`` union widened
  into a leak, and it is why the company arm is checked *before* the owner and
  membership checks rather than added to them;
* a grant alone opens nothing, because the person still has to be on the project's
  team. A company-level grant that opened a project to a partner's entire staff
  would be a bigger leak than the one this closes.

Both are measured with the flag off as well as on, because ``OE_PROJECT_GRANTS``
defaults to False and an install that never sets it has to behave byte-for-byte as
it did before the grant table existed. The off case is not a courtesy assertion:
it is the migration window ADR 006 owner decision 1 asks for, and a change that
could not be turned off could not be rolled out.

Every request-context binding here is done the way the global dependency does it -
``set_request_tenant`` and ``set_request_granted_projects`` - so the guard reads
the same two ContextVars it reads in production, and the last test asserts the
dependency that fills them.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import rls
from app.dependencies import accessible_project_ids, verify_project_access
from app.modules.projects.grants import live_granted_project_ids
from app.modules.projects.models import Project, ProjectParticipantGrant
from app.modules.users.models import Membership, Organization, User
from tests._pg import isolated_engine
from tests.pg.governance_fixtures import add_project

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]


class _World:
    """Three companies, two projects, and a person in each company on each team."""

    def __init__(self) -> None:
        self.factory: async_sessionmaker[AsyncSession] | None = None
        self.org_a = uuid.uuid4()  # owns the granted project
        self.org_b = uuid.uuid4()  # the grantee
        self.org_c = uuid.uuid4()  # invited to nothing
        self.alpha = uuid.uuid4()  # a person of A
        self.beta = uuid.uuid4()  # a person of B, on both projects' teams
        self.gamma = uuid.uuid4()  # a person of C, on both projects' teams
        self.outsider = uuid.uuid4()  # a person of B, on no team
        self.administrator = uuid.uuid4()  # a person of C with the platform role
        self.granted_project = uuid.uuid4()  # owned by A
        self.own_project = uuid.uuid4()  # owned by B
        self.tenants: dict[uuid.UUID, uuid.UUID] = {}


async def _person(session: AsyncSession, user_id: uuid.UUID, organization_id: uuid.UUID, role: str = "editor") -> None:
    session.add(
        User(
            id=user_id,
            email=f"{role}-{user_id.hex[:8]}@layers.test",
            hashed_password="x",
            full_name=f"Layers {role}",
            role=role,
            locale="en",
            is_active=True,
            metadata_={},
        )
    )
    await session.flush()
    session.add(
        Membership(
            user_id=user_id,
            organization_id=organization_id,
            role=role,
            status="active",
            is_default=True,
        )
    )
    await session.flush()


async def _organization(session: AsyncSession, organization_id: uuid.UUID, name: str) -> None:
    session.add(
        Organization(id=organization_id, name=name, slug=f"layers-{name.lower().replace(' ', '-')}", status="active")
    )
    await session.flush()


async def _build(session: AsyncSession) -> _World:
    w = _World()
    await _organization(session, w.org_a, "Alpha")
    await _organization(session, w.org_b, "Beta")
    await _organization(session, w.org_c, "Gamma")

    await _person(session, w.alpha, w.org_a, "manager")
    await _person(session, w.beta, w.org_b)
    await _person(session, w.gamma, w.org_c)
    await _person(session, w.outsider, w.org_b)
    await _person(session, w.administrator, w.org_c, "admin")

    # Both projects carry beta and gamma on their teams, so the person layer
    # answers yes for each of them and the only thing that can differ between the
    # two companies is the company layer.
    w.granted_project = await add_project(session, w.alpha, [w.beta, w.gamma], organization_id=w.org_a)
    w.own_project = await add_project(session, w.beta, [w.beta, w.gamma], organization_id=w.org_b)

    w.tenants = {
        w.alpha: w.org_a,
        w.beta: w.org_b,
        w.gamma: w.org_c,
        w.outsider: w.org_b,
        w.administrator: w.org_c,
    }
    return w


async def _grant(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    grantee: uuid.UUID,
    on_behalf: uuid.UUID,
    granted_by: uuid.UUID,
    status: str = "active",
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
) -> ProjectParticipantGrant:
    grant = ProjectParticipantGrant(
        project_id=project_id,
        grantee_organization_id=grantee,
        granted_by_user_id=granted_by,
        granted_on_behalf_of_organization_id=on_behalf,
        scope="view",
        status=status,
        valid_from=valid_from,
        valid_until=valid_until,
        metadata_={},
    )
    session.add(grant)
    await session.flush()
    return grant


@pytest_asyncio.fixture
async def world():
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            w = await _build(session)
            await session.commit()
        w.factory = factory
        yield w


@pytest.fixture
def grants_on(monkeypatch: pytest.MonkeyPatch):
    """``OE_PROJECT_GRANTS`` on, through the same seam the enforcement flag uses."""
    monkeypatch.setattr(rls, "grants_enabled", lambda: True)


@pytest.fixture
def grants_off(monkeypatch: pytest.MonkeyPatch):
    """The default install: the flag off, and the guard answering as it always did."""
    monkeypatch.setattr(rls, "grants_enabled", lambda: False)


def _bind(w: _World, caller: uuid.UUID, granted: tuple[str, ...] = ()) -> list[object]:
    """Bind a request context the way the two global dependencies do."""
    return [
        rls.set_request_tenant(str(w.tenants[caller])),
        rls.set_request_granted_projects(granted),
    ]


def _unbind(tokens: list[object]) -> None:
    rls.reset_request_granted_projects(tokens[1])
    rls.reset_request_tenant(tokens[0])


async def _denied(
    w: _World, caller: uuid.UUID, project_id: uuid.UUID, granted: tuple[str, ...] = ()
) -> tuple[str, int]:
    """Run the guard and return the refusal's detail, asserting it refused."""
    tokens = _bind(w, caller, granted)
    try:
        async with w.factory() as session:
            with pytest.raises(HTTPException) as caught:
                await verify_project_access(project_id, str(caller), session)
    finally:
        _unbind(tokens)
    return str(caught.value.detail), caught.value.status_code


async def _allowed(w: _World, caller: uuid.UUID, project_id: uuid.UUID, granted: tuple[str, ...] = ()) -> None:
    tokens = _bind(w, caller, granted)
    try:
        async with w.factory() as session:
            await verify_project_access(project_id, str(caller), session)
    finally:
        _unbind(tokens)


# ── both layers, and each one alone ─────────────────────────────────────────


async def test_a_team_membership_alone_stops_opening_a_project_the_callers_company_was_not_invited_to(world, grants_on):
    """The hole this stage closes.

    Beta's person is on the project's team, which is the whole of what the guard
    asked before, and is refused now because beta's company was never invited in.
    The answer is 404 and not 403, so "not yours" and "no such project" stay the
    same answer to somebody holding a list of identifiers.
    """
    w = world
    detail, code = await _denied(w, w.beta, w.granted_project)

    assert code == 404
    assert detail == "Project not found"


async def test_a_grant_without_a_team_membership_opens_nothing(world, grants_on):
    """The other half of the AND.

    Beta's company holds a live grant, and a person of beta's who is on no team is
    still refused: a company-level grant is not a membership, and treating it as
    one would open the project to a partner's entire staff, which is a bigger leak
    than the one this closes.
    """
    w = world
    async with w.factory() as session:
        await _grant(
            session,
            project_id=w.granted_project,
            grantee=w.org_b,
            on_behalf=w.org_a,
            granted_by=w.alpha,
        )
        await session.commit()
        granted = tuple(await live_granted_project_ids(session, str(w.org_b)))
    assert granted == (str(w.granted_project),)

    detail, code = await _denied(w, w.outsider, w.granted_project, granted)

    assert code == 404
    assert detail == "Project not found"


async def test_a_grant_and_a_team_membership_together_open_the_project(world, grants_on):
    w = world
    async with w.factory() as session:
        await _grant(
            session,
            project_id=w.granted_project,
            grantee=w.org_b,
            on_behalf=w.org_a,
            granted_by=w.alpha,
        )
        await session.commit()
        granted = tuple(await live_granted_project_ids(session, str(w.org_b)))

    await _allowed(w, w.beta, w.granted_project, granted)


async def test_the_owning_company_needs_no_grant_to_reach_its_own_project(world, grants_on):
    """The ownership arm of the company layer, with nothing bound in the grant GUC."""
    w = world
    await _allowed(w, w.alpha, w.granted_project, ())


async def test_with_the_flag_off_a_team_membership_alone_still_opens_the_project(world, grants_off):
    """The default install behaves exactly as it did before the grant table existed.

    This is the migration window ADR 006 owner decision 1 asks for, and the reason
    the flag is not a sub-mode of ``OE_RLS_ENFORCE``: the application arm has to be
    switchable on an install where row-level security is off, which is every
    install today.
    """
    w = world
    await _allowed(w, w.beta, w.granted_project, ())
    await _allowed(w, w.gamma, w.granted_project, ())


async def test_a_credential_that_names_no_company_cannot_satisfy_the_company_arm(world, grants_on):
    """Fail closed on the arm that cannot be evaluated.

    A token that says which person it is but not which company cannot pass a
    company check, and guessing a company from the person is precisely the
    confusion ADR 005 removed. Unbound rather than empty: nothing in this context
    named a tenant at all.
    """
    w = world
    tokens = [rls.set_request_tenant(None), rls.set_request_granted_projects((str(w.granted_project),))]
    try:
        async with w.factory() as session:
            with pytest.raises(HTTPException) as caught:
                await verify_project_access(w.granted_project, str(w.beta), session)
    finally:
        _unbind(tokens)

    assert caught.value.status_code == 404


async def test_a_project_with_no_owning_company_is_not_hidden_by_the_company_arm(world, grants_on):
    """There is no company layer to fail, so the person layer answers alone.

    Refusing here would hide every project the boot backfill has not resolved yet
    from the people working on it - a stricter rule than ADR 006 asks for, applied
    at the moment an install is least able to absorb it. The readiness report's
    ``tenant_is_null`` blocker is where those projects stay visible.
    """
    w = world
    async with w.factory() as session:
        orphan = uuid.uuid4()
        session.add(
            Project(
                id=orphan,
                name=f"Orphan {orphan.hex[:6]}",
                currency="EUR",
                status="active",
                owner_id=w.alpha,
                organization_id=None,
                metadata_={},
            )
        )
        await session.commit()

    tokens = _bind(w, w.beta, ())
    try:
        async with w.factory() as session:
            # Beta is not on this project's team either, so the refusal has to come
            # from the person layer and not from the company arm: a 404 either way,
            # which is why the assertion below checks the arm directly.
            from app.modules.projects.grants import company_may_read_project

            project = await session.get(Project, orphan)
            assert company_may_read_project(project, caller_organization_id=str(w.org_b), granted_project_ids=())
            with pytest.raises(HTTPException):
                await verify_project_access(orphan, str(w.beta), session)
    finally:
        _unbind(tokens)


async def test_an_administrator_still_reaches_a_project_their_company_was_not_invited_to(world, grants_on):
    """The one asymmetry, stated rather than left to be found.

    Reading another company's project is what a platform administrator is for, so
    the company arm keeps the admin bypass the guard has always had. Deciding that
    another company *participates* is not an instance decision, which is why
    ``app.modules.projects.grants`` has no bypass at all and
    ``test_only_the_owning_organization_decides_who_participates_in_a_project``
    refuses an administrator of a third company with a 404.
    """
    w = world
    await _allowed(w, w.administrator, w.granted_project, ())


# ── what counts as live ─────────────────────────────────────────────────────


async def test_only_a_live_grant_reaches_the_list_the_predicate_reads(world, grants_on):
    """Revoked, suspended, expired and not-yet-started grants are all absent.

    One project per shape, so the answer is a set of ids rather than a count and a
    missing one cannot hide behind another. This is how a withdrawal closes access
    without touching a single row the grantee wrote: nothing is deleted, the list
    simply stops naming the project.
    """
    w = world
    now = datetime.now(UTC)
    shapes = {
        "open-ended": {},
        "windowed-live": {"valid_from": now - timedelta(days=1), "valid_until": now + timedelta(days=1)},
        "not-yet-started": {"valid_from": now + timedelta(days=1)},
        "expired": {"valid_until": now - timedelta(days=1)},
    }
    async with w.factory() as session:
        expected: set[str] = set()
        for index, (label, window) in enumerate(shapes.items()):
            project_id = uuid.uuid4()
            session.add(
                Project(
                    id=project_id,
                    name=f"{label} {project_id.hex[:6]}",
                    currency="EUR",
                    status="active",
                    owner_id=w.alpha,
                    organization_id=w.org_a,
                    metadata_={},
                )
            )
            await session.flush()
            await _grant(
                session,
                project_id=project_id,
                grantee=w.org_b,
                on_behalf=w.org_a,
                granted_by=w.alpha,
                **window,
            )
            if label in ("open-ended", "windowed-live"):
                expected.add(str(project_id))

        for label in ("revoked", "suspended"):
            project_id = uuid.uuid4()
            session.add(
                Project(
                    id=project_id,
                    name=f"{label} {project_id.hex[:6]}",
                    currency="EUR",
                    status="active",
                    owner_id=w.alpha,
                    organization_id=w.org_a,
                    metadata_={},
                )
            )
            await session.flush()
            await _grant(
                session,
                project_id=project_id,
                grantee=w.org_b,
                on_behalf=w.org_a,
                granted_by=w.alpha,
                status=label,
            )
        await session.commit()

        live = set(await live_granted_project_ids(session, str(w.org_b)))

    assert live == expected, f"expected {sorted(expected)}, got {sorted(live)}"
    assert len(live) == 2


async def test_the_sql_arm_and_the_models_own_is_live_agree_on_every_row(world, grants_on):
    """Two expressions of one rule, compared over every row rather than asserted.

    :attr:`ProjectParticipantGrant.is_live` decides what the application layer
    allows and :func:`live_granted_project_ids` decides what the database returns.
    A caller who is refused by one and served by the other has found a hole, so the
    two are compared row by row over the shapes the previous test built.
    """
    w = world
    now = datetime.now(UTC)
    async with w.factory() as session:
        for offset, status_value in ((-2, "active"), (2, "active")):
            project_id = uuid.uuid4()
            session.add(
                Project(
                    id=project_id,
                    name=f"Agree {project_id.hex[:6]}",
                    currency="EUR",
                    status="active",
                    owner_id=w.alpha,
                    organization_id=w.org_a,
                    metadata_={},
                )
            )
            await session.flush()
            await _grant(
                session,
                project_id=project_id,
                grantee=w.org_b,
                on_behalf=w.org_a,
                granted_by=w.alpha,
                valid_from=now + timedelta(days=offset),
                valid_until=now + timedelta(days=offset + 1),
            )
        await session.commit()

        rows = (
            (
                await session.execute(
                    select(ProjectParticipantGrant).where(ProjectParticipantGrant.grantee_organization_id == w.org_b)
                )
            )
            .scalars()
            .all()
        )
        live = set(await live_granted_project_ids(session, str(w.org_b)))

    assert len(rows) >= 2, "the fixture did not build the shapes this comparison needs"
    disagreed = [
        (str(row.project_id), row.status, row.is_live, str(row.project_id) in live)
        for row in rows
        if row.is_live != (str(row.project_id) in live)
    ]
    assert not disagreed, disagreed


async def test_a_caller_with_no_grants_gets_an_empty_list_and_not_an_error(world, grants_on):
    """An empty list is an answer, and it is the fail-closed one."""
    w = world
    async with w.factory() as session:
        assert await live_granted_project_ids(session, str(w.org_c)) == []
        # A caller naming no company at all gets the same answer rather than a
        # query that matches every grant on the install.
        assert await live_granted_project_ids(session, None) == []


# ── the set-level companion ─────────────────────────────────────────────────


async def test_a_listing_offers_the_granted_project_and_drops_the_uninvited_one(world, grants_on):
    """The same two layers as the guard, expressed as one statement.

    Without the second half a list would offer a project that opens as "Project
    not found", which is the mismatch ``live_only`` exists to prevent. Beta's
    person is on both projects' teams; only one of them was invited.
    """
    w = world
    tokens = _bind(w, w.beta, ())
    try:
        async with w.factory() as session:
            before = await accessible_project_ids(session, str(w.beta))
    finally:
        _unbind(tokens)
    assert before == {w.own_project}, before

    async with w.factory() as session:
        await _grant(
            session,
            project_id=w.granted_project,
            grantee=w.org_b,
            on_behalf=w.org_a,
            granted_by=w.alpha,
        )
        await session.commit()
        granted = tuple(await live_granted_project_ids(session, str(w.org_b)))

    tokens = _bind(w, w.beta, granted)
    try:
        async with w.factory() as session:
            after = await accessible_project_ids(session, str(w.beta))
    finally:
        _unbind(tokens)
    assert after == {w.own_project, w.granted_project}, after


async def test_a_listing_with_the_flag_off_is_what_it_always_was(world, grants_off):
    w = world
    tokens = _bind(w, w.beta, ())
    try:
        async with w.factory() as session:
            ids = await accessible_project_ids(session, str(w.beta))
    finally:
        _unbind(tokens)

    assert ids == {w.own_project, w.granted_project}, ids


async def test_an_administrator_gets_no_filter_from_the_set_level_companion_either(world, grants_on):
    """``None`` means "do not filter", and the company arm does not change that."""
    w = world
    tokens = _bind(w, w.administrator, ())
    try:
        async with w.factory() as session:
            ids = await accessible_project_ids(session, str(w.administrator))
    finally:
        _unbind(tokens)

    assert ids is None


# ── the dependency that fills the binding ───────────────────────────────────


async def test_the_request_dependency_binds_the_projects_a_live_grant_names(world, monkeypatch):
    """``granted_projects_context``, exercised as the global dependency runs it.

    The listener in :mod:`app.core.rls` is synchronous and cannot query, so the
    list is resolved here, once per request, and bound before any handler runs.
    The session is the isolated one rather than the module-level factory, patched
    in at the attribute the dependency reads, because a test that bound a list
    from the shared cluster would be measuring another database's grants.
    """
    from app import database
    from app.dependencies import granted_projects_context

    w = world
    monkeypatch.setattr(rls, "grants_enabled", lambda: True)
    monkeypatch.setattr(database, "async_session_factory", w.factory)

    async with w.factory() as session:
        await _grant(
            session,
            project_id=w.granted_project,
            grantee=w.org_b,
            on_behalf=w.org_a,
            granted_by=w.alpha,
        )
        await session.commit()

    assert rls.current_request_granted_projects() is None, "nothing was bound before the dependency ran"
    context = granted_projects_context(str(w.org_b))
    await context.__anext__()
    try:
        bound = rls.current_request_granted_projects()
    finally:
        with pytest.raises(StopAsyncIteration):
            await context.__anext__()

    assert bound == (str(w.granted_project),)
    # Reset on the way out, so the next request on this worker task does not
    # inherit somebody else's grants.
    assert rls.current_request_granted_projects() is None


async def test_a_caller_naming_no_company_binds_an_empty_list_without_touching_the_database(world, monkeypatch):
    """Unset would leave whatever an earlier task bound in place."""
    from app import database
    from app.dependencies import granted_projects_context

    w = world
    monkeypatch.setattr(rls, "grants_enabled", lambda: True)

    async def _refuse():
        raise AssertionError("the dependency queried for a caller that named no company")

    monkeypatch.setattr(database, "async_session_factory", _refuse)

    context = granted_projects_context(None)
    await context.__anext__()
    try:
        assert rls.current_request_granted_projects() == ()
    finally:
        with pytest.raises(StopAsyncIteration):
            await context.__anext__()
    assert rls.current_request_granted_projects() is None


async def test_with_the_flag_off_the_dependency_binds_nothing_and_queries_nothing(world, monkeypatch):
    """The default path costs a ContextVar and no round trip."""
    from app import database
    from app.dependencies import granted_projects_context

    w = world
    monkeypatch.setattr(rls, "grants_enabled", lambda: False)

    async def _refuse():
        raise AssertionError("the dependency queried with the flag off")

    monkeypatch.setattr(database, "async_session_factory", _refuse)

    context = granted_projects_context(str(w.org_b))
    await context.__anext__()
    try:
        assert rls.current_request_granted_projects() == ()
    finally:
        with pytest.raises(StopAsyncIteration):
            await context.__anext__()


async def test_an_unreadable_grant_table_fails_closed_rather_than_open(world, monkeypatch):
    """A query failure binds an empty list, so the ownership arm keeps working.

    Failing open would hand every caller every granted project on the install;
    failing closed means a company still sees its own projects while the failure
    is logged and investigated, which is the only one of the two that is safe to
    be wrong about.
    """
    from app import database
    from app.dependencies import granted_projects_context

    w = world
    monkeypatch.setattr(rls, "grants_enabled", lambda: True)

    class _Broken:
        def __call__(self):
            raise RuntimeError("the grant table could not be read")

    monkeypatch.setattr(database, "async_session_factory", _Broken())

    context = granted_projects_context(str(w.org_b))
    await context.__anext__()
    try:
        assert rls.current_request_granted_projects() == ()
    finally:
        with pytest.raises(StopAsyncIteration):
            await context.__anext__()

    # And the guard still answers for the caller's own project.
    await _allowed(w, w.beta, w.own_project, ())
