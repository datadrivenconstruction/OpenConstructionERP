"""Issue #79 — Position ↔ CostItem linkage on create/update.

Covers:

* Creating a Position with ``source='cwicr'`` and a valid ``cost_item_id``
  persists the linkage and round-trips it on GET.
* An unknown / inactive ``cost_item_id`` is rejected with 422.
* Patching ``cost_item_id`` onto an existing Position re-links it without
  losing other metadata fields.

Run:
    cd backend
    python -m pytest tests/integration/test_boq_cost_item_link.py -v --tb=short
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


# ── Shared fixtures (module-scoped — same pattern as other BOQ integration tests) ──


@pytest_asyncio.fixture(scope="module")
async def shared_client() -> AsyncClient:
    """Module-scoped client with full app lifecycle."""
    app = create_app()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture(scope="module")
async def shared_auth(shared_client: AsyncClient) -> dict[str, str]:
    """Module-scoped auth: register + force-promote-to-admin + login."""
    unique = uuid.uuid4().hex[:8]
    email = f"boqcost-{unique}@test.io"
    password = f"BoqCost{unique}9!"

    reg = await shared_client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "BOQ Cost Linkage Tester",
            "role": "admin",
        },
    )
    assert reg.status_code == 201, f"Registration failed: {reg.text}"

    # Promote to admin so we have the costs.create + boq.update perms.
    from sqlalchemy import update as sa_update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as session:
        await session.execute(
            sa_update(User)
            .where(User.email == email.lower())
            .values(role="admin", is_active=True)
        )
        await session.commit()

    token = ""
    for attempt in range(3):
        resp = await shared_client.post(
            "/api/v1/users/auth/login",
            json={"email": email, "password": password},
        )
        data = resp.json()
        token = data.get("access_token", "")
        if token:
            break
        if "Too many login attempts" in data.get("detail", ""):
            await asyncio.sleep(5 * (attempt + 1))
            continue
        break
    assert token, f"Login failed: {data}"
    return {"Authorization": f"Bearer {token}"}


# ── Per-module helpers ────────────────────────────────────────────────────────


async def _create_project(client: AsyncClient, auth: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"CostLink Test {uuid.uuid4().hex[:6]}",
            "description": "Issue #79 integration",
            "region": "DACH",
            "classification_standard": "din276",
            "currency": "EUR",
        },
        headers=auth,
    )
    assert resp.status_code == 201, f"Create project failed: {resp.text}"
    return resp.json()["id"]


async def _create_boq(client: AsyncClient, auth: dict[str, str], project_id: str) -> str:
    resp = await client.post(
        "/api/v1/boq/boqs/",
        json={
            "project_id": project_id,
            "name": f"CostLink BOQ {uuid.uuid4().hex[:6]}",
            "description": "Issue #79 integration",
        },
        headers=auth,
    )
    assert resp.status_code == 201, f"Create BOQ failed: {resp.text}"
    return resp.json()["id"]


async def _create_cost_item(client: AsyncClient, auth: dict[str, str]) -> str:
    """Create a fresh CostItem and return its UUID."""
    code = f"OE-79-{uuid.uuid4().hex[:8]}"
    resp = await client.post(
        "/api/v1/costs/",
        json={
            "code": code,
            "description": "Issue #79 — concrete C30/37, 24cm wall",
            "unit": "m3",
            "rate": 185.00,
            "currency": "EUR",
            "source": "cwicr",
            "classification": {"din276": "330"},
            "region": "DACH",
        },
        headers=auth,
    )
    assert resp.status_code == 201, f"Create cost item failed: {resp.text}"
    return resp.json()["id"]


# ═══════════════════════════════════════════════════════════════════════════
#  Issue #79 — POST /boq/boqs/{boq_id}/positions accepts cost_item_id
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_position_create_with_cwicr_and_cost_item_id_round_trips(
    shared_client: AsyncClient, shared_auth: dict[str, str]
) -> None:
    """POST + GET must round-trip cost_item_id when source='cwicr'."""
    client, auth = shared_client, shared_auth
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)
    cost_item_id = await _create_cost_item(client, auth)

    create_resp = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": "79.001",
            "description": "RC wall C30/37 (linked to CWICR)",
            "unit": "m3",
            "quantity": 12.5,
            "unit_rate": 185.00,
            "source": "cwicr",
            "cost_item_id": cost_item_id,
        },
        headers=auth,
    )
    assert create_resp.status_code == 201, f"Create failed: {create_resp.text}"
    created = create_resp.json()
    assert created["source"] == "cwicr"
    assert created["cost_item_id"] == cost_item_id
    # Linkage must also live in metadata so legacy consumers can read it.
    assert created["metadata"].get("cost_item_id") == cost_item_id

    # GET must surface the same linkage.
    get_resp = await client.get(
        f"/api/v1/boq/positions/{created['id']}", headers=auth
    )
    assert get_resp.status_code == 200, f"GET failed: {get_resp.text}"
    fetched = get_resp.json()
    assert fetched["source"] == "cwicr"
    assert fetched["cost_item_id"] == cost_item_id
    assert fetched["metadata"].get("cost_item_id") == cost_item_id


@pytest.mark.asyncio
async def test_position_create_with_unknown_cost_item_id_is_rejected(
    shared_client: AsyncClient, shared_auth: dict[str, str]
) -> None:
    """An unknown UUID must produce 422 with the documented detail message."""
    client, auth = shared_client, shared_auth
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)

    bogus_id = str(uuid.uuid4())
    resp = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": "79.002",
            "description": "broken linkage",
            "unit": "m3",
            "quantity": 1.0,
            "unit_rate": 1.0,
            "source": "cwicr",
            "cost_item_id": bogus_id,
        },
        headers=auth,
    )
    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
    assert "cost_item_id" in resp.text.lower()


@pytest.mark.asyncio
async def test_position_patch_cost_item_id_preserves_other_metadata(
    shared_client: AsyncClient, shared_auth: dict[str, str]
) -> None:
    """PATCHing cost_item_id must not wipe pre-existing metadata keys."""
    client, auth = shared_client, shared_auth
    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)
    cost_item_id = await _create_cost_item(client, auth)

    create_resp = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": "79.003",
            "description": "patch later",
            "unit": "m3",
            "quantity": 1.0,
            "unit_rate": 1.0,
            "metadata": {"note": "original"},
        },
        headers=auth,
    )
    assert create_resp.status_code == 201, f"Create failed: {create_resp.text}"
    position_id = create_resp.json()["id"]

    patch_resp = await client.patch(
        f"/api/v1/boq/positions/{position_id}",
        json={"source": "cwicr", "cost_item_id": cost_item_id},
        headers=auth,
    )
    assert patch_resp.status_code == 200, f"Patch failed: {patch_resp.text}"
    patched = patch_resp.json()
    assert patched["source"] == "cwicr"
    assert patched["cost_item_id"] == cost_item_id
    # The "note" key written at creation time must still be present.
    assert patched["metadata"].get("note") == "original"
    assert patched["metadata"].get("cost_item_id") == cost_item_id
