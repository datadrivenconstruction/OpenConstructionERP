# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Integration tests for GET /api/v1/projects/{id}/module-presence.

The endpoint answers "does this project have any rows in module X?"
for every module the sidebar can render, so the frontend can dim
modules with no data. Each probe is a cheap ``SELECT 1 ... LIMIT 1``
running concurrently.

Coverage:

1.  Auth gates — 401 without a user, 403 when the caller isn't the
    project owner / admin.
2.  Empty project — every field returns False, no exceptions.
3.  Populated modules — inserting a row into a single module's table
    flips that module's bool to True and leaves the rest False.
4.  Missing tables — when the probe SQL references a table that does
    not exist on the test schema (we deliberately probe a synthetic
    name), the endpoint still returns 200 with that key False.
5.  Concurrency — probes run via ``asyncio.gather``; we patch
    ``asyncio.gather`` and assert the call shape so a future
    refactor that serialises probes will fail this test loudly.
6.  Cache — the second call inside the TTL window does NOT re-issue
    the per-probe queries.
"""

from __future__ import annotations

import tempfile
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def _register_minimal_models() -> None:
    """Pull projects + users into Base.metadata.

    The presence-probe SQL targets dozens of module tables; we don't
    register them here. Probes against missing tables return False
    by design (the point of test #4 below), so this minimal set is
    sufficient to exercise the endpoint.
    """
    import app.core.audit  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.users.models  # noqa: F401


@pytest_asyncio.fixture
async def temp_engine_and_factory():
    tmp_db = Path(tempfile.mkdtemp()) / "module_presence_api.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)

    _register_minimal_models()

    from app.database import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    yield engine, factory, tmp_db

    await engine.dispose()
    try:
        tmp_db.unlink(missing_ok=True)
        tmp_db.parent.rmdir()
    except OSError:
        pass


_current_user_payload: dict[str, str] = {}


@pytest_asyncio.fixture
async def app(temp_engine_and_factory) -> AsyncGenerator[FastAPI, None]:
    _engine, factory, _tmp = temp_engine_and_factory

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
    _engine, factory, _tmp = temp_engine_and_factory

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
    """Fresh project + minimal schema → every module reads False, no 500."""
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
    _engine, factory, _tmp = temp_engine_and_factory
    user_id, project_id = await project_owned_by()
    _set_acting_user(user_id)

    # The BOQ model is reachable via Project relationships so its
    # table already lives in Base.metadata from create_all above.
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


@pytest.mark.asyncio
async def test_module_presence_403_for_non_owner(
    client: AsyncClient,
    project_owned_by,
) -> None:
    """Authenticated stranger (non-admin) → 403, not 200."""
    _owner_id, project_id = await project_owned_by()
    stranger_id = uuid.uuid4()
    _set_acting_user(stranger_id, role="estimator")

    resp = await client.get(f"/api/v1/projects/{project_id}/module-presence")
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_module_presence_missing_table_does_not_500(
    client: AsyncClient,
    project_owned_by,
) -> None:
    """All module tables absent → 200 with False everywhere.

    On the minimal test schema almost every probe runs against a
    table that does not exist. The endpoint MUST still return 200
    with False for those keys — that's the whole point of the
    defensive ``OperationalError`` / ``ProgrammingError`` catch.
    """
    user_id, project_id = await project_owned_by()
    _set_acting_user(user_id)

    resp = await client.get(f"/api/v1/projects/{project_id}/module-presence")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # ALL probes target missing tables → every flag is False, no 500.
    assert not any(body.values()), body


@pytest.mark.asyncio
async def test_module_presence_probes_run_concurrently(
    client: AsyncClient,
    project_owned_by,
) -> None:
    """asyncio.gather must wrap the probe coroutines.

    Patches ``asyncio.gather`` inside the module_presence namespace
    and asserts it was invoked exactly once with N coroutine args
    (one per registered probe). If a future refactor accidentally
    serialises probes with an ``await`` loop, this fails loudly.
    """
    from app.modules.projects import module_presence as mp

    user_id, project_id = await project_owned_by()
    _set_acting_user(user_id)
    # The cache is per-process and survives test boundaries; clear
    # it so the patched gather is guaranteed to be reached.
    mp.invalidate_presence_cache()

    call_args: list[tuple] = []
    # Capture the real gather BEFORE patching so the replacement
    # doesn't recurse into itself via ``mp.asyncio.gather``.
    real_gather = mp.asyncio.gather

    async def _capturing_gather(*args, **kwargs):  # type: ignore[no-untyped-def]
        call_args.append(args)
        return await real_gather(*args, **kwargs)

    with patch.object(mp.asyncio, "gather", _capturing_gather):
        resp = await client.get(f"/api/v1/projects/{project_id}/module-presence")
    assert resp.status_code == 200, resp.text

    assert len(call_args) == 1, "gather should be called exactly once per request"
    assert len(call_args[0]) == len(mp.PRESENCE_PROBES), (
        f"gather got {len(call_args[0])} args; expected {len(mp.PRESENCE_PROBES)}"
    )


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
