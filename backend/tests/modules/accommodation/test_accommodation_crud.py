"""CRUD + IDOR tests for the Accommodation module.

Verifies the Wave-5 IDOR pattern: a user from project A always sees 404
for project B's rows — never 403 (no info leak).
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_and_list_accommodation(
    client: AsyncClient,
    admin_auth: tuple[str, dict[str, str]],
    project_id: str,
):
    _, header = admin_auth
    create = await client.post(
        "/api/v1/accommodation/",
        json={
            "project_id": project_id,
            "name": "Camp Alpha",
            "kind": "worker_camp",
            "capacity_total": 100,
        },
        headers=header,
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["name"] == "Camp Alpha"
    assert body["kind"] == "worker_camp"
    assert body["capacity_total"] == 100

    lst = await client.get("/api/v1/accommodation/", headers=header)
    assert lst.status_code == 200, lst.text
    names = [a["name"] for a in lst.json()]
    assert "Camp Alpha" in names


@pytest.mark.asyncio
async def test_get_accommodation_returns_nested_rooms(
    client: AsyncClient,
    admin_auth: tuple[str, dict[str, str]],
    project_id: str,
):
    _, header = admin_auth
    create = await client.post(
        "/api/v1/accommodation/",
        json={
            "project_id": project_id,
            "name": "Hotel Beta",
            "kind": "hotel",
        },
        headers=header,
    )
    accom_id = create.json()["id"]

    # Bulk-create two rooms.
    add_rooms = await client.post(
        f"/api/v1/accommodation/{accom_id}/rooms",
        json={
            "rooms": [
                {"label": "101", "capacity": 2, "base_rate": "85.00"},
                {"label": "102", "capacity": 2, "base_rate": "85.00"},
            ],
        },
        headers=header,
    )
    assert add_rooms.status_code == 201, add_rooms.text

    detail = await client.get(
        f"/api/v1/accommodation/{accom_id}",
        headers=header,
    )
    assert detail.status_code == 200
    payload = detail.json()
    assert len(payload["rooms"]) == 2
    assert payload["active_bookings_count"] == 0


@pytest.mark.asyncio
async def test_update_accommodation(
    client: AsyncClient,
    admin_auth: tuple[str, dict[str, str]],
    project_id: str,
):
    _, header = admin_auth
    create = await client.post(
        "/api/v1/accommodation/",
        json={"project_id": project_id, "name": "To Rename", "kind": "rental"},
        headers=header,
    )
    accom_id = create.json()["id"]

    upd = await client.patch(
        f"/api/v1/accommodation/{accom_id}",
        json={"name": "Renamed", "notes": "important"},
        headers=header,
    )
    assert upd.status_code == 200
    assert upd.json()["name"] == "Renamed"
    assert upd.json()["notes"] == "important"


@pytest.mark.asyncio
async def test_soft_delete_hides_from_list(
    client: AsyncClient,
    admin_auth: tuple[str, dict[str, str]],
    project_id: str,
):
    _, header = admin_auth
    create = await client.post(
        "/api/v1/accommodation/",
        json={"project_id": project_id, "name": "DeleteMe", "kind": "hotel"},
        headers=header,
    )
    accom_id = create.json()["id"]

    dele = await client.delete(
        f"/api/v1/accommodation/{accom_id}",
        headers=header,
    )
    assert dele.status_code == 204

    # Subsequent GET 404s (tombstone respected).
    miss = await client.get(
        f"/api/v1/accommodation/{accom_id}",
        headers=header,
    )
    assert miss.status_code == 404


# ── IDOR ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_idor_cannot_read_other_users_accommodation(
    client: AsyncClient,
    admin_auth: tuple[str, dict[str, str]],
    project_id: str,
    other_user_auth: tuple[str, dict[str, str]],
    other_project_id: str,
):
    """The ``other`` user creates an accommodation in their own project.

    The original admin must see 404 — never 403 — when probing it.
    """
    _, other_header = other_user_auth
    create = await client.post(
        "/api/v1/accommodation/",
        json={
            "project_id": other_project_id,
            "name": "Secret Hotel",
            "kind": "hotel",
        },
        headers=other_header,
    )
    assert create.status_code == 201, create.text
    secret_id = create.json()["id"]

    # Demote primary admin to a fresh, non-admin user so admin-bypass
    # doesn't help us here. Use a brand new account with role=viewer.
    from tests.modules.accommodation.conftest import _register_user

    _, _email, viewer_header = await _register_user(
        client,
        role="viewer",
        tag=uuid.uuid4().hex[:6],
    )

    probe = await client.get(
        f"/api/v1/accommodation/{secret_id}",
        headers=viewer_header,
    )
    # MUST be 404 — Wave-5 IDOR posture: don't reveal that the UUID exists.
    assert probe.status_code == 404, probe.text


@pytest.mark.asyncio
async def test_idor_random_uuid_is_404(
    client: AsyncClient,
    admin_auth: tuple[str, dict[str, str]],
):
    _, header = admin_auth
    bogus = uuid.uuid4()
    probe = await client.get(
        f"/api/v1/accommodation/{bogus}",
        headers=header,
    )
    assert probe.status_code == 404


@pytest.mark.asyncio
async def test_room_label_unique_per_accommodation(
    client: AsyncClient,
    admin_auth: tuple[str, dict[str, str]],
    project_id: str,
):
    _, header = admin_auth
    create = await client.post(
        "/api/v1/accommodation/",
        json={
            "project_id": project_id,
            "name": "Label Test",
            "kind": "hotel",
        },
        headers=header,
    )
    accom_id = create.json()["id"]

    first = await client.post(
        f"/api/v1/accommodation/{accom_id}/rooms",
        json={"rooms": [{"label": "777", "capacity": 1}]},
        headers=header,
    )
    assert first.status_code == 201

    dup = await client.post(
        f"/api/v1/accommodation/{accom_id}/rooms",
        json={"rooms": [{"label": "777", "capacity": 1}]},
        headers=header,
    )
    assert dup.status_code == 409
