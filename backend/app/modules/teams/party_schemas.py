# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Request and response schemas for project parties and record shares."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.teams.party_access import PARTY_PERMISSIONS, PARTY_ROLES, PARTY_SCOPED_KEYS


def _validate_role(value: str) -> str:
    if value not in PARTY_ROLES:
        raise ValueError(f"[teams.validation.party_role.unknown] '{value}' is not a party role")
    return value


def _validate_permission(value: str) -> str:
    if value not in PARTY_PERMISSIONS:
        raise ValueError(f"[teams.validation.party_permission.unknown] '{value}' is not a share permission")
    return value


def validate_party_entity_type(value: str) -> str:
    """Reject a record kind that parties do not scope (a typo would share nothing)."""
    if value not in PARTY_SCOPED_KEYS:
        raise ValueError(f"[teams.validation.party_entity_type.unknown] '{value}' is not a shared register")
    return value


class ProjectPartyCreate(BaseModel):
    """Add a company to a project."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255)
    role: str = Field(default="subcontractor", max_length=32)
    legal_entity_id: UUID | None = None
    contact_id: UUID | None = None
    notes: str = Field(default="", max_length=4000)

    @field_validator("role")
    @classmethod
    def _known_role(cls, v: str) -> str:
        return _validate_role(v)


class ProjectPartyUpdate(BaseModel):
    """Change a party. Omitted fields keep their value."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    role: str | None = Field(default=None, max_length=32)
    legal_entity_id: UUID | None = None
    contact_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=4000)
    is_active: bool | None = None

    @field_validator("role")
    @classmethod
    def _known_role(cls, v: str | None) -> str | None:
        return None if v is None else _validate_role(v)


class ProjectPartyResponse(BaseModel):
    """One party, with how many members are bound to it."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    role: str
    legal_entity_id: UUID | None = None
    contact_id: UUID | None = None
    notes: str = ""
    is_active: bool = True
    is_host: bool = False
    member_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PartyMemberBind(BaseModel):
    """Bind the user in the path to a party."""

    model_config = ConfigDict(extra="forbid")

    party_id: UUID


class PartyMemberResponse(BaseModel):
    """One binding of a project member to a party."""

    user_id: UUID
    party_id: UUID
    party_name: str
    full_name: str = ""
    email: str = ""


class PartyScopeResponse(BaseModel):
    """How party visibility applies to the caller on a project."""

    project_id: UUID
    restricted: bool
    party_id: UUID | None = None
    party_name: str | None = None
    is_host: bool = False
    has_parties: bool = False
    can_manage: bool = False


class RecordShareCreate(BaseModel):
    """Share one record with one party."""

    model_config = ConfigDict(extra="forbid")

    party_id: UUID
    permission: str = Field(default="view", max_length=16)

    @field_validator("permission")
    @classmethod
    def _known_permission(cls, v: str) -> str:
        return _validate_permission(v)


class RecordOriginatorSet(BaseModel):
    """Set or clear the party that originated a record."""

    model_config = ConfigDict(extra="forbid")

    party_id: UUID | None = None


class RecordPartyRow(BaseModel):
    """One party's hold on a record."""

    party_id: UUID
    party_name: str
    party_role: str
    access: str
    permission: str
    shared_by: UUID | None = None
    shared_at: datetime | None = None


class RecordPartiesResponse(BaseModel):
    """Originator and shares of one record, plus what the caller may do with them."""

    entity_type: str
    entity_id: UUID
    originator: RecordPartyRow | None = None
    shares: list[RecordPartyRow] = Field(default_factory=list)
    can_share: bool = False
    can_set_originator: bool = False


class PartyRegisterResponse(BaseModel):
    """One register kind that parties scope."""

    key: str
    label: str
    module: str
