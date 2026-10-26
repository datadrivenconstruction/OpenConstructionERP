# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Drawing revision compare Pydantic schemas.

A PDF compare is computed in the browser and posted with its regions; a DWG
compare is computed by the server from two parsed drawing versions. Both read
back in the same shape. Thumbnails are small data URLs (PNG from the browser,
SVG from the server) and are capped so a compare row stays light.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_CHANGES = 500
MAX_THUMBNAIL_CHARS = 60_000
_THUMB_PREFIXES = ("data:image/png;base64,", "data:image/jpeg;base64,", "data:image/svg+xml;base64,")

ChangeKind = Literal["added", "removed", "modified", "text"]
ChangeStatus = Literal["open", "relevant", "not_relevant"]


class AlignmentIn(BaseModel):
    """How the old sheet was laid onto the new one."""

    method: Literal["none", "auto", "manual"] = "none"
    matrix: list[float] = Field(default_factory=lambda: [1.0, 0.0, 0.0, 1.0, 0.0, 0.0], min_length=6, max_length=6)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    points_old: list[list[float]] = Field(default_factory=list, max_length=2)
    points_new: list[list[float]] = Field(default_factory=list, max_length=2)

    @field_validator("matrix")
    @classmethod
    def _finite(cls, v: list[float]) -> list[float]:
        if not all(math.isfinite(x) for x in v):
            raise ValueError("matrix must hold finite numbers")
        return v


