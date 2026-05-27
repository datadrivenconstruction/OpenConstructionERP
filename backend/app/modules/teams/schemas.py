"""‌⁠‍Teams Pydantic schemas — request/response models."""

import re
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Reject strings that contain NUL bytes, control characters (except TAB/LF/CR),
# or that are entirely whitespace. Catches unicode-chaos and zero-byte SQL
# injection payloads at the edge (Part 5 BUG-148/149, ENH-086).
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


# ── Team-role whitelist (single source of truth) ─────────────────────────
# Previously this list was inline-encoded in the AddMemberRequest regex,
# which let it drift from the RBAC check in service.py. Keep both in sync
# by importing this tuple anywhere the whitelist is consulted.
#
# Two tiers:
#   BASIC_TEAM_ROLES   — assignable by any project-admin/member
#   ELEVATED_TEAM_ROLES — assignable ONLY by a project owner / system admin
#                        (these inherit higher-effective-permission)
BASIC_TEAM_ROLES: tuple[str, ...] = ("member", "lead", "estimator", "viewer")
ELEVATED_TEAM_ROLES: tuple[str, ...] = ("owner", "project_manager")
ALL_TEAM_ROLES: tuple[str, ...] = BASIC_TEAM_ROLES + ELEVATED_TEAM_ROLES
_TEAM_ROLE_PATTERN = r"^(" + "|".join(ALL_TEAM_ROLES) + r")$"


def _reject_unsafe_string(value: str, field: str) -> str:
    """‌⁠‍Strip/validate free-text strings; raise on control-character junk.

    Error messages embed a stable ``teams.validation.*`` i18n key in the
    rendered text so the frontend can localise them without re-parsing the
    human suffix. Schema-validation error messages still surface in English
    via FastAPI's 422 envelope; localisation happens client-side.
    """
    if _CONTROL_CHAR_RE.search(value):
        raise ValueError(f"[teams.validation.{field}.control_characters] {field} contains control characters")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"[teams.validation.{field}.blank] {field} must not be blank")
    return cleaned


# ── Team ─────────────────────────────────────────────────────────────────


class TeamCreate(BaseModel):
    """‌⁠‍Create a new team within a project."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    project_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    name_translations: dict[str, str] | None = None
    # Clamp to positive 32-bit int range so int-overflow fuzz cannot crash
    # downstream DB inserts on SQLite / Postgres (BUG-139-143).
    sort_order: int = Field(default=0, ge=0, le=2_147_483_647)
    is_default: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _sanitize_name(cls, v: str) -> str:
        return _reject_unsafe_string(v, "name")


class TeamUpdate(BaseModel):
    """Partial update for a team."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    name_translations: dict[str, str] | None = None
    sort_order: int | None = Field(default=None, ge=0, le=2_147_483_647)
    is_default: bool | None = None
    is_active: bool | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("name")
    @classmethod
    def _sanitize_name(cls, v: str | None) -> str | None:
        return _reject_unsafe_string(v, "name") if v is not None else v


class MembershipResponse(BaseModel):
    """Team membership in API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    team_id: UUID
    user_id: UUID
    role: str
    created_at: datetime


class TeamResponse(BaseModel):
    """Team in API responses."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    name: str
    name_translations: dict[str, str] | None = None
    sort_order: int
    is_default: bool
    is_active: bool
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    memberships: list[MembershipResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


# ── Membership ───────────────────────────────────────────────────────────


class AddMemberRequest(BaseModel):
    """Add a user to a team.

    The role whitelist accepts both the legacy team-internal roles
    (``member`` / ``lead`` — used by the bare /teams endpoints) and the
    richer project-member role labels (``estimator`` / ``viewer`` /
    ``project_manager`` / ``owner``) surfaced by the Team Strip on
    ProjectDetailPage. Anything outside the whitelist is rejected with 422.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    user_id: UUID
    role: str = Field(
        default="member",
        pattern=_TEAM_ROLE_PATTERN,
    )


# ── Visibility ───────────────────────────────────────────────────────────


class EntityVisibilityCreate(BaseModel):
    """Grant visibility of an entity to a team."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    entity_type: str = Field(..., min_length=1, max_length=100)
    entity_id: str = Field(..., min_length=1, max_length=36)
    team_id: UUID


class EntityVisibilityResponse(BaseModel):
    """Visibility grant in API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    entity_type: str
    entity_id: str
    team_id: UUID
    created_at: datetime
