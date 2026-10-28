"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Issue #347 - per-element formula projection on quantity links (HTTP).

Drives the real quantity-link surface end to end:

* a ``formula`` link evaluates ``area_m2 * 0.5`` per element and the refresh
  aggregates the per-element results (sum), not one field off the raw map;
* an element that lacks a variable the formula needs is reported ``missing``
  (never a silent zero) and does not poison the aggregate;
* apply writes the aggregated formula quantity onto the position;
* the create endpoint validates the projection contract (bad formula, or a
  formula/field field missing for the chosen mode, is a 422).

Isolation matches the sibling quantity-link test: the per-session PostgreSQL
DB + eager model registration come from ``backend/tests/conftest.py`` and the
new ``projection_mode`` / ``formula`` columns land via ``create_all`` (the
model is the schema source of truth), so no ``alembic upgrade`` is needed.

Run:
    cd backend
    python -m pytest tests/integration/test_quantity_link_formula.py -v --tb=short
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture(scope="module")
async def client() -> AsyncClient:
    app = create_app()

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture(scope="module")
async def auth(client: AsyncClient) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"qlf-{unique}@test.io"
    password = f"QLF{unique}9!"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Formula Link Tester"},
    )
    assert reg.status_code == 201, reg.text

    from sqlalchemy import update as sa_update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as session:
        await session.execute(sa_update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await session.commit()

    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


# ── Helpers ───────────────────────────────────────────────────────────────


async def _project(client: AsyncClient, auth: dict[str, str]) -> str:
    r = await client.post(
        "/api/v1/projects/", json={"name": f"QLF {uuid.uuid4().hex[:6]}", "currency": "EUR"}, headers=auth
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _boq(client: AsyncClient, auth: dict[str, str], project_id: str) -> str:
    r = await client.post("/api/v1/boq/boqs/", json={"project_id": project_id, "name": "B"}, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _position(client: AsyncClient, auth: dict[str, str], boq_id: str, **body) -> dict:
    payload = {"boq_id": boq_id, "unit": "m2", "quantity": 0.0, "unit_rate": 100.0}
    payload.update(body)
    r = await client.post(f"/api/v1/boq/boqs/{boq_id}/positions/", json=payload, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


async def _model(client: AsyncClient, auth: dict[str, str], project_id: str, elements: list[dict]) -> str:
    m = await client.post(
        "/api/v1/bim_hub/",
        json={"project_id": project_id, "name": "M", "version": "1", "status": "ready"},
        headers=auth,
    )
    assert m.status_code == 201, m.text
    model_id = m.json()["id"]
    e = await client.post(f"/api/v1/bim_hub/models/{model_id}/elements/", json={"elements": elements}, headers=auth)
    assert e.status_code == 201, e.text
    return model_id


# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_formula_link_evaluates_per_element_then_aggregates(client: AsyncClient, auth: dict[str, str]) -> None:
    project_id = await _project(client, auth)
    boq_id = await _boq(client, auth, project_id)
    pos = await _position(client, auth, boq_id, ordinal="01.001", description="Half-area", unit="m2")
    model_id = await _model(
        client,
        auth,
        project_id,
        [
            {"stable_id": "S1", "element_type": "slab", "quantities": {"area_m2": 10.0}},
            {"stable_id": "S2", "element_type": "slab", "quantities": {"area_m2": 20.0}},
        ],
    )

    created = await client.post(
        f"/api/v1/boq/positions/{pos['id']}/quantity-links/",
        json={
            "model_id": model_id,
            "element_stable_ids": ["S1", "S2"],
            "projection_mode": "formula",
            "formula": "area_m2 * 0.5",
            "aggregation": "sum",
        },
        headers=auth,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["projection_mode"] == "formula"
    assert body["formula"] == "area_m2 * 0.5"
    link_id = body["id"]

    # Refresh: per element 10*0.5=5 and 20*0.5=10 -> sum 15.
    refresh = await client.post(f"/api/v1/boq/boqs/{boq_id}/quantity-links/refresh/", headers=auth)
    assert refresh.status_code == 200, refresh.text
    row = refresh.json()["rows"][0]
    assert float(row["new_quantity"]) == 15.0
    assert sorted(row["contributing_elements"]) == ["S1", "S2"]

    # Apply writes 15 onto the position (total = 15 * 100).
    apply = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/quantity-links/apply/",
        json={"link_ids": [link_id]},
        headers=auth,
    )
    assert apply.status_code == 200, apply.text
    assert apply.json()["applied"] == 1

    fresh = await client.get(f"/api/v1/boq/boqs/{boq_id}", headers=auth)
    applied_pos = next(p for p in fresh.json()["positions"] if p["id"] == pos["id"])
    assert float(applied_pos["quantity"]) == 15.0
    assert float(applied_pos["total"]) == 1500.0
    prov = applied_pos["metadata"]["model_quantity_pull"]
    assert prov["projection_mode"] == "formula"
    assert prov["formula"] == "area_m2 * 0.5"


@pytest.mark.asyncio
async def test_formula_element_missing_variable_is_reported_not_zeroed(
    client: AsyncClient, auth: dict[str, str]
) -> None:
    project_id = await _project(client, auth)
    boq_id = await _boq(client, auth, project_id)
    pos = await _position(client, auth, boq_id, ordinal="02.001", description="mix", unit="m2")
    model_id = await _model(
        client,
        auth,
        project_id,
        [
            {"stable_id": "A", "quantities": {"area_m2": 8.0}},
            {"stable_id": "B", "quantities": {"volume_m3": 3.0}},  # no area_m2
        ],
    )
    created = await client.post(
        f"/api/v1/boq/positions/{pos['id']}/quantity-links/",
        json={
            "model_id": model_id,
            "element_stable_ids": ["A", "B"],
            "projection_mode": "formula",
            "formula": "area_m2 * 2",
            "aggregation": "sum",
        },
        headers=auth,
    )
    assert created.status_code == 201, created.text

    refresh = await client.post(f"/api/v1/boq/boqs/{boq_id}/quantity-links/refresh/", headers=auth)
    row = refresh.json()["rows"][0]
    # Only A resolves (8*2=16); B is surfaced as missing, never a silent zero.
    assert float(row["new_quantity"]) == 16.0
    assert row["contributing_elements"] == ["A"]
    assert row["missing_element_ids"] == ["B"]


@pytest.mark.asyncio
async def test_create_validates_projection_contract(client: AsyncClient, auth: dict[str, str]) -> None:
    project_id = await _project(client, auth)
    boq_id = await _boq(client, auth, project_id)
    pos = await _position(client, auth, boq_id, ordinal="03.001", description="v", unit="m2")
    model_id = await _model(client, auth, project_id, [{"stable_id": "X", "quantities": {"area_m2": 1.0}}])
    base = {"model_id": model_id, "element_stable_ids": ["X"]}

    # Formula mode with a banned construct -> 422.
    r1 = await client.post(
        f"/api/v1/boq/positions/{pos['id']}/quantity-links/",
        json={**base, "projection_mode": "formula", "formula": "area_m2 ** 2"},
        headers=auth,
    )
    assert r1.status_code == 422, r1.text

    # Formula mode without a formula -> 422.
    r2 = await client.post(
        f"/api/v1/boq/positions/{pos['id']}/quantity-links/",
        json={**base, "projection_mode": "formula"},
        headers=auth,
    )
    assert r2.status_code == 422, r2.text

    # Field mode without a quantity_field -> 422.
    r3 = await client.post(
        f"/api/v1/boq/positions/{pos['id']}/quantity-links/",
        json={**base, "projection_mode": "field"},
        headers=auth,
    )
    assert r3.status_code == 422, r3.text

    # Field mode with a quantity_field still works (regression guard).
    r4 = await client.post(
        f"/api/v1/boq/positions/{pos['id']}/quantity-links/",
        json={**base, "projection_mode": "field", "quantity_field": "area_m2"},
        headers=auth,
    )
    assert r4.status_code == 201, r4.text
    assert r4.json()["projection_mode"] == "field"
