"""Booking state-machine + date-validation tests."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _make_room(
    client: AsyncClient,
    header: dict[str, str],
    project_id: str,
    *,
    kind: str = "hotel",
    label: str = "RM-001",
    room_status: str = "available",
) -> str:
    """Helper: create an accommodation + one room, return room_id."""
    accom = await client.post(
        "/api/v1/accommodation/",
        json={"project_id": project_id, "name": f"Accom-{label}", "kind": kind},
        headers=header,
    )
    accom_id = accom.json()["id"]
    rooms = await client.post(
        f"/api/v1/accommodation/{accom_id}/rooms",
        json={"rooms": [{"label": label, "capacity": 1, "status": room_status}]},
        headers=header,
    )
    return rooms.json()[0]["id"]


@pytest.mark.asyncio
async def test_reject_check_out_not_after_check_in(
    client: AsyncClient,
    admin_auth: tuple[str, dict[str, str]],
    project_id: str,
):
    _, header = admin_auth
    room_id = await _make_room(client, header, project_id, label="SM-A")

    resp = await client.post(
        f"/api/v1/accommodation/rooms/{room_id}/bookings",
        json={
            "occupant_name": "Alice",
            "check_in": "2026-06-10",
            "check_out": "2026-06-10",  # same day — invalid
        },
        headers=header,
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_reject_booking_on_maintenance_room(
    client: AsyncClient,
    admin_auth: tuple[str, dict[str, str]],
    project_id: str,
):
    _, header = admin_auth
    room_id = await _make_room(
        client,
        header,
        project_id,
        label="SM-MAINT",
        room_status="maintenance",
    )

    resp = await client.post(
        f"/api/v1/accommodation/rooms/{room_id}/bookings",
        json={
            "occupant_name": "Bob",
            "check_in": "2026-06-10",
            "check_out": "2026-06-12",
        },
        headers=header,
    )
    assert resp.status_code == 409, resp.text


@pytest.mark.asyncio
async def test_legal_full_lifecycle(
    client: AsyncClient,
    admin_auth: tuple[str, dict[str, str]],
    project_id: str,
):
    """reserved → checked_in → checked_out is always allowed."""
    _, header = admin_auth
    room_id = await _make_room(client, header, project_id, label="SM-FLOW")

    create = await client.post(
        f"/api/v1/accommodation/rooms/{room_id}/bookings",
        json={
            "occupant_name": "Cara",
            "check_in": "2026-07-01",
            "check_out": "2026-07-05",
        },
        headers=header,
    )
    assert create.status_code == 201
    booking_id = create.json()["id"]

    to_in = await client.patch(
        f"/api/v1/accommodation/bookings/{booking_id}",
        json={"status": "checked_in"},
        headers=header,
    )
    assert to_in.status_code == 200
    assert to_in.json()["status"] == "checked_in"

    to_out = await client.patch(
        f"/api/v1/accommodation/bookings/{booking_id}",
        json={"status": "checked_out"},
        headers=header,
    )
    assert to_out.status_code == 200
    assert to_out.json()["status"] == "checked_out"


@pytest.mark.asyncio
async def test_reject_illegal_transitions(
    client: AsyncClient,
    admin_auth: tuple[str, dict[str, str]],
    project_id: str,
):
    """``reserved → checked_out`` (skip checked_in) and any move out of
    a terminal state must be rejected with 409."""
    _, header = admin_auth
    room_id = await _make_room(client, header, project_id, label="SM-BAD")

    create = await client.post(
        f"/api/v1/accommodation/rooms/{room_id}/bookings",
        json={
            "occupant_name": "Drew",
            "check_in": "2026-08-01",
            "check_out": "2026-08-03",
        },
        headers=header,
    )
    booking_id = create.json()["id"]

    skip = await client.patch(
        f"/api/v1/accommodation/bookings/{booking_id}",
        json={"status": "checked_out"},
        headers=header,
    )
    assert skip.status_code == 409, skip.text

    # Cancel from reserved is legal.
    cancel = await client.patch(
        f"/api/v1/accommodation/bookings/{booking_id}",
        json={"status": "cancelled"},
        headers=header,
    )
    assert cancel.status_code == 200

    # And re-opening from cancelled is forbidden.
    reopen = await client.patch(
        f"/api/v1/accommodation/bookings/{booking_id}",
        json={"status": "reserved"},
        headers=header,
    )
    assert reopen.status_code == 409


@pytest.mark.asyncio
async def test_open_ended_booking_allowed(
    client: AsyncClient,
    admin_auth: tuple[str, dict[str, str]],
    project_id: str,
):
    """Worker-camp residency frequently has no check-out date."""
    _, header = admin_auth
    room_id = await _make_room(
        client,
        header,
        project_id,
        kind="worker_camp",
        label="SM-CAMP",
    )

    resp = await client.post(
        f"/api/v1/accommodation/rooms/{room_id}/bookings",
        json={
            "occupant_name": "Eli",
            "check_in": "2026-09-01",
            # check_out omitted on purpose
        },
        headers=header,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["check_out"] is None


@pytest.mark.asyncio
async def test_booking_requires_occupant(
    client: AsyncClient,
    admin_auth: tuple[str, dict[str, str]],
    project_id: str,
):
    """Either occupant_contact_id OR occupant_name must be supplied."""
    _, header = admin_auth
    room_id = await _make_room(client, header, project_id, label="SM-EMPTY")

    resp = await client.post(
        f"/api/v1/accommodation/rooms/{room_id}/bookings",
        json={
            "check_in": "2026-10-01",
            "check_out": "2026-10-02",
        },
        headers=header,
    )
    assert resp.status_code == 422, resp.text
