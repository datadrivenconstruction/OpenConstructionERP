# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the inbound webhook signature-verification seam.

Pure (no DB, no app, no network): exercises
:func:`verify_provider_signature` and its helpers directly. Proves the seam
fails closed when no secret is configured and when the signature is wrong /
missing, accepts a correct HMAC over the RAW body (with and without the
``sha256=`` prefix), is byte-exact (a re-serialised body does not verify) and is
keyed per provider via the documented environment variable.
"""

from __future__ import annotations

import hashlib
import hmac

import pytest

from app.modules.inbound_capture.router import (
    _provider_secret_env_name,
    resolve_provider_secret,
    verify_provider_signature,
)


def _sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def test_secret_env_name_is_normalized() -> None:
    assert _provider_secret_env_name("twilio") == "INBOUND_CAPTURE_SECRET__TWILIO"
    # Non-alphanumerics map to underscore and the name is upper-cased.
    assert _provider_secret_env_name("ms-teams") == "INBOUND_CAPTURE_SECRET__MS_TEAMS"


def test_resolve_secret_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INBOUND_CAPTURE_SECRET__TWILIO", "s3cr3t")
    assert resolve_provider_secret("twilio") == "s3cr3t"
    # Unconfigured provider -> None (verification then fails closed).
    monkeypatch.delenv("INBOUND_CAPTURE_SECRET__SLACK", raising=False)
    assert resolve_provider_secret("slack") is None


def test_verify_fails_closed_without_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INBOUND_CAPTURE_SECRET__TWILIO", raising=False)
    body = b'{"id": "m1"}'
    headers = {"x-inbound-signature": _sign("whatever", body)}
    # No secret configured for the provider -> reject, never trust the body.
    assert verify_provider_signature("twilio", body, headers) is False


def test_verify_accepts_correct_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "s3cr3t"
    monkeypatch.setenv("INBOUND_CAPTURE_SECRET__TWILIO", secret)
    body = b'{"id": "m1", "from": "+15551230000", "text": "hi"}'
    headers = {"x-inbound-signature": _sign(secret, body)}
    assert verify_provider_signature("twilio", body, headers) is True


def test_verify_accepts_sha256_prefixed_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "s3cr3t"
    monkeypatch.setenv("INBOUND_CAPTURE_SECRET__GITHUBISH", secret)
    body = b'{"id": "m2"}'
    headers = {"x-hub-signature-256": "sha256=" + _sign(secret, body)}
    assert verify_provider_signature("githubish", body, headers) is True


def test_verify_rejects_wrong_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INBOUND_CAPTURE_SECRET__TWILIO", "right-secret")
    body = b'{"id": "m1"}'
    headers = {"x-inbound-signature": _sign("wrong-secret", body)}
    assert verify_provider_signature("twilio", body, headers) is False


def test_verify_rejects_missing_signature_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INBOUND_CAPTURE_SECRET__TWILIO", "s3cr3t")
    body = b'{"id": "m1"}'
    assert verify_provider_signature("twilio", body, {}) is False


def test_verify_is_byte_exact(monkeypatch: pytest.MonkeyPatch) -> None:
    """A signature over the raw bytes must not verify against altered bytes."""
    secret = "s3cr3t"
    monkeypatch.setenv("INBOUND_CAPTURE_SECRET__TWILIO", secret)
    signed_body = b'{"id":"m1"}'
    # Same JSON, different bytes (whitespace) - signature must NOT carry over.
    reserialized = b'{"id": "m1"}'
    headers = {"x-inbound-signature": _sign(secret, signed_body)}
    assert verify_provider_signature("twilio", reserialized, headers) is False
    assert verify_provider_signature("twilio", signed_body, headers) is True
