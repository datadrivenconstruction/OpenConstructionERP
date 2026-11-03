# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Webhook signing, replay window, retry schedule and outcome rules.

Pure functions: no I/O, no clock of their own. Callers pass ``now`` so tests
can freeze time and receivers can reuse :func:`verify_signature` as is.

Wire format::

    X-OE-Signature: t=<unix seconds>,v1=<hex hmac_sha256(secret, f"{t}.{body}")>
"""

from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, timedelta
from typing import Literal

SIGNATURE_HEADER = "X-OE-Signature"
LEGACY_SIGNATURE_HEADER = "X-Webhook-Signature"  # body-only HMAC, kept for two releases
EVENT_HEADER = "X-OE-Event"
DELIVERY_HEADER = "X-OE-Delivery"

#: A signature older (or newer) than this many seconds is rejected by receivers.
REPLAY_WINDOW_S = 300

#: Wait before retry n (n = failed sends so far): 1 min, 5 min, 30 min, 6 h.
RETRY_DELAYS_S: tuple[int, ...] = (60, 300, 1800, 21600)
MAX_ATTEMPTS = len(RETRY_DELAYS_S) + 1

Outcome = Literal["delivered", "retry", "dead"]


def sign(secret: str, timestamp: int, body: bytes) -> str:
    """Hex HMAC-SHA256 of ``"<timestamp>."`` followed by the raw body."""
    return hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()


def signature_header(secret: str, body: bytes, now: int | None = None) -> str:
    """Value of ``X-OE-Signature`` for ``body`` at ``now`` (unix seconds)."""
    t = int(time.time()) if now is None else int(now)
    return f"t={t},v1={sign(secret, t, body)}"


def legacy_signature(secret: str, body: bytes) -> str:
    """Value of the old ``X-Webhook-Signature`` header: HMAC of the body alone."""
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def parse_signature_header(header: str) -> tuple[int, list[str]] | None:
    """Split ``t=...,v1=...`` into the timestamp and the v1 digests; ``None`` if malformed."""
    timestamp: int | None = None
    digests: list[str] = []
    for part in header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            try:
                timestamp = int(value)
            except ValueError:
                return None
        elif key == "v1" and value:
            digests.append(value)
    if timestamp is None or not digests:
        return None
    return timestamp, digests


def verify_signature(
    secret: str,
    header: str,
    body: bytes,
    *,
    now: int | None = None,
    tolerance_s: int = REPLAY_WINDOW_S,
) -> bool:
    """Check an ``X-OE-Signature`` header the way a receiver should.

    False when the header is malformed, the timestamp lies outside
    ``tolerance_s`` of ``now`` (replay), or no digest matches. The digest is
    compared in constant time.
    """
    parsed = parse_signature_header(header or "")
    if parsed is None:
        return False
    timestamp, digests = parsed
    current = int(time.time()) if now is None else int(now)
    if abs(current - timestamp) > tolerance_s:
        return False
    expected = sign(secret, timestamp, body)
    return any(hmac.compare_digest(expected, d) for d in digests)


def next_retry_at(attempts_made: int, now: datetime) -> datetime | None:
    """When to try again after ``attempts_made`` failed sends; ``None`` once the schedule is spent."""
    if attempts_made < 1 or attempts_made > len(RETRY_DELAYS_S):
        return None
    return now + timedelta(seconds=RETRY_DELAYS_S[attempts_made - 1])


def classify_status(status_code: int) -> Outcome:
    """2xx is delivered; 408 and 429 and 5xx are worth retrying; any other status is final.

    Redirects are never followed, so a 3xx is a final failure like a 4xx.
    """
    if 200 <= status_code < 300:
        return "delivered"
    if status_code in (408, 429) or status_code >= 500:
        return "retry"
    return "dead"
