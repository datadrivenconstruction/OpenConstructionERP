# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Teams Pydantic schemas - request/response models."""

import re
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.teams.entity_types import (
    VISIBILITY_ENTITY_TYPE_KEYS,
    enforced_entity_type_keys,
)

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
#   BASIC_TEAM_ROLES   - assignable by any project-admin/member
#   ELEVATED_TEAM_ROLES - assignable ONLY by a project owner / system admin
#                        (these inherit higher-effective-permission)
BASIC_TEAM_ROLES: tuple[str, ...] = ("member", "lead", "estimator", "viewer")
ELEVATED_TEAM_ROLES: tuple[str, ...] = ("owner", "project_manager")
ALL_TEAM_ROLES: tuple[str, ...] = BASIC_TEAM_ROLES + ELEVATED_TEAM_ROLES
_TEAM_ROLE_PATTERN = r"^(" + "|".join(ALL_TEAM_ROLES) + r")$"


# ── Team kinds ───────────────────────────────────────────────────────────
# Which party a team represents. Purely descriptive: a kind carries no
# permission of its own, it only lets the operations lead tell an internal
# team from a client-side or subcontractor one in the picker, and lets the
# UI colour-code a restriction by who is on the other side of it.
TEAM_KINDS: tuple[str, ...] = (
    "internal",
    "client",
    "subcontractor",
    "consultant",
    "supplier",
    "authority",
)
DEFAULT_TEAM_KIND = "internal"
_TEAM_KIND_PATTERN = r"^(" + "|".join(TEAM_KINDS) + r")$"

# ``kind`` and ``description`` live inside the team's existing ``metadata``
# JSON column rather than in columns of their own. The schema owns the two
# keys, validates them, and lifts them onto first-class response fields, so
# the API contract is typed while the storage needs no DDL. Anything else a
# caller puts in ``metadata`` is passed through untouched.
_KIND_META_KEY = "kind"
_DESCRIPTION_META_KEY = "description"


def _reject_unsafe_string(value: str, field: str) -> str:
    """Strip/validate free-text strings; raise on control-character junk.

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
    """Create a new team within a project."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    project_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    name_translations: dict[str, str] | None = None
    description: str = Field(default="", max_length=2000)
    kind: str = Field(default=DEFAULT_TEAM_KIND, pattern=_TEAM_KIND_PATTERN)
    # Clamp to positive 32-bit int range so int-overflow fuzz cannot crash
    # downstream DB inserts on SQLite / Postgres (BUG-139-143).
    sort_order: int = Field(default=0, ge=0, le=2_147_483_647)
    is_default: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _sanitize_name(cls, v: str) -> str:
        return _reject_unsafe_string(v, "name")

    @field_validator("description")
    @classmethod
    def _sanitize_description(cls, v: str) -> str:
        # An empty description is legitimate, so only the control-character
        # half of the shared guard applies here.
        if _CONTROL_CHAR_RE.search(v):
            raise ValueError(
                "[teams.validation.description.control_characters] description contains control characters"
            )
        return v.strip()

    def storage_metadata(self) -> dict[str, Any]:
        """The ``metadata`` dict as stored, with ``kind`` / ``description`` folded in."""
        return _fold_team_meta(dict(self.metadata), kind=self.kind, description=self.description)


class TeamUpdate(BaseModel):
    """Partial update for a team."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    name_translations: dict[str, str] | None = None
    description: str | None = Field(default=None, max_length=2000)
    kind: str | None = Field(default=None, pattern=_TEAM_KIND_PATTERN)
    sort_order: int | None = Field(default=None, ge=0, le=2_147_483_647)
    is_default: bool | None = None
    is_active: bool | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("name")
    @classmethod
    def _sanitize_name(cls, v: str | None) -> str | None:
        return _reject_unsafe_string(v, "name") if v is not None else v

    @field_validator("description")
    @classmethod
    def _sanitize_description(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if _CONTROL_CHAR_RE.search(v):
            raise ValueError(
                "[teams.validation.description.control_characters] description contains control characters"
            )
        return v.strip()

    def touches_metadata(self) -> bool:
        """True when this update has to rewrite the stored ``metadata`` dict."""
        fields = self.model_fields_set
        return bool({"metadata", "kind", "description"} & fields)

    def merged_metadata(self, current: dict[str, Any] | None) -> dict[str, Any]:
        """Fold the set fields of this update into the team's stored metadata.

        ``metadata`` given explicitly replaces the dict wholesale (the existing
        contract); ``kind`` / ``description`` are then applied on top so a
        caller can change one without resending the other.
        """
        fields = self.model_fields_set
        base = dict(self.metadata or {}) if "metadata" in fields else dict(current or {})
        kind = self.kind if "kind" in fields else None
        description = self.description if "description" in fields else None
        return _fold_team_meta(base, kind=kind, description=description)


def _fold_team_meta(
    base: dict[str, Any],
    *,
    kind: str | None,
    description: str | None,
) -> dict[str, Any]:
    """Write the two schema-owned keys into a metadata dict.

    An empty description is stored as an absent key rather than an empty
    string, so "never set" and "cleared" read the same on the way out.
    """
    merged = dict(base)
    if kind is not None:
        merged[_KIND_META_KEY] = kind
    if description is not None:
        if description:
            merged[_DESCRIPTION_META_KEY] = description
        else:
            merged.pop(_DESCRIPTION_META_KEY, None)
    return merged


class MembershipResponse(BaseModel):
    """Team membership in API responses.

    ``email`` / ``full_name`` are filled in by the service when it joins the
    membership rows to ``User``; they stay empty on the paths that do not, so a
    caller can always rely on the id fields and treat the display fields as a
    convenience.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    team_id: UUID
    user_id: UUID
    role: str
    email: str = ""
    full_name: str = ""
    is_active: bool = True
    created_at: datetime


