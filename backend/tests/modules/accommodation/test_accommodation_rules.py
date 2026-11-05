"""The ``accommodation`` rule set: each rule on its own, then enforced at the write points."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.modules.accommodation.validators import (
    ACCOMMODATION_RULE_SET,
    BookingDatesOrderedRule,
    CapacityCoversRoomsRule,
    ChargeCurrencyRule,
    ChargePeriodRule,
    RoomRateMatchesKindRule,
    register_accommodation_validation_rules,
)


async def _run(rule: object, data: dict, locale: str = "en"):
    return await rule.validate(ValidationContext(data=data, metadata={"locale": locale}))


def _failed(results: list) -> list:
    return [r for r in results if not r.passed]


# ── Each rule fires, and a valid record passes ──────────────────────────────


@pytest.mark.asyncio
async def test_booking_dates_rule() -> None:
    rule = BookingDatesOrderedRule()
    ok = {"booking": {"id": "b", "check_in": "2026-11-01", "check_out": "2026-11-03"}}
    open_ended = {"booking": {"id": "b", "check_in": "2026-11-01", "check_out": None}}
    bad = {"booking": {"id": "b", "check_in": "2026-11-05", "check_out": "2026-11-03"}}
    assert not _failed(await _run(rule, ok))
    assert not _failed(await _run(rule, open_ended))
    failed = _failed(await _run(rule, bad))
    assert len(failed) == 1 and failed[0].severity == Severity.ERROR


@pytest.mark.asyncio
async def test_charge_period_rule_orders_and_warns_outside_stay() -> None:
    rule = ChargePeriodRule()
    stay = {"stay_start": "2026-11-01", "stay_end": "2026-11-10"}
    ok = {"charge": {"id": "c", "period_start": "2026-11-02", "period_end": "2026-11-09", **stay}}
    backwards = {"charge": {"id": "c", "period_start": "2026-11-09", "period_end": "2026-11-02", **stay}}
    outside = {"charge": {"id": "c", "period_start": "2026-11-02", "period_end": "2026-11-20", **stay}}
    assert not _failed(await _run(rule, ok))
    assert _failed(await _run(rule, backwards))[0].severity == Severity.ERROR
    assert _failed(await _run(rule, outside))[0].severity == Severity.WARNING


@pytest.mark.asyncio
async def test_charge_currency_rule() -> None:
    rule = ChargeCurrencyRule()
    assert not _failed(await _run(rule, {"charge": {"id": "c", "amount": "10", "currency": "EUR"}}))
    assert not _failed(await _run(rule, {"charge": {"id": "c", "amount": "0", "currency": ""}}))
    failed = _failed(await _run(rule, {"charge": {"id": "c", "amount": "10", "currency": " "}}))
    assert len(failed) == 1 and failed[0].severity == Severity.ERROR


@pytest.mark.asyncio
async def test_capacity_rule_is_a_warning() -> None:
    rule = CapacityCoversRoomsRule()
    ok = {"accommodation": {"id": "a", "capacity_total": 10, "rooms_capacity_total": 10}}
    unstated = {"accommodation": {"id": "a", "capacity_total": 0, "rooms_capacity_total": 40}}
    bad = {"accommodation": {"id": "a", "capacity_total": 10, "rooms_capacity_total": 14}}
    assert not _failed(await _run(rule, ok))
    assert not _failed(await _run(rule, unstated))
    failed = _failed(await _run(rule, bad))
    assert len(failed) == 1 and failed[0].severity == Severity.WARNING


@pytest.mark.asyncio
async def test_room_rate_rule() -> None:
    rule = RoomRateMatchesKindRule()
    hotel = {
        "accommodation": {"id": "a", "kind": "hotel"},
        "rooms": [{"id": "r", "label": "1", "base_rate": "80", "currency": "EUR"}],
    }
    camp_free = {
        "accommodation": {"id": "a", "kind": "worker_camp"},
        "rooms": [{"id": "r", "label": "1", "base_rate": "0", "currency": ""}],
    }
    camp_paid = {
        "accommodation": {"id": "a", "kind": "worker_camp"},
        "rooms": [{"id": "r", "label": "1", "base_rate": "80", "currency": "EUR"}],
    }
    no_currency = {
        "accommodation": {"id": "a", "kind": "hotel"},
        "rooms": [{"id": "r", "label": "1", "base_rate": "80", "currency": ""}],
    }
    assert not _failed(await _run(rule, hotel))
    assert not _failed(await _run(rule, camp_free))
    assert len(_failed(await _run(rule, camp_paid))) == 1
    assert len(_failed(await _run(rule, no_currency))) == 1
    assert all(r.severity == Severity.WARNING for r in _failed(await _run(rule, camp_paid)))


@pytest.mark.asyncio
async def test_messages_come_back_in_the_callers_language() -> None:
    bad = {"booking": {"id": "b", "check_in": "2026-11-05", "check_out": "2026-11-03"}}
    en = _failed(await _run(BookingDatesOrderedRule(), bad, "en"))[0].message
    de = _failed(await _run(BookingDatesOrderedRule(), bad, "de"))[0].message
    assert en != de and "2026-11-03" in de


def test_rules_are_registered_in_the_set() -> None:
    register_accommodation_validation_rules()
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets([ACCOMMODATION_RULE_SET])}
    assert {
        "accommodation.booking_dates_ordered",
        "accommodation.charge_period",
        "accommodation.charge_currency",
        "accommodation.capacity_covers_rooms",
        "accommodation.room_rate",
    } <= ids


# ── Enforced at the API write points ────────────────────────────────────────


async def _accom(client: AsyncClient, header: dict, project_id: str, **over) -> str:
    body = {"project_id": project_id, "name": f"R-{uuid.uuid4().hex[:6]}", "kind": "hotel", **over}
    resp = await client.post("/api/v1/accommodation/", json=body, headers=header)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _room(client: AsyncClient, header: dict, accom_id: str, **over) -> dict:
    room = {"label": f"R{uuid.uuid4().hex[:5]}", "capacity": 1, "base_rate": "50", "base_rate_currency": "EUR", **over}
    resp = await client.post(f"/api/v1/accommodation/{accom_id}/rooms", json={"rooms": [room]}, headers=header)
    assert resp.status_code == 201, resp.text
    return resp.json()[0]


async def _booking(client: AsyncClient, header: dict, room_id: str, check_in: str, check_out: str) -> dict:
    resp = await client.post(
        f"/api/v1/accommodation/rooms/{room_id}/bookings",
        json={"occupant_name": "Crew", "check_in": check_in, "check_out": check_out},
        headers=header,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _rule_ids(resp) -> set[str]:
    return {e["rule_id"] for e in resp.json()["detail"]["errors"]}


@pytest.mark.asyncio
async def test_patching_one_date_past_the_other_is_refused_with_the_rule_code(client, admin_auth, project_id) -> None:
    _, header = admin_auth
    room = await _room(client, header, await _accom(client, header, project_id))
    booking = await _booking(client, header, room["id"], "2026-12-01", "2026-12-05")
    resp = await client.patch(
        f"/api/v1/accommodation/bookings/{booking['id']}", json={"check_in": "2026-12-10"}, headers=header
    )
    assert resp.status_code == 422, resp.text
    assert "accommodation.booking_dates_ordered" in _rule_ids(resp)
    stored = await client.get(f"/api/v1/accommodation/bookings/{booking['id']}", headers=header)
    assert stored.json()["check_in"] == "2026-12-01"


@pytest.mark.asyncio
async def test_a_legacy_violating_booking_stays_editable(client, admin_auth, project_id) -> None:
    from sqlalchemy import text

    from app.database import async_session_factory

    _, header = admin_auth
    room = await _room(client, header, await _accom(client, header, project_id))
    booking = await _booking(client, header, room["id"], "2027-01-01", "2027-01-05")
    async with async_session_factory() as session:
        await session.execute(
            text("UPDATE oe_accommodation_booking SET check_out = '2026-12-20' WHERE id = :i"),
            {"i": booking["id"]},
        )
        await session.commit()
    resp = await client.patch(
        f"/api/v1/accommodation/bookings/{booking['id']}", json={"occupant_name": "Renamed crew"}, headers=header
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["occupant_name"] == "Renamed crew"


@pytest.mark.asyncio
async def test_charge_period_pushed_backwards_is_refused(client, admin_auth, project_id) -> None:
    _, header = admin_auth
    room = await _room(client, header, await _accom(client, header, project_id))
    booking = await _booking(client, header, room["id"], "2027-02-01", "2027-02-10")
    made = await client.post(
        f"/api/v1/accommodation/bookings/{booking['id']}/charges",
        json={
            "kind": "extra",
            "amount": "40",
            "currency": "EUR",
            "period_start": "2027-02-01",
            "period_end": "2027-02-03",
        },
        headers=header,
    )
    assert made.status_code == 201, made.text
    assert made.json()["validation_warnings"] == []
    resp = await client.patch(
        f"/api/v1/accommodation/charges/{made.json()['id']}", json={"period_start": "2027-02-09"}, headers=header
    )
    assert resp.status_code == 422, resp.text
    assert "accommodation.charge_period" in _rule_ids(resp)


@pytest.mark.asyncio
async def test_charge_outside_the_stay_is_reported_not_blocked(client, admin_auth, project_id) -> None:
    _, header = admin_auth
    room = await _room(client, header, await _accom(client, header, project_id))
    booking = await _booking(client, header, room["id"], "2027-03-01", "2027-03-05")
    resp = await client.post(
        f"/api/v1/accommodation/bookings/{booking['id']}/charges",
        json={
            "kind": "extra",
            "amount": "40",
            "currency": "EUR",
            "period_start": "2027-03-04",
            "period_end": "2027-03-20",
        },
        headers=header,
    )
    assert resp.status_code == 201, resp.text
    assert [w["rule_id"] for w in resp.json()["validation_warnings"]] == ["accommodation.charge_period"]


@pytest.mark.asyncio
async def test_charge_without_any_currency_is_refused(client, admin_auth, project_id) -> None:
    _, header = admin_auth
    # The fixture project states no currency and the room carries none either.
    room = await _room(client, header, await _accom(client, header, project_id), base_rate="0", base_rate_currency="")
    booking = await _booking(client, header, room["id"], "2027-04-01", "2027-04-05")
    resp = await client.post(
        f"/api/v1/accommodation/bookings/{booking['id']}/charges",
        json={"kind": "extra", "amount": "40"},
        headers=header,
    )
    assert resp.status_code == 422, resp.text
    assert "accommodation.charge_currency" in _rule_ids(resp)
    ok = await client.post(
        f"/api/v1/accommodation/bookings/{booking['id']}/charges",
        json={"kind": "extra", "amount": "40", "currency": "EUR"},
        headers=header,
    )
    assert ok.status_code == 201, ok.text


@pytest.mark.asyncio
async def test_rooms_over_the_rated_capacity_warn_on_bulk_create_and_update(client, admin_auth, project_id) -> None:
    _, header = admin_auth
    accom_id = await _accom(client, header, project_id, capacity_total=3)
    resp = await client.post(
        f"/api/v1/accommodation/{accom_id}/rooms",
        json={"rooms": [{"label": "A", "capacity": 2}, {"label": "B", "capacity": 4}]},
        headers=header,
    )
    assert resp.status_code == 201, resp.text
    assert {w["rule_id"] for r in resp.json() for w in r["validation_warnings"]} == {
        "accommodation.capacity_covers_rooms"
    }
    patched = await client.patch(f"/api/v1/accommodation/{accom_id}", json={"capacity_total": 20}, headers=header)
    assert patched.status_code == 200 and patched.json()["validation_warnings"] == []


@pytest.mark.asyncio
async def test_camp_room_with_a_rate_warns(client, admin_auth, project_id) -> None:
    _, header = admin_auth
    accom_id = await _accom(client, header, project_id, kind="worker_camp")
    resp = await client.post(
        f"/api/v1/accommodation/{accom_id}/rooms",
        json={"rooms": [{"label": "C1", "capacity": 4, "base_rate": "30", "base_rate_currency": "EUR"}]},
        headers=header,
    )
    assert resp.status_code == 201, resp.text
    assert [w["rule_id"] for w in resp.json()[0]["validation_warnings"]] == ["accommodation.room_rate"]
    room_id = resp.json()[0]["id"]
    again = await client.patch(f"/api/v1/accommodation/rooms/{room_id}", json={"capacity": 5}, headers=header)
    assert again.status_code == 200, again.text
    assert Decimal(again.json()["base_rate"]) == Decimal("30")
