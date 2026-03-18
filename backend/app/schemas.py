"""Core schemas — shared Pydantic models for the entire platform.

These models define the canonical data structures.
Used for API request/response, internal data passing, and validation.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ── Enums ───────────────────────────────────────────────────────────────────


class MeasurementUnit(str, Enum):
    M = "m"
    M2 = "m2"
    M3 = "m3"
    KG = "kg"
    T = "t"
    PCS = "pcs"
    LSUM = "lsum"
    H = "h"
    SET = "set"
    LM = "lm"       # linear meter (Laufmeter)
    L = "l"          # liter
    PA = "pa"        # pauschal (lump sum DE)


class SourceType(str, Enum):
    MANUAL = "manual"
    CAD_IMPORT = "cad_import"
    AI_TAKEOFF = "ai_takeoff"
    GAEB_IMPORT = "gaeb_import"
    EXCEL_IMPORT = "excel_import"
    API = "api"


class ValidationStatusEnum(str, Enum):
    PENDING = "pending"
    PASSED = "passed"
    WARNINGS = "warnings"
    ERRORS = "errors"


# ── Base ────────────────────────────────────────────────────────────────────


class OEBase(BaseModel):
    """Base model with common config."""

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )


class OEResponse(OEBase):
    """Base for API responses with id and timestamps."""

    id: UUID
    created_at: datetime
    updated_at: datetime


# ── Project ─────────────────────────────────────────────────────────────────


class ProjectCreate(OEBase):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    region: str = "DACH"  # DACH, UK, US, INTL
    classification_standard: str = "din276"  # din276, nrm, masterformat
    currency: str = "EUR"
    locale: str = "de"
    validation_rule_sets: list[str] = Field(default=["boq_quality"])
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectResponse(OEResponse):
    name: str
    description: str
    region: str
    classification_standard: str
    currency: str
    locale: str
    validation_rule_sets: list[str]
    metadata: dict[str, Any]
    owner_id: UUID


# ── BOQ Position ────────────────────────────────────────────────────────────


class Classification(OEBase):
    """Multi-standard classification codes for a BOQ position."""

    din276: str | None = None   # e.g., "330"
    nrm: str | None = None      # e.g., "2.6.1"
    masterformat: str | None = None  # e.g., "03 30 00"
    uniclass: str | None = None
    omniclass: str | None = None
    custom: dict[str, str] = Field(default_factory=dict)


class PositionCreate(OEBase):
    boq_id: UUID
    parent_id: UUID | None = None
    ordinal: str = Field(..., min_length=1, max_length=50)
    description: str = Field(..., min_length=1)
    unit: MeasurementUnit
    quantity: Decimal = Field(default=Decimal("0"), ge=0)
    unit_rate: Decimal = Field(default=Decimal("0"), ge=0)
    classification: Classification = Field(default_factory=Classification)
    source: SourceType = SourceType.MANUAL
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    assembly_id: UUID | None = None
    cad_element_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PositionResponse(OEResponse):
    boq_id: UUID
    parent_id: UUID | None
    ordinal: str
    description: str
    unit: MeasurementUnit
    quantity: Decimal
    unit_rate: Decimal
    total: Decimal  # computed: quantity × unit_rate
    classification: Classification
    source: SourceType
    confidence: float | None
    assembly_id: UUID | None
    cad_element_ids: list[str]
    validation_status: ValidationStatusEnum
    metadata: dict[str, Any]


class PositionUpdate(OEBase):
    ordinal: str | None = None
    description: str | None = None
    unit: MeasurementUnit | None = None
    quantity: Decimal | None = None
    unit_rate: Decimal | None = None
    classification: Classification | None = None
    metadata: dict[str, Any] | None = None


# ── Cost Database ───────────────────────────────────────────────────────────


class CostItemResponse(OEBase):
    id: UUID
    code: str                    # CWICR code or external code
    description: str             # Multi-language via i18n key or inline
    descriptions: dict[str, str] = Field(default_factory=dict)  # {"en": "...", "de": "..."}
    unit: MeasurementUnit
    rate: Decimal
    currency: str = "EUR"
    source: str = "cwicr"        # cwicr, rsmeans, bki, custom
    classification: Classification = Field(default_factory=Classification)
    components: list[dict[str, Any]] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    region: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class CostSearchQuery(OEBase):
    q: str = ""                  # Text search
    unit: MeasurementUnit | None = None
    classification_code: str | None = None
    source: str | None = None
    region: str | None = None
    min_rate: Decimal | None = None
    max_rate: Decimal | None = None
    locale: str = "en"           # Return descriptions in this language
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    semantic: bool = False       # Use vector search (Qdrant)


# ── CAD Canonical Format ────────────────────────────────────────────────────


class CADElement(OEBase):
    """Single element from CAD conversion — canonical format."""

    id: str
    category: str                # wall, floor, roof, column, beam, door, window, ...
    classification: Classification = Field(default_factory=Classification)
    geometry: dict[str, Any] = Field(default_factory=dict)  # type, length, area, volume, etc.
    properties: dict[str, Any] = Field(default_factory=dict)  # material, fire_rating, etc.
    quantities: dict[str, float] = Field(default_factory=dict)  # area: 37.5, volume: 9.0
    relations: dict[str, str | None] = Field(default_factory=dict)  # level, zone, parent


class CADImportResult(OEBase):
    """Result of a CAD file conversion."""

    format_version: str = "1.0"
    source_type: str             # dwg, dgn, rvt, ifc, pdf
    source_filename: str
    converter_version: str
    elements: list[CADElement]
    levels: list[dict[str, Any]] = Field(default_factory=list)
    zones: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


# ── Validation ──────────────────────────────────────────────────────────────


class ValidationResultSchema(OEBase):
    rule_id: str
    rule_name: str
    severity: str       # error, warning, info
    category: str       # structure, completeness, consistency, compliance, quality
    passed: bool
    message: str
    element_ref: str | None = None
    suggestion: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ValidationReportSchema(OEBase):
    id: str
    target_type: str
    target_id: str
    status: str         # passed, warnings, errors, skipped
    score: float
    rule_sets_applied: list[str]
    results: list[ValidationResultSchema]
    counts: dict[str, int]  # total, passed, errors, warnings, infos
    duration_ms: float


# ── Module ──────────────────────────────────────────────────────────────────


class ModuleInfoSchema(OEBase):
    name: str
    display_name: str
    version: str
    description: str = ""
    author: str = ""
    category: str = "community"
    depends: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    installed: bool = False
    update_available: bool = False


# ── Pagination ──────────────────────────────────────────────────────────────


class PaginatedResponse(OEBase):
    items: list[Any]
    total: int
    limit: int
    offset: int
    has_more: bool
