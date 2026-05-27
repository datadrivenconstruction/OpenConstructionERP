# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""HTTP integration tests for the Coordination Hub endpoints.

Covers:
    * GET /projects/{id}/dashboard      — happy path, 401, 404, 403-via-permission
    * GET /projects/{id}/trade-matrix   — happy path + empty
    * GET /projects/{id}/timeline       — happy path + window

Per ``feedback_test_isolation.md`` ``DATABASE_URL`` is redirected to a
per-module temp SQLite file BEFORE ``app`` is first imported (mirrors
``test_cost_endpoints.py``).
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (MUST run BEFORE app imports) ─────────────

_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-cohub-ep-"))
_TMP_DB = _TMP_DIR / "cohub.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

from datetime import UTC

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

# ── App / auth / project fixtures ─────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
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


@pytest_asyncio.fixture(scope="module")
async def client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _register_admin(client: AsyncClient) -> tuple[str, dict[str, str]]:
    """Register + promote a fresh admin user, return ``(user_id, header)``."""
    from tests.integration._auth_helpers import promote_to_admin

    tag = uuid.uuid4().hex[:8]
    email = f"cohub-{tag}@test.io"
    password = f"CoHubTest{tag}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": f"CoHub Tester {tag}",
            "role": "admin",
        },
    )
    assert reg.status_code in (200, 201), reg.text
    await promote_to_admin(email)
    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    token = login.json().get("access_token", "")
    assert token, login.text
    return reg.json()["id"], {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="module")
async def auth_pair(client: AsyncClient) -> tuple[str, dict[str, str]]:
    return await _register_admin(client)


@pytest_asyncio.fixture(scope="module")
async def auth(auth_pair: tuple[str, dict[str, str]]) -> dict[str, str]:
    return auth_pair[1]


@pytest_asyncio.fixture(scope="module")
async def project_id(client: AsyncClient, auth: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": "Coordination Hub Endpoints",
            "description": "endpoints",
        },
        headers=auth,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


# ── Seeding helpers ───────────────────────────────────────────────────────


async def _seed_clash(
    project_id_: str,
    *,
    a_disc: str = "Architectural",
    b_disc: str = "Structural",
    status_: str = "new",
) -> str:
    """Seed one ClashRun + one ClashResult; return the clash row id."""
    from app.database import async_session_factory
    from app.modules.clash.models import ClashResult, ClashRun

    async with async_session_factory() as session:
        run = ClashRun(
            project_id=uuid.UUID(project_id_),
            name="EP Run",
            model_ids=[str(uuid.uuid4())],
            status="completed",
            created_by=str(uuid.uuid4()),
        )
        session.add(run)
        await session.flush()
        clash = ClashResult(
            run_id=run.id,
            a_element_id=uuid.uuid4(),
            b_element_id=uuid.uuid4(),
            a_stable_id=f"A-{uuid.uuid4().hex[:6]}",
            b_stable_id=f"B-{uuid.uuid4().hex[:6]}",
            a_name="a",
            b_name="b",
            a_discipline=a_disc,
            b_discipline=b_disc,
            a_model_id=uuid.uuid4(),
            b_model_id=uuid.uuid4(),
            clash_type="hard",
            penetration_m=0.05,
            distance_m=0.0,
            cx=0.0,
            cy=0.0,
            cz=0.0,
            status=status_,
            severity="medium",
            signature=uuid.uuid4().hex[:16],
        )
        session.add(clash)
        await session.commit()
        return str(clash.id)


async def _seed_federation(project_id_: str, name: str = "Fed A") -> str:
    from app.database import async_session_factory
    from app.modules.bim_hub.models import BIMFederation

    async with async_session_factory() as session:
        fed = BIMFederation(
            project_id=uuid.UUID(project_id_),
            name=name,
            origin_offset={"x": 0, "y": 0, "z": 0},
            shared_units="m",
        )
        session.add(fed)
        await session.commit()
        return str(fed.id)


def _invalidate_cache() -> None:
    """Drop the in-memory dashboard cache between tests."""
    from app.modules.coordination_hub.service import (
        CoordinationHubService,
    )

    CoordinationHubService.invalidate_cache()


