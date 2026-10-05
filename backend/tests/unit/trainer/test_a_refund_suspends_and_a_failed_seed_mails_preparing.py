# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Wave 2 contract additions that need no database.

* A refund or chargeback payload maps to ``OrderRefunded`` (decision 42).
* A failed seed sends the "being prepared" welcome, never "ready" (decision 41).
* An unknown readback names what the learner can do only when there is an
  action (decision 40).
* The hint reveal answer is self-consistent (decision 30).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.trainer.checker.grading import readback_reason_key
from app.modules.trainer.checker.registry import OPEN_LEVELING_KEY, ProbeResult
from app.modules.trainer.provisioning import welcome_html, welcome_subject
from app.modules.trainer.schemas import HintRevealResult, ReadbackValue, RevealedHint
from app.modules.trainer.webhook import REFUND_TYPES, OrderRefunded, PayloadError, parse_generic_payload


@pytest.mark.parametrize("event_type", sorted(REFUND_TYPES))
def test_a_refund_maps_to_order_refunded_and_grants_nothing(event_type: str) -> None:
    event = parse_generic_payload(
        {
            "id": "evt_9",
            "type": event_type,
            "data": {"email": " Buyer@Example.COM ", "offer_code": "course-uk-1", "card": {"last4": "4242"}},
        }
    )
    assert event.order is None
    assert event.refund == OrderRefunded(event_id="evt_9", email="buyer@example.com", offer_code="course-uk-1")
    assert "card" not in event.payload["data"]


def test_a_refund_without_an_email_is_a_payload_error() -> None:
    with pytest.raises(PayloadError):
        parse_generic_payload({"id": "evt_9", "type": "order.refunded", "data": {"offer_code": "x"}})


@pytest.mark.parametrize("locale", ["en", "de", "fr", "es", "ru"])
def test_a_failed_seed_mails_the_preparing_variant(locale: str) -> None:
    ready = welcome_subject(locale, ["Course"], queued=False)
    preparing = welcome_subject(locale, ["Course"], queued=False, preparing=True)
    assert preparing != ready
    common = {
        "locale": locale,
        "name": "Learner",
        "email": "learner@example.com",
        "course_titles": ["Course"],
        "queued": False,
        "reset_url": None,
        "forgot_url": "https://example.com/forgot",
        "academy_url": "https://example.com/academy",
    }
    assert welcome_html(**common, preparing=True) != welcome_html(**common)


def _unknown(detail: str | None) -> ProbeResult:
    return ProbeResult(value=None, unit="money", status="unknown", detail=detail)


def test_only_an_uncomputed_levelling_table_names_an_action() -> None:
    assert readback_reason_key(_unknown("not_computed: open the levelling view")) == OPEN_LEVELING_KEY
    assert readback_reason_key(_unknown("not_found: no such bid")) is None
    assert readback_reason_key(_unknown(None)) is None
    assert readback_reason_key(None) is None


def test_a_reading_with_a_value_carries_no_reason() -> None:
    with pytest.raises(ValidationError):
        ReadbackValue(id="rb0", state="match", app_value="1.00", kind="money", reason_key=OPEN_LEVELING_KEY)
    item = ReadbackValue(id="rb0", state="unknown", app_value=None, kind="money", reason_key=OPEN_LEVELING_KEY)
    assert item.reason_key == OPEN_LEVELING_KEY


def test_a_hint_reveal_returns_the_last_revealed_hint() -> None:
    ok = HintRevealResult(hint=RevealedHint(index=1, text="b"), hints_revealed=2, hints_total=2)
    assert ok.hint.index == 1
    with pytest.raises(ValidationError):
        HintRevealResult(hint=RevealedHint(index=0, text="a"), hints_revealed=2, hints_total=2)
    with pytest.raises(ValidationError):
        HintRevealResult(hint=RevealedHint(index=2, text="c"), hints_revealed=3, hints_total=2)
