"""Integration tests for the per-user custom-unit catalogue.

``PATCH /api/v1/users/me/custom-units/`` used to replace the stored list
with the body. The client sent its own local copy, so two sessions under
one login overwrote each other and a unit added in one was lost. The PATCH
is now additive: it never removes a stored unit, and it adds only units that
are new (not in the unit registry, not already stored under the same
identity key).

Run: pytest backend/tests/modules/users/test_custom_units.py -v
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

URL = "/api/v1/users/me/custom-units/"


@pytest_asyncio.fixture
async def client():
    """Boot the full app once per test (lifespan = module discovery)."""
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


async def _login(client: AsyncClient, email: str, password: str = "CustomUnits123") -> dict[str, str]:
    resp = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    return {"Authorization": f"Bearer {resp.json().get('access_token', '')}"}


async def _register(client: AsyncClient, password: str = "CustomUnits123") -> str:
    email = f"units-{uuid.uuid4().hex[:8]}@prefs.io"
    await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Custom Units Tester"},
    )
    return email


@pytest.mark.asyncio
async def test_two_sessions_each_adding_a_unit_keep_both(client):
    """Two logins of one user add different units; neither loses the other's."""
    email = await _register(client)
    session_a = await _login(client, email)
    session_b = await _login(client, email)

    # Both sessions loaded an empty list, then each adds its own unit.
    resp_a = await client.patch(URL, headers=session_a, json={"units": ["pallet-x"]})
    assert resp_a.status_code == 200, resp_a.text
    resp_b = await client.patch(URL, headers=session_b, json={"units": ["crate-y"]})
    assert resp_b.status_code == 200, resp_b.text

    got = await client.get(URL, headers=session_a)
    assert got.json() == {"units": ["pallet-x", "crate-y"]}


@pytest.mark.asyncio
async def test_stale_full_list_does_not_drop_a_unit_added_elsewhere(client):
    """An old client sending its whole (stale) list keeps what the other added."""
    email = await _register(client)
    session_a = await _login(client, email)
    session_b = await _login(client, email)

    await client.patch(URL, headers=session_a, json={"units": ["pallet-x", "crate-y"]})
    # Session B's local copy predates "crate-y" and it adds "drum-z".
    resp = await client.patch(URL, headers=session_b, json={"units": ["pallet-x", "drum-z"]})

    assert resp.json() == {"units": ["pallet-x", "crate-y", "drum-z"]}
    assert (await client.get(URL, headers=session_a)).json() == {"units": ["pallet-x", "crate-y", "drum-z"]}


@pytest.mark.asyncio
async def test_registry_units_and_spelling_duplicates_are_not_stored(client):
    """Units every picker already offers, and case / superscript twins, add nothing."""
    email = await _register(client)
    headers = await _login(client, email)

    await client.patch(URL, headers=headers, json={"units": ["Pallet-X"]})
    resp = await client.patch(
        URL,
        headers=headers,
        # m3 / M3 / m³ and "lsum" are registry units, "tonne" a registry
        # alias; "pallet-x" is the stored unit in another case.
        json={"units": ["m3", "M3", "m³", "lsum", "tonne", "pallet-x", "  Pallet-X  "]},
    )

    assert resp.json() == {"units": ["Pallet-X"]}


@pytest.mark.asyncio
async def test_repeating_the_same_patch_is_idempotent(client):
    """Sending the same unit twice leaves one copy."""
    email = await _register(client)
    headers = await _login(client, email)

    await client.patch(URL, headers=headers, json={"units": ["bucket²"]})
    resp = await client.patch(URL, headers=headers, json={"units": ["BUCKET2"]})

    assert resp.json() == {"units": ["bucket²"]}
