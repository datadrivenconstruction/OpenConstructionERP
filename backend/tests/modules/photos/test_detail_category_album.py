"""The photo detail drawer: category and album round-trip through the archive API.

A US site photo uploaded as "site" is re-filed as "defect" and put in the
"Punch walk L2" album; reading it back returns both. The archive refuses a
category outside the shared set, an album of another project, and a viewer.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.modules.photos.test_api import BASE, _upload


async def _album(client, header, project_id, name=None):
    resp = await client.post(
        f"{BASE}/albums/",
        json={"project_id": project_id, "name": name or f"Punch walk {uuid.uuid4().hex[:4]}"},
        headers=header,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_category_change_is_read_back(client: AsyncClient, admin_auth, project_id):
    _, header = admin_auth
    photo = (await _upload(client, header, project_id)).json()["items"][0]
    assert photo["category"] == "site"

    for category in ("progress", "defect", "delivery", "safety", "aerial", "other"):
        patched = await client.patch(f"{BASE}/{photo['id']}/", json={"category": category}, headers=header)
        assert patched.status_code == 200, patched.text
        assert patched.json()["category"] == category
        got = (await client.get(f"{BASE}/{photo['id']}/", headers=header)).json()
        assert got["category"] == category


@pytest.mark.asyncio
async def test_unknown_category_is_refused(client: AsyncClient, admin_auth, project_id):
    _, header = admin_auth
    photo = (await _upload(client, header, project_id)).json()["items"][0]
    bad = await client.patch(f"{BASE}/{photo['id']}/", json={"category": "Drone"}, headers=header)
    assert bad.status_code == 422
    assert (await client.get(f"{BASE}/{photo['id']}/", headers=header)).json()["category"] == "site"


@pytest.mark.asyncio
async def test_album_set_move_and_clear(client: AsyncClient, admin_auth, project_id):
    _, header = admin_auth
    photo = (await _upload(client, header, project_id)).json()["items"][0]
    assert photo["album_ids"] == []
    walk = await _album(client, header, project_id)
    handover = await _album(client, header, project_id)

    put = await client.put(f"{BASE}/{photo['id']}/albums/", json={"album_ids": [walk["id"]]}, headers=header)
    assert put.status_code == 200, put.text
    assert put.json()["album_ids"] == [walk["id"]]
    assert (await client.get(f"{BASE}/{photo['id']}/", headers=header)).json()["album_ids"] == [walk["id"]]
    listed = (await client.get(f"{BASE}/?project_id={project_id}&album={walk['id']}", headers=header)).json()
    assert [p["id"] for p in listed["items"]] == [photo["id"]]
    assert listed["items"][0]["album_ids"] == [walk["id"]]

    moved = await client.put(f"{BASE}/{photo['id']}/albums/", json={"album_ids": [handover["id"]]}, headers=header)
    assert moved.json()["album_ids"] == [handover["id"]]
    left = (await client.get(f"{BASE}/?project_id={project_id}&album={walk['id']}", headers=header)).json()
    assert left["total"] == 0

    cleared = await client.put(f"{BASE}/{photo['id']}/albums/", json={"album_ids": []}, headers=header)
    assert cleared.json()["album_ids"] == []


@pytest.mark.asyncio
async def test_album_of_another_project_is_refused(
    client: AsyncClient, admin_auth, project_id, other_user_auth, other_project_id
):
    _, header = admin_auth
    _, other_header = other_user_auth
    photo = (await _upload(client, header, project_id)).json()["items"][0]
    foreign = await _album(client, other_header, other_project_id)

    resp = await client.put(f"{BASE}/{photo['id']}/albums/", json={"album_ids": [foreign["id"]]}, headers=header)
    assert resp.status_code == 404
    missing = await client.put(f"{BASE}/{photo['id']}/albums/", json={"album_ids": [str(uuid.uuid4())]}, headers=header)
    assert missing.status_code == 404
    assert (await client.get(f"{BASE}/{photo['id']}/", headers=header)).json()["album_ids"] == []


@pytest.mark.asyncio
async def test_viewer_can_read_but_not_file_a_photo(client: AsyncClient, admin_auth, project_id, role_headers):
    _, header = admin_auth
    viewer, editor = role_headers["viewer"], role_headers["editor"]
    photo = (await _upload(client, header, project_id)).json()["items"][0]
    album = await _album(client, header, project_id)

    assert (await client.get(f"{BASE}/{photo['id']}/", headers=viewer)).status_code == 200
    body = {"album_ids": [album["id"]]}
    assert (await client.put(f"{BASE}/{photo['id']}/albums/", json=body, headers=viewer)).status_code == 403
    assert (
        await client.patch(f"{BASE}/{photo['id']}/", json={"category": "defect"}, headers=viewer)
    ).status_code == 403
    assert (await client.put(f"{BASE}/{photo['id']}/albums/", json=body, headers=editor)).status_code == 200
