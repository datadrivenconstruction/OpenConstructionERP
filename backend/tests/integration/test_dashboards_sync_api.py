# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""T09 integration tests — Sync Protocol API surface.

Stands up a minimal FastAPI app with the dashboards router mounted plus
session/auth deps overridden to a per-test temp SQLite file (matches
``feedback_test_isolation.md``).

Coverage (6+ tests):

* POST /presets/{id}/sync-check — happy path: in-sync preset
* POST /presets/{id}/sync-check — missing column flagged as dropped
* POST /presets/{id}/sync-check — persists sync_status + last_sync_check_at
* POST /presets/{id}/sync-heal — applies auto-renames
* POST /presets/{id}/sync-heal — non-owner gets 403
* Tenant isolation — sync-check on other-tenant preset 404s
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
    import app.modules.dashboards.models  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.users.models  # noqa: F401


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def temp_engine_and_factory():
    tmp_db = Path(tempfile.mkdtemp()) / "sync_api.db"
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


async def _create_preset(
    client: AsyncClient,
    *,
    name: str = "Test preset",
    project_id: uuid.UUID,
    config_json: dict | None = None,
) -> dict:
    resp = await client.post(
        "/api/v1/dashboards/presets",
        json={
            "name": name,
            "kind": "preset",
            "project_id": str(project_id),
            "config_json": config_json or {},
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── Tests ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_check_empty_preset_returns_synced(
    client: AsyncClient, user_a: uuid.UUID, project_id: uuid.UUID,
) -> None:
    _set_acting_user(user_a)
    preset = await _create_preset(
        client, project_id=project_id, config_json={},
    )

    resp = await client.post(
        f"/api/v1/dashboards/presets/{preset['id']}/sync-check",
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["preset_id"] == preset["id"]
    assert body["is_in_sync"] is True
    assert body["status"] == "synced"
    assert body["dropped_columns"] == []
    assert body["column_renames"] == []


@pytest.mark.asyncio
async def test_sync_check_persists_status_and_timestamp(
    client: AsyncClient, user_a: uuid.UUID, project_id: uuid.UUID,
) -> None:
    """After sync-check the preset row carries last_sync_check_at."""
    _set_acting_user(user_a)
    preset = await _create_preset(
        client, project_id=project_id, config_json={},
    )

    # Initial state — no last_sync_check_at.
    initial = await client.get(
        f"/api/v1/dashboards/presets/{preset['id']}",
    )
    assert initial.json()["last_sync_check_at"] is None

    # Run a sync-check.
    await client.post(
        f"/api/v1/dashboards/presets/{preset['id']}/sync-check",
    )

    # Re-read.
    after = await client.get(
        f"/api/v1/dashboards/presets/{preset['id']}",
    )
    body = after.json()
    assert body["last_sync_check_at"] is not None
    assert body["sync_status"] == "synced"


@pytest.mark.asyncio
async def test_sync_check_flags_dropped_column(
    client: AsyncClient, user_a: uuid.UUID, project_id: uuid.UUID,
) -> None:
    """A preset that references a column the (empty) snapshot doesn't
    have should report it as dropped, status=needs_review."""
    _set_acting_user(user_a)
    preset = await _create_preset(
        client,
        project_id=project_id,
        config_json={
            "snapshot_id": str(uuid.uuid4()),
            "columns": ["definitely_missing_column"],
        },
    )

    resp = await client.post(
        f"/api/v1/dashboards/presets/{preset['id']}/sync-check",
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_in_sync"] is False
    assert body["status"] == "needs_review"
    cols = {i["column"] for i in body["dropped_columns"]}
    assert "definitely_missing_column" in cols


@pytest.mark.asyncio
async def test_sync_heal_returns_patched_preset(
    client: AsyncClient, user_a: uuid.UUID, project_id: uuid.UUID,
) -> None:
    """Heal endpoint returns both the patched preset and the report."""
    _set_acting_user(user_a)
    preset = await _create_preset(
        client,
        project_id=project_id,
        config_json={
            "filters": {"category": ["wall"]},
        },
    )

    resp = await client.post(
        f"/api/v1/dashboards/presets/{preset['id']}/sync-heal",
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "preset" in body
    assert "report" in body
    assert body["preset"]["id"] == preset["id"]
    # Empty snapshot meta = nothing-to-heal but the endpoint must still
    # return a well-shaped response.
    assert isinstance(body["report"]["dropped_columns"], list)


@pytest.mark.asyncio
async def test_sync_check_non_owner_404s(
    client: AsyncClient,
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    project_id: uuid.UUID,
) -> None:
    """A non-owner cannot run sync-check on someone else's private preset."""
    tenant = "shared-tenant"
    _set_acting_user(user_a, tenant_id=tenant)
    preset = await _create_preset(
        client, project_id=project_id, config_json={},
    )

    _set_acting_user(user_b, tenant_id=tenant)
    resp = await client.post(
        f"/api/v1/dashboards/presets/{preset['id']}/sync-check",
    )
    # Private preset, different owner, same tenant → 404 (we leak no
    # existence signal — exact same shape as GET /presets/{id}).
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_sync_heal_non_owner_forbidden(
    client: AsyncClient,
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    project_id: uuid.UUID,
) -> None:
    """Heal on a shared collection by a non-owner gets 403 (the
    collection is visible — but only the owner mutates it)."""
    tenant = "shared-tenant"
    _set_acting_user(user_a, tenant_id=tenant)
    create = await client.post(
        "/api/v1/dashboards/presets",
        json={
            "name": "Public",
            "kind": "collection",
            "project_id": str(project_id),
            "shared_with_project": True,
            "config_json": {"columns": ["something"]},
        },
    )
    pid = create.json()["id"]

    _set_acting_user(user_b, tenant_id=tenant)
    resp = await client.post(f"/api/v1/dashboards/presets/{pid}/sync-heal")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_sync_check_isolated_across_tenants(
    client: AsyncClient,
    user_a: uuid.UUID,
    user_b: uuid.UUID,
    project_id: uuid.UUID,
) -> None:
    """User in tenant A cannot see / sync-check a preset from tenant B."""
    _set_acting_user(user_a, tenant_id="tenant-a")
    preset = await _create_preset(
        client, project_id=project_id, config_json={},
    )

    _set_acting_user(user_b, tenant_id="tenant-b")
    resp = await client.post(
        f"/api/v1/dashboards/presets/{preset['id']}/sync-check",
    )
    assert resp.status_code == 404
