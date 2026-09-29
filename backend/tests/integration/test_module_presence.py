# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Integration tests for GET /api/v1/projects/{id}/module-presence.

The endpoint answers "does this project have any rows in module X?"
for every module the sidebar can render, so the frontend can dim
modules with no data. Each probe is a cheap ``SELECT 1 ... LIMIT 1``
running concurrently.

Coverage:

1.  Auth gates — 401 without a user, 404 when the caller cannot read the
    project (owner, member or admin can), the same answer as a missing one.
2.  Empty project — every field returns False, no exceptions.
3.  Populated modules — inserting a row into a single module's table
    flips that module's bool to True and leaves the rest False.
4.  Empty tables — when a module's table exists but holds no rows for
    the project, the endpoint still returns 200 with that key False
    (and the defensive catch keeps it 200 even for a missing table).
5.  Concurrency — probes run via ``asyncio.gather``; we patch
    ``asyncio.gather`` and assert the call shape so a future
    refactor that serialises probes will fail this test loudly.
6.  Cache — the second call inside the TTL window does NOT re-issue
    the per-probe queries.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests._pg import isolated_engine


@pytest_asyncio.fixture
async def temp_engine_and_factory():
    """Per-test throwaway PostgreSQL database, cloned from the schema-loaded template.

    The app under test opens its own sessions via the ``get_session`` override, so
    the test and the app run on separate connections that must see each other's
    commits - hence a real throwaway database rather than a savepoint-rolled-back
    shared session.
    """
    async with isolated_engine() as engine:
        factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        yield engine, factory


_current_user_payload: dict[str, str] = {}


@pytest_asyncio.fixture
async def app(temp_engine_and_factory) -> AsyncGenerator[FastAPI, None]:
    _engine, factory = temp_engine_and_factory

    from app.dependencies import (
        get_current_user_id,
        get_current_user_payload,
        get_session,
    )
    from app.modules.projects.router import router as projects_router

    fastapi_app = FastAPI()
    fastapi_app.include_router(projects_router, prefix="/api/v1/projects")

    async def _override_session() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def _override_payload() -> dict[str, str]:
        return dict(_current_user_payload)

    async def _override_user_id() -> str:
        sub = _current_user_payload.get("sub", "")
        if not sub:
            # Mirror what the real dependency does when no token is
            # supplied — raise a 401 from inside the dependency.
            from fastapi import HTTPException, status

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
            )
        return sub

    fastapi_app.dependency_overrides[get_session] = _override_session
    fastapi_app.dependency_overrides[get_current_user_payload] = _override_payload
    fastapi_app.dependency_overrides[get_current_user_id] = _override_user_id

    yield fastapi_app


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    # Reset cache + acting user between tests so cross-test state
    # never leaks (the presence cache is module-global by design).
    from app.modules.projects.module_presence import invalidate_presence_cache

    invalidate_presence_cache()
    _current_user_payload.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def project_owned_by(temp_engine_and_factory):
    _engine, factory = temp_engine_and_factory

    from app.modules.projects.models import Project
    from app.modules.users.models import User

    async def _make() -> tuple[uuid.UUID, uuid.UUID]:
        user = User(
            id=uuid.uuid4(),
            email=f"owner-{uuid.uuid4().hex[:6]}@presence.io",
            hashed_password="x" * 60,
            full_name="Presence Owner",
            role="estimator",
            locale="en",
            is_active=True,
            metadata_={},
        )
        project = Project(
            id=uuid.uuid4(),
            name="Module Presence Test Project",
            owner_id=user.id,
            status="active",
        )
        async with factory() as session:
            session.add(user)
            await session.flush()
            session.add(project)
            await session.commit()
        return user.id, project.id

    return _make


def _set_acting_user(user_id: uuid.UUID, role: str = "estimator") -> None:
    _current_user_payload.clear()
    _current_user_payload["sub"] = str(user_id)
    _current_user_payload["role"] = role


# ── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_module_presence_returns_all_false_on_empty_project(
    client: AsyncClient,
    project_owned_by,
) -> None:
    """Fresh project, no module rows → every module reads False, no 500."""
    user_id, project_id = await project_owned_by()
    _set_acting_user(user_id)

    resp = await client.get(f"/api/v1/projects/{project_id}/module-presence")
    assert resp.status_code == 200, resp.text

    body = resp.json()
    # Every value is a bool, every bool is False on a brand-new project.
    assert all(isinstance(v, bool) for v in body.values()), body
    assert not any(body.values()), f"expected all False, got truthy keys: {[k for k, v in body.items() if v]}"

    # And the sidebar slug "5d" survives the alias round-trip.
    assert "5d" in body
    assert "five_d" not in body


@pytest.mark.asyncio
async def test_module_presence_flips_true_when_module_table_has_row(
    client: AsyncClient,
    project_owned_by,
    temp_engine_and_factory,
) -> None:
    """Insert one BOQ row → ``boq`` (+ alias ``estimation_dashboard``) flip True.

    Other modules stay False — proves the per-probe wiring is real,
    not a constant-True fall-through.
    """
    _engine, factory = temp_engine_and_factory
    user_id, project_id = await project_owned_by()
    _set_acting_user(user_id)

    # The BOQ model lives in the schema-loaded template the throwaway
    # database is cloned from, so its table already exists.
    # Use the model directly so we don't have to mirror its schema.
    from app.modules.boq.models import BOQ

    async with factory() as session:
        session.add(
            BOQ(
                id=uuid.uuid4(),
                project_id=project_id,
                name="presence-test-boq",
                description="",
                status="draft",
            ),
        )
        await session.commit()

    resp = await client.get(f"/api/v1/projects/{project_id}/module-presence")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # estimation_dashboard is an explicit alias of boq in the registry.
    assert body["boq"] is True, body
    assert body["estimation_dashboard"] is True, body
    # Spot-check unrelated modules remain False.
    assert body["finance"] is False
    assert body["rfi"] is False
    assert body["safety"] is False


@pytest.mark.asyncio
async def test_module_presence_requires_authentication(
    client: AsyncClient,
    project_owned_by,
) -> None:
    """No JWT → 401, not 200 or 500."""
    _user_id, project_id = await project_owned_by()
    # Deliberately do NOT call _set_acting_user — payload stays empty.
    _current_user_payload.clear()

    resp = await client.get(f"/api/v1/projects/{project_id}/module-presence")
    assert resp.status_code == 401, resp.text


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_module_presence_404_for_a_stranger(
    client: AsyncClient,
    project_owned_by,
) -> None:
    """Authenticated stranger (non-admin) → 404, the same answer as a missing project."""
    _owner_id, project_id = await project_owned_by()
    stranger_id = uuid.uuid4()
    _set_acting_user(stranger_id, role="estimator")

    resp = await client.get(f"/api/v1/projects/{project_id}/module-presence")
    assert resp.status_code == 404, resp.text


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_project_reads_open_for_a_viewer_member(
    client: AsyncClient,
    project_owned_by,
    temp_engine_and_factory,
) -> None:
    """A viewer on the project team reads the profile, modules and presence.

    These three are reads the project page makes as it opens. They used the
    owner check, so every member who was not the owner got 403 on a project
    that otherwise opened for them. Membership is what grants read access
    everywhere else in the module, and a stranger still gets 404.
    """
    from app.modules.teams.models import Team, TeamMembership
    from app.modules.users.models import User

    _owner_id, project_id = await project_owned_by()
    _engine, factory = temp_engine_and_factory
    member_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=member_id,
                email=f"member-{uuid.uuid4().hex[:6]}@presence.io",
                hashed_password="x" * 60,
                full_name="Presence Member",
                role="viewer",
                locale="en",
                is_active=True,
                metadata_={},
            )
        )
        team = Team(id=uuid.uuid4(), project_id=project_id, name="Default", metadata_={})
        session.add(team)
        await session.flush()
        session.add(TeamMembership(id=uuid.uuid4(), team_id=team.id, user_id=member_id, role="member"))
        await session.commit()

    _set_acting_user(member_id, role="viewer")
    for path in ("module-presence", "profile", "modules"):
        resp = await client.get(f"/api/v1/projects/{project_id}/{path}")
        assert resp.status_code == 200, (path, resp.text)

    _set_acting_user(uuid.uuid4(), role="viewer")
    for path in ("module-presence", "profile", "modules"):
        resp = await client.get(f"/api/v1/projects/{project_id}/{path}")
        assert resp.status_code == 404, (path, resp.text)


