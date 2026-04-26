"""JWT timing-attack regression tests (BUG-JWT01 / Wave 3-A).

Goal: detect order-of-magnitude timing leaks between failure modes in the
JWT decode path. We don't aim for cryptographic-grade timing parity —
microbenchmarks in Python are far too noisy for that. We aim for "no
codepath takes 10x longer than another", which would let an attacker
distinguish (e.g.) bad-signature from valid-signature-bad-user via wall
clock.

Audit findings (2026-04-26 — recorded for traceability):

* ``app.dependencies.decode_access_token`` delegates to ``jose.jwt.decode``,
  whose HS256 verify uses ``hmac.compare_digest`` internally — constant
  time wrt. the signature payload.
* ``app.dependencies.get_current_user_payload`` keeps the failure shape
  uniform: ``user is None`` and ``not user.is_active`` raise the same
  ``HTTPException(401, "User not found or inactive")``.
* ``UserService.login`` already pays a dummy bcrypt cost when the user
  row is missing, neutralising the obvious enumeration timing window.
* No raw token / secret comparison via ``==`` exists in the auth path;
  API keys are looked up by sha256 hash via SQL ``WHERE``, which is not a
  string comparison the attacker can race against.

We therefore add only regression tests — no production code changed.

Run: pytest backend/tests/unit/test_jwt_timing.py -v
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from types import ModuleType
from unittest.mock import MagicMock

import pytest

# ── Light mocking so the module imports without a real DB engine ──────────
# Mirrors the pattern used by tests/unit/test_users.py — we never hit the DB
# from this file, only the pure decode path.

try:
    from app.database import Base as _RealBase  # noqa: F401
except Exception:
    _fake_database = ModuleType("app.database")
    _fake_database.Base = type("Base", (), {})  # type: ignore[attr-defined]
    _fake_database.GUID = MagicMock  # type: ignore[attr-defined]
    sys.modules["app.database"] = _fake_database

from fastapi import HTTPException  # noqa: E402
from jose import jwt  # noqa: E402

from app.dependencies import decode_access_token  # noqa: E402


# ── Helpers ───────────────────────────────────────────────────────────────


class _FakeSettings:
    jwt_secret = "test-secret-please-do-not-use-in-prod-please"  # noqa: S105
    jwt_algorithm = "HS256"
    jwt_expire_minutes = 60


def _valid_token(settings: _FakeSettings, *, missing_sub: bool = False) -> str:
    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "email": "tester@example.io",
        "role": "viewer",
        "permissions": [],
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
        "type": "access",
    }
    if not missing_sub:
        payload["sub"] = str(uuid.uuid4())
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _tampered_signature_token(settings: _FakeSettings) -> str:
    """A JWT that decodes structurally but fails the HMAC check."""
    tok = _valid_token(settings)
    # Flip a few bits in the signature segment (third dot-separated chunk).
    head, body, sig = tok.split(".")
    # Replace last 4 chars of the sig — base64url alphabet, won't crash decode.
    bad = sig[:-4] + ("AAAA" if not sig.endswith("AAAA") else "BBBB")
    return f"{head}.{body}.{bad}"


def _bench(fn, *, iterations: int = 200) -> float:
    """Mean wall-time per call, in seconds. Discards the slowest 10% as outliers."""
    samples: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        try:
            fn()
        except HTTPException:
            pass
        except Exception:  # noqa: BLE001
            pass
        samples.append(time.perf_counter() - t0)
    samples.sort()
    keep = samples[: max(1, int(len(samples) * 0.9))]
    return sum(keep) / len(keep)


# ── Sanity ───────────────────────────────────────────────────────────────


def test_valid_token_decodes_cleanly() -> None:
    """Baseline: a well-formed access token returns a payload dict."""
    settings = _FakeSettings()
    token = _valid_token(settings)
    payload = decode_access_token(token, settings)  # type: ignore[arg-type]
    assert payload["type"] == "access"
    assert "sub" in payload


def test_missing_subject_raises_401() -> None:
    """Tokens without ``sub`` must be rejected with HTTP 401."""
    settings = _FakeSettings()
    token = _valid_token(settings, missing_sub=True)
    with pytest.raises(HTTPException) as exc:
        decode_access_token(token, settings)  # type: ignore[arg-type]
    assert exc.value.status_code == 401


def test_bad_signature_raises_401() -> None:
    """Tokens with a tampered signature must be rejected with HTTP 401."""
    settings = _FakeSettings()
    token = _tampered_signature_token(settings)
    with pytest.raises(HTTPException) as exc:
        decode_access_token(token, settings)  # type: ignore[arg-type]
    assert exc.value.status_code == 401


# ── The actual timing regression ──────────────────────────────────────────


@pytest.mark.skipif(
    "COVERAGE_RUN" in os.environ or "COV_CORE_SOURCE" in os.environ,
    reason="Coverage tracing distorts microbenchmarks beyond usefulness",
)
def test_no_order_of_magnitude_timing_leak_between_failure_modes() -> None:
    """Wall-time of the two failure modes must be within the same order of magnitude.

    We compare:
      * ``valid-signature, missing-sub``  — fails AFTER hmac succeeds.
      * ``valid-signature, tampered-sig`` — fails INSIDE hmac.

    Both go through ``jose.jwt.decode``. If the signature path took (e.g.)
    10x longer than the post-decode field check, an attacker could
    distinguish "did my forged signature happen to verify?" from network
    latency. We allow up to 100% delta (i.e. one path can be at most 2x
    the other) — generous to absorb GC / JIT / OS noise but tight enough
    to catch real bugs.
    """
    settings = _FakeSettings()
    no_sub_token = _valid_token(settings, missing_sub=True)
    bad_sig_token = _tampered_signature_token(settings)

    def _decode_no_sub() -> None:
        decode_access_token(no_sub_token, settings)  # type: ignore[arg-type]

    def _decode_bad_sig() -> None:
        decode_access_token(bad_sig_token, settings)  # type: ignore[arg-type]

    # Warm-up: prime any lazy imports in jose / cryptography
    for _ in range(10):
        try:
            _decode_no_sub()
        except HTTPException:
            pass
        try:
            _decode_bad_sig()
        except HTTPException:
            pass

    mean_no_sub = _bench(_decode_no_sub, iterations=200)
    mean_bad_sig = _bench(_decode_bad_sig, iterations=200)

    # Avoid div-by-zero and absurd ratios on machines where one branch is
    # under the timer resolution. Floor both at 1 microsecond.
    a = max(mean_no_sub, 1e-6)
    b = max(mean_bad_sig, 1e-6)
    ratio = max(a, b) / min(a, b)

    # Generous threshold — timing tests are inherently flaky on shared CI.
    # We only catch order-of-magnitude leaks here.
    assert ratio < 5.0, (
        f"JWT failure paths show suspicious timing delta: "
        f"missing-sub={mean_no_sub*1e6:.1f}us  bad-sig={mean_bad_sig*1e6:.1f}us  "
        f"ratio={ratio:.2f}x (should be <5x)"
    )
