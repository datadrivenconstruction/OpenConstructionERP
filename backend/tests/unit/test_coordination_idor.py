# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""IDOR audit tests for the Coordination Hub module.

Verifies that cross-tenant requests to coordination dashboard, thresholds,
trade-matrix, and timeline endpoints are denied (404 per
verify_project_access contract — no UUID existence leak).

Coverage:
* GET /coordination/projects/{pid}/dashboard — attacker → 404
* GET /coordination/projects/{pid}/trade-matrix — attacker → 404
* GET /coordination/projects/{pid}/timeline — attacker → 404
* GET /coordination/projects/{pid}/thresholds — attacker → 404
* PUT /coordination/projects/{pid}/thresholds/{metric} — attacker → 404
* Owner of a different project → 404 (wrong project)
* Admin → 200 (exempt from IDOR guard)
"""

from __future__ import annotations

import os
import tempfile
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-coord-idor-"))
_TMP_DB = _TMP_DIR / "coord_idor.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402


@pytest_asyncio.fixture(scope="module")
async def app_factory():
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield app


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    from app.database import async_session_factory

    async with async_session_factory() as session:
        yield session


async def _seed_user_and_project(session) -> tuple[uuid.UUID, uuid.UUID]:
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        email=f"coord-idor-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="Coord IDOR Tester",
        role="editor",
    )
    session.add(user)
    await session.flush()
    project = Project(name="Coord IDOR Project", owner_id=user.id)
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return user.id, project.id


def _override_payload(
    app,
    user_id: uuid.UUID,
    *,
    role: str = "editor",
    perms: list[str] | None = None,
) -> None:
    from app.dependencies import get_current_user_payload

    async def _payload() -> dict:
        return {
            "sub": str(user_id),
            "role": role,
            "permissions": list(perms or []),
        }

    app.dependency_overrides[get_current_user_payload] = _payload


# ── Dashboard IDOR ─────────────────────────────────────────────────────────


async def test_dashboard_cross_user_returns_404(app_factory, db_session):
    """Non-owner GET /coordination/projects/{pid}/dashboard → 404."""
    app = app_factory
    _owner_id, victim_project = await _seed_user_and_project(db_session)
    attacker_id, _attacker_project = await _seed_user_and_project(db_session)

    _override_payload(app, attacker_id, role="editor", perms=["coordination.read"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/coordination/projects/{victim_project}/dashboard")
        assert resp.status_code == 404, f"Expected 404 for cross-project dashboard, got {resp.status_code}: {resp.text}"
    finally:
        app.dependency_overrides.clear()


async def test_dashboard_owner_succeeds(app_factory, db_session):
    """Project owner GET /coordination/projects/{pid}/dashboard → 200."""
    app = app_factory
    owner_id, project_id = await _seed_user_and_project(db_session)

    _override_payload(app, owner_id, role="editor", perms=["coordination.read"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/coordination/projects/{project_id}/dashboard")
        assert resp.status_code == 200, resp.text
    finally:
        app.dependency_overrides.clear()


# ── Trade-matrix IDOR ──────────────────────────────────────────────────────


async def test_trade_matrix_cross_user_returns_404(app_factory, db_session):
    """Non-owner GET /coordination/projects/{pid}/trade-matrix → 404."""
    app = app_factory
    _owner_id, victim_project = await _seed_user_and_project(db_session)
    attacker_id, _ = await _seed_user_and_project(db_session)

    _override_payload(app, attacker_id, role="editor", perms=["coordination.read"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/coordination/projects/{victim_project}/trade-matrix")
        assert resp.status_code == 404, f"Expected 404 for cross-project trade-matrix, got {resp.status_code}"
    finally:
        app.dependency_overrides.clear()


# ── Timeline IDOR ──────────────────────────────────────────────────────────


async def test_timeline_cross_user_returns_404(app_factory, db_session):
    """Non-owner GET /coordination/projects/{pid}/timeline → 404."""
    app = app_factory
    _owner_id, victim_project = await _seed_user_and_project(db_session)
    attacker_id, _ = await _seed_user_and_project(db_session)

    _override_payload(app, attacker_id, role="editor", perms=["coordination.read"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/coordination/projects/{victim_project}/timeline")
        assert resp.status_code == 404, f"Expected 404 for cross-project timeline, got {resp.status_code}"
    finally:
        app.dependency_overrides.clear()


# ── Thresholds IDOR ────────────────────────────────────────────────────────


async def test_thresholds_get_cross_user_returns_404(app_factory, db_session):
    """Non-owner GET /coordination/projects/{pid}/thresholds → 404."""
    app = app_factory
    _owner_id, victim_project = await _seed_user_and_project(db_session)
    attacker_id, _ = await _seed_user_and_project(db_session)

    _override_payload(app, attacker_id, role="editor", perms=["coordination.read"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/coordination/projects/{victim_project}/thresholds")
        assert resp.status_code == 404, f"Expected 404 for cross-project thresholds GET, got {resp.status_code}"
    finally:
        app.dependency_overrides.clear()


async def test_thresholds_put_cross_user_returns_404(app_factory, db_session):
    """Non-owner PUT /coordination/projects/{pid}/thresholds/{metric} → 404."""
    app = app_factory
    _owner_id, victim_project = await _seed_user_and_project(db_session)
    attacker_id, _ = await _seed_user_and_project(db_session)

    _override_payload(
        app,
        attacker_id,
        role="editor",
        perms=["coordination.read", "coordination.write"],
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                f"/api/v1/coordination/projects/{victim_project}/thresholds/open_clashes_total",
                json={"warn_value": "100", "error_value": "200", "enabled": True},
            )
        assert resp.status_code == 404, f"Expected 404 for cross-project thresholds PUT, got {resp.status_code}"
    finally:
        app.dependency_overrides.clear()


# ── Admin exemption ────────────────────────────────────────────────────────


async def test_admin_can_access_any_project_dashboard(app_factory, db_session):
    """Admin (DB-seeded with role='admin') GET /coordination/dashboard → 200.

    verify_project_access exempts admins by checking the role column in the DB,
    so the admin user must be a real DB row.
    """
    from app.modules.users.models import User

    app = app_factory
    _owner_id, project_id = await _seed_user_and_project(db_session)

    admin_user = User(
        email=f"admin-coord-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="Admin Coord User",
        role="admin",
    )
    db_session.add(admin_user)
    await db_session.commit()
    await db_session.refresh(admin_user)

    _override_payload(app, admin_user.id, role="admin", perms=["coordination.read"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/coordination/projects/{project_id}/dashboard")
        assert resp.status_code == 200, (
            f"Admin should access any project dashboard, got {resp.status_code}: {resp.text}"
        )
    finally:
        app.dependency_overrides.clear()
