"""Tests for database utilities.

Tests the GUID type decorator and Base model column definitions.
No actual database connection required — tests operate on the type
and ORM metadata only.

The app.database module creates an engine at import time, which requires
aiosqlite or asyncpg. We patch the engine-creation side effects before
importing, so only the GUID and Base definitions are loaded.
"""

import sys
import uuid
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

# Patch the config module so create_engine_from_settings doesn't need a real DB
# before we import app.database.
_ensure_config = sys.modules.get("app.config")
if _ensure_config is None:
    _fake_config = ModuleType("app.config")
    _fake_settings = MagicMock()
    _fake_settings.database_url = "sqlite+aiosqlite:///./test.db"
    _fake_settings.database_echo = False
    _fake_settings.database_pool_size = 5
    _fake_settings.database_max_overflow = 5
    _fake_config.get_settings = MagicMock(return_value=_fake_settings)  # type: ignore[attr-defined]
    sys.modules["app.config"] = _fake_config

# Now we can safely import — engine creation will use SQLite path
# which may fail on aiosqlite, so we also patch create_async_engine.
with patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=MagicMock()):
    # Force re-import if already cached with a broken engine
    if "app.database" in sys.modules:
        del sys.modules["app.database"]
    from app.database import GUID, Base  # noqa: E402


# ── GUID TypeDecorator ───────────────────────────────────────────────────────


class TestGUID:
    def setup_method(self):
        self.guid = GUID()

    # -- process_bind_param (Python -> DB) --

    def test_bind_uuid_object(self):
        uid = uuid.uuid4()
        result = self.guid.process_bind_param(uid, dialect=None)
        assert result == str(uid)
        assert isinstance(result, str)

    def test_bind_string_passthrough(self):
        uid_str = str(uuid.uuid4())
        result = self.guid.process_bind_param(uid_str, dialect=None)
        assert result == uid_str

    def test_bind_none_returns_none(self):
        result = self.guid.process_bind_param(None, dialect=None)
        assert result is None

    # -- process_result_value (DB -> Python) --

    def test_result_string_to_uuid(self):
        uid = uuid.uuid4()
        result = self.guid.process_result_value(str(uid), dialect=None)
        assert result == uid
        assert isinstance(result, uuid.UUID)

    def test_result_none_returns_none(self):
        result = self.guid.process_result_value(None, dialect=None)
        assert result is None

    def test_result_uuid_passthrough(self):
        uid = uuid.uuid4()
        result = self.guid.process_result_value(uid, dialect=None)
        assert result == uid
        assert isinstance(result, uuid.UUID)

    def test_roundtrip(self):
        """UUID -> bind (str) -> result (UUID) roundtrip."""
        original = uuid.uuid4()
        stored = self.guid.process_bind_param(original, dialect=None)
        restored = self.guid.process_result_value(stored, dialect=None)
        assert restored == original

    def test_cache_ok(self):
        assert GUID.cache_ok is True

    def test_impl_is_string_36(self):
        """GUID.impl should be String(36)."""
        assert GUID.impl.length == 36


# ── Base model ───────────────────────────────────────────────────────────────


class TestBaseModel:
    def test_has_id_column(self):
        assert hasattr(Base, "id")

    def test_has_created_at_column(self):
        assert hasattr(Base, "created_at")

    def test_has_updated_at_column(self):
        assert hasattr(Base, "updated_at")

    def test_id_is_in_class_dict(self):
        """id should be defined directly on Base."""
        assert "id" in Base.__dict__

    def test_created_at_in_class_dict(self):
        assert "created_at" in Base.__dict__

    def test_updated_at_in_class_dict(self):
        assert "updated_at" in Base.__dict__

    def test_metadata_has_naming_convention(self):
        """Base.metadata should have the naming convention applied."""
        nc = Base.metadata.naming_convention
        assert "ix" in nc
        assert "uq" in nc
        assert "fk" in nc
        assert "pk" in nc
        assert "ck" in nc
