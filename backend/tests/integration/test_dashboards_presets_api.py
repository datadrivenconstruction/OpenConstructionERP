"""T05 integration tests — Dashboard Presets & Collections API.

Stands up a minimal FastAPI app with just the dashboards router mounted
plus session/auth dependencies overridden to point at a per-test temp
SQLite file (``feedback_test_isolation.md``).

Coverage (8+ tests):

* POST /presets — happy path (private preset)
* POST /presets — collection auto-promote when shared_with_project=True
* GET /presets — owner sees own private presets
* GET /presets — non-owner sees only collections shared with project
* GET /presets/{id} — 404 on someone else's private preset
* PATCH /presets/{id} — owner can rename
* PATCH /presets/{id} — non-owner gets 403
* DELETE /presets/{id} — owner removes
* POST /presets/{id}/share — toggles sharing flag
* Validation — empty name → 422
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.dependencies import get_current_user_payload, get_session

# ── Helpers ────────────────────────────────────────────────────────────────


def _register_minimal_models() -> None:
    """Pull dashboards + FK-target modules into Base.metadata."""
    import app.modules.dashboards.models  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.users.models  # noqa: F401


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def temp_engine_and_factory():
    tmp_db = Path(tempfile.mkdtemp()) / "presets_api.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)

    _register_minimal_models()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False,
    )

    yield engine, factory, tmp_db

    await engine.dispose()
    try:
        tmp_db.unlink(missing_ok=True)
        tmp_db.parent.rmdir()
    except OSError:
        pass


# Each test that wants to swap the acting user mutates this dict.
_current_user_payload: dict[str, str] = {}


@pytest_asyncio.fixture
async def app(temp_engine_and_factory) -> AsyncGenerator[FastAPI, None]:
    _engine, factory, _tmp = temp_engine_and_factory

    from app.modules.dashboards.router import router as dashboards_router

    app = FastAPI()
    app.include_router(dashboards_router, prefix="/api/v1/dashboards")

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

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user_payload] = _override_payload

    yield app


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def user_a() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def user_b() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def project_id() -> uuid.UUID:
    return uuid.uuid4()


def _set_acting_user(user_id: uuid.UUID, tenant_id: str | None = None) -> None:
    _current_user_payload.clear()
    _current_user_payload["sub"] = str(user_id)
    _current_user_payload["tenant_id"] = tenant_id or str(user_id)


# ── Tests ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_private_preset_happy_path(
    client: AsyncClient, user_a: uuid.UUID, project_id: uuid.UUID,
) -> None:
    _set_acting_user(user_a)
    resp = await client.post(
        "/api/v1/dashboards/presets",
        json={
            "name": "My weekly overview",
            "description": "Wall + door distributions",
            "kind": "preset",
            "project_id": str(project_id),
            "config_json": {
                "snapshot_id": str(uuid.uuid4()),
                "filters": {"category": ["wall"]},
                "charts": [{"type": "bar"}],
            },
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "My weekly overview"
    assert body["kind"] == "preset"
    assert body["shared_with_project"] is False
    assert body["owner_id"] == str(user_a)


@pytest.mark.asyncio
async def test_create_with_shared_promotes_to_collection(
    client: AsyncClient, user_a: uuid.UUID, project_id: uuid.UUID,
) -> None:
    _set_acting_user(user_a)
    resp = await client.post(
        "/api/v1/dashboards/presets",
        json={
            "name": "Public dashboard",
            "kind": "preset",
            "project_id": str(project_id),
            "shared_with_project": True,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    # 'preset' + shared=True must auto-promote to 'collection'.
    assert body["kind"] == "collection"
    assert body["shared_with_project"] is True


@pytest.mark.asyncio
async def test_owner_lists_own_presets(
    client: AsyncClient, user_a: uuid.UUID, project_id: uuid.UUID,
) -> None:
    _set_acting_user(user_a)
    for name in ("First", "Second"):
        await client.post(
            "/api/v1/dashboards/presets",
            json={"name": name, "kind": "preset", "project_id": str(project_id)},
        )

    resp = await client.get(
        f"/api/v1/dashboards/presets?project_id={project_id}",
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    names = sorted(item["name"] for item in body["items"])
    assert names == ["First", "Second"]


@pytest.mark.asyncio
async def test_non_owner_only_sees_shared_collections(
    client: AsyncClient,
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    project_id: uuid.UUID,
) -> None:
    """User A creates one private + one shared collection on the project.
    User B (same project, same tenant) sees only the shared collection."""
    # Single tenant for both to share visibility.
    tenant = "shared-tenant"

    _set_acting_user(user_a, tenant_id=tenant)
    await client.post(
        "/api/v1/dashboards/presets",
        json={
            "name": "Private",
            "kind": "preset",
            "project_id": str(project_id),
        },
    )
    await client.post(
        "/api/v1/dashboards/presets",
        json={
            "name": "Public",
            "kind": "collection",
            "project_id": str(project_id),
            "shared_with_project": True,
        },
    )

    _set_acting_user(user_b, tenant_id=tenant)
    resp = await client.get(
        f"/api/v1/dashboards/presets?project_id={project_id}",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Public"


@pytest.mark.asyncio
async def test_get_other_users_private_preset_404s(
    client: AsyncClient, user_a: uuid.UUID, user_b: uuid.UUID,
    project_id: uuid.UUID,
) -> None:
    tenant = "shared-tenant"
    _set_acting_user(user_a, tenant_id=tenant)
    create = await client.post(
        "/api/v1/dashboards/presets",
        json={
            "name": "Mine",
            "kind": "preset",
            "project_id": str(project_id),
        },
    )
    pid = create.json()["id"]

    _set_acting_user(user_b, tenant_id=tenant)
    resp = await client.get(f"/api/v1/dashboards/presets/{pid}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_owner_can_patch_name(
    client: AsyncClient, user_a: uuid.UUID, project_id: uuid.UUID,
) -> None:
    _set_acting_user(user_a)
    create = await client.post(
        "/api/v1/dashboards/presets",
        json={"name": "Old name", "project_id": str(project_id)},
    )
    pid = create.json()["id"]

    resp = await client.patch(
        f"/api/v1/dashboards/presets/{pid}",
        json={"name": "New name"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "New name"


@pytest.mark.asyncio
async def test_non_owner_patch_forbidden(
    client: AsyncClient,
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    project_id: uuid.UUID,
) -> None:
    """Non-owner trying to patch a *visible* (shared) preset is 403,
    not 404 — once it's a public collection, the existence isn't the
    secret, the right to edit is.
    """
    tenant = "shared-tenant"
    _set_acting_user(user_a, tenant_id=tenant)
    create = await client.post(
        "/api/v1/dashboards/presets",
        json={
            "name": "Public",
            "kind": "collection",
            "project_id": str(project_id),
            "shared_with_project": True,
        },
    )
    pid = create.json()["id"]

    _set_acting_user(user_b, tenant_id=tenant)
    resp = await client.patch(
        f"/api/v1/dashboards/presets/{pid}",
        json={"name": "Hijacked"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_owner_can_delete(
    client: AsyncClient, user_a: uuid.UUID, project_id: uuid.UUID,
) -> None:
    _set_acting_user(user_a)
    create = await client.post(
        "/api/v1/dashboards/presets",
        json={"name": "Doomed", "project_id": str(project_id)},
    )
    pid = create.json()["id"]

    resp = await client.delete(f"/api/v1/dashboards/presets/{pid}")
    assert resp.status_code == 204

    # Reading after delete is a 404.
    resp_get = await client.get(f"/api/v1/dashboards/presets/{pid}")
    assert resp_get.status_code == 404


@pytest.mark.asyncio
async def test_share_endpoint_toggles_flag(
    client: AsyncClient, user_a: uuid.UUID, project_id: uuid.UUID,
) -> None:
    _set_acting_user(user_a)
    create = await client.post(
        "/api/v1/dashboards/presets",
        json={"name": "Toggle", "project_id": str(project_id)},
    )
    pid = create.json()["id"]
    assert create.json()["shared_with_project"] is False

    # Toggle on.
    resp1 = await client.post(f"/api/v1/dashboards/presets/{pid}/share")
    assert resp1.status_code == 200
    body1 = resp1.json()
    assert body1["shared_with_project"] is True
    assert body1["kind"] == "collection"

    # Toggle off.
    resp2 = await client.post(f"/api/v1/dashboards/presets/{pid}/share")
    assert resp2.status_code == 200
    assert resp2.json()["shared_with_project"] is False


@pytest.mark.asyncio
async def test_create_with_empty_name_rejected(
    client: AsyncClient, user_a: uuid.UUID, project_id: uuid.UUID,
) -> None:
    _set_acting_user(user_a)
    resp = await client.post(
        "/api/v1/dashboards/presets",
        json={"name": "", "project_id": str(project_id)},
    )
    # Pydantic catches min_length=1 → 422 at the FastAPI layer.
    assert resp.status_code == 422
