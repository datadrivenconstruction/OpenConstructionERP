"""Reject overlapping live bookings on the same room (V6 regression).

Pre-fix the create endpoint accepted any number of overlapping bookings on
the same room — silently double-booking a hotel slot or worker bunk. The
service-layer guard now matches the half-open interval rule used by the
list-bookings overlap filter so the contract is symmetric on read+write.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _make_room(
    client: AsyncClient,
    header: dict[str, str],
    project_id: str,
    *,
    label: str = "RM-001",
) -> str:
    accom = await client.post(
        "/api/v1/accommodation/",
        json={"project_id": project_id, "name": f"Accom-{label}", "kind": "hotel"},
        headers=header,
    )
    accom_id = accom.json()["id"]
    rooms = await client.post(
        f"/api/v1/accommodation/{accom_id}/rooms",
        json={"rooms": [{"label": label, "capacity": 1, "status": "available"}]},
        headers=header,
    )
    return rooms.json()[0]["id"]


async def _book(
    client: AsyncClient,
    header: dict[str, str],
    room_id: str,
    *,
    check_in: str,
    check_out: str | None,
    status_val: str = "reserved",
    name: str = "Guest",
):
    body: dict = {
        "occupant_name": name,
        "check_in": check_in,
        "status": status_val,
    }
    if check_out is not None:
        body["check_out"] = check_out
    return await client.post(
        f"/api/v1/accommodation/rooms/{room_id}/bookings",
        json=body,
        headers=header,
    )


@pytest.mark.asyncio
async def test_overlap_full_inside_other_rejected(
    client: AsyncClient,
    admin_auth: tuple[str, dict[str, str]],
    project_id: str,
):
    _, header = admin_auth
    room_id = await _make_room(client, header, project_id, label="OV-A")

    r1 = await _book(client, header, room_id, check_in="2026-07-10", check_out="2026-07-20")
    assert r1.status_code == 201, r1.text

    r2 = await _book(
        client,
        header,
        room_id,
        check_in="2026-07-12",
        check_out="2026-07-15",
        name="Overlapper",
    )
    assert r2.status_code == 409, r2.text


@pytest.mark.asyncio
async def test_overlap_left_edge_rejected(
    client: AsyncClient,
    admin_auth: tuple[str, dict[str, str]],
    project_id: str,
):
    _, header = admin_auth
    room_id = await _make_room(client, header, project_id, label="OV-B")

    r1 = await _book(client, header, room_id, check_in="2026-07-10", check_out="2026-07-20")
    assert r1.status_code == 201

    # Starts before, ends inside — half-open overlap.
    r2 = await _book(client, header, room_id, check_in="2026-07-05", check_out="2026-07-12")
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_back_to_back_allowed(
    client: AsyncClient,
    admin_auth: tuple[str, dict[str, str]],
    project_id: str,
):
    _, header = admin_auth
    room_id = await _make_room(client, header, project_id, label="OV-C")

    r1 = await _book(client, header, room_id, check_in="2026-07-10", check_out="2026-07-15")
    assert r1.status_code == 201

    # Same room, check_in == previous check_out — half-open semantics
    # mean these don't overlap and should both be allowed.
    r2 = await _book(client, header, room_id, check_in="2026-07-15", check_out="2026-07-20")
    assert r2.status_code == 201, r2.text


@pytest.mark.asyncio
async def test_open_ended_blocks_future(
    client: AsyncClient,
    admin_auth: tuple[str, dict[str, str]],
    project_id: str,
):
    _, header = admin_auth
    room_id = await _make_room(client, header, project_id, label="OV-D")

    r1 = await _book(client, header, room_id, check_in="2026-07-10", check_out=None)
    assert r1.status_code == 201

    # Anything starting after the open-ended booking's check_in is blocked.
    r2 = await _book(client, header, room_id, check_in="2026-12-01", check_out="2026-12-05")
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_cancelled_booking_does_not_block(
    client: AsyncClient,
    admin_auth: tuple[str, dict[str, str]],
    project_id: str,
):
    _, header = admin_auth
    room_id = await _make_room(client, header, project_id, label="OV-E")

    r1 = await _book(client, header, room_id, check_in="2026-07-10", check_out="2026-07-20")
    assert r1.status_code == 201
    booking_id = r1.json()["id"]

    cancel = await client.patch(
        f"/api/v1/accommodation/bookings/{booking_id}",
        json={"status": "cancelled"},
        headers=header,
    )
    assert cancel.status_code == 200, cancel.text

    # Window is now free.
    r2 = await _book(client, header, room_id, check_in="2026-07-12", check_out="2026-07-15")
    assert r2.status_code == 201, r2.text


@pytest.mark.asyncio
async def test_patch_dates_into_overlap_rejected(
    client: AsyncClient,
    admin_auth: tuple[str, dict[str, str]],
    project_id: str,
):
    _, header = admin_auth
    room_id = await _make_room(client, header, project_id, label="OV-F")

    r1 = await _book(client, header, room_id, check_in="2026-07-10", check_out="2026-07-15")
    assert r1.status_code == 201

    r2 = await _book(client, header, room_id, check_in="2026-08-10", check_out="2026-08-15")
    assert r2.status_code == 201
    b2_id = r2.json()["id"]

    # PATCH b2's check_in back into b1's window — must 409.
    patch = await client.patch(
        f"/api/v1/accommodation/bookings/{b2_id}",
        json={"check_in": "2026-07-12", "check_out": "2026-07-14"},
        headers=header,
    )
    assert patch.status_code == 409, patch.text
