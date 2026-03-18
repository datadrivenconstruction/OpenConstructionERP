"""Tests for user service utilities and schemas.

Tests cover password hashing, API key generation, JWT token creation,
and Pydantic schema validation. No database required — the heavy ORM
import chain is mocked so that pure utility functions can be tested in
isolation.
"""

import hashlib
import sys
import uuid
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from app.core.permissions import PermissionRegistry, Role

# ── Mock the database module to avoid asyncpg/engine at import time ──────────
# app.modules.users.service → app.modules.users.models → app.database (engine)
# We intercept app.database before importing service.py so that no real DB
# engine is created.

_fake_database = ModuleType("app.database")
_fake_database.Base = type("Base", (), {})  # type: ignore[attr-defined]
sys.modules.setdefault("app.database", _fake_database)

# Also mock the repository module since it depends on the session.
_fake_repository = ModuleType("app.modules.users.repository")
_fake_repository.UserRepository = MagicMock  # type: ignore[attr-defined]
_fake_repository.APIKeyRepository = MagicMock  # type: ignore[attr-defined]
sys.modules.setdefault("app.modules.users.repository", _fake_repository)

# Now we can safely import the service utilities and schemas.
from app.modules.users.schemas import (  # noqa: E402
    ChangePasswordRequest,
    LoginRequest,
    UserCreate,
    UserUpdate,
)
from app.modules.users.service import (  # noqa: E402
    create_access_token,
    create_refresh_token,
    generate_api_key,
    hash_password,
    verify_password,
)

