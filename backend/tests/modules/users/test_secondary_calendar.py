"""Integration tests for the per-user secondary (Hijri) calendar preference.

Run: pytest backend/tests/modules/users/test_secondary_calendar.py -v
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

URL = "/api/v1/users/me/preferences/"


@pytest_asyncio.fixture
async def client():
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


async def _headers(client: AsyncClient) -> dict[str, str]:
    email = f"seccal-{uuid.uuid4().hex[:8]}@prefs.io"
    password = "SecCal12345"
    await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Sec Cal Tester"},
    )
    resp = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    return {"Authorization": f"Bearer {resp.json().get('access_token', '')}"}


@pytest.mark.asyncio
async def test_choice_round_trips_and_clears(client):
    headers = await _headers(client)
    assert (await client.get(URL, headers=headers)).json()["secondary_calendar"] is None

    patch = await client.patch(URL, headers=headers, json={"secondary_calendar": "hijri"})
    assert patch.status_code == 200, patch.text
    assert (await client.get(URL, headers=headers)).json()["secondary_calendar"] == "hijri"

    await client.patch(URL, headers=headers, json={"secondary_calendar": "none"})
    assert (await client.get(URL, headers=headers)).json()["secondary_calendar"] == "none"

    await client.patch(URL, headers=headers, json={"secondary_calendar": None})
    assert (await client.get(URL, headers=headers)).json()["secondary_calendar"] is None


@pytest.mark.asyncio
async def test_unknown_value_is_rejected(client):
    headers = await _headers(client)
    resp = await client.patch(URL, headers=headers, json={"secondary_calendar": "julian"})
    assert resp.status_code == 422
