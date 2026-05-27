"""Tests for the accommodation/room booking list endpoints.

Covers:
    * GET /accommodation/{id}/bookings — paginated multi-room list with
      ``room_label`` decoration
    * Status filter (single + multi value)
    * Date-overlap filter
    * IDOR — 404 (not 403) when the caller can't see the project
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


async def _create_accom_with_rooms(
    client: AsyncClient,
    header: dict[str, str],
    project_id: str,
    *,
    name: str,
    labels: list[str],
) -> tuple[str, list[str]]:
    """Helper: create one accommodation + N rooms; return ``(accom_id, room_ids)``."""
    accom = await client.post(
        "/api/v1/accommodation/",
        json={"project_id": project_id, "name": name, "kind": "worker_camp"},
        headers=header,
    )
    assert accom.status_code in (200, 201), accom.text
    accom_id = accom.json()["id"]

    rooms = await client.post(
        f"/api/v1/accommodation/{accom_id}/rooms",
        json={"rooms": [{"label": lbl, "capacity": 1} for lbl in labels]},
        headers=header,
    )
    assert rooms.status_code == 201, rooms.text
    room_ids = [r["id"] for r in rooms.json()]
    return accom_id, room_ids


async def _make_booking(
    client: AsyncClient,
    header: dict[str, str],
    room_id: str,
    *,
    name: str,
    check_in: str,
    check_out: str | None,
    status_: str = "reserved",
) -> str:
    payload: dict = {
        "occupant_name": name,
        "check_in": check_in,
        "status": status_,
    }
    if check_out is not None:
        payload["check_out"] = check_out
    resp = await client.post(
        f"/api/v1/accommodation/rooms/{room_id}/bookings",
        json=payload,
        headers=header,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_list_for_accommodation_paginated(
    client: AsyncClient,
    admin_auth: tuple[str, dict[str, str]],
    project_id: str,
):
    """Create 7 bookings across 3 rooms → list returns all 7 with room_label."""
    _, header = admin_auth
    accom_id, room_ids = await _create_accom_with_rooms(
        client,
        header,
        project_id,
        name="List-A",
        labels=["LA-1", "LA-2", "LA-3"],
    )

    # 3 bookings on LA-1, 2 on LA-2, 2 on LA-3 = 7 total.
    layout = [
        (room_ids[0], "LA-1", 3),
        (room_ids[1], "LA-2", 2),
        (room_ids[2], "LA-3", 2),
    ]
    expected_label_by_room: dict[str, str] = {}
    created_ids: set[str] = set()
    for rid, label, count in layout:
        expected_label_by_room[rid] = label
        for i in range(count):
            month = 6 + i  # 6,7,8 → distinct months to keep the test stable
            check_in = f"2026-{month:02d}-01"
            check_out = f"2026-{month:02d}-15"
            bid = await _make_booking(
                client,
                header,
                rid,
                name=f"{label}-occ-{i}",
                check_in=check_in,
                check_out=check_out,
            )
            created_ids.add(bid)

    resp = await client.get(
        f"/api/v1/accommodation/{accom_id}/bookings",
        headers=header,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body
    items = body["items"]
    assert len(items) == 7, items
    # All ids match.
    assert {it["id"] for it in items} == created_ids
    # ``room_label`` is populated for every row and matches the parent room.
    for it in items:
        assert it["room_label"] == expected_label_by_room[it["room_id"]]
    # Pagination shape.
    assert body["limit"] == 50
    assert body["offset"] == 0


@pytest.mark.asyncio
async def test_list_filters_by_status(
    client: AsyncClient,
    admin_auth: tuple[str, dict[str, str]],
    project_id: str,
):
    """``?status=reserved`` returns only reserved bookings; multi-value works too."""
    _, header = admin_auth
    accom_id, room_ids = await _create_accom_with_rooms(
        client,
        header,
        project_id,
        name="List-Status",
        labels=["LS-1", "LS-2"],
    )

    # 1 reserved on LS-1, 1 checked_in on LS-2.
    bid_reserved = await _make_booking(
        client,
        header,
        room_ids[0],
        name="reserved-occupant",
        check_in="2027-01-01",
        check_out="2027-01-05",
        status_="reserved",
    )
    bid_checked_in = await _make_booking(
        client,
        header,
        room_ids[1],
        name="checked-in-occupant",
        check_in="2027-02-01",
        check_out="2027-02-05",
        status_="checked_in",
    )

    # Only reserved.
    resp = await client.get(
        f"/api/v1/accommodation/{accom_id}/bookings?status=reserved",
        headers=header,
    )
    assert resp.status_code == 200, resp.text
    ids = [it["id"] for it in resp.json()["items"]]
    assert ids == [bid_reserved], ids

    # Multi-value: both reserved + checked_in.
    resp = await client.get(
        f"/api/v1/accommodation/{accom_id}/bookings?status=reserved&status=checked_in",
        headers=header,
    )
    assert resp.status_code == 200, resp.text
    ids = {it["id"] for it in resp.json()["items"]}
    assert ids == {bid_reserved, bid_checked_in}

    # Unknown status → 422.
    bad = await client.get(
        f"/api/v1/accommodation/{accom_id}/bookings?status=ghost",
        headers=header,
    )
    assert bad.status_code == 422, bad.text


@pytest.mark.asyncio
async def test_list_filters_by_date_overlap(
    client: AsyncClient,
    admin_auth: tuple[str, dict[str, str]],
    project_id: str,
):
    """A booking 2026-06-01 → 2026-06-15 is included when the filter
    window is 2026-06-10 → 2026-06-12, and excluded when the window is
    fully outside its range."""
    _, header = admin_auth
    accom_id, room_ids = await _create_accom_with_rooms(
        client,
        header,
        project_id,
        name="List-Dates",
        labels=["LD-1"],
    )
    bid = await _make_booking(
        client,
        header,
        room_ids[0],
        name="window-occupant",
        check_in="2026-06-01",
        check_out="2026-06-15",
    )
    # Also create one that doesn't overlap at all.
    bid_other = await _make_booking(
        client,
        header,
        room_ids[0],
        name="other-occupant",
        check_in="2027-01-01",
        check_out="2027-01-05",
    )

    # Overlapping window — should include bid but not bid_other.
    overlap = await client.get(
        f"/api/v1/accommodation/{accom_id}/bookings?from_date=2026-06-10&to_date=2026-06-12",
        headers=header,
    )
    assert overlap.status_code == 200, overlap.text
    ids = {it["id"] for it in overlap.json()["items"]}
    assert bid in ids
    assert bid_other not in ids

    # Window entirely before both bookings — empty result.
    miss = await client.get(
        f"/api/v1/accommodation/{accom_id}/bookings?from_date=2025-01-01&to_date=2025-12-31",
        headers=header,
    )
    assert miss.status_code == 200, miss.text
    assert miss.json()["items"] == []


@pytest.mark.asyncio
async def test_list_idor_404(
    client: AsyncClient,
    admin_auth: tuple[str, dict[str, str]],
    project_id: str,
):
    """A user without access to project A gets 404 (not 403) for its bookings.

    Uses a fresh ``viewer`` user — admin would bypass the access gate
    entirely via ``_user_is_admin``.
    """
    _, header_a = admin_auth
    accom_id, room_ids = await _create_accom_with_rooms(
        client,
        header_a,
        project_id,
        name="IDOR-target",
        labels=["IX-1"],
    )
    await _make_booking(
        client,
        header_a,
        room_ids[0],
        name="secret-occupant",
        check_in="2026-06-01",
        check_out="2026-06-02",
    )

    # Non-admin viewer in a different scope must NOT see this.
    from tests.modules.accommodation.conftest import _register_user

    _, _email, viewer_header = await _register_user(
        client,
        role="viewer",
        tag=f"lb-{uuid.uuid4().hex[:6]}",
    )

    resp = await client.get(
        f"/api/v1/accommodation/{accom_id}/bookings",
        headers=viewer_header,
    )
    assert resp.status_code == 404, resp.text

    # Same posture for the room-scoped endpoint.
    resp = await client.get(
        f"/api/v1/accommodation/rooms/{room_ids[0]}/bookings",
        headers=viewer_header,
    )
    assert resp.status_code == 404, resp.text
