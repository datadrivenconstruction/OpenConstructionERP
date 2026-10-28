# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Request bodies of the stakeholders API. Responses are plain JSON built by the service.

Every request model forbids unknown fields, so a client that sends a computed
value (a classification, ``next_due``, ``overdue``) is told so instead of
having it silently ignored (rule 2: classification is never accepted).
Money arrives as a decimal string.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

_CODE = r"^[a-z0-9][a-z0-9_]*$"
# A stakeholder code as people write it (S-001, NB.12): no spaces, no control characters.
_REF = r"^[A-Za-z0-9][A-Za-z0-9._/-]*$"
# Head counts are stored in a 32-bit integer; nothing real comes near this.
_MAX_COUNT = 100_000_000


# Keys of a stakeholder's ``geo``: free text (None) or a coordinate bounded by the given magnitude.
GEO_LIMITS: dict[str, float | None] = {"address": None, "parcel_ref": None, "lat": 90.0, "lon": 180.0}


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SettingsPut(_In):
    framework_source: Literal["shipped", "tenant", "pack"] | None = None
    framework_id: str | None = Field(default=None, max_length=64)
    framework_version: int | None = Field(default=None, ge=1)
    analysis_method: str | None = Field(default=None, max_length=64)
    review_interval_days: int | None = Field(default=None, ge=1, le=3650)
    owner_area_code: str | None = Field(default=None, max_length=64)
    commitment_route_id: uuid.UUID | None = None