class TeamResponse(BaseModel):
    """Team in API responses."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    name: str
    name_translations: dict[str, str] | None = None
    description: str = ""
    kind: str = DEFAULT_TEAM_KIND
    sort_order: int
    is_default: bool
    is_active: bool
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    memberships: list[MembershipResponse] = Field(default_factory=list)
    member_count: int = 0
    #: How many records in the project this team is allowed to see that other
    #: teams are not. ``None`` when the caller asked for a shape that does not
    #: count them, so zero always means "counted, and there are none".
    restricted_record_count: int | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def _lift_metadata_fields(self) -> "TeamResponse":
        """Surface the two schema-owned metadata keys as typed fields.

        Runs after validation so it sees the stored ``metadata`` dict whether
        the instance came from an ORM row or from a plain dict. An unknown or
        missing ``kind`` reads back as the default rather than raising - a row
        written before this catalogue existed must still be listable.
        """
        meta = self.metadata or {}
        if not self.description:
            stored = meta.get(_DESCRIPTION_META_KEY)
            if isinstance(stored, str):
                self.description = stored
        stored_kind = meta.get(_KIND_META_KEY)
        if isinstance(stored_kind, str) and stored_kind in TEAM_KINDS:
            self.kind = stored_kind
        if not self.member_count:
            self.member_count = len(self.memberships)
        return self


# ── Membership ───────────────────────────────────────────────────────────


class UpdateMemberRoleRequest(BaseModel):
    """Change the role a user holds inside a team.

    Split from :class:`AddMemberRequest` because the two answer different
    questions - "who is on this team" versus "what does this person do here" -
    and because a role change into an ELEVATED role goes through the same
    owner-only gate as granting one on the way in.
    """

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    role: str = Field(..., pattern=_TEAM_ROLE_PATTERN)


class AddMemberRequest(BaseModel):
    """Add a user to a team.

    The role whitelist accepts both the legacy team-internal roles
    (``member`` / ``lead`` - used by the bare /teams endpoints) and the
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


def _validate_entity_type(value: str) -> str:
    """Reject a record kind outside the catalogue.

    A typo would otherwise write a restriction that hides nothing while
    reading as enforced. See :mod:`app.modules.teams.entity_types`.
    """
    if value not in VISIBILITY_ENTITY_TYPE_KEYS:
        raise ValueError(
            f"[teams.validation.entity_type.unknown] '{value}' is not a record kind that can be restricted"
        )
    return value


class EntityVisibilityCreate(BaseModel):
    """Restrict one record to one team."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    entity_type: str = Field(..., min_length=1, max_length=100)
    entity_id: str = Field(..., min_length=1, max_length=36)
    team_id: UUID

    @field_validator("entity_type")
    @classmethod
    def _known_entity_type(cls, v: str) -> str:
        return _validate_entity_type(v)

    @field_validator("entity_id")
    @classmethod
    def _sanitize_entity_id(cls, v: str) -> str:
        return _reject_unsafe_string(v, "entity_id")


class TeamVisibilityGrantRequest(BaseModel):
    """Restrict one record to the team named in the path."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    entity_type: str = Field(..., min_length=1, max_length=100)
    entity_id: str = Field(..., min_length=1, max_length=36)

    @field_validator("entity_type")
    @classmethod
    def _known_entity_type(cls, v: str) -> str:
        return _validate_entity_type(v)

    @field_validator("entity_id")
    @classmethod
    def _sanitize_entity_id(cls, v: str) -> str:
        return _reject_unsafe_string(v, "entity_id")


