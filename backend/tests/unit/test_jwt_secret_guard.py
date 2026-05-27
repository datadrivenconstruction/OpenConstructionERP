"""JWT secret guard — security audit 2026-05-24 follow-up.

The model validator ``_refuse_default_jwt_in_non_dev`` on ``Settings`` is the
single point that prevents a fresh ``docker compose up`` from accidentally
shipping with the bundled dev JWT secret. The audit asked us to harden it:

* reject *any* known weak default in non-dev (``change-me``, ``secret``,
  ``jwt-secret``, etc.) — not just the bundled one;
* reject secrets shorter than ``_JWT_SECRET_MIN_LENGTH`` (32 chars) in
  non-dev, regardless of whether they look "random";
* in dev, log a one-shot WARNING with the secret length and a reminder
  to set ``OE_JWT_SECRET`` before shipping.

These tests pin all three behaviours so a future refactor can't silently
weaken the guard.
"""

from __future__ import annotations

import logging

import pytest

from app.config import (
    _JWT_KNOWN_WEAK_SECRETS,
    _JWT_SECRET_MIN_LENGTH,
    Settings,
    reset_jwt_dev_warning,
)

# A safe-by-construction secret used wherever a test needs to *succeed*
# in non-dev — long enough to pass the 32-char floor, not in the known-
# weak set, and visually obvious that it's test fixture data.
_GOOD_SECRET = "x" * 40  # 40 > 32, not in _JWT_KNOWN_WEAK_SECRETS


def _build(**overrides):
    """Construct ``Settings`` without touching the on-disk .env file.

    Mirrors the pattern in ``test_config.py`` — passing ``_env_file=None``
    short-circuits pydantic-settings' .env loader, so the test only sees
    the kwargs we explicitly pass.
    """
    defaults = {
        "_env_file": None,
        "database_url": "sqlite+aiosqlite:///./test.db",
        "database_sync_url": "sqlite:///./test.db",
    }
    defaults.update(overrides)
    return Settings(**defaults)


class TestRejectsWeakSecretInProduction:
    """``app_env=production`` MUST refuse every known weak secret + short ones."""

    @pytest.mark.parametrize("weak", sorted(_JWT_KNOWN_WEAK_SECRETS))
    def test_known_weak_default_rejected(self, weak: str) -> None:
        with pytest.raises(RuntimeError) as excinfo:
            _build(app_env="production", app_debug=False, jwt_secret=weak)
        msg = str(excinfo.value)
        # The error should name the bad value and tell the operator how
        # to generate a fresh one — these are the two pieces of info a
        # fast incident response actually needs.
        assert "well-known weak default" in msg
        assert weak in msg
        assert "secrets.token_urlsafe" in msg or "openssl rand" in msg

    def test_change_me_explicitly_rejected(self) -> None:
        # Spelled out so the trip-wire shows up by name in test output if
        # someone tries to add ``"change-me"`` to a deployment template.
        with pytest.raises(RuntimeError):
            _build(app_env="production", app_debug=False, jwt_secret="change-me")

    def test_short_secret_rejected(self) -> None:
        # 31 chars — one byte below the floor — exercise the length gate
        # without overlapping the known-weak gate.
        secret = "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P"  # noqa: S105
        assert len(secret) < _JWT_SECRET_MIN_LENGTH
        assert secret not in _JWT_KNOWN_WEAK_SECRETS
        with pytest.raises(RuntimeError) as excinfo:
            _build(app_env="production", app_debug=False, jwt_secret=secret)
        msg = str(excinfo.value)
        assert "only" in msg and "characters" in msg
        assert str(_JWT_SECRET_MIN_LENGTH) in msg

    def test_empty_secret_rejected(self) -> None:
        # Empty / None is treated as "0 chars" — rejected by the length
        # gate. Guards against an operator who set ``JWT_SECRET=`` and
        # expected the model default to kick in (it does not — pydantic
        # passes through the empty string).
        with pytest.raises(RuntimeError):
            _build(app_env="production", app_debug=False, jwt_secret="")

    def test_staging_rejects_same_as_production(self) -> None:
        # The guard fires for any non-development APP_ENV, not just
        # production. Staging is the most common forgotten environment.
        with pytest.raises(RuntimeError):
            _build(
                app_env="staging",
                jwt_secret="openestimate-local-dev-key",
            )


class TestAcceptsStrongSecretInProduction:
    """A long, non-default secret MUST boot cleanly in production."""

    def test_long_random_secret_accepted(self) -> None:
        s = _build(app_env="production", app_debug=False, jwt_secret=_GOOD_SECRET)
        assert s.jwt_secret == _GOOD_SECRET
        assert s.is_production is True

    def test_exactly_min_length_accepted(self) -> None:
        # Boundary: a secret of *exactly* the minimum length passes.
        # Anything < min should fail (tested above); == min should pass.
        secret = "a" * _JWT_SECRET_MIN_LENGTH
        s = _build(app_env="production", app_debug=False, jwt_secret=secret)
        assert len(s.jwt_secret) == _JWT_SECRET_MIN_LENGTH


class TestDevelopmentWarningPath:
    """``app_env=development`` is permissive but MUST log a one-shot warning."""

    def setup_method(self) -> None:
        # Re-arm the once-per-process latch so each test sees a fresh
        # warning emission opportunity.
        reset_jwt_dev_warning()

    def test_dev_with_default_secret_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger="openestimate.config"):
            s = _build(app_env="development", jwt_secret="openestimate-local-dev-key")
        assert s.jwt_secret == "openestimate-local-dev-key"
        # Exactly one matching warning expected.
        matching = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and "JWT_SECRET" in r.message and "bundled development default" in r.message
        ]
        assert len(matching) == 1
        # The warning should report the length (26 chars for the bundled
        # default ``openestimate-local-dev-key``) so the operator can tell
        # at a glance whether they're still on the default without
        # echoing the secret itself.
        expected_len = len("openestimate-local-dev-key")
        assert f"length={expected_len}" in matching[0].message
        # And it should point at the override env var so the next step
        # is obvious.
        assert "OE_JWT_SECRET" in matching[0].message

    def test_dev_warning_is_one_shot(self, caplog: pytest.LogCaptureFixture) -> None:
        # Construct twice — second instantiation must NOT re-emit the
        # warning, so log noise stays bounded under hot-reload / repeated
        # Settings() construction in tests.
        with caplog.at_level(logging.WARNING, logger="openestimate.config"):
            _build(app_env="development", jwt_secret="openestimate-local-dev-key")
            _build(app_env="development", jwt_secret="openestimate-local-dev-key")
        matching = [r for r in caplog.records if "bundled development default" in r.message]
        assert len(matching) == 1

    def test_dev_with_strong_secret_logs_nothing(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger="openestimate.config"):
            _build(app_env="development", jwt_secret=_GOOD_SECRET)
        matching = [r for r in caplog.records if "bundled development default" in r.message]
        assert matching == []

    def test_dev_with_short_secret_does_not_raise(self) -> None:
        # The length gate is intentionally a no-op in dev so a fresh
        # checkout can run with whatever is in .env without ceremony.
        # We don't assert "no warning" here — short non-default secrets
        # in dev are common (e.g. ``test``) and the warning path is
        # specifically about the BUNDLED default, not about length.
        s = _build(app_env="development", jwt_secret="short")
        assert s.jwt_secret == "short"
