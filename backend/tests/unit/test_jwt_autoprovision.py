# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Zero-config JWT secret auto-provisioning (production hardening).

``_ensure_persistent_jwt_secret`` lets the published production image boot with
no ``JWT_SECRET`` set: it generates a strong random secret, persists it under
the data dir, and re-uses it across restarts. It stays a strict no-op in
development and whenever the operator already supplied a real secret, so the
strict ``Settings`` validator (pinned in ``test_jwt_secret_guard.py``) is never
bypassed for a deliberately weak value.

These tests pin that contract. They construct nothing that needs a database and
import only ``app.config`` (pure stdlib + pydantic), so they run under the
py3.11 DB-free lane as well as the full suite.
"""

from __future__ import annotations

import os
import pathlib
from collections.abc import Iterator

import pytest

from app.config import (
    _JWT_SECRET_MIN_LENGTH,
    _ensure_persistent_jwt_secret,
    _jwt_secret_persist_dir,
    _non_development_env,
    _operator_supplied_jwt_secret,
)

# A value that clears every "not supplied" filter: > 32 chars and not one of
# the known-weak placeholders.
_STRONG = "s3cure-" + "x" * 40

# Environment variables these tests read or write. Snapshotted and restored
# around every test so a direct ``os.environ`` write by the helper (it exports
# JWT_SECRET without going through monkeypatch) can't leak between tests.
_MANAGED = (
    "JWT_SECRET",
    "OE_JWT_SECRET",
    "APP_ENV",
    "OE_APP_ENV",
    "OE_DATA_DIR",
    "DATA_DIR",
    "OE_CLI_DATA_DIR",
)


@pytest.fixture(autouse=True)
def _isolated_env() -> Iterator[None]:
    """Give each test a clean, development-default env and fully restore it."""
    saved = {name: os.environ.get(name) for name in _MANAGED}
    for name in _MANAGED:
        os.environ.pop(name, None)
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


class TestNonDevelopmentEnv:
    """``_non_development_env`` reads APP_ENV before Settings exists."""

    def test_unset_defaults_to_development(self) -> None:
        assert _non_development_env() is False

    def test_explicit_development(self) -> None:
        os.environ["APP_ENV"] = "development"
        assert _non_development_env() is False

    def test_production(self) -> None:
        os.environ["APP_ENV"] = "production"
        assert _non_development_env() is True

    def test_staging(self) -> None:
        os.environ["APP_ENV"] = "staging"
        assert _non_development_env() is True

    def test_oe_prefixed_spelling(self) -> None:
        os.environ["OE_APP_ENV"] = "production"
        assert _non_development_env() is True


class TestOperatorSuppliedSecret:
    """Only a real, non-placeholder secret counts as operator-supplied."""

    def test_none_when_unset(self) -> None:
        assert _operator_supplied_jwt_secret() is None

    def test_none_for_known_weak_placeholder(self) -> None:
        os.environ["JWT_SECRET"] = "change-me"
        assert _operator_supplied_jwt_secret() is None

    def test_none_for_blank(self) -> None:
        os.environ["JWT_SECRET"] = "   "
        assert _operator_supplied_jwt_secret() is None

    def test_returns_real_secret(self) -> None:
        os.environ["JWT_SECRET"] = _STRONG
        assert _operator_supplied_jwt_secret() == _STRONG

    def test_returns_short_secret_verbatim(self) -> None:
        # A too-short but non-placeholder value is returned as-is so the strict
        # Settings validator - not this helper - rejects it in production.
        os.environ["JWT_SECRET"] = "short"
        assert _operator_supplied_jwt_secret() == "short"

    def test_oe_prefixed_spelling(self) -> None:
        os.environ["OE_JWT_SECRET"] = _STRONG
        assert _operator_supplied_jwt_secret() == _STRONG


class TestPersistDir:
    """The persist dir honours the platform data-dir overrides."""

    def test_honours_oe_data_dir(self, tmp_path: pathlib.Path) -> None:
        os.environ["OE_DATA_DIR"] = str(tmp_path)
        assert _jwt_secret_persist_dir() == tmp_path

    def test_defaults_to_home_openestimate(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda _cls: home))
        assert _jwt_secret_persist_dir() == home / ".openestimate"

    def test_falls_back_when_home_unresolvable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # No data-dir override (the autouse fixture cleared them) and Path.home()
        # cannot resolve a home dir - the resolver must not abort boot.
        def _boom(_cls: type[pathlib.Path]) -> pathlib.Path:
            raise RuntimeError("no home directory")

        monkeypatch.setattr(pathlib.Path, "home", classmethod(_boom))
        assert _jwt_secret_persist_dir() == pathlib.Path(".openestimate")


class TestEnsurePersistentJwtSecret:
    """The end-to-end auto-provision contract."""

    def test_noop_in_development(self, tmp_path: pathlib.Path) -> None:
        os.environ["OE_DATA_DIR"] = str(tmp_path)  # dev: ignored
        _ensure_persistent_jwt_secret()
        assert os.environ.get("JWT_SECRET") is None
        assert not (tmp_path / ".jwt-secret").exists()

    def test_noop_when_operator_supplied(self, tmp_path: pathlib.Path) -> None:
        os.environ["APP_ENV"] = "production"
        os.environ["OE_DATA_DIR"] = str(tmp_path)
        os.environ["JWT_SECRET"] = _STRONG
        _ensure_persistent_jwt_secret()
        assert os.environ["JWT_SECRET"] == _STRONG
        assert not (tmp_path / ".jwt-secret").exists()

    def test_short_operator_secret_left_untouched(self, tmp_path: pathlib.Path) -> None:
        # Deliberately weak (too short): the helper must NOT overwrite it, so
        # the Settings validator can reject it loudly in production.
        os.environ["APP_ENV"] = "production"
        os.environ["OE_DATA_DIR"] = str(tmp_path)
        os.environ["JWT_SECRET"] = "short"
        _ensure_persistent_jwt_secret()
        assert os.environ["JWT_SECRET"] == "short"
        assert not (tmp_path / ".jwt-secret").exists()

    def test_generates_and_persists_in_production(self, tmp_path: pathlib.Path) -> None:
        os.environ["APP_ENV"] = "production"
        os.environ["OE_DATA_DIR"] = str(tmp_path)
        _ensure_persistent_jwt_secret()
        secret = os.environ["JWT_SECRET"]
        assert len(secret) >= _JWT_SECRET_MIN_LENGTH
        persisted = (tmp_path / ".jwt-secret").read_text(encoding="utf-8").strip()
        assert persisted == secret

    def test_known_weak_placeholder_triggers_generation(self, tmp_path: pathlib.Path) -> None:
        os.environ["APP_ENV"] = "production"
        os.environ["OE_DATA_DIR"] = str(tmp_path)
        os.environ["JWT_SECRET"] = "change-me"
        _ensure_persistent_jwt_secret()
        secret = os.environ["JWT_SECRET"]
        assert secret != "change-me"
        assert len(secret) >= _JWT_SECRET_MIN_LENGTH
        assert (tmp_path / ".jwt-secret").is_file()

    def test_reuses_persisted_secret(self, tmp_path: pathlib.Path) -> None:
        existing = "persisted-" + "y" * 40
        (tmp_path / ".jwt-secret").write_text(existing, encoding="utf-8")
        os.environ["APP_ENV"] = "production"
        os.environ["OE_DATA_DIR"] = str(tmp_path)
        _ensure_persistent_jwt_secret()
        assert os.environ["JWT_SECRET"] == existing

    def test_regenerates_when_persisted_too_short(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / ".jwt-secret").write_text("tiny", encoding="utf-8")
        os.environ["APP_ENV"] = "production"
        os.environ["OE_DATA_DIR"] = str(tmp_path)
        _ensure_persistent_jwt_secret()
        secret = os.environ["JWT_SECRET"]
        assert secret != "tiny"
        assert len(secret) >= _JWT_SECRET_MIN_LENGTH
