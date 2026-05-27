# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File References Pydantic schemas — request/response models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── Constants (mirrors file_comments.schemas.ALLOWED_FILE_KINDS) ───────

ALLOWED_FILE_KINDS: tuple[str, ...] = (
    "document",
    "photo",
    "sheet",
    "bim_model",
    "dwg_drawing",
    "takeoff",
    "report",
    "markup",
)
_FILE_KIND_PATTERN = r"^(document|photo|sheet|bim_model|dwg_drawing|takeoff|report|markup)$"

# Target type union — open by design, validated by the schema but not
# foreign-keyed. The string list is exported so the frontend can render
# a typeahead picker without round-tripping to /api/.
ALLOWED_TARGET_TYPES: tuple[str, ...] = (
    "rfi",
    "issue",
    "task",
    "submittal",
    "punch_item",
    "change_order",
    "meeting",
    "field_report",
    "tender_package",
    "bid",
    "contract",
    "transmittal",
    "bcf_topic",
    "boq_position",
    "project",
    "clash_run",
)
_TARGET_TYPE_PATTERN = (
    r"^(rfi|issue|task|submittal|punch_item|change_order|meeting|"
    r"field_report|tender_package|bid|contract|transmittal|bcf_topic|"
    r"boq_position|project|clash_run)$"
)

# Violation codes — the union is closed because the scanner has finite
# checks. New codes require a backend change anyway (the scanner needs
# to know how to detect them).
ViolationCode = Literal[
    "not-iso19650",
    "missing-volume",
    "bad-level",
    "bad-role-code",
    "bad-number",
    "too-many-parts",
    "too-few-parts",
]

_RULE_SET_PATTERN = r"^(iso19650|none)$"


# ── ISO 19650 validation ──────────────────────────────────────────────


class Iso19650ValidateRequest(BaseModel):
    """Body for ``POST /file-references/validate-name/``."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    filename: str = Field(..., min_length=1, max_length=255)
    rule_set: str = Field(default="iso19650", pattern=_RULE_SET_PATTERN)


class Iso19650Parts(BaseModel):
    """Parsed structural parts of an ISO 19650 filename.

    Any field is ``None`` when the hyphen-split could not isolate it.
    The frontend uses these to pre-populate the IsoNameBuilder wizard.
    """

    project: str | None = None
    originator: str | None = None
    volume: str | None = None
    level: str | None = None
    type: str | None = None
    role: str | None = None
    number: str | None = None
    status: str | None = None
    revision: str | None = None


class Iso19650Result(BaseModel):
    """Result of validating a single filename against ISO 19650."""

    filename: str
    rule_set: str
    is_valid: bool
    violation_codes: list[str] = Field(default_factory=list)
    parts: Iso19650Parts


# ── Project-wide scan ─────────────────────────────────────────────────


class NamingViolationResponse(BaseModel):
    """One row of the ``GET /violations/`` list."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    rule_set: str
    file_kind: str
    file_id: str
    filename: str
    violation_codes: list[str]
    summary: str | None = None
    acknowledged_at: datetime | None = None
    acknowledged_by_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class NamingViolationListResponse(BaseModel):
    """``GET /violations/?project_id=&limit=&offset=`` payload."""

    items: list[NamingViolationResponse]
    total: int
    limit: int
    offset: int


class ProjectScanResponse(BaseModel):
    """Result of running the naming scan over a whole project."""

    project_id: UUID
    rule_set: str
    scanned: int
    violations_added: int
    violations_updated: int
    violations_cleared: int


# ── Cross-entity references ──────────────────────────────────────────


class FileReferenceCreate(BaseModel):
    """Body for ``POST /file-references/``."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    project_id: UUID
    file_kind: str = Field(..., pattern=_FILE_KIND_PATTERN)
    file_id: str = Field(..., min_length=1, max_length=255)
    target_type: str = Field(..., pattern=_TARGET_TYPE_PATTERN)
    target_id: str = Field(..., min_length=1, max_length=255)
    relation: str = Field(default="references", min_length=1, max_length=32)
    target_label: str | None = Field(default=None, max_length=255)


class FileReferenceResponse(BaseModel):
    """One link row returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    file_kind: str
    file_id: str
    target_type: str
    target_id: str
    relation: str
    target_label: str | None = None
    created_by_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class FileReferenceListResponse(BaseModel):
    """``GET /?kind=&file_id=`` or ``GET /by-target/`` payload."""

    items: list[FileReferenceResponse]
    total: int
