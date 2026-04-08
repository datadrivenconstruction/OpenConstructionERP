"""User Pydantic schemas for request/response validation."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# A small set of common/leaked passwords to reject outright. Cheap defence
# against the most embarrassing weak passwords without bringing in a 100k+
# entry breach corpus. Stored lowercase for case-insensitive matching.
_COMMON_PASSWORDS: frozenset[str] = frozenset(
    {
        "password",
        "password1",
        "password123",
        "12345678",
        "123456789",
        "1234567890",
        "1234567",
        "qwerty123",
        "qwertyuiop",
        "qwerty12",
        "letmein",
        "letmein123",
        "admin123",
        "admin1234",
        "welcome1",
        "welcome123",
        "iloveyou",
        "monkey123",
        "abc12345",
        "abcd1234",
        "p@ssw0rd",
        "p@ssword",
        "passw0rd",
        "trustno1",
    }
)


def _validate_strong_password(value: str) -> str:
    """Reject weak passwords. Used by `UserCreate`, `ChangePasswordRequest`,
    and `ResetPasswordRequest` so the policy is consistent everywhere.

    Rules (intentionally lenient — strong enough to block trivial passwords
    without frustrating power users):
      - 8+ chars
      - Must contain at least one letter and at least one digit
      - Must not be in the common-passwords blacklist (case-insensitive)
    """
    if len(value) < 8:
        raise ValueError("Password must be at least 8 characters")
    if not any(ch.isalpha() for ch in value):
        raise ValueError("Password must contain at least one letter")
    if not any(ch.isdigit() for ch in value):
        raise ValueError("Password must contain at least one digit")
    if value.lower() in _COMMON_PASSWORDS:
        raise ValueError("Password is too common — please choose a stronger one")
    return value


# ── Auth ───────────────────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    """User login request.

    No min_length on password — validation of password format before credential
    check would reveal the password policy to unauthenticated users.
    """

    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class TokenResponse(BaseModel):
    """JWT token pair response."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class RefreshRequest(BaseModel):
    """Refresh token request."""

    refresh_token: str


# ── User CRUD ──────────────────────────────────────────────────────────────


class UserCreate(BaseModel):
    """Create a new user."""

    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str = Field(..., min_length=1, max_length=255)
    role: str = Field(default="editor", pattern=r"^(admin|manager|editor|viewer)$")
    locale: str = Field(default="en", max_length=10)

    @field_validator("password")
    @classmethod
    def _check_password_strength(cls, v: str) -> str:
        return _validate_strong_password(v)


class UserUpdate(BaseModel):
    """Update user profile."""

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    locale: str | None = Field(default=None, max_length=10)
    metadata: dict[str, Any] | None = None
    timezone: str | None = Field(default=None, max_length=50)
    measurement_system: str | None = Field(default=None, max_length=20)
    paper_size: str | None = Field(default=None, max_length=10)
    number_format: str | None = Field(default=None, max_length=20)
    date_format: str | None = Field(default=None, max_length=20)
    currency_code: str | None = Field(default=None, max_length=10)


class UserAdminUpdate(BaseModel):
    """Admin-level user update (role, active status)."""

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    role: str | None = Field(default=None, pattern=r"^(admin|manager|editor|viewer)$")
    is_active: bool | None = None
    locale: str | None = Field(default=None, max_length=10)


class UserResponse(BaseModel):
    """User in API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str
    role: str
    locale: str
    is_active: bool
    last_login_at: datetime | None
    timezone: str
    measurement_system: str
    paper_size: str
    number_format: str
    date_format: str
    currency_code: str
    created_at: datetime
    updated_at: datetime


class UserMeResponse(UserResponse):
    """Current user response with extra details."""

    permissions: list[str] = Field(default_factory=list)


class UserPreferencesUpdate(BaseModel):
    """Update regional preferences only."""

    timezone: str | None = Field(default=None, max_length=50)
    measurement_system: str | None = Field(default=None, max_length=20)
    paper_size: str | None = Field(default=None, max_length=10)
    number_format: str | None = Field(default=None, max_length=20)
    date_format: str | None = Field(default=None, max_length=20)
    currency_code: str | None = Field(default=None, max_length=10)


class UserPreferencesResponse(BaseModel):
    """Regional preferences response."""

    model_config = ConfigDict(from_attributes=True)

    timezone: str
    measurement_system: str
    paper_size: str
    number_format: str
    date_format: str
    currency_code: str


class ChangePasswordRequest(BaseModel):
    """Change password request."""

    current_password: str = Field(..., min_length=8, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _check_new_password_strength(cls, v: str) -> str:
        return _validate_strong_password(v)


class ForgotPasswordRequest(BaseModel):
    """Forgot password request — triggers reset token generation."""

    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    """Forgot password response.

    Always returns a success message to prevent email enumeration.
    Token is included only in dev mode for testing.
    """

    message: str
    token: str | None = None


class ResetPasswordRequest(BaseModel):
    """Reset password using a previously issued reset token."""

    token: str
    new_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _check_new_password_strength(cls, v: str) -> str:
        return _validate_strong_password(v)


class ResetPasswordResponse(BaseModel):
    """Reset password response."""

    message: str


# ── API Keys ───────────────────────────────────────────────────────────────


class APIKeyCreate(BaseModel):
    """Create a new API key."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    expires_in_days: int | None = Field(default=None, ge=1, le=365)
    permissions: list[str] = Field(default_factory=list)


class APIKeyResponse(BaseModel):
    """API key in responses (no secret)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    key_prefix: str
    description: str
    is_active: bool
    permissions: list[str]
    expires_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime


class APIKeyCreatedResponse(APIKeyResponse):
    """Response when creating an API key — includes the full key (shown only once)."""

    key: str  # Full API key — shown only at creation time
