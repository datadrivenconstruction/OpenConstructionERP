"""HR-driven room-suggestion tests.

The suggestion endpoint must:
    * return the lowest-labelled available worker-camp room
    * skip non worker-camp accommodations entirely
    * 404 when no candidate room exists
    * 404 when the employee contact doesn't exist
    * NOT mutate room status (the UI confirms before booking)
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient


@pytest_asyncio.fixture
async def hr_contact(admin_auth: tuple[str, dict[str, str]]) -> str:
    """Seed a contact via the public Contacts API."""
    from app.database import async_session_factory
    from app.modules.contacts.models import Contact

    async with async_session_factory() as sess:
        c = Contact(
            contact_type="employee",
            first_name="Sven",
            last_name="Crew",
        )
        sess.add(c)
        await sess.commit()
        return str(c.id)


async def _make_camp_with_rooms(
    client: AsyncClient,
    header: dict[str, str],
    project_id: str,
    labels: list[str],
    *,
    kind: str = "worker_camp",
    statuses: list[str] | None = None,
    name: str = "Sugg Camp",
) -> str:
    accom = await client.post(
        "/api/v1/accommodation/",
        json={"project_id": project_id, "name": name, "kind": kind},
        headers=header,
    )
    accom_id = accom.json()["id"]
    statuses = statuses or ["available"] * len(labels)
    rooms = [{"label": lbl, "capacity": 1, "status": st} for lbl, st in zip(labels, statuses, strict=True)]
    add = await client.post(
        f"/api/v1/accommodation/{accom_id}/rooms",
        json={"rooms": rooms},
        headers=header,
    )
    assert add.status_code == 201, add.text
    return accom_id


@pytest.mark.asyncio
async def test_returns_lowest_available_room(
    client: AsyncClient,
    admin_auth: tuple[str, dict[str, str]],
    project_id: str,
    hr_contact: str,
):
    _, header = admin_auth
    await _make_camp_with_rooms(
        client,
        header,
        project_id,
        labels=["B-202", "B-101", "B-303"],
        name="Sorted Camp",
    )

    resp = await client.post(
        "/api/v1/accommodation/bookings/suggest-from-hr",
        json={
            "employee_contact_id": hr_contact,
            "start_date": "2026-12-01",
        },
        headers=header,
    )
    assert resp.status_code == 200, resp.text
    # Lexicographic minimum of the three labels.
    assert resp.json()["room_label"] == "B-101"


@pytest.mark.asyncio
async def test_skips_blocked_and_maintenance_rooms(
    client: AsyncClient,
    admin_auth: tuple[str, dict[str, str]],
    project_id: str,
    hr_contact: str,
):
    _, header = admin_auth
    await _make_camp_with_rooms(
        client,
        header,
        project_id,
        labels=["A-101", "A-102", "A-103"],
        statuses=["maintenance", "blocked", "available"],
        name="Mixed Camp",
    )

    resp = await client.post(
        "/api/v1/accommodation/bookings/suggest-from-hr",
        json={
            "employee_contact_id": hr_contact,
            "start_date": "2026-12-01",
        },
        headers=header,
    )
    assert resp.status_code == 200
    # Only A-103 is available — even though A-101 lex-sorts first.
    assert resp.json()["room_label"] == "A-103"


@pytest.mark.asyncio
async def test_skips_non_worker_camp(
    client: AsyncClient,
    admin_auth: tuple[str, dict[str, str]],
    project_id: str,
    hr_contact: str,
):
    """Hotel / rental accommodations are never suggested.

    Asserts on ``accommodation_kind`` rather than 404 — prior tests in
    this module may have left available worker-camp rooms in the shared
    fixture project, so the suggester legitimately returns a camp room.
    What we MUST prove is that a hotel room is never picked even though
    it's available, lexicographically lowest, and freshly seeded.
    """
    _, header = admin_auth
    await _make_camp_with_rooms(
        client,
        header,
        project_id,
        labels=["AAA-001"],  # would lex-sort first if hotels were eligible
        kind="hotel",
        name="Should Skip Hotel",
    )

    resp = await client.post(
        "/api/v1/accommodation/bookings/suggest-from-hr",
        json={
            "employee_contact_id": hr_contact,
            "start_date": "2026-12-01",
        },
        headers=header,
    )
    # 200 (a camp room was found) or 404 (no camp rooms at all) is fine;
    # what's NOT fine is a hotel being suggested.
    assert resp.status_code in (200, 404), resp.text
    if resp.status_code == 200:
        assert resp.json()["accommodation_kind"] == "worker_camp", "non worker_camp accommodation was suggested"


@pytest.mark.asyncio
async def test_404_when_no_available_room(
    client: AsyncClient,
    admin_auth: tuple[str, dict[str, str]],
    project_id: str,
    hr_contact: str,
):
    _, header = admin_auth
    # All rooms blocked.
    await _make_camp_with_rooms(
        client,
        header,
        project_id,
        labels=["X-1", "X-2"],
        statuses=["blocked", "blocked"],
        name="All Blocked",
    )

    # Previous tests in the module may have seeded available worker-camp
    # rooms. Force every worker-camp room (across all tests' fixtures) to
    # "blocked" so this assertion is deterministic regardless of order.
    from sqlalchemy import select, update

    from app.database import async_session_factory
    from app.modules.accommodation.models import Accommodation, Room

    async with async_session_factory() as sess:
        camp_ids = (
            (await sess.execute(select(Accommodation.id).where(Accommodation.kind == "worker_camp"))).scalars().all()
        )
        if camp_ids:
            await sess.execute(update(Room).where(Room.accommodation_id.in_(camp_ids)).values(status="blocked"))
        await sess.commit()

    resp = await client.post(
        "/api/v1/accommodation/bookings/suggest-from-hr",
        json={
            "employee_contact_id": hr_contact,
            "start_date": "2026-12-01",
        },
        headers=header,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_404_when_employee_contact_missing(
    client: AsyncClient,
    admin_auth: tuple[str, dict[str, str]],
    project_id: str,
):
    _, header = admin_auth
    bogus_contact = uuid.uuid4()
    resp = await client.post(
        "/api/v1/accommodation/bookings/suggest-from-hr",
        json={
            "employee_contact_id": str(bogus_contact),
            "start_date": "2026-12-01",
        },
        headers=header,
    )
    assert resp.status_code == 404
