# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Rebar schedule Pydantic schemas (request/response models)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.rebar_schedule.abs_format import SUPER_GROUPS

_GROUP_PATTERN = "^(" + "|".join(SUPER_GROUPS) + ")$"


class AbsFinding(BaseModel):
    """One validation finding against one record."""

    rule_id: str
    rule_name: str
    severity: str
    category: str
    passed: bool
    message: str
    element_ref: str | None = None
    suggestion: str | None = None


class AbsValidationSummary(BaseModel):
    """What the ``bvbs_abs`` rule set made of a file."""

    status: str = Field(description="passed, info, warnings or errors")
    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    # Only failing results travel; a report over a thousand shapes would
    # otherwise be almost entirely rows saying OK.
    findings: list[AbsFinding] = Field(default_factory=list)


class RebarShapeResponse(BaseModel):
    """One bending shape."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    import_id: UUID
    project_id: UUID
    line_no: int
    super_group: str
    project_ref: str | None = None
    drawing_ref: str | None = None
    drawing_index: str | None = None
    position: str | None = None
    length_mm: Decimal | None = None
    quantity: int | None = None
    weight_kg: Decimal | None = None
    diameter_mm: Decimal | None = None
    steel_grade: str | None = None
    bending_roller_mm: Decimal | None = None
    mesh_type: str | None = None
    width_mm: Decimal | None = None
    height_mm: Decimal | None = None
    layer: int | None = None
    stagger_group: str | None = None
    geometry: dict | None = None
    block_layout: str | None = None
    checksum_ok: bool = True
    raw: str


class RebarShapeListResponse(BaseModel):
    """A page of bending shapes."""

    items: list[RebarShapeResponse]
    total: int
    offset: int
    limit: int


class RebarImportResponse(BaseModel):
    """One imported ABS file."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    filename: str
    content_sha256: str
    encoding: str
    record_count: int
    total_weight_kg: Decimal | None = None
    validation_status: str
    error_count: int
    warning_count: int
    created_by: str | None = None
    created_at: datetime | None = None


class RebarImportListResponse(BaseModel):
    """A page of imports."""

    items: list[RebarImportResponse]
    total: int
    offset: int
    limit: int


class RebarImportResult(BaseModel):
    """What an import call returns: the stored file plus its findings."""

    import_record: RebarImportResponse
    validation: AbsValidationSummary
    # True when the file's bytes were already imported into this project and
    # the existing import was returned untouched.
    duplicate: bool = False


class AbsPreviewRequest(BaseModel):
    """A dry run: parse and validate without storing anything."""

    model_config = ConfigDict(str_strip_whitespace=False)

    content: str = Field(min_length=1, description="The ABS file's text")
    locale: str | None = Field(default=None, max_length=16)


class AbsPreviewShape(BaseModel):
    """One shape as seen by a dry run, before anything is stored."""

    line_no: int
    super_group: str
    drawing_ref: str | None = None
    position: str | None = None
    length_mm: Decimal | None = None
    quantity: int | None = None
    weight_kg: Decimal | None = None
    diameter_mm: Decimal | None = None
    steel_grade: str | None = None
    checksum_ok: bool
    block_layout: str


class AbsPreviewResponse(BaseModel):
    """The result of a dry run."""

    record_count: int
    encoding: str
    total_weight_kg: Decimal | None = None
    shapes: list[AbsPreviewShape]
    validation: AbsValidationSummary


class CuttingItem(BaseModel):
    """One diameter row in a cutting summary."""

    diameter_mm: str
    bars: int
    weight_kg: float


class SuperGroupInfo(BaseModel):
    """One super-group of the standard, for a picker."""

    code: str = Field(pattern=_GROUP_PATTERN)
    kind: str = Field(description="i18n key naming what the super-group covers")


class SuperGroupsResponse(BaseModel):
    """The super-groups the format defines, and the rule set that checks them."""

    groups: list[SuperGroupInfo]
    rule_set: str
    rule_ids: list[str]
    max_record_length: int
