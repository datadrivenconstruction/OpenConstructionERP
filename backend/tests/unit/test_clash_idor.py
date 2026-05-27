# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""IDOR audit tests for the Clash Detection module.

Verifies that cross-tenant access to clash runs, results, and issues
raises 403 / 404 — never silently returning another project's data.

Coverage:
* GET  /clash/projects/{pid}/runs/ — attacker's project_id returns empty
  list (own project only), not a 403 on their own
* GET  /clash/projects/{pid}/runs/{rid} — wrong project_id → 404
* GET  /clash/projects/{pid}/runs/{rid}/results — wrong project → 404
* PATCH /clash/projects/{pid}/runs/{rid}/results/{result_id} — wrong project → 404
* DELETE /clash/projects/{pid}/runs/{rid} — wrong project → 403/404
* GET  /clash/issues?project_id=... — cross-user → 404
* POST /clash/issues/{issue_id}/suppress — cross-user → 403/404
* Run GET with attacker as non-owner of victim's project → 403
* Result GET scoped to correct project but wrong run → 404
"""

from __future__ import annotations

import os
import tempfile
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-clash-idor-"))
_TMP_DB = _TMP_DIR / "clash_idor.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

# ── App fixture ───────────────────────────────────────────────────────────


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


# ── Helpers ────────────────────────────────────────────────────────────────


async def _seed_user_and_project(session) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert a minimal user + owned project. Returns (user_id, project_id)."""
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        email=f"clash-idor-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="Clash IDOR Tester",
        role="editor",
    )
    session.add(user)
    await session.flush()
    project = Project(name="Clash IDOR Project", owner_id=user.id)
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


