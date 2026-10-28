"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A project PATCH that names a legal entity is answered, not dropped.

The owning entity is set through ``PUT /legal-entities/projects/{id}/entity``,
which checks the legal entities permission. ``PATCH /projects/{id}`` used to
accept ``legal_entity_id``, ignore it and answer 200, so a script assigning
entities that way reported success while every project stayed unassigned.

Run:
    cd backend
    python -m pytest tests/integration/test_project_patch_legal_entity.py -v
"""

import asyncio
import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

pytestmark = __import__("pytest").mark.asyncio


@pytest_asyncio.fixture(scope="module")
async def client():
    app = create_app()
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture(scope="module")
async def admin(client: AsyncClient) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email, password = f"pe-{unique}@test.io", f"Patch{unique}9"
    reg = await client.post(
        "/api/v1/users/auth/register", json={"email": email, "password": password, "full_name": "Patch"}
    )
    assert reg.status_code == 201, reg.text
    from ._auth_helpers import promote_to_admin

    await promote_to_admin(email)
    for attempt in range(3):
        data = (await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})).json()
        if data.get("access_token"):
            return {"Authorization": f"Bearer {data['access_token']}"}
        await asyncio.sleep(5 * (attempt + 1))
    raise AssertionError(f"login failed: {data}")


@pytest_asyncio.fixture(scope="module")
async def world(client: AsyncClient, admin: dict[str, str]) -> dict[str, str]:
    tag = uuid.uuid4().hex[:6].upper()
    project = await client.post("/api/v1/projects/", json={"name": f"Patch {tag}", "currency": "CAD"}, headers=admin)
    assert project.status_code == 201, project.text
    entity = await client.post(
        "/api/v1/legal-entities/entities/",
        json={
            "code": f"P{tag}",
            "name": "Patch Holdings Inc.",
            "country_code": "CA",
            "subdivision_code": "CA-ON",
            "functional_currency": "CAD",
        },
        headers=admin,
    )
    assert entity.status_code == 201, entity.text
    return {"project": project.json()["id"], "entity": entity.json()["id"]}


async def test_a_real_change_is_refused_and_points_at_the_entity_endpoint(
    client: AsyncClient, admin: dict[str, str], world: dict[str, str]
) -> None:
    resp = await client.patch(
        f"/api/v1/projects/{world['project']}", json={"legal_entity_id": world["entity"]}, headers=admin
    )
    assert resp.status_code == 422, resp.text
    assert "/legal-entities/projects/" in resp.text
    project = (await client.get(f"/api/v1/projects/{world['project']}", headers=admin)).json()
    assert project["legal_entity_id"] is None


async def test_sending_back_the_current_entity_with_other_fields_is_fine(
    client: AsyncClient, admin: dict[str, str], world: dict[str, str]
) -> None:
    assigned = await client.put(
        f"/api/v1/legal-entities/projects/{world['project']}/entity",
        json={"legal_entity_id": world["entity"]},
        headers=admin,
    )
    assert assigned.status_code == 200, assigned.text
    resp = await client.patch(
        f"/api/v1/projects/{world['project']}",
        json={"legal_entity_id": world["entity"], "description": "Round-tripped"},
        headers=admin,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["description"] == "Round-tripped"
    assert resp.json()["legal_entity_id"] == world["entity"]
