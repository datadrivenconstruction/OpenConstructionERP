"""User Pydantic schemas for request/response validation."""

import re
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


def _sanitize_name(name: str) -> str:
    """Strip HTML tags from a name to prevent XSS."""
    return re.sub(r"<[^>]+>", "", name).strip()

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

    email: EmailStr = Field(..., description="Valid email address (used for login)")
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Password (min 8 chars, must contain at least one letter and one digit)",
    )
    full_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Full display name (HTML tags are stripped)",
    )
    role: str = Field(
        default="editor",
        pattern=r"^(admin|manager|editor|viewer)$",
        description="User role. Must be one of: admin, manager, editor, viewer",
    )
    locale: str = Field(
        default="en", max_length=10, description="Preferred locale code (e.g. en, de, fr)"
    )
    company: str = Field(
        default="",
        max_length=255,
        description="Company or organisation name (optional)",
    )
    job_title: str = Field(
        default="",
        max_length=255,
        description="Job title / role in the company (optional)",
    )
    how_found_us: str = Field(
        default="",
        max_length=100,
        description="How the user discovered the platform (optional)",
    )

    @field_validator("password")
    @classmethod
    def _check_password_strength(cls, v: str) -> str:
        return _validate_strong_password(v)

    @field_validator("full_name")
    @classmethod
    def _sanitize_full_name(cls, v: str) -> str:
        return _sanitize_name(v)

    @field_validator("company")
    @classmethod
    def _sanitize_company(cls, v: str) -> str:
        return _sanitize_name(v) if v else ""

    @field_validator("job_title")
    @classmethod
    def _sanitize_job_title(cls, v: str) -> str:
        return _sanitize_name(v) if v else ""


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

    @field_validator("full_name")
    @classmethod
    def _sanitize_full_name(cls, v: str | None) -> str | None:
        if v is not None:
            return _sanitize_name(v)
        return v


class UserAdminUpdate(BaseModel):
    """Admin-level user update (role, active status)."""

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    role: str | None = Field(default=None, pattern=r"^(admin|manager|editor|viewer)$")
    is_active: bool | None = None
    locale: str | None = Field(default=None, max_length=10)

    @field_validator("full_name")
    @classmethod
    def _sanitize_full_name(cls, v: str | None) -> str | None:
        if v is not None:
            return _sanitize_name(v)
        return v


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

    Always returns a generic message to prevent email enumeration.
    The reset token is NEVER included in the response — it must only
    be delivered via a secure side-channel (email).
    """

    message: str


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


# ── Onboarding ────────────────────────────────────────────────────────────────


class OnboardingRequest(BaseModel):
    """Save onboarding wizard choices."""

    company_type: str = Field(
        ...,
        pattern=r"^(general_contractor|estimator|project_management|architecture_engineering|full_enterprise)$",
        description="Selected company type preset key",
    )
    enabled_modules: list[str] = Field(
        default_factory=list,
        description="Final list of module keys the user wants enabled",
    )
    interface_mode: str = Field(
        default="advanced",
        pattern=r"^(simple|advanced)$",
        description="Chosen interface complexity mode",
    )
    completed: bool = Field(
        default=True,
        description="Whether onboarding is considered complete",
    )


class OnboardingResponse(BaseModel):
    """Onboarding state for the current user."""

    completed: bool = False
    company_type: str | None = None
    enabled_modules: list[str] = Field(default_factory=list)
    interface_mode: str | None = None
