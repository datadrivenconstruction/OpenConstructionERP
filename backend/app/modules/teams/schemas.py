"""Teams Pydantic schemas — request/response models."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── Team ─────────────────────────────────────────────────────────────────


class TeamCreate(BaseModel):
    """Create a new team within a project."""

    project_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    name_translations: dict[str, str] | None = None
    sort_order: int = 0
    is_default: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class TeamUpdate(BaseModel):
    """Partial update for a team."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    name_translations: dict[str, str] | None = None
    sort_order: int | None = None
    is_default: bool | None = None
    is_active: bool | None = None
    metadata: dict[str, Any] | None = None


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
    """Add a user to a team."""

    user_id: UUID
    role: str = Field(
        default="member",
        pattern=r"^(member|lead)$",
    )


# ── Visibility ───────────────────────────────────────────────────────────


class EntityVisibilityCreate(BaseModel):
    """Grant visibility of an entity to a team."""

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
