# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Webhook signature format, replay window, retry schedule and status rules (pure)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.modules.integrations import webhook_signing as ws

SECRET = "whsec_test_secret_0123456789abcdef"
BODY = b'{"event":"ping"}'
T = 1700000000
DIGEST = "a70a711c5f52ad54882edafa369d18004043461fff3191bfe1fd1831e417219b"
LEGACY_DIGEST = "64c8a10f9b085d60c7c153797706460f4eb2dc37e339e509771a995245186edd"


def test_signature_test_vector():
    assert ws.sign(SECRET, T, BODY) == DIGEST
    assert ws.signature_header(SECRET, BODY, T) == f"t={T},v1={DIGEST}"
    assert ws.legacy_signature(SECRET, BODY) == LEGACY_DIGEST


def test_verify_accepts_a_fresh_signature():
    header = ws.signature_header(SECRET, BODY, T)
    assert ws.verify_signature(SECRET, header, BODY, now=T)
    assert ws.verify_signature(SECRET, header, BODY, now=T + ws.REPLAY_WINDOW_S)


@pytest.mark.parametrize("skew", [ws.REPLAY_WINDOW_S + 1, 3600, -(ws.REPLAY_WINDOW_S + 1)])
def test_replay_window_rejects_old_and_future_timestamps(skew):
    header = ws.signature_header(SECRET, BODY, T)
    assert not ws.verify_signature(SECRET, header, BODY, now=T + skew)


def test_verify_rejects_tampering_and_junk():
    header = ws.signature_header(SECRET, BODY, T)
    assert not ws.verify_signature(SECRET, header, BODY + b" ", now=T)
    assert not ws.verify_signature("another-secret-of-24-chars!!", header, BODY, now=T)
    assert not ws.verify_signature(SECRET, f"t={T + 1},v1={DIGEST}", BODY, now=T)  # timestamp is part of the MAC
    for junk in ("", "garbage", f"t=abc,v1={DIGEST}", f"t={T}", f"v1={DIGEST}"):
        assert not ws.verify_signature(SECRET, junk, BODY, now=T)


def test_verify_accepts_any_matching_v1_among_several():
    header = f"t={T},v1={'0' * 64},v1={DIGEST}"
    assert ws.verify_signature(SECRET, header, BODY, now=T)


def test_backoff_schedule_exact_timestamps():
    t0 = datetime(2026, 11, 3, 12, 0, 0, tzinfo=UTC)
    got = [ws.next_retry_at(n, t0) for n in range(0, 7)]
    assert got == [
        None,
        datetime(2026, 11, 3, 12, 1, 0, tzinfo=UTC),  # after the 1st failure: 1 min
        datetime(2026, 11, 3, 12, 5, 0, tzinfo=UTC),  # 5 min
        datetime(2026, 11, 3, 12, 30, 0, tzinfo=UTC),  # 30 min
        datetime(2026, 11, 3, 18, 0, 0, tzinfo=UTC),  # 6 h
        None,  # the 5th failure ends it
        None,
    ]
    assert ws.MAX_ATTEMPTS == 5


@pytest.mark.parametrize(
    ("code", "outcome"),
    [
        (200, "delivered"),
        (204, "delivered"),
        (299, "delivered"),
        (301, "dead"),
        (302, "dead"),
        (400, "dead"),
        (401, "dead"),
        (404, "dead"),
        (410, "dead"),
        (422, "dead"),
        (408, "retry"),
        (429, "retry"),
        (500, "retry"),
        (502, "retry"),
        (503, "retry"),
    ],
)
def test_status_classification(code, outcome):
    assert ws.classify_status(code) == outcome