@pytest.mark.asyncio
async def test_module_presence_empty_tables_do_not_500(
    client: AsyncClient,
    project_owned_by,
) -> None:
    """Every module table present but empty → 200 with False everywhere.

    The schema is fully materialised, but a brand-new project has no
    rows in any module table, so every probe's ``SELECT 1 ... LIMIT 1``
    yields nothing. The endpoint MUST still return 200 with False for
    those keys and never raise — the defensive
    ``OperationalError`` / ``ProgrammingError`` catch also keeps it 200
    if a probe ever targets a table that is missing on some schema.
    """
    user_id, project_id = await project_owned_by()
    _set_acting_user(user_id)

    resp = await client.get(f"/api/v1/projects/{project_id}/module-presence")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # No project has any module rows → every flag is False, no 500.
    assert not any(body.values()), body


@pytest.mark.asyncio
async def test_module_presence_probes_run_one_at_a_time(
    client: AsyncClient,
    project_owned_by,
) -> None:
    """The probes must never overlap: they share one AsyncSession.

    This asserted the opposite until 2026-09-22 - that ``asyncio.gather``
    wrapped the probe coroutines - and reached for ``mp.asyncio.gather`` to
    prove it. The module dropped the concurrency, and the ``asyncio`` import
    with it, on purpose: an AsyncSession is not safe for concurrent
    operations, and on PostgreSQL one failing probe aborts the shared
    transaction and drags every later probe into a false negative, dimming
    half the sidebar. So the guard points the other way now. Counting probe
    calls alone would not catch a regression - a gathered run makes the same
    number of calls - so the assertion is on overlap.
    """
    from app.modules.projects import module_presence as mp

    user_id, project_id = await project_owned_by()
    _set_acting_user(user_id)
    # The cache is per-process and survives test boundaries; clear
    # it so the probes are guaranteed to be reached.
    mp.invalidate_presence_cache()

    real_probe = mp._run_one_probe
    in_flight = 0
    peak = 0
    calls = 0

    async def _counting_probe(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal in_flight, peak, calls
        in_flight += 1
        peak = max(peak, in_flight)
        calls += 1
        try:
            return await real_probe(*args, **kwargs)
        finally:
            in_flight -= 1

    with patch.object(mp, "_run_one_probe", _counting_probe):
        resp = await client.get(f"/api/v1/projects/{project_id}/module-presence")
    assert resp.status_code == 200, resp.text

    assert calls == len(mp.PRESENCE_PROBES), f"ran {calls} probes; expected {len(mp.PRESENCE_PROBES)}"
    assert peak == 1, f"{peak} probes were in flight at once, and they share one session"


@pytest.mark.asyncio
async def test_module_presence_is_cached_within_ttl(
    client: AsyncClient,
    project_owned_by,
) -> None:
    """Second call within TTL must NOT re-run the probes.

    Patches the underlying ``_run_one_probe`` to count invocations
    and asserts: first request runs all probes; second request
    (immediately after) runs zero.
    """
    from app.modules.projects import module_presence as mp

    user_id, project_id = await project_owned_by()
    _set_acting_user(user_id)
    mp.invalidate_presence_cache()

    real_runner = mp._run_one_probe
    call_count = {"n": 0}

    async def _counting_runner(session, probe, pid):  # type: ignore[no-untyped-def]
        call_count["n"] += 1
        return await real_runner(session, probe, pid)

    with patch.object(mp, "_run_one_probe", _counting_runner):
        r1 = await client.get(f"/api/v1/projects/{project_id}/module-presence")
        first_count = call_count["n"]
        r2 = await client.get(f"/api/v1/projects/{project_id}/module-presence")
        second_count = call_count["n"]

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert first_count == len(mp.PRESENCE_PROBES), f"first call should run all probes, got {first_count}"
    assert second_count == first_count, (
        f"second call should hit cache (0 extra runs), got {second_count - first_count} extra"
    )
