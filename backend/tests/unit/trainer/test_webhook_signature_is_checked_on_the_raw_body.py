# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The store webhook trusts only an HMAC over the raw bytes, bound to a fresh timestamp.

Every refusal below has its passing twin: the same body, headers and clock
with only the one property under test changed, so a check that refused
everything would fail the twin.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from app.modules.trainer import webhook
from app.modules.trainer.webhook import (
    REPLAY_WINDOW_SECONDS,
    VerifyFailure,
    compute_signature,
    verify_delivery,
)

SECRET = "whsec_unit_0123456789abcdef"
NOW = 1_790_000_000
BODY = json.dumps(
    {"id": "evt_1", "type": "order.paid", "data": {"offer_code": "p1", "email": "a@example.com"}},
    separators=(",", ":"),
).encode()


def _headers(body: bytes = BODY, *, ts: int = NOW, secret: str = SECRET, prefix: str = "sha256=") -> dict[str, str]:
    return {
        "X-OE-Timestamp": str(ts),
        "X-OE-Signature": prefix + compute_signature(secret, body, str(ts)),
    }


def test_a_correctly_signed_fresh_delivery_passes() -> None:
    assert verify_delivery(BODY, _headers(), SECRET, now=NOW) is None


def test_a_bare_hex_signature_and_any_header_case_pass() -> None:
    headers = {key.lower(): value for key, value in _headers(prefix="").items()}
    assert verify_delivery(BODY, headers, SECRET, now=NOW) is None


def test_the_signature_is_hmac_sha256_of_timestamp_dot_raw_body() -> None:
    expected = hmac.new(SECRET.encode(), f"{NOW}.".encode() + BODY, hashlib.sha256).hexdigest()
    assert compute_signature(SECRET, BODY, str(NOW)) == expected


def test_a_signature_made_with_another_secret_is_refused() -> None:
    assert verify_delivery(BODY, _headers(secret="whsec_other"), SECRET, now=NOW) is VerifyFailure.BAD_SIGNATURE


def test_a_body_changed_after_signing_is_refused() -> None:
    headers = _headers()
    tampered = BODY.replace(b"a@example.com", b"z@example.com")
    assert verify_delivery(BODY, headers, SECRET, now=NOW) is None
    assert verify_delivery(tampered, headers, SECRET, now=NOW) is VerifyFailure.BAD_SIGNATURE


def test_the_same_json_reserialised_is_refused() -> None:
    reserialised = json.dumps(json.loads(BODY), indent=2).encode()
    assert json.loads(reserialised) == json.loads(BODY)
    assert verify_delivery(reserialised, _headers(), SECRET, now=NOW) is VerifyFailure.BAD_SIGNATURE


def test_a_fresh_timestamp_on_an_old_signature_is_refused() -> None:
    """Replaying a captured body under a new timestamp header breaks the MAC."""
    old = _headers(ts=NOW - 3600)
    replayed = {"X-OE-Timestamp": str(NOW), "X-OE-Signature": old["X-OE-Signature"]}
    assert verify_delivery(BODY, replayed, SECRET, now=NOW) is VerifyFailure.BAD_SIGNATURE


@pytest.mark.parametrize("offset", [REPLAY_WINDOW_SECONDS + 1, -(REPLAY_WINDOW_SECONDS + 1), 86_400])
def test_a_timestamp_outside_the_window_is_refused(offset: int) -> None:
    assert verify_delivery(BODY, _headers(ts=NOW + offset), SECRET, now=NOW) is VerifyFailure.STALE_TIMESTAMP


@pytest.mark.parametrize("offset", [REPLAY_WINDOW_SECONDS, -REPLAY_WINDOW_SECONDS, 0])
def test_a_timestamp_inside_the_window_passes(offset: int) -> None:
    assert verify_delivery(BODY, _headers(ts=NOW + offset), SECRET, now=NOW) is None


@pytest.mark.parametrize(
    ("headers", "failure"),
    [
        ({}, VerifyFailure.MISSING_SIGNATURE),
        ({"X-OE-Signature": "sha256=" + "0" * 64}, VerifyFailure.MISSING_TIMESTAMP),
        ({"X-OE-Signature": "md5=abc", "X-OE-Timestamp": str(NOW)}, VerifyFailure.MALFORMED_SIGNATURE),
        ({"X-OE-Signature": "0" * 63, "X-OE-Timestamp": str(NOW)}, VerifyFailure.MALFORMED_SIGNATURE),
        ({"X-OE-Signature": "sha256=" + "0" * 64, "X-OE-Timestamp": "-5"}, VerifyFailure.MALFORMED_TIMESTAMP),
        ({"X-OE-Signature": "sha256=" + "0" * 64, "X-OE-Timestamp": "1e9"}, VerifyFailure.MALFORMED_TIMESTAMP),
    ],
)
def test_missing_or_malformed_headers_are_refused(headers: dict[str, str], failure: VerifyFailure) -> None:
    assert verify_delivery(BODY, headers, SECRET, now=NOW) is failure


def test_a_non_ascii_signature_is_refused_not_crashed() -> None:
    """Starlette decodes headers as latin-1; ``compare_digest`` on such a str raises."""
    headers = {"X-OE-Signature": "sha256=" + "é" * 64, "X-OE-Timestamp": str(NOW)}
    assert verify_delivery(BODY, headers, SECRET, now=NOW) is VerifyFailure.MALFORMED_SIGNATURE


def test_the_comparison_is_constant_time(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[bytes, bytes]] = []
    real = hmac.compare_digest

    def spy(a: bytes, b: bytes) -> bool:
        calls.append((a, b))
        return real(a, b)

    monkeypatch.setattr(webhook.hmac, "compare_digest", spy)
    assert verify_delivery(BODY, _headers(), SECRET, now=NOW) is None
    assert verify_delivery(BODY, _headers(secret="other"), SECRET, now=NOW) is VerifyFailure.BAD_SIGNATURE
    assert len(calls) == 2
    assert all(isinstance(a, bytes) and isinstance(b, bytes) for a, b in calls)
