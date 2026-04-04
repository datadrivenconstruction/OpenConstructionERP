"""Tests for application configuration.

Validates that Settings has all required fields, correct defaults,
and computed fields work as expected. No database required.
"""

import os

import pytest

from app.config import Settings


class TestSettingsDefaults:
    @pytest.fixture
    def settings(self, monkeypatch):
        """Create Settings with env vars to avoid loading .env file issues."""
        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
        monkeypatch.setenv("DATABASE_SYNC_URL", "sqlite:///./test.db")
        monkeypatch.setenv("APP_ENV", "development")
        return Settings(
            _env_file=None,
            database_url="sqlite+aiosqlite:///./test.db",
            database_sync_url="sqlite:///./test.db",
        )

    def test_app_name_default(self, settings):
        assert settings.app_name == "OpenConstructionERP"

    def test_app_version_default(self, settings):
        assert settings.app_version == "0.2.4"

    def test_app_env_default(self, settings):
        assert settings.app_env == "development"

    def test_app_debug_default(self, settings):
        assert settings.app_debug is True

    def test_log_level_default(self, settings):
        assert settings.log_level == "INFO"

    def test_jwt_algorithm_default(self, settings):
        assert settings.jwt_algorithm == "HS256"

    def test_jwt_expire_minutes_default(self, settings):
        assert settings.jwt_expire_minutes == 60

    def test_jwt_refresh_expire_days_default(self, settings):
        assert settings.jwt_refresh_expire_days == 30

    def test_database_pool_size_default(self, settings):
        assert settings.database_pool_size == 20

    def test_database_max_overflow_default(self, settings):
        assert settings.database_max_overflow == 10

    def test_database_echo_default(self, settings):
        assert settings.database_echo is False

    def test_s3_bucket_default(self, settings):
        assert settings.s3_bucket == "openestimate"

    def test_default_validation_rule_sets(self, settings):
        assert settings.default_validation_rule_sets == ["boq_quality"]


class TestSettingsRequired:
    """Verify all expected fields exist on the Settings model."""

    @pytest.fixture
    def settings(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
        monkeypatch.setenv("DATABASE_SYNC_URL", "sqlite:///./test.db")
        return Settings(
            _env_file=None,
            database_url="sqlite+aiosqlite:///./test.db",
            database_sync_url="sqlite:///./test.db",
        )

    def test_has_database_url(self, settings):
        assert hasattr(settings, "database_url")

    def test_has_jwt_secret(self, settings):
        assert hasattr(settings, "jwt_secret")

    def test_has_allowed_origins(self, settings):
        assert hasattr(settings, "allowed_origins")

    def test_has_redis_url(self, settings):
        assert hasattr(settings, "redis_url")

    def test_has_s3_endpoint(self, settings):
        assert hasattr(settings, "s3_endpoint")

    def test_has_openai_api_key(self, settings):
        assert hasattr(settings, "openai_api_key")

    def test_has_anthropic_api_key(self, settings):
        assert hasattr(settings, "anthropic_api_key")


class TestComputedFields:
    @pytest.fixture
    def dev_settings(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
        monkeypatch.setenv("DATABASE_SYNC_URL", "sqlite:///./test.db")
        return Settings(
            _env_file=None,
            app_env="development",
            database_url="sqlite+aiosqlite:///./test.db",
            database_sync_url="sqlite:///./test.db",
        )

    @pytest.fixture
    def prod_settings(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
        monkeypatch.setenv("DATABASE_SYNC_URL", "sqlite:///./test.db")
        return Settings(
            _env_file=None,
            app_env="production",
            app_debug=False,
            database_url="sqlite+aiosqlite:///./test.db",
            database_sync_url="sqlite:///./test.db",
        )

    def test_is_production_false_in_dev(self, dev_settings):
        assert dev_settings.is_production is False

    def test_is_production_true_in_prod(self, prod_settings):
        assert prod_settings.is_production is True

    def test_cors_origins_single(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
        monkeypatch.setenv("DATABASE_SYNC_URL", "sqlite:///./test.db")
        s = Settings(
            _env_file=None,
            allowed_origins="http://localhost:5173",
            database_url="sqlite+aiosqlite:///./test.db",
            database_sync_url="sqlite:///./test.db",
        )
        assert s.cors_origins == ["http://localhost:5173"]

    def test_cors_origins_multiple(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
        monkeypatch.setenv("DATABASE_SYNC_URL", "sqlite:///./test.db")
        s = Settings(
            _env_file=None,
            allowed_origins="http://localhost:5173, https://app.openestimate.io",
            database_url="sqlite+aiosqlite:///./test.db",
            database_sync_url="sqlite:///./test.db",
        )
        assert s.cors_origins == [
            "http://localhost:5173",
            "https://app.openestimate.io",
        ]

    def test_cors_origins_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
        monkeypatch.setenv("DATABASE_SYNC_URL", "sqlite:///./test.db")
        s = Settings(
            _env_file=None,
            allowed_origins="  http://a.com ,  http://b.com  ",
            database_url="sqlite+aiosqlite:///./test.db",
            database_sync_url="sqlite:///./test.db",
        )
        assert s.cors_origins == ["http://a.com", "http://b.com"]
