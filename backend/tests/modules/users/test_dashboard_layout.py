"""Integration tests for the per-user dashboard widget layout API.

Mirrors the sidebar-preferences test suite. The endpoints move the dashboard
widget order + hidden list off per-browser localStorage onto the user record
so the layout follows the user across browsers and devices:

* ``GET  /api/v1/users/me/dashboard-layout/`` — empty defaults when the user
  has never customised the dashboard.
* ``PUT  /api/v1/users/me/dashboard-layout/`` — upserts the layout; a
  subsequent GET must return what was just written.
* Validation: non-list / non-string body items are rejected by Pydantic.

Run: pytest backend/tests/modules/users/test_dashboard_layout.py -v
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
    password: str = "DashboardLayout123",
) -> tuple[str, dict[str, str]]:
    """Register a fresh user and return (email, auth_headers)."""
    if email is None:
        email = f"dashlayout-{uuid.uuid4().hex[:8]}@prefs.io"
    await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "Dashboard Layout Tester",
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
async def test_get_dashboard_layout_empty_for_new_user(client):
    """A user who has never saved a layout must get empty defaults, not 404."""
    _email, headers = await _register_and_login(client)

    resp = await client.get("/api/v1/users/me/dashboard-layout/", headers=headers)

    assert resp.status_code == 200, f"Expected 200 but got {resp.status_code}: {resp.text!r}"
    body = resp.json()
    assert body == {"order": [], "hidden": []}


# ── PUT then GET round-trip ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_put_then_get_dashboard_layout_round_trip(client):
    """A PUT followed by a GET returns the exact same payload (order preserved)."""
    _email, headers = await _register_and_login(client)

    payload = {
        "order": ["kpi", "projects", "boq_summary", "risk_top"],
        "hidden": ["activity", "weather_site"],
    }
    put_resp = await client.put(
        "/api/v1/users/me/dashboard-layout/",
        headers=headers,
        json=payload,
    )
    assert put_resp.status_code == 200, put_resp.text
    assert put_resp.json() == payload

    get_resp = await client.get("/api/v1/users/me/dashboard-layout/", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json() == payload


@pytest.mark.asyncio
async def test_put_overwrites_previous_value(client):
    """A second PUT fully replaces the first payload (not merge / append)."""
    _email, headers = await _register_and_login(client)

    await client.put(
        "/api/v1/users/me/dashboard-layout/",
        headers=headers,
        json={"order": ["a", "b", "c"], "hidden": ["x"]},
    )
    await client.put(
        "/api/v1/users/me/dashboard-layout/",
        headers=headers,
        json={"order": ["z"], "hidden": []},
    )

    resp = await client.get("/api/v1/users/me/dashboard-layout/", headers=headers)
    assert resp.json() == {"order": ["z"], "hidden": []}


# ── Per-user isolation ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_user_a_write_does_not_affect_user_b(client):
    """User A's layout stays with A (the whole point of moving off localStorage)."""
    _email_a, headers_a = await _register_and_login(client)
    _email_b, headers_b = await _register_and_login(client)

    await client.put(
        "/api/v1/users/me/dashboard-layout/",
        headers=headers_a,
        json={"order": ["kpi", "projects"], "hidden": ["analytics"]},
    )

    resp_b = await client.get("/api/v1/users/me/dashboard-layout/", headers=headers_b)
    assert resp_b.status_code == 200
    assert resp_b.json() == {"order": [], "hidden": []}

    resp_a = await client.get("/api/v1/users/me/dashboard-layout/", headers=headers_a)
    assert resp_a.json() == {"order": ["kpi", "projects"], "hidden": ["analytics"]}


# ── Pydantic validation ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_put_rejects_non_list_order(client):
    """Pydantic must reject ``order`` that isn't a list."""
    _email, headers = await _register_and_login(client)

    resp = await client.put(
        "/api/v1/users/me/dashboard-layout/",
        headers=headers,
        json={"order": "not-a-list", "hidden": []},
    )
    assert resp.status_code in (400, 422), f"Expected 4xx for non-list order but got {resp.status_code}: {resp.text!r}"


@pytest.mark.asyncio
async def test_put_rejects_non_list_hidden(client):
    """Pydantic must reject ``hidden`` that isn't a list."""
    _email, headers = await _register_and_login(client)

    resp = await client.put(
        "/api/v1/users/me/dashboard-layout/",
        headers=headers,
        json={"order": [], "hidden": {"foo": True}},
    )
    assert resp.status_code in (400, 422), f"Expected 4xx for non-list hidden but got {resp.status_code}: {resp.text!r}"


@pytest.mark.asyncio
async def test_put_rejects_non_string_items(client):
    """Pydantic must reject non-string items inside ``order`` / ``hidden``."""
    _email, headers = await _register_and_login(client)

    resp = await client.put(
        "/api/v1/users/me/dashboard-layout/",
        headers=headers,
        json={"order": ["kpi", 42, None], "hidden": []},
    )
    assert resp.status_code in (400, 422), (
        f"Expected 4xx for non-string items but got {resp.status_code}: {resp.text!r}"
    )


@pytest.mark.asyncio
async def test_put_dedupes_and_strips(client):
    """Server cleans up duplicates + whitespace so clients can stay dumb."""
    _email, headers = await _register_and_login(client)

    resp = await client.put(
        "/api/v1/users/me/dashboard-layout/",
        headers=headers,
        json={
            "order": ["  kpi  ", "kpi", "projects", "", "   "],
            "hidden": ["activity", "activity", "  weather_site  "],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["order"] == ["kpi", "projects"]
    assert body["hidden"] == ["activity", "weather_site"]


# ── Auth required ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_endpoints_require_authentication(client):
    """Both endpoints must reject anonymous callers."""
    get_resp = await client.get("/api/v1/users/me/dashboard-layout/")
    assert get_resp.status_code in (401, 403)

    put_resp = await client.put(
        "/api/v1/users/me/dashboard-layout/",
        json={"order": ["kpi"], "hidden": []},
    )
    assert put_resp.status_code in (401, 403)
