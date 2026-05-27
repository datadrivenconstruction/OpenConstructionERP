"""Integration tests for the per-user sidebar visibility preferences API.

Covers the new endpoints introduced after v4.5.0 that move the sidebar
"hidden modules" list off per-browser localStorage onto the user record
so the choice follows the user across browsers and devices:

* ``GET /api/v1/users/me/sidebar-preferences``  — returns empty list when
  the user has never customised the sidebar.
* ``PUT /api/v1/users/me/sidebar-preferences``  — upserts the list; a
  subsequent GET must return what was just written.
* Isolation: user A's writes must not bleed into user B's reads (the
  original localStorage bug we are fixing).
* Validation: non-string array items are rejected by Pydantic at the
  schema boundary.

Run: pytest backend/tests/integration/test_users_sidebar_preferences.py -v
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
    password: str = "SidebarPrefs123",
) -> tuple[str, dict[str, str]]:
    """Register a fresh user and return (email, auth_headers)."""
    if email is None:
        email = f"sidebar-{uuid.uuid4().hex[:8]}@prefs.io"
    await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "Sidebar Prefs Tester",
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
async def test_get_sidebar_preferences_empty_for_new_user(client):
    """A user who has never saved preferences must get an empty list, not 404."""
    _email, headers = await _register_and_login(client)

    resp = await client.get("/api/v1/users/me/sidebar-preferences/", headers=headers)

    assert resp.status_code == 200, f"Expected 200 but got {resp.status_code}: {resp.text!r}"
    body = resp.json()
    assert body == {"hidden_modules": []}


# ── PUT then GET round-trip ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_put_then_get_sidebar_preferences_round_trip(client):
    """A PUT followed by a GET returns the exact same list (order preserved)."""
    _email, headers = await _register_and_login(client)

    payload = {"hidden_modules": ["/finance", "/sustainability", "/hse"]}
    put_resp = await client.put(
        "/api/v1/users/me/sidebar-preferences/",
        headers=headers,
        json=payload,
    )
    assert put_resp.status_code == 200, put_resp.text
    assert put_resp.json() == payload

    get_resp = await client.get("/api/v1/users/me/sidebar-preferences/", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json() == payload


@pytest.mark.asyncio
async def test_put_overwrites_previous_value(client):
    """A second PUT must fully replace the first list (not merge / append)."""
    _email, headers = await _register_and_login(client)

    await client.put(
        "/api/v1/users/me/sidebar-preferences/",
        headers=headers,
        json={"hidden_modules": ["/a", "/b", "/c"]},
    )
    await client.put(
        "/api/v1/users/me/sidebar-preferences/",
        headers=headers,
        json={"hidden_modules": ["/x"]},
    )

    resp = await client.get("/api/v1/users/me/sidebar-preferences/", headers=headers)
    assert resp.json() == {"hidden_modules": ["/x"]}


# ── Per-user isolation (the localStorage bug we are fixing) ─────────────────


@pytest.mark.asyncio
async def test_user_a_write_does_not_affect_user_b(client):
    """The whole point of this refactor: user A's hidden list stays with A."""
    _email_a, headers_a = await _register_and_login(client)
    _email_b, headers_b = await _register_and_login(client)

    await client.put(
        "/api/v1/users/me/sidebar-preferences/",
        headers=headers_a,
        json={"hidden_modules": ["/finance", "/qms"]},
    )

    resp_b = await client.get("/api/v1/users/me/sidebar-preferences/", headers=headers_b)
    assert resp_b.status_code == 200
    assert resp_b.json() == {"hidden_modules": []}

    resp_a = await client.get("/api/v1/users/me/sidebar-preferences/", headers=headers_a)
    assert resp_a.json() == {"hidden_modules": ["/finance", "/qms"]}


# ── Pydantic validation ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_put_rejects_non_string_array_items(client):
    """Pydantic must reject ``hidden_modules`` items that aren't strings."""
    _email, headers = await _register_and_login(client)

    resp = await client.put(
        "/api/v1/users/me/sidebar-preferences/",
        headers=headers,
        json={"hidden_modules": ["/finance", 42, None]},
    )
    assert resp.status_code in (400, 422), (
        f"Expected 4xx for non-string items but got {resp.status_code}: {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_put_dedupes_and_strips(client):
    """Server cleans up duplicates + whitespace so clients can stay dumb."""
    _email, headers = await _register_and_login(client)

    resp = await client.put(
        "/api/v1/users/me/sidebar-preferences/",
        headers=headers,
        json={"hidden_modules": ["  /finance  ", "/finance", "/qms", "", "   "]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["hidden_modules"] == ["/finance", "/qms"]


# ── Auth required ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_endpoints_require_authentication(client):
    """Both endpoints must reject anonymous callers."""
    get_resp = await client.get("/api/v1/users/me/sidebar-preferences/")
    assert get_resp.status_code in (401, 403)

    put_resp = await client.put(
        "/api/v1/users/me/sidebar-preferences/",
        json={"hidden_modules": ["/finance"]},
    )
    assert put_resp.status_code in (401, 403)