class SetEntityVisibilityRequest(BaseModel):
    """Replace the full set of teams a record is restricted to.

    This is the operation the UI performs: the operations lead ticks the teams
    that may see a record and saves once. An empty list lifts the restriction
    entirely and returns the record to "open to every project member", which is
    the widest state reachable and is still narrower than the project itself.
    """

    model_config = ConfigDict(extra="ignore")

    team_ids: list[UUID] = Field(default_factory=list, max_length=200)

    @field_validator("team_ids")
    @classmethod
    def _dedupe(cls, v: list[UUID]) -> list[UUID]:
        seen: set[UUID] = set()
        out: list[UUID] = []
        for team_id in v:
            if team_id not in seen:
                seen.add(team_id)
                out.append(team_id)
        return out


class EntityVisibilityResponse(BaseModel):
    """A single restriction row in API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    entity_type: str
    entity_id: str
    team_id: UUID
    created_at: datetime


class VisibilityTeamRef(BaseModel):
    """The team side of a restriction, denormalised for display."""

    team_id: UUID
    name: str
    kind: str = DEFAULT_TEAM_KIND
    is_active: bool = True
    member_count: int = 0


class EntityVisibilityState(BaseModel):
    """Who can see one record, and whether anything enforces it.

    ``restricted`` False means no row exists, so the record follows plain
    project access. ``viewer_count`` counts the distinct users reachable
    through the named teams and deliberately excludes the project owner and
    system admins, who always retain access - a zero there is the "nobody but
    the owner can open this any more" state the validation rules flag.
    """

    entity_type: str
    entity_id: str
    project_id: UUID
    restricted: bool
    teams: list[VisibilityTeamRef] = Field(default_factory=list)
    viewer_count: int = 0
    #: False when no consumer subtracts this record kind yet, so the UI can say
    #: "recorded, not yet enforced" instead of implying a lock that is not there.
    enforced: bool = False
    #: Whether the caller themselves would still reach this record under the
    #: current teams. Lets the panel warn "you are about to restrict this to
    #: teams you are not on" before the save rather than after it.
    caller_can_see: bool = True


class RestrictedEntityRow(BaseModel):
    """One restricted record in the project-wide restriction register."""

    entity_type: str
    entity_id: str
    team_ids: list[UUID] = Field(default_factory=list)
    team_names: list[str] = Field(default_factory=list)
    viewer_count: int = 0
    enforced: bool = False


class EntityTypeResponse(BaseModel):
    """One record kind that can carry a restriction."""

    key: str
    label: str
    module: str
    enforced: bool


class AccessMatrixMember(BaseModel):
    """One person's effective reach across a project's restricted records."""

    user_id: UUID
    email: str = ""
    full_name: str = ""
    is_project_owner: bool = False
    is_system_admin: bool = False
    team_ids: list[UUID] = Field(default_factory=list)
    team_names: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    #: Of the project's restricted records, how many this person can still
    #: open, and how many are now closed to them.
    visible_restricted_count: int = 0
    hidden_restricted_count: int = 0


class AccessMatrixResponse(BaseModel):
    """The whole project's "who sees what" answer in one payload."""

    project_id: UUID
    restricted_record_count: int = 0
    members: list[AccessMatrixMember] = Field(default_factory=list)


class TeamsValidationFinding(BaseModel):
    """One validation-rule result rendered for the UI.

    ``key`` is the stable i18n key (``teams.validation.<rule_id>``); ``context``
    carries the rule's own details plus the rendered English message, so a
    locale that has not been swept yet still shows something true.
    """

    rule_id: str
    key: str
    severity: str
    message: str
    element_ref: str | None = None
    suggestion: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class TeamsValidationReport(BaseModel):
    """The teams rule set run over one project."""

    project_id: UUID
    status: str
    #: ``None`` when nothing was checked (no teams yet, or the run failed).
    #: Never coerced to 1.0 - "not checked" must not read as "clean".
    score: float | None = None
    error_count: int = 0
    warning_count: int = 0
    findings: list[TeamsValidationFinding] = Field(default_factory=list)


def entity_type_catalogue() -> list[EntityTypeResponse]:
    """The catalogue as API rows, computed once per call from the tuple."""
    from app.modules.teams.entity_types import VISIBILITY_ENTITY_TYPES

    enforced = enforced_entity_type_keys()
    return [
        EntityTypeResponse(key=et.key, label=et.label, module=et.module, enforced=et.key in enforced)
        for et in VISIBILITY_ENTITY_TYPES
    ]
