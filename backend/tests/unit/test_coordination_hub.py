"""Baseline tests for the Coordination Hub aggregator (v4.2.0).

Covers:

* **KPI fetch happy-path** — ``GET /v1/coordination/projects/{pid}/dashboard``
  returns a 200 with the canonical ``CoordinationDashboardResponse``
  shape (federations / clashes / rule_packs / smart_views / bcf_activity /
  open_cost_impact_total) for a project owned by the caller. Sibling-
  module tables may be empty — the aggregator must still answer with
  honest zeros, never a 500.
* **Cross-user IDOR** — a second user hitting the same project's
  dashboard must see a 404 (per ``verify_project_access`` contract:
  leak no UUID existence).
* **Threshold seeding is gated by ``coordination.write``** — a VIEWER
  GET of ``/thresholds`` returns the defaults without inserting a DB
  row; an EDITOR GET *does* seed. Regression guard for the surgical
  fix in ``service.evaluate_thresholds(..., allow_seed=...)``.

Per ``feedback_test_isolation.md`` the module redirects ``DATABASE_URL``
to a fresh temp SQLite BEFORE any ``app`` import.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

# ── Per-module SQLite isolation (MUST run BEFORE app imports) ─────────────

_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-coord-hub-"))
_TMP_DB = _TMP_DIR / "coordination_hub.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_factory():
    """Boot the FastAPI app once per module against the temp SQLite."""
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
    """Insert a minimal user + project owned by that user.

    Returns ``(user_id, project_id)``.
    """
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        email=f"coord-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="Coord Tester",
        role="editor",
    )
    session.add(user)
    await session.flush()
    project = Project(name="Coord Test Project", owner_id=user.id)
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return user.id, project.id


def _override_payload(app, user_id: uuid.UUID, *, role: str, perms: list[str]) -> None:
    """Inject a fake JWT payload so the route's auth gates see the caller."""
    from app.dependencies import get_current_user_payload

    async def _payload() -> dict:
        return {
            "sub": str(user_id),
            "role": role,
            "permissions": list(perms),
        }

    app.dependency_overrides[get_current_user_payload] = _payload


# ── Tests ─────────────────────────────────────────────────────────────────


async def test_dashboard_happy_path_returns_canonical_shape(app_factory, db_session):
    """GET /dashboard returns 200 with the canonical KPI payload."""
    app = app_factory
    user_id, project_id = await _seed_user_and_project(db_session)
    _override_payload(app, user_id, role="editor", perms=["coordination.read"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/coordination/projects/{project_id}/dashboard")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Canonical top-level shape — every aggregator section is present
        # even when the sibling tables are empty (honest-zero contract).
        assert body["project_id"] == str(project_id)
        assert "currency" in body  # may be "" when project has no currency
        assert "as_of" in body
        for key in (
            "federations",
            "clashes",
            "rule_packs",
            "smart_views",
            "bcf_activity",
        ):
            assert key in body, f"missing section: {key}"
        # Each numeric default lands at zero.
        assert body["federations"]["count"] == 0
        assert body["clashes"]["open_count"] == 0
        assert body["bcf_activity"]["topics_exported_30d"] == 0
        assert body["open_cost_impact_total"] == 0.0
    finally:
        app.dependency_overrides.clear()


async def test_dashboard_blocks_cross_user_idor(app_factory, db_session):
    """A different user hitting the same project's dashboard sees 404."""
    app = app_factory
    _owner_id, project_id = await _seed_user_and_project(db_session)
    intruder_id = uuid.uuid4()  # not seeded, not the owner
    _override_payload(app, intruder_id, role="editor", perms=["coordination.read"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/coordination/projects/{project_id}/dashboard")
        # verify_project_access raises 404 (not 403) by design — no UUID
        # existence leak.
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


async def test_thresholds_get_does_not_seed_for_viewer(app_factory, db_session):
    """VIEWER GET of /thresholds returns defaults WITHOUT a DB write.

    Regression guard for the seed-on-GET privilege fix: a plain
    ``coordination.read`` caller must never trigger an insert into
    ``oe_coordination_threshold``.
    """
    from app.modules.coordination_hub.models import (
        DEFAULT_THRESHOLDS,
        CoordinationThreshold,
    )

    app = app_factory
    user_id, project_id = await _seed_user_and_project(db_session)
    _override_payload(app, user_id, role="viewer", perms=["coordination.read"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/coordination/projects/{project_id}/thresholds")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # The response itself is honest — every default metric is
        # surfaced so the UI can render an editable table.
        assert len(body["thresholds"]) == len(DEFAULT_THRESHOLDS)
        # But no row should have landed in the DB.
        rows = (
            (
                await db_session.execute(
                    select(CoordinationThreshold).where(CoordinationThreshold.project_id == project_id)
                )
            )
            .scalars()
            .all()
        )
        assert rows == [], f"VIEWER GET should NOT seed the threshold table; found {len(rows)} row(s)."
    finally:
        app.dependency_overrides.clear()


async def test_thresholds_get_seeds_for_editor(app_factory, db_session):
    """EDITOR GET of /thresholds seeds defaults (one row per metric)."""
    from app.modules.coordination_hub.models import (
        DEFAULT_THRESHOLDS,
        CoordinationThreshold,
    )

    app = app_factory
    user_id, project_id = await _seed_user_and_project(db_session)
    _override_payload(
        app,
        user_id,
        role="editor",
        perms=["coordination.read", "coordination.write"],
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/coordination/projects/{project_id}/thresholds")
        assert resp.status_code == 200, resp.text
        # Refresh: a new session sees the seed committed by the request.
        from app.database import async_session_factory

        async with async_session_factory() as fresh:
            rows = (
                (
                    await fresh.execute(
                        select(CoordinationThreshold).where(CoordinationThreshold.project_id == project_id)
                    )
                )
                .scalars()
                .all()
            )
        assert len(rows) == len(DEFAULT_THRESHOLDS)
    finally:
        app.dependency_overrides.clear()


# ── Pure unit: warn ≤ error validation ───────────────────────────────────


async def test_update_threshold_rejects_inverted_warn_error(app_factory, db_session):
    """update_threshold raises on warn > error (regression guard)."""
    from decimal import Decimal

    from app.modules.coordination_hub.service import CoordinationHubService

    _user_id, project_id = await _seed_user_and_project(db_session)
    svc = CoordinationHubService(db_session)
    with pytest.raises(ValueError, match="warn_value must be less than or equal"):
        await svc.update_threshold(
            project_id,
            "open_clashes_total",
            warn_value=Decimal("500"),
            error_value=Decimal("100"),
            enabled=None,
        )
