"""A gated registration mode must never strand a user whose gate cannot be delivered."""

from __future__ import annotations

import pytest

from app.config import Settings, effective_registration_mode


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    for key in ("OE_REGISTRATION_MODE", "REGISTRATION_MODE", "OE_EMAIL_BACKEND", "OE_SMTP_HOST", "OE_DESKTOP"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)


def test_email_verify_without_smtp_is_open(monkeypatch):
    s = _settings(monkeypatch, OE_REGISTRATION_MODE="email-verify")
    assert effective_registration_mode(s) == "open"


def test_email_verify_with_smtp_stays_gated(monkeypatch):
    s = _settings(
        monkeypatch, OE_REGISTRATION_MODE="email-verify", OE_EMAIL_BACKEND="smtp", OE_SMTP_HOST="mail.example.org"
    )
    assert effective_registration_mode(s) == "email-verify"


def test_desktop_default_is_open(monkeypatch):
    s = _settings(monkeypatch, OE_DESKTOP="1")
    assert effective_registration_mode(s) == "open"


def test_desktop_explicit_admin_approve_is_respected(monkeypatch):
    s = _settings(monkeypatch, OE_DESKTOP="1", OE_REGISTRATION_MODE="admin-approve")
    assert effective_registration_mode(s) == "admin-approve"


def test_server_default_stays_admin_approve(monkeypatch):
    monkeypatch.setattr("sys.frozen", False, raising=False)
    s = _settings(monkeypatch)
    assert effective_registration_mode(s) == "admin-approve"


def test_closed_is_never_loosened(monkeypatch):
    s = _settings(monkeypatch, OE_DESKTOP="1", OE_REGISTRATION_MODE="closed")
    assert effective_registration_mode(s) == "closed"
