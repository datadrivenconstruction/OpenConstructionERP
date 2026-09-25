"""Integration tests for the per-user Simple / Advanced menu choice.

The choice used to live only in one browser's localStorage. It now follows
the login through ``/api/v1/users/me/view-mode/``, which is ``null`` until the
user picks a mode, so the client can tell "never chose" from a choice.

Run: pytest backend/tests/modules/users/test_view_mode.py -v
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

URL = "/api/v1/users/me/view-mode/"


@pytest_asyncio.fixture
async def client():
    """Boot the full app once per test (lifespan = module discovery)."""
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


async def _headers(client: AsyncClient) -> dict[str, str]:
    email = f"viewmode-{uuid.uuid4().hex[:8]}@prefs.io"
    password = "ViewMode12345"
    await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "View Mode Tester"},
    )
    resp = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    return {"Authorization": f"Bearer {resp.json().get('access_token', '')}"}


@pytest.mark.asyncio
async def test_choice_round_trips_and_clears(client):
    """Null for a new user, then the stored choice, then null again once cleared."""
    headers = await _headers(client)

    assert (await client.get(URL, headers=headers)).json() == {"mode": None}

    put = await client.put(URL, headers=headers, json={"mode": "advanced"})
    assert put.status_code == 200, put.text
    assert (await client.get(URL, headers=headers)).json() == {"mode": "advanced"}

    await client.put(URL, headers=headers, json={"mode": None})
    assert (await client.get(URL, headers=headers)).json() == {"mode": None}

    bad = await client.put(URL, headers=headers, json={"mode": "expert"})
    assert bad.status_code == 422


@pytest.mark.asyncio
async def test_onboarding_interface_mode_is_not_a_choice(client):
    """The onboarding record's interface_mode never reads back as the user's mode.

    Old clients wrote ``advanced`` there on every profile save, whatever the
    user had picked, so treating it as a choice would move people silently.
    """
    headers = await _headers(client)
    saved = await client.post(
        "/api/v1/users/me/onboarding/",
        headers=headers,
        json={"company_type": None, "enabled_modules": ["boq"], "interface_mode": "advanced", "completed": True},
    )
    assert saved.status_code == 200, saved.text

    assert (await client.get(URL, headers=headers)).json() == {"mode": None}
