# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Integration tests for the CWICR matcher HTTP API (T12).

Covers:
    POST /api/v1/costs/match/
    POST /api/v1/costs/match-from-position/
    404 on unknown position id
    Tenant isolation (matches don't leak across tenants — we only return
        items the request can already see via the standard search filter)
    Empty query → 200 with empty list

Run:
    cd backend
    python -m pytest tests/integration/test_costs_match_api.py -v --tb=short
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

# ── Shared fixtures (module-scoped, mirrors test_boq_cost_item_link.py) ──


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
    email = f"matcher-{unique}@test.io"
    password = f"Matcher{unique}9!"

    reg = await shared_client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "CWICR Matcher Tester",
            "role": "admin",
        },
    )
    assert reg.status_code == 201, f"Registration failed: {reg.text}"

    # Promote to admin so we have costs.create + boq.update perms.
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


# ── Per-module helpers ────────────────────────────────────────────────────


async def _create_project(client: AsyncClient, auth: dict[str, str]) -> str:
    resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": f"Matcher Test {uuid.uuid4().hex[:6]}",
            "description": "T12 matcher integration",
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
            "name": f"Matcher BOQ {uuid.uuid4().hex[:6]}",
            "description": "T12 matcher integration",
        },
        headers=auth,
    )
    assert resp.status_code == 201, f"Create BOQ failed: {resp.text}"
    return resp.json()["id"]


async def _create_position(
    client: AsyncClient,
    auth: dict[str, str],
    boq_id: str,
    *,
    description: str,
    unit: str = "m3",
) -> str:
    resp = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": f"T12.{uuid.uuid4().hex[:4]}",
            "description": description,
            "unit": unit,
            "quantity": 10.0,
            "unit_rate": 0.0,
        },
        headers=auth,
    )
    assert resp.status_code == 201, f"Create position failed: {resp.text}"
    return resp.json()["id"]


async def _create_cost_item(
    client: AsyncClient,
    auth: dict[str, str],
    *,
    description: str,
    unit: str = "m3",
    rate: float = 100.0,
    code: str | None = None,
    region: str = "T12-MATCHER",
) -> str:
    """Create a fresh CostItem and return its UUID."""
    code = code or f"T12-{uuid.uuid4().hex[:8]}"
    resp = await client.post(
        "/api/v1/costs/",
        json={
            "code": code,
            "description": description,
            "unit": unit,
            "rate": rate,
            "currency": "EUR",
            "source": "cwicr",
            "classification": {"din276": "330"},
            "region": region,
        },
        headers=auth,
    )
    assert resp.status_code == 201, f"Create cost item failed: {resp.text}"
    return resp.json()["id"]


# ═══════════════════════════════════════════════════════════════════════════
#  POST /api/v1/costs/match/
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_match_endpoint_returns_ranked_results(
    shared_client: AsyncClient, shared_auth: dict[str, str]
) -> None:
    """Top-K results come back ranked by score with the right shape."""
    client, auth = shared_client, shared_auth
    region = f"T12-{uuid.uuid4().hex[:6]}"

    # Seed three CWICR-style items in a unique region so we don't pick up
    # rows from other tests.
    await _create_cost_item(
        client, auth,
        description="Reinforced concrete wall C30/37",
        unit="m3", rate=185.0, region=region,
    )
    await _create_cost_item(
        client, auth,
        description="Brick wall, 24cm clay brick",
        unit="m2", rate=78.0, region=region,
    )
    await _create_cost_item(
        client, auth,
        description="Wood formwork for slabs",
        unit="m2", rate=42.5, region=region,
    )

    resp = await client.post(
        "/api/v1/costs/match/",
        json={
            "query": "reinforced concrete wall",
            "unit": "m3",
            "top_k": 5,
            "mode": "lexical",
            "region": region,
        },
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) >= 1
    # Top result must be the concrete wall row.
    assert "concrete" in body[0]["description"].lower()
    assert body[0]["unit"] == "m3"
    # Score field is in the public contract.
    assert 0.0 <= body[0]["score"] <= 1.0
    # Source must reflect the requested mode.
    assert body[0]["source"] in {"lexical", "hybrid"}
    # Sorted descending.
    scores = [r["score"] for r in body]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_match_endpoint_empty_query_returns_empty_list(
    shared_client: AsyncClient, shared_auth: dict[str, str]
) -> None:
    """Empty / whitespace queries are 200 + [], not 422."""
    client, auth = shared_client, shared_auth
    resp = await client.post(
        "/api/v1/costs/match/",
        json={"query": "   ", "top_k": 5},
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


# ═══════════════════════════════════════════════════════════════════════════
#  POST /api/v1/costs/match-from-position/
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_match_from_position_resolves_description(
    shared_client: AsyncClient, shared_auth: dict[str, str]
) -> None:
    """Loading the position by id is equivalent to matching its description."""
    client, auth = shared_client, shared_auth
    region = f"T12-{uuid.uuid4().hex[:6]}"

    await _create_cost_item(
        client, auth,
        description="Reinforced concrete wall C30/37",
        unit="m3", rate=185.0, region=region,
    )

    project_id = await _create_project(client, auth)
    boq_id = await _create_boq(client, auth, project_id)
    position_id = await _create_position(
        client, auth, boq_id,
        description="Reinforced concrete wall, 24cm",
        unit="m3",
    )

    resp = await client.post(
        "/api/v1/costs/match-from-position/",
        json={"position_id": position_id, "top_k": 3, "region": region},
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body, list)
    assert body, "expected at least one match"
    assert "concrete" in body[0]["description"].lower()


@pytest.mark.asyncio
async def test_match_from_position_unknown_id_returns_404(
    shared_client: AsyncClient, shared_auth: dict[str, str]
) -> None:
    """Unknown position UUID must produce a 404 with the documented detail."""
    client, auth = shared_client, shared_auth
    bogus = str(uuid.uuid4())
    resp = await client.post(
        "/api/v1/costs/match-from-position/",
        json={"position_id": bogus, "top_k": 3},
        headers=auth,
    )
    assert resp.status_code == 404, resp.text
    assert "not found" in resp.json().get("detail", "").lower()


# ═══════════════════════════════════════════════════════════════════════════
#  Tenant / region isolation
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_match_respects_region_isolation(
    shared_client: AsyncClient, shared_auth: dict[str, str]
) -> None:
    """Items in region A must not surface for queries scoped to region B."""
    client, auth = shared_client, shared_auth
    region_a = f"T12A-{uuid.uuid4().hex[:6]}"
    region_b = f"T12B-{uuid.uuid4().hex[:6]}"

    await _create_cost_item(
        client, auth,
        description="ISOLATION-MARKER concrete wall",
        unit="m3", rate=185.0, region=region_a,
    )

    # Query in region B — we must NOT see the region A row.
    resp = await client.post(
        "/api/v1/costs/match/",
        json={
            "query": "ISOLATION-MARKER concrete wall",
            "top_k": 5,
            "region": region_b,
        },
        headers=auth,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # The marker row lives in region A only; region B query must skip it.
    descriptions = [r["description"] for r in body]
    assert not any("ISOLATION-MARKER" in d for d in descriptions), (
        f"Region isolation broken: leaked rows = {descriptions}"
    )

    # Sanity: querying region A surfaces it.
    resp_a = await client.post(
        "/api/v1/costs/match/",
        json={
            "query": "ISOLATION-MARKER concrete wall",
            "top_k": 5,
            "region": region_a,
        },
        headers=auth,
    )
    assert resp_a.status_code == 200
    body_a = resp_a.json()
    assert any("ISOLATION-MARKER" in r["description"] for r in body_a)