class StakeholderIn(_In):
    code: str | None = Field(default=None, pattern=_REF, max_length=40)
    display_name: str | None = Field(default=None, max_length=255)
    category: str | None = Field(default=None, max_length=64)
    contact_id: uuid.UUID | None = None
    is_group: bool | None = None
    group_size_estimate: int | None = Field(default=None, ge=0, le=_MAX_COUNT)
    parent_stakeholder_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    interests: str | None = Field(default=None, max_length=10000)
    expectations: str | None = Field(default=None, max_length=10000)
    concerns: str | None = Field(default=None, max_length=10000)
    relationship_owner_user_id: uuid.UUID | None = None
    geo: dict[str, str] | None = None
    is_confidential: bool | None = None
    status: Literal["active", "dormant", "archived"] | None = None
    risk_id: uuid.UUID | None = None

    @field_validator("geo")
    @classmethod
    def _geo_keys(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        """``address``, ``parcel_ref``, ``lat``, ``lon``; empty values are dropped, coordinates must be on the globe."""
        if value is None:
            return None
        out: dict[str, str] = {}
        for key, raw in value.items():
            if key not in GEO_LIMITS:
                raise ValueError(f"unknown geo key: {key}")
            text = raw.strip()
            if not text:
                continue
            limit = GEO_LIMITS[key]
            if limit is None:
                if len(text) > 255:
                    raise ValueError(f"geo.{key} is too long")
            else:
                try:
                    number = float(text)
                except ValueError as exc:
                    raise ValueError(f"geo.{key} is not a number") from exc
                if not -limit <= number <= limit:
                    raise ValueError(f"geo.{key} is out of range")
            out[key] = text
        return out or None


class AssessmentIn(_In):
    method_code: str | None = Field(default=None, max_length=64)
    scores: dict[str, int | bool]
    engagement_current: str | None = Field(default=None, max_length=32)
    engagement_desired: str | None = Field(default=None, max_length=32)
    attitude: int | None = Field(default=None, ge=-2, le=2)
    rationale: str = Field(default="", max_length=5000)


class PlanItemIn(_In):
    title: str | None = Field(default=None, max_length=255)
    purpose: str | None = Field(default=None, max_length=10000)
    key_message: str | None = Field(default=None, max_length=10000)
    audience_stakeholder_ids: list[uuid.UUID] | None = None
    audience_categories: list[str] | None = None
    audience_body_id: uuid.UUID | None = None
    participation_level: str | None = Field(default=None, max_length=32)
    channel: str | None = Field(default=None, max_length=32)
    format_code: str | None = Field(default=None, max_length=64)
    frequency: str | None = Field(default=None, max_length=255)
    trigger_kind: Literal["gate", "event"] | None = None
    trigger_ref: str | None = Field(default=None, max_length=128)
    owner_user_id: uuid.UUID | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    status: Literal["planned", "active", "paused", "completed", "cancelled"] | None = None


class EventIn(_In):
    plan_item_id: uuid.UUID | None = None
    occurrence_date: date | None = None
    format_code: str | None = Field(default=None, max_length=64)
    participation_level: str | None = Field(default=None, max_length=32)
    title: str | None = Field(default=None, max_length=255)
    held_on: date | None = None
    location: str | None = Field(default=None, max_length=255)
    stakeholder_ids: list[uuid.UUID] | None = None
    attendance_count: int | None = Field(default=None, ge=0, le=_MAX_COUNT)
    outcome: str | None = Field(default=None, max_length=10000)
    feedback_summary: str | None = Field(default=None, max_length=10000)
    meeting_id: uuid.UUID | None = None
    correspondence_ids: list[uuid.UUID] | None = None
    cde_container_ids: list[uuid.UUID] | None = None
    status: Literal["planned", "held", "cancelled"] | None = None


class CommitmentIn(_In):
    stakeholder_ids: list[uuid.UUID] | None = None
    source_kind: Literal["event", "meeting", "correspondence", "permit_condition", "manual"] | None = None
    source_ref: str | None = Field(default=None, max_length=255)
    text: str | None = Field(default=None, max_length=10000)
    category: str | None = Field(default=None, max_length=32)
    owner_user_id: uuid.UUID | None = None
    due_date: date | None = None
    verification: str | None = Field(default=None, max_length=10000)
    cost_estimate: str | None = Field(default=None, max_length=40)
    currency: str | None = Field(default=None, max_length=3)
    release_item_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    risk_id: uuid.UUID | None = None
    requirement_id: uuid.UUID | None = None


class CommitmentTransition(_In):
    target: Literal["agreed", "in_progress", "fulfilled", "verified", "withdrawn", "breached"]
    rationale: str = Field(default="", max_length=5000)
    communicated_back_at: datetime | None = None
    loop_not_required_rationale: str = Field(default="", max_length=5000)
    create_risk: bool = False


class HolderIn(_In):
    roster_member_id: uuid.UUID | None = None
    holder_contact_id: uuid.UUID | None = None
    deputy_roster_member_id: uuid.UUID | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    conflict_rationale: str = Field(default="", max_length=5000)


class RoleHoldersPut(_In):
    holders: list[HolderIn]
    custom_label: str = Field(default="", max_length=255)


class BodyIn(_In):
    code: str | None = Field(default=None, pattern=_CODE, max_length=64)
    body_type: str | None = Field(default=None, max_length=64)
    name: str | None = Field(default=None, max_length=255)
    chair_role_code: str | None = Field(default=None, max_length=64)
    quorum_kind: Literal["min_members", "majority", "unanimous"] | None = None
    quorum_min: int | None = Field(default=None, ge=1, le=100)
    decision_level: int | None = Field(default=None, ge=1, le=20)
    meeting_series_ref: str | None = Field(default=None, max_length=64)
    terms_container_id: uuid.UUID | None = None


class MemberIn(_In):
    role_code: str | None = Field(default=None, max_length=64)
    user_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    voting: bool = True
    valid_from: date | None = None
    valid_to: date | None = None


class MembersPut(_In):
    members: list[MemberIn]


class MandateRowIn(_In):
    decision_type: str = Field(max_length=64)
    scope: str = Field(default="", max_length=128)
    holder_kind: Literal["role", "body"]
    holder_code: str = Field(max_length=64)
    letter: Literal["P", "D", "A", "C", "I"]
    scope_note: str = Field(default="", max_length=5000)


class MandatesPut(_In):
    rows: list[MandateRowIn]


class FrameworkCreate(_In):
    code: str = Field(pattern=_CODE, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    based_on_source: Literal["shipped", "tenant"] | None = None
    based_on_id: str | None = Field(default=None, max_length=64)
    based_on_version: int | None = Field(default=None, ge=1)


class FrameworkUpdate(_In):
    name: str | None = Field(default=None, max_length=255)
    body: dict[str, Any] | None = None


class FileExportIn(_In):
    document: Literal["register", "organisation"]
    format: Literal["pdf", "xlsx"] = "pdf"
    # Required once the frame document is binding: the revision then goes through a change request.
    change_reason: str = Field(default="", max_length=5000)
    change_impact: str = Field(default="", max_length=5000)
