"""Money / Decimal precision tests for charges.

Float coercion would silently break sub-cent precision on rollups; this
suite ensures every dollar/euro stays exact through the API round-trip
and that DB persistence keeps the Decimal type.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient


async def _make_booking(
    client: AsyncClient,
    header: dict[str, str],
    project_id: str,
) -> str:
    """Create an accommodation + room + booking, return the booking id."""
    accom = await client.post(
        "/api/v1/accommodation/",
        json={"project_id": project_id, "name": "ChargeTest", "kind": "hotel"},
        headers=header,
    )
    accom_id = accom.json()["id"]
    rooms = await client.post(
        f"/api/v1/accommodation/{accom_id}/rooms",
        json={
            "rooms": [
                {
                    "label": "CH-1",
                    "capacity": 1,
                    "base_rate": "199.99",
                    "base_rate_currency": "EUR",
                },
            ],
        },
        headers=header,
    )
    room_id = rooms.json()[0]["id"]
    booking = await client.post(
        f"/api/v1/accommodation/rooms/{room_id}/bookings",
        json={
            "occupant_name": "Decimal Tester",
            "check_in": "2026-11-01",
            "check_out": "2026-11-03",
        },
        headers=header,
    )
    return booking.json()["id"]


@pytest.mark.asyncio
async def test_charge_amount_round_trips_exactly(
    client: AsyncClient,
    admin_auth: tuple[str, dict[str, str]],
    project_id: str,
):
    """``0.10 + 0.20`` is exact when stored as Decimal — proves no float coercion."""
    _, header = admin_auth
    booking_id = await _make_booking(client, header, project_id)

    a = await client.post(
        f"/api/v1/accommodation/bookings/{booking_id}/charges",
        json={
            "kind": "extra",
            "description": "minibar",
            "amount": "0.10",
            "currency": "EUR",
        },
        headers=header,
    )
    b = await client.post(
        f"/api/v1/accommodation/bookings/{booking_id}/charges",
        json={
            "kind": "extra",
            "description": "minibar 2",
            "amount": "0.20",
            "currency": "EUR",
        },
        headers=header,
    )
    assert a.status_code == 201
    assert b.status_code == 201

    lst = await client.get(
        f"/api/v1/accommodation/bookings/{booking_id}/charges",
        headers=header,
    )
    assert lst.status_code == 200
    charges = lst.json()
    total = sum(Decimal(str(c["amount"])) for c in charges)
    assert total == Decimal("0.30"), f"expected exact 0.30, got {total!r} — float coercion suspected"


@pytest.mark.asyncio
async def test_high_precision_amount_preserved(
    client: AsyncClient,
    admin_auth: tuple[str, dict[str, str]],
    project_id: str,
):
    """A cents value like 199.99 must come back unchanged (no float drift)."""
    _, header = admin_auth
    booking_id = await _make_booking(client, header, project_id)

    create = await client.post(
        f"/api/v1/accommodation/bookings/{booking_id}/charges",
        json={
            "kind": "base_rent",
            "amount": "199.99",
            "currency": "USD",
        },
        headers=header,
    )
    assert create.status_code == 201, create.text
    assert Decimal(str(create.json()["amount"])) == Decimal("199.99")


@pytest.mark.asyncio
async def test_currency_inheritance_when_blank(
    client: AsyncClient,
    admin_auth: tuple[str, dict[str, str]],
    project_id: str,
):
    """Blank charge currency inherits from the room's base_rate_currency."""
    _, header = admin_auth
    booking_id = await _make_booking(client, header, project_id)

    create = await client.post(
        f"/api/v1/accommodation/bookings/{booking_id}/charges",
        json={"kind": "extra", "amount": "12.50"},
        headers=header,
    )
    assert create.status_code == 201, create.text
    # Room was created with EUR base_rate_currency above.
    assert create.json()["currency"] == "EUR"


@pytest.mark.asyncio
async def test_negative_amount_rejected(
    client: AsyncClient,
    admin_auth: tuple[str, dict[str, str]],
    project_id: str,
):
    """Negative amounts must 422 — refunds are modelled as kind='refund'."""
    _, header = admin_auth
    booking_id = await _make_booking(client, header, project_id)

    resp = await client.post(
        f"/api/v1/accommodation/bookings/{booking_id}/charges",
        json={"kind": "extra", "amount": "-5.00", "currency": "EUR"},
        headers=header,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_persisted_amount_is_decimal_type(
    client: AsyncClient,
    admin_auth: tuple[str, dict[str, str]],
    project_id: str,
):
    """Direct DB read must yield a Decimal — proves the column type stuck."""
    _, header = admin_auth
    booking_id = await _make_booking(client, header, project_id)
    create = await client.post(
        f"/api/v1/accommodation/bookings/{booking_id}/charges",
        json={"kind": "extra", "amount": "42.42", "currency": "EUR"},
        headers=header,
    )
    charge_id = create.json()["id"]

    import uuid

    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.accommodation.models import Charge

    async with async_session_factory() as sess:
        row = (await sess.execute(select(Charge).where(Charge.id == uuid.UUID(charge_id)))).scalar_one()
        assert isinstance(row.amount, Decimal), f"expected Decimal, got {type(row.amount).__name__}"
        assert row.amount == Decimal("42.42")