class ChangeIn(BaseModel):
    """One changed region found in the browser."""

    kind: ChangeKind
    page: int | None = Field(default=None, ge=1)
    x: float = Field(..., allow_inf_nan=False)
    y: float = Field(..., allow_inf_nan=False)
    w: float = Field(..., ge=0.0, allow_inf_nan=False)
    h: float = Field(..., ge=0.0, allow_inf_nan=False)
    score: float | None = Field(default=None, ge=0.0, allow_inf_nan=False)
    old_text: str | None = Field(default=None, max_length=2000)
    new_text: str | None = Field(default=None, max_length=2000)
    details: dict[str, Any] = Field(default_factory=dict)
    thumbnail: str | None = Field(default=None, max_length=MAX_THUMBNAIL_CHARS)

    @field_validator("thumbnail")
    @classmethod
    def _thumb(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith(_THUMB_PREFIXES):
            raise ValueError("thumbnail must be a PNG, JPEG or SVG data URL")
        return v


class PdfComparisonCreate(BaseModel):
    """Store a PDF sheet compare computed in the browser."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    name: str = Field(default="", max_length=255)
    old_ref_id: str = Field(..., min_length=1, max_length=64)
    new_ref_id: str = Field(..., min_length=1, max_length=64)
    old_page: int = Field(default=1, ge=1, le=10_000)
    new_page: int = Field(default=1, ge=1, le=10_000)
    page_width: float = Field(..., gt=0, allow_inf_nan=False)
    page_height: float = Field(..., gt=0, allow_inf_nan=False)
    alignment: AlignmentIn = Field(default_factory=AlignmentIn)
    settings: dict[str, Any] = Field(default_factory=dict)
    changes: list[ChangeIn] = Field(default_factory=list, max_length=MAX_CHANGES)


class DwgComparisonCreate(BaseModel):
    """Ask the server to diff two DWG/DXF revisions.

    Either two versions (of one drawing or of two drawings) or two drawings,
    in which case each drawing's latest parsed version is used.
    """

    project_id: UUID
    name: str = Field(default="", max_length=255)
    old_drawing_id: UUID
    new_drawing_id: UUID
    old_version_id: UUID | None = None
    new_version_id: UUID | None = None
    tolerance: float | None = Field(default=None, gt=0, allow_inf_nan=False)


class ChangeUpdate(BaseModel):
    """Reviewer's triage of one change."""

    model_config = ConfigDict(str_strip_whitespace=True)

    status: ChangeStatus | None = None
    comment: str | None = Field(default=None, max_length=5000)


class ChangeRfiCreate(BaseModel):
    """Raise an RFI from a change; empty fields are prefilled from the change."""

    model_config = ConfigDict(str_strip_whitespace=True)

    subject: str | None = Field(default=None, max_length=500)
    question: str | None = Field(default=None, max_length=10_000)
    priority: Literal["low", "normal", "high", "critical"] = "normal"


class ChangeMarkupCreate(BaseModel):
    """Drop a revision cloud on the new sheet around a change."""

    model_config = ConfigDict(str_strip_whitespace=True)

    text: str | None = Field(default=None, max_length=2000)
    color: str = Field(default="#dc2626", max_length=20)


class ChangeResponse(BaseModel):
    """One changed region as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    comparison_id: UUID
    seq: int
    kind: str
    page: int | None = None
    x: float
    y: float
    w: float
    h: float
    score: float | None = None
    old_text: str | None = None
    new_text: str | None = None
    layer: str | None = None
    entity_type: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    thumbnail: str | None = None
    status: str
    comment: str | None = None
    rfi_id: str | None = None
    markup_id: str | None = None
    flagged_at: datetime | None = None
    flagged_measurement_ids: list[str] = Field(default_factory=list)
    flagged_annotation_ids: list[str] = Field(default_factory=list)
    flagged_position_ids: list[str] = Field(default_factory=list)
    reviewed_by: str | None = None
    updated_at: datetime


class ComparisonSummary(BaseModel):
    """A stored compare without its change list (register view)."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    source_kind: str
    old_ref_id: str
    new_ref_id: str
    old_page: int | None = None
    new_page: int | None = None
    old_label: str
    new_label: str
    old_revision: str | None = None
    new_revision: str | None = None
    page_width: float | None = None
    page_height: float | None = None
    alignment: dict[str, Any] = Field(default_factory=dict)
    settings: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    created_by: str
    created_at: datetime
    updated_at: datetime


class ComparisonResponse(ComparisonSummary):
    """A stored compare with every change."""

    changes: list[ChangeResponse] = Field(default_factory=list)


class AffectedItem(BaseModel):
    """A takeoff measurement, DWG annotation or markup that sits inside a change."""

    id: str
    source: Literal["takeoff", "dwg_annotation", "markup"]
    document_id: str | None = None
    page: int | None = None
    label: str = ""
    revision: Literal["old", "new"]
    linked_boq_position_id: str | None = None


class AffectedPosition(BaseModel):
    """A BOQ position whose quantity comes from something inside a change."""

    id: str
    ordinal: str = ""
    description: str = ""


class RemeasureResponse(BaseModel):
    """What sits inside a change, and whether it was flagged.

    ``dry_run`` answers "what would be flagged" so the user confirms before
    anything is written.
    """

    change_id: UUID
    dry_run: bool
    items: list[AffectedItem] = Field(default_factory=list)
    positions: list[AffectedPosition] = Field(default_factory=list)
    flagged_at: datetime | None = None


class FollowUpResponse(BaseModel):
    """The id of the RFI or markup raised from a change, plus the change."""

    target_id: str
    label: str = ""
    change: ChangeResponse


class PreviousRevisionResponse(BaseModel):
    """The revision a takeoff document most likely supersedes, if one is known."""

    document_id: str
    previous_document_id: str | None = None
    previous_label: str | None = None
    source: Literal["documents_chain", "none"] = "none"


class ValidationResultOut(BaseModel):
    """One rule result of the ``drawing_compare`` rule set."""

    rule_id: str
    severity: str
    passed: bool
    message: str
    element_ref: str | None = None
    suggestion: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ValidationResponse(BaseModel):
    """Traffic-light summary of a compare's validation."""

    status: str
    score: float | None = None
    errors: int = 0
    warnings: int = 0
    results: list[ValidationResultOut] = Field(default_factory=list)
