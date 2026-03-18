"""User Pydantic schemas for request/response validation."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# ── Auth ───────────────────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    """User login request."""

    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


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


class UserUpdate(BaseModel):
    """Update user profile."""

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    locale: str | None = Field(default=None, max_length=10)
    metadata: dict[str, Any] | None = None


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
    created_at: datetime
    updated_at: datetime


class UserMeResponse(UserResponse):
    """Current user response with extra details."""

    permissions: list[str] = Field(default_factory=list)


class ChangePasswordRequest(BaseModel):
    """Change password request."""

    current_password: str = Field(..., min_length=8, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)


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
