# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The generic adapter maps a store payload to ``OrderPaid`` and strips payment PII."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.modules.trainer.webhook import (
    ADAPTERS,
    DEFAULT_PROVIDER,
    GENERIC_ADAPTER,
    ORDER_PAID,
    OrderPaid,
    PayloadError,
    parse_generic_payload,
    redact_payload,
)


def _payload(**data_overrides: object) -> dict:
    data: dict[str, object] = {
        "offer_code": "course-de-1",
        "order_ref": "ord-77",
        "email": "  Buyer@Example.COM ",
        "name": "Erika Muster",
        "locale": "de-AT",
        "paid_at": "2026-10-05T10:00:00Z",
        "amount": "199.00",
        "currency": "EUR",
        "billing_address": {"street": "Hauptstr. 1", "city": "Wien"},
        "phone": "+43 1 234",
        "card": {"last4": "4242"},
        "tax_id": "ATU123",
        "customer": {"vatNumber": "ATU999", "company": "Muster GmbH", "ipAddress": "203.0.113.9"},
    }
    data.update(data_overrides)
    return {"id": "evt_42", "type": ORDER_PAID, "data": data}


def test_a_paid_order_maps_to_order_paid() -> None:
    event = parse_generic_payload(_payload())
    assert event.event_id == "evt_42"
    assert event.event_type == ORDER_PAID
    assert event.order == OrderPaid(
        event_id="evt_42",
        offer_code="course-de-1",
        order_ref="ord-77",
        email="buyer@example.com",
        name="Erika Muster",
        locale="de-AT",
        paid_at=datetime(2026, 10, 5, 10, 0, tzinfo=UTC),
    )


def test_the_stored_payload_keeps_the_buyer_and_drops_payment_pii() -> None:
    stored = parse_generic_payload(_payload()).payload["data"]
    assert stored["email"].strip().lower() == "buyer@example.com"
    assert stored["name"] == "Erika Muster"
    assert stored["amount"] == "199.00"
    assert stored["customer"] == {"company": "Muster GmbH"}
    for gone in ("billing_address", "phone", "card", "tax_id"):
        assert gone not in stored


def test_redaction_matches_word_parts_not_substrings() -> None:
    kept = {"company": 1, "description": 2, "recipient": 3, "shipped": 4}
    dropped = {"ip": 1, "zip": 2, "shippingAddress": 3, "mobile_phone": 4, "IBAN": 5, "pan": 6}
    assert redact_payload({**kept, **dropped}) == kept
    assert redact_payload([{"phone": 1, "ok": 2}]) == [{"ok": 2}]


def test_an_unknown_event_type_maps_without_an_order() -> None:
    event = parse_generic_payload({"id": "evt_9", "type": "order.refunded", "data": {"phone": "1"}})
    assert event.order is None
    assert event.event_type == "order.refunded"
    assert event.payload == {"id": "evt_9", "type": "order.refunded", "data": {}}


@pytest.mark.parametrize(
    ("payload", "has_event_id"),
    [
        ([], False),
        ({"type": ORDER_PAID}, False),
        ({"id": "", "type": ORDER_PAID}, False),
        ({"id": "x" * 129, "type": ORDER_PAID}, False),
        ({"id": "evt_1"}, True),
        ({"id": "evt_1", "type": ORDER_PAID}, True),
        ({"id": "evt_1", "type": ORDER_PAID, "data": "nope"}, True),
    ],
)
def test_a_payload_of_the_wrong_shape_is_refused(payload: object, has_event_id: bool) -> None:
    with pytest.raises(PayloadError) as caught:
        parse_generic_payload(payload)
    assert (caught.value.event_id is not None) is has_event_id


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"email": "not-an-email"}, "email"),
        ({"offer_code": None}, "offer_code"),
        ({"paid_at": "2026-10-05T10:00:00"}, "paid_at"),
        ({"paid_at": None}, "paid_at"),
    ],
)
def test_a_bad_order_field_is_named_without_its_value(override: dict, field: str) -> None:
    with pytest.raises(PayloadError) as caught:
        parse_generic_payload(_payload(**override))
    assert field in caught.value.reason
    assert caught.value.event_id == "evt_42"
    assert "not-an-email" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True


def test_the_generic_adapter_is_the_default_provider() -> None:
    assert ADAPTERS[DEFAULT_PROVIDER] is GENERIC_ADAPTER
    assert GENERIC_ADAPTER.signature_header == GENERIC_ADAPTER.signature_header.lower()
    assert GENERIC_ADAPTER.timestamp_header == GENERIC_ADAPTER.timestamp_header.lower()