from jose import jwt  # noqa: E402


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_settings(**overrides):
    """Create a minimal settings-like object for token tests."""
    defaults = {
        "jwt_secret": "test-secret-key-for-unit-tests",
        "jwt_algorithm": "HS256",
        "jwt_expire_minutes": 60,
        "jwt_refresh_expire_days": 30,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_user(
    user_id=None,
    email="test@example.com",
    role="editor",
    hashed_password="$2b$12$fakehash",
    is_active=True,
):
    """Create a lightweight user-like object for token tests."""
    return SimpleNamespace(
        id=user_id or uuid.uuid4(),
        email=email,
        role=role,
        hashed_password=hashed_password,
        is_active=is_active,
    )


# ── Password hashing tests ───────────────────────────────────────────────────


class TestPasswordHashing:
    def test_hash_password_returns_string(self):
        hashed = hash_password("MySecretP@ss123")
        assert isinstance(hashed, str)

    def test_hash_password_not_plaintext(self):
        password = "MySecretP@ss123"
        hashed = hash_password(password)
        assert hashed != password

    def test_hash_password_bcrypt_format(self):
        """bcrypt hashes start with $2b$ (or $2a$)."""
        hashed = hash_password("testpassword")
        assert hashed.startswith("$2b$") or hashed.startswith("$2a$")

    def test_hash_password_different_for_same_input(self):
        """Each hash should use a different salt."""
        h1 = hash_password("samepassword")
        h2 = hash_password("samepassword")
        assert h1 != h2

    def test_verify_password_correct(self):
        password = "CorrectHorse42!"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        hashed = hash_password("original")
        assert verify_password("wrong", hashed) is False

    def test_verify_password_empty_string(self):
        hashed = hash_password("notempty")
        assert verify_password("", hashed) is False

    def test_hash_and_verify_unicode_password(self):
        password = "P@sswort-mit-Umlauten-\u00e4\u00f6\u00fc\u00df"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True
        assert verify_password("wrong", hashed) is False

    def test_hash_and_verify_max_bcrypt_length(self):
        """bcrypt supports up to 72 bytes."""
        password = "a" * 72
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_hash_rejects_password_over_72_bytes(self):
        """Raw bcrypt raises ValueError for passwords exceeding 72 bytes."""
        password = "a" * 73
        with pytest.raises(ValueError, match="72"):
            hash_password(password)


# ── API key generation tests ─────────────────────────────────────────────────


class TestAPIKeyGeneration:
    def test_generate_api_key_returns_tuple_of_three(self):
        result = generate_api_key()
        assert isinstance(result, tuple)
        assert len(result) == 3

    def test_full_key_has_prefix(self):
        full_key, _, _ = generate_api_key()
        assert full_key.startswith("oe_")

    def test_key_prefix_is_first_12_chars(self):
        full_key, _, key_prefix = generate_api_key()
        assert key_prefix == full_key[:12]

    def test_key_hash_is_sha256_of_full_key(self):
        full_key, key_hash, _ = generate_api_key()
        expected = hashlib.sha256(full_key.encode()).hexdigest()
        assert key_hash == expected

    def test_key_hash_is_64_hex_chars(self):
        _, key_hash, _ = generate_api_key()
        assert len(key_hash) == 64
        assert all(c in "0123456789abcdef" for c in key_hash)

    def test_keys_are_unique(self):
        keys = {generate_api_key()[0] for _ in range(50)}
        assert len(keys) == 50

    def test_hashes_are_unique(self):
        hashes = {generate_api_key()[1] for _ in range(50)}
        assert len(hashes) == 50

    def test_full_key_sufficient_length(self):
        """The key should be long enough for security (oe_ + 32-byte urlsafe b64)."""
        full_key, _, _ = generate_api_key()
        # secrets.token_urlsafe(32) produces ~43 chars, plus 3 for 'oe_'
        assert len(full_key) > 40


# ── Token creation tests ─────────────────────────────────────────────────────


class TestAccessToken:
    @pytest.fixture(autouse=True)
    def _setup_permissions(self):
        """Set up a clean permission registry for token tests."""
        from app.core.permissions import permission_registry

        original_perms = dict(permission_registry._permissions)
        original_modules = dict(permission_registry._module_permissions)
        permission_registry.clear()
        permission_registry.register_module_permissions(
            "test",
            {
                "test.read": Role.VIEWER,
                "test.write": Role.EDITOR,
                "test.admin": Role.ADMIN,
            },
        )
        yield
        permission_registry.clear()
        permission_registry._permissions.update(original_perms)
        permission_registry._module_permissions.update(original_modules)

    def test_access_token_is_valid_jwt(self):
        settings = _make_settings()
        user = _make_user()
        token = create_access_token(user, settings)
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        assert payload is not None

    def test_access_token_contains_sub(self):
        settings = _make_settings()
        user_id = uuid.uuid4()
        user = _make_user(user_id=user_id)
        token = create_access_token(user, settings)
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        assert payload["sub"] == str(user_id)

    def test_access_token_contains_email(self):
        settings = _make_settings()
        user = _make_user(email="alice@example.com")
        token = create_access_token(user, settings)
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        assert payload["email"] == "alice@example.com"

    def test_access_token_contains_role(self):
        settings = _make_settings()
        user = _make_user(role="manager")
        token = create_access_token(user, settings)
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        assert payload["role"] == "manager"

    def test_access_token_contains_permissions(self):
        settings = _make_settings()
        user = _make_user(role="editor")
        token = create_access_token(user, settings)
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        perms = payload["permissions"]
        assert "test.read" in perms
        assert "test.write" in perms
        assert "test.admin" not in perms

    def test_access_token_admin_gets_all_permissions(self):
        settings = _make_settings()
        user = _make_user(role="admin")
        token = create_access_token(user, settings)
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        perms = payload["permissions"]
        assert "test.read" in perms
        assert "test.write" in perms
        assert "test.admin" in perms

    def test_access_token_type_is_access(self):
        settings = _make_settings()
        user = _make_user()
        token = create_access_token(user, settings)
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        assert payload["type"] == "access"

    def test_access_token_has_iat_and_exp(self):
        settings = _make_settings(jwt_expire_minutes=30)
        user = _make_user()
        token = create_access_token(user, settings)
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        assert "iat" in payload
        assert "exp" in payload
        # exp should be iat + expire_minutes * 60
        assert payload["exp"] - payload["iat"] == 30 * 60

    def test_access_token_extra_claims(self):
        settings = _make_settings()
        user = _make_user()
        token = create_access_token(user, settings, extra_claims={"tenant_id": "t-123"})
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        assert payload["tenant_id"] == "t-123"

    def test_access_token_wrong_secret_fails(self):
        settings = _make_settings(jwt_secret="correct-secret")
        user = _make_user()
        token = create_access_token(user, settings)
        with pytest.raises(Exception):
            jwt.decode(token, "wrong-secret", algorithms=["HS256"])


class TestRefreshToken:
    def test_refresh_token_is_valid_jwt(self):
        settings = _make_settings()
        user = _make_user()
        token = create_refresh_token(user, settings)
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        assert payload is not None

    def test_refresh_token_contains_sub(self):
        settings = _make_settings()
        user_id = uuid.uuid4()
        user = _make_user(user_id=user_id)
        token = create_refresh_token(user, settings)
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        assert payload["sub"] == str(user_id)

    def test_refresh_token_type_is_refresh(self):
        settings = _make_settings()
        user = _make_user()
        token = create_refresh_token(user, settings)
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        assert payload["type"] == "refresh"

    def test_refresh_token_has_longer_expiry(self):
        settings = _make_settings(jwt_expire_minutes=60, jwt_refresh_expire_days=7)
        user = _make_user()
        access = create_access_token(user, settings)
        refresh = create_refresh_token(user, settings)
        access_payload = jwt.decode(
            access, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
        refresh_payload = jwt.decode(
            refresh, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
        access_ttl = access_payload["exp"] - access_payload["iat"]
        refresh_ttl = refresh_payload["exp"] - refresh_payload["iat"]
        assert refresh_ttl > access_ttl
        assert refresh_ttl == 7 * 24 * 60 * 60

    def test_refresh_token_does_not_contain_permissions(self):
        settings = _make_settings()
        user = _make_user()
        token = create_refresh_token(user, settings)
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        assert "permissions" not in payload

    def test_refresh_token_does_not_contain_email(self):
        settings = _make_settings()
        user = _make_user()
        token = create_refresh_token(user, settings)
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        assert "email" not in payload

    def test_refresh_token_does_not_contain_role(self):
        settings = _make_settings()
        user = _make_user()
        token = create_refresh_token(user, settings)
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        assert "role" not in payload


# ── Schema validation tests ──────────────────────────────────────────────────


class TestUserCreateSchema:
    def test_valid_user_create(self):
        data = UserCreate(
            email="user@example.com",
            password="StrongP@ss1",
            full_name="Test User",
        )
        assert data.email == "user@example.com"
        assert data.password == "StrongP@ss1"
        assert data.full_name == "Test User"

    def test_default_role_is_editor(self):
        data = UserCreate(
            email="user@example.com",
            password="StrongP@ss1",
            full_name="Test User",
        )
        assert data.role == "editor"

    def test_default_locale_is_en(self):
        data = UserCreate(
            email="user@example.com",
            password="StrongP@ss1",
            full_name="Test User",
        )
        assert data.locale == "en"

    def test_valid_roles(self):
        for role in ("admin", "manager", "editor", "viewer"):
            data = UserCreate(
                email="user@example.com",
                password="StrongP@ss1",
                full_name="Test User",
                role=role,
            )
            assert data.role == role

    def test_invalid_role_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            UserCreate(
                email="user@example.com",
                password="StrongP@ss1",
                full_name="Test User",
                role="superuser",
            )
        assert "role" in str(exc_info.value).lower() or "pattern" in str(exc_info.value).lower()

    def test_invalid_email_rejected(self):
        with pytest.raises(ValidationError):
            UserCreate(
                email="not-an-email",
                password="StrongP@ss1",
                full_name="Test User",
            )

    def test_empty_email_rejected(self):
        with pytest.raises(ValidationError):
            UserCreate(
                email="",
                password="StrongP@ss1",
                full_name="Test User",
            )

    def test_password_too_short(self):
        with pytest.raises(ValidationError) as exc_info:
            UserCreate(
                email="user@example.com",
                password="short",
                full_name="Test User",
            )
        errors = exc_info.value.errors()
        password_errors = [e for e in errors if "password" in str(e.get("loc", []))]
        assert len(password_errors) > 0

    def test_password_min_length_boundary(self):
        """Exactly 8 characters should pass."""
        data = UserCreate(
            email="user@example.com",
            password="12345678",
            full_name="Test User",
        )
        assert len(data.password) == 8

    def test_password_seven_chars_rejected(self):
        """7 characters should fail."""
        with pytest.raises(ValidationError):
            UserCreate(
                email="user@example.com",
                password="1234567",
                full_name="Test User",
            )

    def test_password_max_length_boundary(self):
        """Exactly 128 characters should pass."""
        data = UserCreate(
            email="user@example.com",
            password="a" * 128,
            full_name="Test User",
        )
        assert len(data.password) == 128

    def test_password_over_max_rejected(self):
        with pytest.raises(ValidationError):
            UserCreate(
                email="user@example.com",
                password="a" * 129,
                full_name="Test User",
            )

    def test_full_name_required(self):
        with pytest.raises(ValidationError):
            UserCreate(
                email="user@example.com",
                password="StrongP@ss1",
                full_name="",
            )

    def test_full_name_max_length(self):
        data = UserCreate(
            email="user@example.com",
            password="StrongP@ss1",
            full_name="A" * 255,
        )
        assert len(data.full_name) == 255

    def test_full_name_over_max_rejected(self):
        with pytest.raises(ValidationError):
            UserCreate(
                email="user@example.com",
                password="StrongP@ss1",
                full_name="A" * 256,
            )


class TestLoginRequestSchema:
    def test_valid_login(self):
        data = LoginRequest(email="user@example.com", password="password123")
        assert data.email == "user@example.com"
        assert data.password == "password123"

    def test_invalid_email(self):
        with pytest.raises(ValidationError):
            LoginRequest(email="invalid", password="password123")

    def test_password_too_short(self):
        with pytest.raises(ValidationError):
            LoginRequest(email="user@example.com", password="short")

    def test_password_min_length(self):
        data = LoginRequest(email="user@example.com", password="12345678")
        assert data.password == "12345678"

    def test_password_max_length(self):
        data = LoginRequest(email="user@example.com", password="a" * 128)
        assert len(data.password) == 128

    def test_password_over_max_rejected(self):
        with pytest.raises(ValidationError):
            LoginRequest(email="user@example.com", password="a" * 129)

    def test_missing_email_rejected(self):
        with pytest.raises(ValidationError):
            LoginRequest(password="password123")  # type: ignore[call-arg]

    def test_missing_password_rejected(self):
        with pytest.raises(ValidationError):
            LoginRequest(email="user@example.com")  # type: ignore[call-arg]


class TestChangePasswordRequestSchema:
    def test_valid_change_password(self):
        data = ChangePasswordRequest(
            current_password="OldP@ssw0rd",
            new_password="NewP@ssw0rd",
        )
        assert data.current_password == "OldP@ssw0rd"
        assert data.new_password == "NewP@ssw0rd"

    def test_current_password_too_short(self):
        with pytest.raises(ValidationError):
            ChangePasswordRequest(
                current_password="short",
                new_password="NewP@ssw0rd",
            )

    def test_new_password_too_short(self):
        with pytest.raises(ValidationError):
            ChangePasswordRequest(
                current_password="OldP@ssw0rd",
                new_password="short",
            )


class TestUserUpdateSchema:
    def test_all_fields_optional(self):
        data = UserUpdate()
        assert data.full_name is None
        assert data.locale is None
        assert data.metadata is None

    def test_partial_update(self):
        data = UserUpdate(full_name="New Name")
        assert data.full_name == "New Name"
        assert data.locale is None

    def test_full_name_min_length(self):
        with pytest.raises(ValidationError):
            UserUpdate(full_name="")

    def test_metadata_accepts_dict(self):
        data = UserUpdate(metadata={"theme": "dark", "timezone": "Europe/Berlin"})
        assert data.metadata == {"theme": "dark", "timezone": "Europe/Berlin"}
