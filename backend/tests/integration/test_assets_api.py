"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for the Asset Operations API (/api/v1/assets).

Drives the full HTTP stack against create_app() so routing, permission
gating, project-access checks and serialization are all exercised. BIM
assets are seeded directly via ORM (the BIM upload pipeline is heavy and
out of scope here) and then read back through the public endpoints.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update as sa_update

from app.database import async_session_factory
from app.main import create_app
from app.modules.bim_hub.models import BIMElement, BIMModel
from app.modules.users.models import User


@pytest_asyncio.fixture
async def client():
    app = create_app()

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture
async def auth_headers(client):
    unique = uuid.uuid4().hex[:8]
    email = f"assets-{unique}@smoke.io"
    password = f"AssetsTest{unique}9!"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Assets Tester"},
    )
    assert reg.status_code == 201, reg.text
    async with async_session_factory() as session:
        await session.execute(sa_update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await session.commit()
    resp = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    token = resp.json().get("access_token", "")
    assert token, resp.text
    return {"Authorization": f"Bearer {token}"}


async def _create_project(client, headers) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={"name": "Assets Ops Project", "region": "DACH", "currency": "EUR"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _seed_bim(project_id: str) -> None:
    """Seed one model with a mix of tracked assets + a discoverable element."""
    async with async_session_factory() as session:
        model = BIMModel(project_id=uuid.UUID(project_id), name="Mechanical.rvt", status="ready")
        session.add(model)
        await session.flush()
        session.add_all(
            [
                BIMElement(
                    model_id=model.id,
                    stable_id="AHU-01",
                    element_type="Mechanical Equipment",
                    name="Rooftop AHU",
                    properties={"category": "Mechanical Equipment", "manufacturer": "Trane"},
                    asset_info={"warranty_until": "2020-01-01", "manufacturer": "Trane"},
                    is_tracked_asset=True,
                ),
                BIMElement(
                    model_id=model.id,
                    stable_id="PUMP-09",
                    element_type="Pump",
                    name="CW Pump",
                    properties={"category": "Mechanical Equipment"},
                    asset_info={"warranty_until": "2031-01-01"},
                    is_tracked_asset=True,
                ),
                # Discoverable candidate (not yet tracked).
                BIMElement(
                    model_id=model.id,
                    stable_id="FAN-02",
                    element_type="Mechanical Equipment",
                    name="Exhaust Fan",
                    properties={"category": "Mechanical Equipment", "manufacturer": "Greenheck"},
                    is_tracked_asset=False,
                ),
                # Pure geometry - never an asset.
                BIMElement(
                    model_id=model.id,
                    stable_id="WALL-01",
                    element_type="Walls",
                    name="Exterior Wall",
                    properties={"category": "Walls"},
                    is_tracked_asset=False,
                ),
            ]
        )
        await session.commit()


@pytest.mark.asyncio
async def test_portfolio_and_list_enriched(client, auth_headers):
    pid = await _create_project(client, auth_headers)
    await _seed_bim(pid)

    # Portfolio roll-up.
    resp = await client.get(f"/api/v1/assets/portfolio?project_id={pid}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    summary = resp.json()
    assert summary["total_assets"] == 2
    assert summary["warranties_expired"] == 1
    assert summary["needs_attention"] >= 1

    # Health-enriched list, worst first.
    resp = await client.get(f"/api/v1/assets/?project_id={pid}&sort=attention", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    assert body["items"][0]["stable_id"] == "AHU-01"
    assert body["items"][0]["health"]["warranty_status"] == "expired"


@pytest.mark.asyncio
async def test_warranty_status_filter(client, auth_headers):
    pid = await _create_project(client, auth_headers)
    await _seed_bim(pid)
    resp = await client.get(f"/api/v1/assets/?project_id={pid}&warranty_status=expired", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["stable_id"] == "AHU-01"


@pytest.mark.asyncio
async def test_discover_ranks_candidates(client, auth_headers):
    pid = await _create_project(client, auth_headers)
    await _seed_bim(pid)
    resp = await client.get(f"/api/v1/assets/discover?project_id={pid}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    stable_ids = {c["stable_id"] for c in body["items"]}
    assert "FAN-02" in stable_ids
    assert "WALL-01" not in stable_ids
    fan = next(c for c in body["items"] if c["stable_id"] == "FAN-02")
    assert fan["suggested_asset_info"].get("manufacturer") == "Greenheck"


@pytest.mark.asyncio
async def test_warranty_alerts_scan_only(client, auth_headers):
    pid = await _create_project(client, auth_headers)
    await _seed_bim(pid)
    resp = await client.post(
        f"/api/v1/assets/warranty-alerts?project_id={pid}",
        json={"lead_days": 90, "dispatch": False},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["dispatched"] is False
    assert body["items"][0]["status"] == "expired"


@pytest.mark.asyncio
async def test_service_log_append_roundtrip(client, auth_headers):
    pid = await _create_project(client, auth_headers)
    await _seed_bim(pid)
    # Find AHU-01 element id via the list endpoint.
    resp = await client.get(f"/api/v1/assets/?project_id={pid}", headers=auth_headers)
    items = resp.json()["items"]
    ahu = next(i for i in items if i["stable_id"] == "AHU-01")
    eid = ahu["id"]

    resp = await client.post(
        f"/api/v1/assets/{eid}/service-log",
        json={"date": "2026-06-01", "note": "Annual service", "kind": "service"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["service_log"]) == 1
    assert body["service_log"][0]["note"] == "Annual service"
    assert body["health"]["last_serviced"] == "2026-06-01"


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_cross_project_access_is_denied(client, auth_headers):
    # A random project id the user has no access to -> 404 (IDOR defence).
    bogus = uuid.uuid4()
    resp = await client.get(f"/api/v1/assets/portfolio?project_id={bogus}", headers=auth_headers)
    assert resp.status_code == 404