# ── Endpoint tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dashboard_returns_200_with_zero_when_empty(client: AsyncClient, auth: dict[str, str], project_id: str):
    _invalidate_cache()
    resp = await client.get(
        f"/api/v1/coordination/projects/{project_id}/dashboard",
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["project_id"] == project_id
    assert body["currency"] == "EUR"
    assert body["federations"]["count"] == 0
    assert body["clashes"]["open_count"] == 0
    assert body["clashes"]["resolved_count"] == 0
    # v3 §10 — money is Decimal-as-string on the JSON wire.
    assert body["open_cost_impact_total"] == "0"


@pytest.mark.asyncio
async def test_dashboard_counts_federations_correctly(client: AsyncClient, auth: dict[str, str], project_id: str):
    _invalidate_cache()
    await _seed_federation(project_id, name="Fed F1")
    await _seed_federation(project_id, name="Fed F2")
    resp = await client.get(
        f"/api/v1/coordination/projects/{project_id}/dashboard",
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["federations"]["count"] >= 2


@pytest.mark.asyncio
async def test_dashboard_counts_open_vs_resolved_clashes(client: AsyncClient, auth: dict[str, str], project_id: str):
    _invalidate_cache()
    await _seed_clash(project_id, status_="new")
    await _seed_clash(project_id, status_="resolved")
    resp = await client.get(
        f"/api/v1/coordination/projects/{project_id}/dashboard",
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # At least one open + one resolved must show up.
    assert body["clashes"]["open_count"] >= 1
    assert body["clashes"]["resolved_count"] >= 1


@pytest.mark.asyncio
async def test_dashboard_currency_comes_from_project(client: AsyncClient, auth: dict[str, str], project_id: str):
    """Edit project currency → next dashboard call surfaces the change."""
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.projects.models import Project

    async with async_session_factory() as session:
        await session.execute(update(Project).where(Project.id == uuid.UUID(project_id)).values(currency="USD"))
        await session.commit()
    _invalidate_cache()
    resp = await client.get(
        f"/api/v1/coordination/projects/{project_id}/dashboard",
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["currency"] == "USD"

    # Restore for downstream tests.
    async with async_session_factory() as session:
        await session.execute(update(Project).where(Project.id == uuid.UUID(project_id)).values(currency="EUR"))
        await session.commit()
    _invalidate_cache()


@pytest.mark.asyncio
async def test_dashboard_404_when_project_missing(client: AsyncClient, auth: dict[str, str]):
    bogus = uuid.uuid4()
    resp = await client.get(
        f"/api/v1/coordination/projects/{bogus}/dashboard",
        headers=auth,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_dashboard_401_when_unauthenticated(client: AsyncClient, project_id: str):
    resp = await client.get(f"/api/v1/coordination/projects/{project_id}/dashboard")
    # Unauthed → 401 from the auth layer.
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_dashboard_blocks_other_users_project(client: AsyncClient, project_id: str):
    """A different VIEWER without admin can't reach this project."""
    # Register a plain viewer (post-promote intentionally skipped).
    tag = uuid.uuid4().hex[:8]
    email = f"cohub-viewer-{tag}@test.io"
    password = f"ViewerPW{tag}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "Viewer",
            "role": "viewer",
        },
    )
    assert reg.status_code in (200, 201), reg.text
    # Promote them to active=True but keep them VIEWER (not admin).
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as session:
        await session.execute(update(User).where(User.email == email).values(is_active=True))
        await session.commit()
    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    token = login.json().get("access_token", "")
    assert token, login.text
    viewer_auth = {"Authorization": f"Bearer {token}"}
    resp = await client.get(
        f"/api/v1/coordination/projects/{project_id}/dashboard",
        headers=viewer_auth,
    )
    # verify_project_access returns 404 (no leak) when not owner +
    # not admin. Either 403 (permission denied) or 404 is acceptable —
    # both deny access without leaking project existence.
    assert resp.status_code in (403, 404)


@pytest.mark.asyncio
async def test_dashboard_last_run_at_set_after_clash_run(client: AsyncClient, auth: dict[str, str], project_id: str):
    """``clashes.last_run_at`` is non-null once a completed run exists."""
    _invalidate_cache()
    from datetime import datetime

    from app.database import async_session_factory
    from app.modules.clash.models import ClashRun

    async with async_session_factory() as session:
        run = ClashRun(
            project_id=uuid.UUID(project_id),
            name="Completed run",
            model_ids=[],
            status="completed",
            created_by=str(uuid.uuid4()),
            completed_at=datetime.now(UTC),
        )
        session.add(run)
        await session.commit()
    resp = await client.get(
        f"/api/v1/coordination/projects/{project_id}/dashboard",
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["clashes"]["last_run_at"] is not None


@pytest.mark.asyncio
async def test_trade_matrix_endpoint_returns_cells(client: AsyncClient, auth: dict[str, str], project_id: str):
    _invalidate_cache()
    await _seed_clash(project_id, a_disc="Architectural", b_disc="Structural")
    await _seed_clash(project_id, a_disc="Mechanical", b_disc="Structural")
    resp = await client.get(
        f"/api/v1/coordination/projects/{project_id}/trade-matrix",
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["project_id"] == project_id
    assert "trades" in body
    assert len(body["trades"]) == 6
    # Cells include at least one (arch, struct) entry.
    pairs = {(c["row"], c["col"]) for c in body["cells"]}
    assert any((r, c) in pairs for r, c in [("arch", "struct"), ("mep", "struct")])


@pytest.mark.asyncio
async def test_timeline_endpoint_returns_events(client: AsyncClient, auth: dict[str, str], project_id: str):
    _invalidate_cache()
    await _seed_federation(project_id, name="Timeline Fed")
    resp = await client.get(
        f"/api/v1/coordination/projects/{project_id}/timeline",
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["project_id"] == project_id
    assert isinstance(body["events"], list)
    # Federation-created events surface within the default window.
    assert any(e["type"] == "federation_created" for e in body["events"])


@pytest.mark.asyncio
async def test_timeline_endpoint_validates_days(client: AsyncClient, auth: dict[str, str], project_id: str):
    """``days=0`` is rejected (ge=1)."""
    resp = await client.get(
        f"/api/v1/coordination/projects/{project_id}/timeline?days=0",
        headers=auth,
    )
    assert resp.status_code == 422
