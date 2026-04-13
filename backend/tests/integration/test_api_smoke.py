"""Integration smoke tests — verify critical API paths work end-to-end.

Tests the full stack: HTTP → Router → Service → Repository → SQLite.
Uses the FastAPI test client with an in-memory SQLite database.

Run: pytest tests/integration/test_api_smoke.py -v
"""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture
async def client():
    """Create a test client with app lifecycle (startup/shutdown) triggered."""
    app = create_app()

    # Trigger startup events so modules load and tables are created
    from contextlib import asynccontextmanager

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
    """Get auth headers — registers + logs in a test user."""
    # Register
    await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": "test@smoke.io",
            "password": "testtest123",
            "full_name": "Smoke Tester",
        },
    )
    # Login
    resp = await client.post(
        "/api/v1/users/auth/login",
        json={"email": "test@smoke.io", "password": "testtest123"},
    )
    token = resp.json().get("access_token", "")
    return {"Authorization": f"Bearer {token}"}


# ── Health ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"


@pytest.mark.asyncio
async def test_system_status(client):
    resp = await client.get("/api/system/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "api" in data
    assert "database" in data
    assert "vector_db" in data


# ── Auth ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_register_and_login(client):
    import uuid

    unique_email = f"auth-{uuid.uuid4().hex[:6]}@smoke.io"
    # Use a password that survives v0.8.0 strong-password policy:
    # 8+ chars, has letters, has digits, not in the common-password blacklist.
    test_password = f"SmokeTest{uuid.uuid4().hex[:6]}9"
    resp = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": unique_email,
            "password": test_password,
            "full_name": "Auth User",
        },
    )
    assert resp.status_code == 201
    user = resp.json()
    assert user["email"] == unique_email

    resp = await client.post(
        "/api/v1/users/auth/login",
        json={"email": unique_email, "password": test_password},
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()


# ── Projects ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_project_crud(client, auth_headers):
    headers = auth_headers

    # Create
    resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": "Smoke Test Project",
            "description": "Integration test",
            "region": "DACH",
            "classification_standard": "din276",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert resp.status_code == 201
    project = resp.json()
    pid = project["id"]

    # List
    resp = await client.get("/api/v1/projects/", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) >= 1

    # Get
    resp = await client.get(f"/api/v1/projects/{pid}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "Smoke Test Project"


# ── BOQ ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_boq_full_workflow(client, auth_headers):
    headers = auth_headers

    # Create project
    resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": "BOQ Test",
            "region": "UK",
            "classification_standard": "nrm",
            "currency": "GBP",
        },
        headers=headers,
    )
    pid = resp.json()["id"]

    # Create BOQ
    resp = await client.post(
        "/api/v1/boq/boqs/",
        json={"project_id": pid, "name": "Test Estimate"},
        headers=headers,
    )
    assert resp.status_code == 201
    boq = resp.json()
    bid = boq["id"]

    # Add section
    resp = await client.post(
        f"/api/v1/boq/boqs/{bid}/sections/",
        json={"ordinal": "01", "description": "Substructure"},
        headers=headers,
    )
    assert resp.status_code == 201
    section = resp.json()
    sid = section["id"]

    # Add position
    resp = await client.post(
        f"/api/v1/boq/boqs/{bid}/positions/",
        json={
            "boq_id": bid,
            "ordinal": "01.001",
            "description": "Concrete foundation",
            "unit": "m3",
            "quantity": 150,
            "unit_rate": 285.00,
            "parent_id": sid,
        },
        headers=headers,
    )
    assert resp.status_code == 201
    pos = resp.json()
    assert float(pos["total"]) == 42750.0

    # Get BOQ with positions
    resp = await client.get(f"/api/v1/boq/boqs/{bid}", headers=headers)
    assert resp.status_code == 200
    full = resp.json()
    assert len(full["positions"]) >= 2  # section + position

    # Duplicate
    resp = await client.post(f"/api/v1/boq/boqs/{bid}/duplicate/", json={}, headers=headers)
    assert resp.status_code == 201
    dup = resp.json()
    assert dup["id"] != bid
    assert "Copy" in dup["name"]


# ── Costs ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cost_search(client, auth_headers):
    resp = await client.get("/api/v1/costs/?limit=5", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data


@pytest.mark.asyncio
async def test_cost_search_requires_auth(client):
    """Cost search should return 401 without authentication."""
    resp = await client.get("/api/v1/costs/?limit=5")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_cost_regions(client, auth_headers):
    resp = await client.get("/api/v1/costs/regions/", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_vector_status(client, auth_headers):
    resp = await client.get("/api/v1/costs/vector/status/", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "connected" in data
    assert "engine" in data


# ── Tendering ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tendering_packages(client, auth_headers):
    headers = auth_headers

    # The tendering packages list endpoint requires a project_id
    # query param to prevent cross-tenant enumeration (added in
    # v1.4.x security pass).  Create a throwaway project first.
    proj_resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": "TenderingSmoke",
            "region": "DACH",
            "classification_standard": "din276",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert proj_resp.status_code == 201
    pid = proj_resp.json()["id"]

    resp = await client.get(
        f"/api/v1/tendering/packages/?project_id={pid}", headers=headers
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── Schedule ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_schedule_crud(client, auth_headers):
    headers = auth_headers

    # Create project
    resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": "Schedule Test",
            "region": "DACH",
            "classification_standard": "din276",
            "currency": "EUR",
        },
        headers=headers,
    )
    pid = resp.json()["id"]

    # Create schedule
    resp = await client.post(
        "/api/v1/schedule/schedules/",
        json={
            "project_id": pid,
            "name": "Main Schedule",
            "start_date": "2026-04-01",
            "end_date": "2027-04-01",
        },
        headers=headers,
    )
    assert resp.status_code == 201
    schedule = resp.json()
    assert schedule["name"] == "Main Schedule"
