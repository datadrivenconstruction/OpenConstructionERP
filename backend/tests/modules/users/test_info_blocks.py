"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for the per-user module info-card collapse API.

Mirrors the dashboard-layout / sidebar-preferences suites. The endpoints move
the DismissibleInfo collapse state off per-browser localStorage onto the user
record so a card the user collapsed (into the pill next to "How it works")
stays collapsed across browsers and devices:

* ``GET  /api/v1/users/me/info-blocks/`` - empty map when the user has never
  collapsed a card.
* ``PUT  /api/v1/users/me/info-blocks/`` - upserts the map; a subsequent GET
  returns exactly what was written.
* Sanitisation: keys are trimmed, blanks dropped, values coerced to bool.

Run: pytest backend/tests/modules/users/test_info_blocks.py -v
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture
async def client():
    """Boot the full app once per test (lifespan = module discovery)."""
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


async def _register_and_login(
    client: AsyncClient,
    *,
    email: str | None = None,
    password: str = "InfoBlocks123",
) -> tuple[str, dict[str, str]]:
    """Register a fresh user and return (email, auth_headers)."""
    if email is None:
        email = f"infoblocks-{uuid.uuid4().hex[:8]}@prefs.io"
    await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "Info Blocks Tester",
        },
    )
    resp = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    token = resp.json().get("access_token", "")
    return email, {"Authorization": f"Bearer {token}"}


# ── GET on fresh user ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_info_blocks_empty_for_new_user(client):
    """A user who has never collapsed a card gets an empty map, not a 404."""
    _email, headers = await _register_and_login(client)

    resp = await client.get("/api/v1/users/me/info-blocks/", headers=headers)

    assert resp.status_code == 200, f"Expected 200 but got {resp.status_code}: {resp.text!r}"
    assert resp.json() == {"blocks": {}}


# ── PUT then GET round-trip ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_put_then_get_round_trip(client):
    """A PUT followed by a GET returns the exact same map (both states kept)."""
    _email, headers = await _register_and_login(client)

    payload = {"blocks": {"site_supervision": True, "boq": False, "transmittals": True}}
    put_resp = await client.put(
        "/api/v1/users/me/info-blocks/",
        headers=headers,
        json=payload,
    )
    assert put_resp.status_code == 200, put_resp.text
    assert put_resp.json() == payload

    get_resp = await client.get("/api/v1/users/me/info-blocks/", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json() == payload


@pytest.mark.asyncio
async def test_put_overwrites_previous_value(client):
    """A second PUT fully replaces the first map (not merge / append)."""
    _email, headers = await _register_and_login(client)

    await client.put(
        "/api/v1/users/me/info-blocks/",
        headers=headers,
        json={"blocks": {"a": True, "b": True}},
    )
    await client.put(
        "/api/v1/users/me/info-blocks/",
        headers=headers,
        json={"blocks": {"c": True}},
    )

    resp = await client.get("/api/v1/users/me/info-blocks/", headers=headers)
    assert resp.json() == {"blocks": {"c": True}}


# ── Per-user isolation ──────────────────────────────────────────────────────


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_user_a_write_does_not_affect_user_b(client):
    """User A's collapse state stays with A (the whole point of the endpoint)."""
    _email_a, headers_a = await _register_and_login(client)
    _email_b, headers_b = await _register_and_login(client)

    await client.put(
        "/api/v1/users/me/info-blocks/",
        headers=headers_a,
        json={"blocks": {"cde": True}},
    )

    resp_b = await client.get("/api/v1/users/me/info-blocks/", headers=headers_b)
    assert resp_b.status_code == 200
    assert resp_b.json() == {"blocks": {}}

    resp_a = await client.get("/api/v1/users/me/info-blocks/", headers=headers_a)
    assert resp_a.json() == {"blocks": {"cde": True}}


# ── Sanitisation ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_put_strips_keys_and_drops_blanks(client):
    """Server trims key whitespace and drops empty keys so clients stay dumb."""
    _email, headers = await _register_and_login(client)

    resp = await client.put(
        "/api/v1/users/me/info-blocks/",
        headers=headers,
        json={"blocks": {"  boq  ": True, "": True, "   ": False, "rfi": False}},
    )
    assert resp.status_code == 200
    assert resp.json() == {"blocks": {"boq": True, "rfi": False}}


@pytest.mark.asyncio
async def test_put_coerces_truthy_values_to_bool(client):
    """Non-bool JSON values are coerced to real booleans on the way in."""
    _email, headers = await _register_and_login(client)

    resp = await client.put(
        "/api/v1/users/me/info-blocks/",
        headers=headers,
        json={"blocks": {"one": 1, "zero": 0}},
    )
    assert resp.status_code == 200
    assert resp.json() == {"blocks": {"one": True, "zero": False}}


@pytest.mark.asyncio
async def test_put_rejects_non_object_blocks(client):
    """Pydantic must reject ``blocks`` that isn't an object/dict."""
    _email, headers = await _register_and_login(client)

    resp = await client.put(
        "/api/v1/users/me/info-blocks/",
        headers=headers,
        json={"blocks": ["not", "a", "map"]},
    )
    assert resp.status_code in (400, 422), (
        f"Expected 4xx for non-object blocks but got {resp.status_code}: {resp.text!r}"
    )


# ── Auth required ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_endpoints_require_authentication(client):
    """Both endpoints must reject anonymous callers."""
    get_resp = await client.get("/api/v1/users/me/info-blocks/")
    assert get_resp.status_code in (401, 403)

    put_resp = await client.put(
        "/api/v1/users/me/info-blocks/",
        json={"blocks": {"boq": True}},
    )
    assert put_resp.status_code in (401, 403)
