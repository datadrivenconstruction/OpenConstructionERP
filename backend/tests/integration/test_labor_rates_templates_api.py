# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Regression test for POST /api/v1/labor-rates/templates/ returning a 500.

A minimal, schema-valid create payload (just ``name`` and ``base_wage``) was
observed to 500 on a live instance after passing validation - the template
list stayed empty, so nothing was persisted. This exercises the real router
through the full ASGI app (not the service in isolation) against the
embedded PostgreSQL database, since the failure was reported against a real
request/response cycle.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from tests.integration._auth_helpers import promote_to_admin


@pytest_asyncio.fixture(scope="module")
async def client():
    """Test client with app lifecycle (startup/shutdown) triggered.

    Module-scoped: each ``create_app()`` re-runs full startup (assemblies,
    cost items, regional indices, ...) against the embedded PostgreSQL
    instance, which dominates the runtime of these tests. One boot per file
    is the pattern already used by ``test_bim_persistence.py``; it is safe
    because ``pyproject.toml`` pins ``asyncio_default_fixture_loop_scope``
    and ``asyncio_default_test_loop_scope`` to ``session``, so every test and
    fixture in the run shares one event loop.
    """
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
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    """Register + promote to admin + log in, returning bearer auth headers."""
    unique = uuid.uuid4().hex[:8]
    email = f"labor-rates-{unique}@test.io"
    password = f"LaborRates{unique}9!"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Labor Rates Tester"},
    )
    assert reg.status_code == 201, f"Registration failed: {reg.text}"

    await promote_to_admin(email)

    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, f"Login failed: {login.text}"
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def test_create_template_minimal_payload_does_not_500(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """The minimal schema-valid create payload must not 500 after validation.

    Regression for a reported defect: ``{"name": ..., "base_wage": "45.00"}``
    (no ``components``, no ``currency``, no ``description`` - all of which
    have defaults) reached the handler, passed Pydantic validation, and then
    raised an unhandled exception. A payload with a deliberately invalid
    on-cost ``kind`` correctly 422s, proving the request does reach the
    handler in the minimal case rather than being rejected earlier.
    """
    resp = await client.post(
        "/api/v1/labor-rates/templates/",
        json={"name": "Minimal Template", "base_wage": "45.00"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, f"expected 201, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["name"] == "Minimal Template"
    assert body["base_wage"] == "45.00"
    assert body["components"] == []

    # The template must actually be persisted (the reported bug left the
    # list empty because nothing was ever written).
    listing = await client.get("/api/v1/labor-rates/templates/", headers=auth_headers)
    assert listing.status_code == 200
    ids = [row["id"] for row in listing.json()]
    assert body["id"] in ids


async def test_create_template_invalid_component_kind_422s(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """A deliberately invalid on-cost ``kind`` must 422 (proves validation runs)."""
    resp = await client.post(
        "/api/v1/labor-rates/templates/",
        json={
            "name": "Bad Component Kind",
            "base_wage": "45.00",
            "components": [{"label": "Overhead", "kind": "not-a-real-kind", "value": "10"}],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422


async def test_create_template_with_components_does_not_500(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """A create payload that does carry on-cost components must also succeed.

    The minimal-payload regression above leaves ``components`` empty, which
    exercises one branch of the fix in ``LaborRateService.create_template``.
    This covers the non-empty branch so the fix does not trade one broken
    path for another.
    """
    resp = await client.post(
        "/api/v1/labor-rates/templates/",
        json={
            "name": "Template With Components",
            "base_wage": "50.00",
            "components": [
                {"label": "Social security", "kind": "percentage", "value": "12.5"},
                {"label": "Tool allowance", "kind": "fixed", "value": "2.00"},
            ],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, f"expected 201, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert len(body["components"]) == 2
    labels = {c["label"] for c in body["components"]}
    assert labels == {"Social security", "Tool allowance"}
