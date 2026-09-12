# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pydantic schemas for the authority-submission factory."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── Vocabularies (open-ended; packs may extend via the DB) ─────────────

# Built-in format families. The DB column is a plain String so a regional pack
# can persist a value outside this list; the API validates against the union so
# the built-in UI pickers stay honest.
FORMAT_KEYS: tuple[str, ...] = (
    "minstroy_xml",  # RU Minstroy expertise XML (supplied by a regional pack)
    "gaeb_x83",  # DACH GAEB tender exchange - the proven pattern
    "cobie",  # asset-handover register
    "eplan",  # US e-Plan submission
    "generic_xml",  # jurisdiction-neutral fallback
    "bauantrag_xml",  # DE Bauantrag / Bauvoranfrage
    "doc_package_xml",  # generic document submission package
    "custom",
)

# Submission lifecycle.
STATUSES: tuple[str, ...] = (
    "draft",
    "validated",
    "signed_pending",
    "submitted",
    "accepted",
    "rejected",
)

# Statuses a caller may set through PATCH. draft/validated are reached through
# the validate action, not set by hand; submitted is reached through submit.
_SETTABLE_STATUSES: tuple[str, ...] = (
    "signed_pending",
    "accepted",
    "rejected",
    "draft",
)
_SETTABLE_STATUS_PATTERN = "^(" + "|".join(_SETTABLE_STATUSES) + ")$"


# ── Profile ────────────────────────────────────────────────────────────


class SubmissionProfileResponse(BaseModel):
    """A submission profile returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    jurisdiction: str | None = None
    format_key: str
    schema_version: str
    root_element: str
    field_spec: list[dict[str, Any]] = Field(default_factory=list)
    description: str = ""
    is_builtin: bool = False
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


# ── Submission create / update ─────────────────────────────────────────


class SubmissionCreate(BaseModel):
    """Body for ``POST /v1/authority-submission/submissions``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    profile_id: UUID
    title: str = Field(..., min_length=1, max_length=255)
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SubmissionUpdate(BaseModel):
    """Body for ``PATCH /v1/authority-submission/submissions/{id}``.

    Editing ``payload`` invalidates any generated XML / validation report and
    resets the lifecycle to ``draft``. ``status`` may only be moved along the
    allowed transitions; ``submitted`` is reached through the dedicated submit
    endpoint, not here.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=255)
    payload: dict[str, Any] | None = None
    status: str | None = Field(default=None, pattern=_SETTABLE_STATUS_PATTERN)
    metadata: dict[str, Any] | None = None


# ── Submission response ────────────────────────────────────────────────


class SubmissionResponse(BaseModel):
    """A submission returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    profile_id: UUID
    title: str
    payload: dict[str, Any] = Field(default_factory=dict)
    status: str = "draft"
    generated_xml: str | None = None
    validation_report: dict[str, Any] | None = None
    submitted_at: datetime | None = None
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias="metadata_",
    )
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


class ValidationReportResponse(BaseModel):
    """The structured report returned by the validate endpoint."""

    model_config = ConfigDict(from_attributes=True)

    status: str
    score: float
    checked: int
    errors: int
    missing_required: list[str] = Field(default_factory=list)
    type_mismatches: list[dict[str, Any]] = Field(default_factory=list)
    results: list[dict[str, Any]] = Field(default_factory=list)


class GeneratedXmlResponse(BaseModel):
    """The XML returned by the generate-xml endpoint."""

    submission_id: UUID
    xml: str


__all__ = [
    "FORMAT_KEYS",
    "STATUSES",
    "GeneratedXmlResponse",
    "SubmissionCreate",
    "SubmissionProfileResponse",
    "SubmissionResponse",
    "SubmissionUpdate",
    "ValidationReportResponse",
]
