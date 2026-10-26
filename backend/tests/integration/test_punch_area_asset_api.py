"""HTTP tests: where a punch item is (area) and which asset it concerns."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update as sa_update

from app.database import async_session_factory
from app.main import create_app
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def client():
    app = create_app()

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac


async def _user(client, role: str) -> dict:
    unique = uuid.uuid4().hex[:8]
    email = f"punchloc-{role}-{unique}@smoke.io"
    password = f"PunchLoc{unique}9!"
    reg = await client.post(
        "/api/v1/users/auth/register", json={"email": email, "password": password, "full_name": f"Punch {role}"}
    )
    assert reg.status_code == 201, reg.text
    async with async_session_factory() as session:
        await session.execute(sa_update(User).where(User.email == email.lower()).values(role=role, is_active=True))
        await session.commit()
    resp = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    token = resp.json().get("access_token", "")
    assert token, resp.text
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def admin(client):
    return await _user(client, "admin")


async def _project(client, headers) -> str:
    resp = await client.post(
        "/api/v1/projects/", json={"name": "Punch Location", "region": "DACH", "currency": "EUR"}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create(client, headers, project_id: str, title: str, **extra) -> dict:
    resp = await client.post(
        "/api/v1/punchlist/items/", json={"project_id": project_id, "title": title, **extra}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_create_stores_area_and_asset_link(client, admin):
    project_id = await _project(client, admin)
    item = await _create(
        client,
        admin,
        project_id,
        "Loose handrail",
        area="  Level 2 / Stair B ",
        asset_kind="bim_element",
        asset_ref="el-42",
        asset_label="Handrail H2",
    )
    assert item["area"] == "Level 2 / Stair B"
    assert (item["asset_kind"], item["asset_ref"], item["asset_label"]) == ("bim_element", "el-42", "Handrail H2")


async def test_unlinked_item_has_empty_location_fields(client, admin):
    project_id = await _project(client, admin)
    item = await _create(client, admin, project_id, "Plain")
    assert item["area"] is None and item["asset_ref"] is None and item["asset_kind"] is None


async def test_asset_kind_is_validated(client, admin):
    project_id = await _project(client, admin)
    resp = await client.post(
        "/api/v1/punchlist/items/",
        json={"project_id": project_id, "title": "x", "asset_kind": "spaceship", "asset_ref": "1"},
        headers=admin,
    )
    assert resp.status_code == 422


async def test_label_without_asset_is_dropped(client, admin):
    project_id = await _project(client, admin)
    item = await _create(client, admin, project_id, "Orphan label", asset_kind="tag", asset_label="Ghost")
    assert item["asset_ref"] is None and item["asset_label"] is None and item["asset_kind"] is None


async def test_update_sets_changes_and_clears_the_link(client, admin):
    project_id = await _project(client, admin)
    item = await _create(client, admin, project_id, "Door")
    patch = await client.patch(
        f"/api/v1/punchlist/items/{item['id']}",
        json={"area": "Block A", "asset_kind": "plant", "asset_ref": "pl-1", "asset_label": "Pump 1"},
        headers=admin,
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["asset_ref"] == "pl-1" and patch.json()["area"] == "Block A"
    cleared = await client.patch(
        f"/api/v1/punchlist/items/{item['id']}", json={"asset_ref": "", "area": ""}, headers=admin
    )
    body = cleared.json()
    assert body["asset_ref"] is None and body["asset_kind"] is None and body["asset_label"] is None
    assert body["area"] is None


async def test_list_filters_by_area_and_asset(client, admin):
    project_id = await _project(client, admin)
    await _create(client, admin, project_id, "A1", area="Block A", asset_kind="tag", asset_ref="T-1")
    await _create(client, admin, project_id, "A2", area="Block A")
    await _create(client, admin, project_id, "B1", area="Block B", asset_kind="tag", asset_ref="T-1")
    by_area = await client.get(f"/api/v1/punchlist/items/?project_id={project_id}&area=Block%20A", headers=admin)
    assert {i["title"] for i in by_area.json()["items"]} == {"A1", "A2"}
    assert by_area.json()["total"] == 2
    by_asset = await client.get(f"/api/v1/punchlist/?project_id={project_id}&asset_ref=T-1", headers=admin)
    assert {i["title"] for i in by_asset.json()["items"]} == {"A1", "B1"}
    both = await client.get(
        f"/api/v1/punchlist/items/?project_id={project_id}&area=Block%20B&asset_ref=T-1", headers=admin
    )
    assert [i["title"] for i in both.json()["items"]] == ["B1"]


async def test_filter_is_project_scoped(client, admin):
    me = await _user(client, "editor")
    other = await _user(client, "editor")
    mine = await _project(client, me)
    theirs = await _project(client, other)
    await _create(client, other, theirs, "Foreign", area="Block A")
    resp = await client.get(f"/api/v1/punchlist/items/?project_id={mine}&area=Block%20A", headers=me)
    assert resp.json()["total"] == 0
    denied = await client.get(f"/api/v1/punchlist/items/?project_id={theirs}&area=Block%20A", headers=me)
    assert denied.status_code in (403, 404)
