"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The settings model must accept the documented ``OE_``-prefixed env vars.

Regression guard for a production report: ``OE_REGISTRATION_MODE`` (the spelling
used throughout the docs, examples and deployment guides) was silently ignored
because the settings model declared no ``env_prefix``, so only the bare
``REGISTRATION_MODE`` bound to the field. An operator who set
``OE_REGISTRATION_MODE=closed`` got the default ("admin-approve") instead.

The fix adds a second, ``OE_``-prefixed environment source. Both spellings now
populate the field and the bare name keeps priority, so existing deployments
that already use the unprefixed variables are unaffected.
"""

from __future__ import annotations

import pytest

from app.config import Settings


def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    # Construction runs the JWT-secret validator; development mode + a strong
    # secret keep it lenient regardless of what APP_ENV/JWT_SECRET the CI
    # environment happens to set. Clear both registration spellings so each
    # test starts from a known blank slate (conftest sets a bare default).
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("JWT_SECRET", "unit-test-secret-0123456789-abcdefghij")
    for name in ("REGISTRATION_MODE", "OE_REGISTRATION_MODE"):
        monkeypatch.delenv(name, raising=False)


def test_oe_prefixed_var_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate(monkeypatch)
    monkeypatch.setenv("OE_REGISTRATION_MODE", "closed")
    settings = Settings(_env_file=None)
    assert settings.registration_mode == "closed"


def test_bare_var_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate(monkeypatch)
    monkeypatch.setenv("REGISTRATION_MODE", "email-verify")
    settings = Settings(_env_file=None)
    assert settings.registration_mode == "email-verify"


def test_bare_name_wins_when_both_set(monkeypatch: pytest.MonkeyPatch) -> None:
    _isolate(monkeypatch)
    monkeypatch.setenv("REGISTRATION_MODE", "open")
    monkeypatch.setenv("OE_REGISTRATION_MODE", "closed")
    settings = Settings(_env_file=None)
    assert settings.registration_mode == "open"


def test_oe_prefix_works_for_other_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    # The fix is generic, not special-cased to registration_mode: any field the
    # docs document with an OE_ prefix should resolve the same way.
    _isolate(monkeypatch)
    monkeypatch.delenv("SLOW_QUERY_MS", raising=False)
    monkeypatch.setenv("OE_SLOW_QUERY_MS", "1234")
    settings = Settings(_env_file=None)
    assert settings.slow_query_ms == 1234