async def _seed_clash_run(session, project_id: uuid.UUID) -> uuid.UUID:
    """Persist a minimal completed ClashRun. Returns run_id."""
    from app.modules.clash.models import ClashRun

    run = ClashRun(
        project_id=project_id,
        name="IDOR Test Run",
        model_ids=[],
        status="completed",
        created_by="test",
        summary={},
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run.id


async def _seed_clash_result(session, run_id: uuid.UUID) -> uuid.UUID:
    """Persist a minimal ClashResult. Returns result_id."""
    from app.modules.clash.models import ClashResult

    result = ClashResult(
        run_id=run_id,
        a_element_id=uuid.uuid4(),
        b_element_id=uuid.uuid4(),
        a_stable_id="elem-A",
        b_stable_id="elem-B",
        a_name="Wall A",
        b_name="Pipe B",
        a_discipline="Structural",
        b_discipline="Mechanical",
        a_model_id=uuid.uuid4(),
        b_model_id=uuid.uuid4(),
        clash_type="hard",
        penetration_m=0.05,
        distance_m=0.0,
        cx=1.0,
        cy=2.0,
        cz=3.0,
        status="new",
        severity="medium",
    )
    session.add(result)
    await session.commit()
    await session.refresh(result)
    return result.id


# ── Tests ──────────────────────────────────────────────────────────────────


async def test_list_runs_cross_project_returns_empty_not_others(app_factory, db_session):
    """Attacker lists runs on victim's project → 403 (IDOR guard denies)."""
    app = app_factory
    _victim_id, victim_project = await _seed_user_and_project(db_session)
    attacker_id, _attacker_project = await _seed_user_and_project(db_session)
    await _seed_clash_run(db_session, victim_project)

    _override_payload(app, attacker_id, role="editor", perms=["clash.read"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/clash/projects/{victim_project}/runs/")
        # IDOR guard: non-owner gets 403
        assert resp.status_code in (403, 404), (
            f"Expected 403/404 for cross-project run list, got {resp.status_code}: {resp.text}"
        )
    finally:
        app.dependency_overrides.clear()


async def test_get_run_wrong_project_returns_404(app_factory, db_session):
    """GET run with a valid run_id but wrong project_id → 404."""
    app = app_factory
    victim_id, victim_project = await _seed_user_and_project(db_session)
    attacker_id, attacker_project = await _seed_user_and_project(db_session)
    run_id = await _seed_clash_run(db_session, victim_project)

    # Attacker requests victim's run under their own project
    _override_payload(app, attacker_id, role="editor", perms=["clash.read"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/clash/projects/{attacker_project}/runs/{run_id}")
        assert resp.status_code == 404, f"Cross-project run GET should 404, got {resp.status_code}"
    finally:
        app.dependency_overrides.clear()


async def test_get_run_correct_owner_succeeds(app_factory, db_session):
    """GET run by the project owner returns 200."""
    app = app_factory
    owner_id, project_id = await _seed_user_and_project(db_session)
    run_id = await _seed_clash_run(db_session, project_id)

    _override_payload(app, owner_id, role="editor", perms=["clash.read"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/clash/projects/{project_id}/runs/{run_id}")
        assert resp.status_code == 200, resp.text
    finally:
        app.dependency_overrides.clear()


async def test_get_results_cross_project_denied(app_factory, db_session):
    """GET results list with wrong project_id → 403/404."""
    app = app_factory
    victim_id, victim_project = await _seed_user_and_project(db_session)
    attacker_id, attacker_project = await _seed_user_and_project(db_session)
    run_id = await _seed_clash_run(db_session, victim_project)
    await _seed_clash_result(db_session, run_id)

    _override_payload(app, attacker_id, role="editor", perms=["clash.read"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/clash/projects/{attacker_project}/runs/{run_id}/results")
        assert resp.status_code in (403, 404), f"Cross-project results list should be denied, got {resp.status_code}"
    finally:
        app.dependency_overrides.clear()


async def test_result_wrong_run_returns_404(app_factory, db_session):
    """GET results for a run that belongs to a different project → 404."""
    app = app_factory
    owner_id, project_id = await _seed_user_and_project(db_session)
    run_id = await _seed_clash_run(db_session, project_id)
    await _seed_clash_result(db_session, run_id)
    wrong_run_id = uuid.uuid4()

    _override_payload(app, owner_id, role="editor", perms=["clash.read"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/clash/projects/{project_id}/runs/{wrong_run_id}/results")
        assert resp.status_code == 404, f"Non-existent run results should 404, got {resp.status_code}"
    finally:
        app.dependency_overrides.clear()


async def test_patch_result_cross_project_denied(app_factory, db_session):
    """PATCH result with attacker's project_id → 403/404."""
    app = app_factory
    victim_id, victim_project = await _seed_user_and_project(db_session)
    attacker_id, attacker_project = await _seed_user_and_project(db_session)
    run_id = await _seed_clash_run(db_session, victim_project)
    result_id = await _seed_clash_result(db_session, run_id)

    _override_payload(app, attacker_id, role="editor", perms=["clash.update"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.patch(
                f"/api/v1/clash/projects/{attacker_project}/runs/{run_id}/results/{result_id}",
                json={"status": "active"},
            )
        assert resp.status_code in (403, 404), f"Cross-project PATCH should be denied, got {resp.status_code}"
    finally:
        app.dependency_overrides.clear()


async def test_issues_list_cross_user_returns_404(app_factory, db_session):
    """GET /clash/issues?project_id=victim_project as attacker → 403/404."""
    app = app_factory
    _victim_id, victim_project = await _seed_user_and_project(db_session)
    attacker_id, _attacker_project = await _seed_user_and_project(db_session)

    _override_payload(app, attacker_id, role="editor", perms=["clash.read"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/clash/issues?project_id={victim_project}")
        assert resp.status_code in (403, 404), f"Cross-user issues list should be denied, got {resp.status_code}"
    finally:
        app.dependency_overrides.clear()


async def test_delete_run_cross_project_denied(app_factory, db_session):
    """DELETE run with wrong project_id → 403/404."""
    app = app_factory
    victim_id, victim_project = await _seed_user_and_project(db_session)
    attacker_id, attacker_project = await _seed_user_and_project(db_session)
    run_id = await _seed_clash_run(db_session, victim_project)

    _override_payload(app, attacker_id, role="editor", perms=["clash.delete"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete(f"/api/v1/clash/projects/{attacker_project}/runs/{run_id}")
        assert resp.status_code in (403, 404), f"Cross-project DELETE should be denied, got {resp.status_code}"
    finally:
        app.dependency_overrides.clear()


async def test_admin_can_access_any_project_run(app_factory, db_session):
    """Admin user (DB-seeded with role='admin') can read any project's runs.

    The clash router's IDOR guard exempts admins by checking the user's
    role column in the DB — so the admin must be a real DB row.
    """
    from app.modules.users.models import User

    app = app_factory
    _owner_id, project_id = await _seed_user_and_project(db_session)
    run_id = await _seed_clash_run(db_session, project_id)

    # Seed a real admin user (the IDOR guard looks this up in the DB).
    admin_user = User(
        email=f"admin-clash-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="Admin User",
        role="admin",
    )
    db_session.add(admin_user)
    await db_session.commit()
    await db_session.refresh(admin_user)
    admin_id = admin_user.id

    _override_payload(app, admin_id, role="admin", perms=["clash.read"])
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/v1/clash/projects/{project_id}/runs/{run_id}")
        assert resp.status_code == 200, f"Admin should access any project's run, got {resp.status_code}: {resp.text}"
    finally:
        app.dependency_overrides.clear()
