# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pydantic schemas and canonical vocabularies for site supervision."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── Canonical vocabularies (open-ended; packs may extend via the DB) ───
#
# Jurisdiction-neutral code sets. The DB columns are plain String so a regional
# pack can persist a value outside these lists without a migration; the API
# validates against the union so the built-in UI pickers stay honest.

DISCIPLINES: tuple[str, ...] = (
    "architecture",
    "structure",
    "mep",
    "geotech",
    "general",
    "other",
)

VISIT_STATUSES: tuple[str, ...] = ("planned", "conducted", "reported")

ENTRY_CATEGORIES: tuple[str, ...] = (
    "conformance",  # work observed to conform
    "deviation",  # a departure from the design / spec
    "hidden_works",  # an acceptance-of-hidden-works item (AOSR-style)
    "instruction",  # an instruction issued to the contractor
    "motivated_refusal",  # a reasoned refusal to accept / sign off
)

ENTRY_STATUSES: tuple[str, ...] = ("open", "addressed", "refused_motivated", "closed")

# Categories whose entries, when linked to a change reference, feed the change
# route (change sheet / MOC).
CHANGE_FEEDING_CATEGORIES: tuple[str, ...] = ("instruction", "deviation")

_DISCIPLINE_PATTERN = "^(" + "|".join(DISCIPLINES) + ")$"
_VISIT_STATUS_PATTERN = "^(" + "|".join(VISIT_STATUSES) + ")$"
_ENTRY_CATEGORY_PATTERN = "^(" + "|".join(ENTRY_CATEGORIES) + ")$"
_ENTRY_STATUS_PATTERN = "^(" + "|".join(ENTRY_STATUSES) + ")$"


# ── Visit ──────────────────────────────────────────────────────────────


class SupervisionVisitCreate(BaseModel):
    """Body for ``POST /v1/site-supervision/visits/``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    planned_date: date | None = None
    actual_date: date | None = None
    visitor: str = Field(default="", max_length=255)
    discipline: str = Field(default="general", pattern=_DISCIPLINE_PATTERN)
    status: str = Field(default="planned", pattern=_VISIT_STATUS_PATTERN)
    summary: str = Field(default="", max_length=20000)
    photo_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SupervisionVisitUpdate(BaseModel):
    """Body for ``PATCH /v1/site-supervision/visits/{id}``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    planned_date: date | None = None
    actual_date: date | None = None
    visitor: str | None = Field(default=None, max_length=255)
    discipline: str | None = Field(default=None, pattern=_DISCIPLINE_PATTERN)
    status: str | None = Field(default=None, pattern=_VISIT_STATUS_PATTERN)
    summary: str | None = Field(default=None, max_length=20000)
    photo_refs: list[str] | None = None
    metadata: dict[str, Any] | None = None


class SupervisionVisitResponse(BaseModel):
    """Visit returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    planned_date: date | None = None
    actual_date: date | None = None
    visitor: str = ""
    discipline: str = "general"
    status: str = "planned"
    summary: str = ""
    photo_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


# ── Entry ──────────────────────────────────────────────────────────────


class SupervisionEntryCreate(BaseModel):
    """Body for ``POST /v1/site-supervision/entries/``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    visit_id: UUID
    ordinal: str = Field(default="", max_length=32)
    observation: str = Field(default="", max_length=20000)
    category: str = Field(default="conformance", pattern=_ENTRY_CATEGORY_PATTERN)
    structured_fields: dict[str, Any] = Field(default_factory=dict)
    links_to_change_ref: str | None = Field(default=None, max_length=64)
    status: str = Field(default="open", pattern=_ENTRY_STATUS_PATTERN)


class SupervisionEntryUpdate(BaseModel):
    """Body for ``PATCH /v1/site-supervision/entries/{id}``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    ordinal: str | None = Field(default=None, max_length=32)
    observation: str | None = Field(default=None, max_length=20000)
    category: str | None = Field(default=None, pattern=_ENTRY_CATEGORY_PATTERN)
    structured_fields: dict[str, Any] | None = None
    links_to_change_ref: str | None = Field(default=None, max_length=64)
    status: str | None = Field(default=None, pattern=_ENTRY_STATUS_PATTERN)


class SupervisionEntryRefuse(BaseModel):
    """Body for ``POST /v1/site-supervision/entries/{id}/refuse``.

    A motivated refusal must carry a reason; an empty reason is rejected.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    reason: str = Field(..., min_length=1, max_length=20000)


class SupervisionEntryResponse(BaseModel):
    """Entry returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    visit_id: UUID
    project_id: UUID
    ordinal: str = ""
    observation: str = ""
    category: str = "conformance"
    structured_fields: dict[str, Any] = Field(default_factory=dict)
    links_to_change_ref: str | None = None
    status: str = "open"
    resolved_at: datetime | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


__all__ = [
    "CHANGE_FEEDING_CATEGORIES",
    "DISCIPLINES",
    "ENTRY_CATEGORIES",
    "ENTRY_STATUSES",
    "VISIT_STATUSES",
    "SupervisionEntryCreate",
    "SupervisionEntryRefuse",
    "SupervisionEntryResponse",
    "SupervisionEntryUpdate",
    "SupervisionVisitCreate",
    "SupervisionVisitResponse",
    "SupervisionVisitUpdate",
]
