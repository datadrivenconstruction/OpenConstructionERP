# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Surfaces and volumes request and response schemas.

Volumes travel as JSON numbers in m3 rounded to the millimetre cube the screen
never shows; the screen shows one decimal, the BOQ three.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Method = Literal["grid", "tin", "end_area"]
QuantityKind = Literal["cut", "fill", "net", "loose_cut"]
Ring = list[tuple[float, float]]


class Finding(BaseModel):
    rule_id: str
    severity: str
    message: str
    suggestion: str | None = None
    element_ref: str | None = None


class SurfaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    code: str
    name: str
    source: str
    point_set_id: uuid.UUID | None = None
    source_filename: str = ""
    epsg: int | None = None
    accuracy_tier: str | None = None
    point_count: int = 0
    triangle_count: int = 0
    area_m2: float = 0.0
    z_min: float | None = None
    z_max: float | None = None
    note: str = ""
    in_use: int = 0
    created_at: datetime | None = None
    breakline_count: int = 0
    findings: list[Finding] = Field(default_factory=list)


class SurfaceFromPoints(BaseModel):
    """A surface triangulated from one or more imported point sets."""

    name: str = Field(min_length=1, max_length=255)
    point_set_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)
    note: str = Field(default="", max_length=2000)
    #: Polylines of [e, n, z] kept as triangle edges (toe, crest, kerb).
    breaklines: list[list[tuple[float, float, float]]] = Field(default_factory=list, max_length=2000)
    #: Point codes whose points, in file order, are strung into one breakline per code.
    breakline_codes: list[str] = Field(default_factory=list, max_length=50)
    #: Outer boundary: triangles outside it are dropped.
    boundary: Ring | None = None

    @field_validator("boundary")
    @classmethod
    def _ring(cls, v: Ring | None) -> Ring | None:
        if v is not None and len(v) < 3:
            raise ValueError("A boundary needs at least three corners")
        return v


class LandXmlImport(BaseModel):
    text: str = Field(max_length=30_000_000)
    filename: str = Field(default="", max_length=255)
    name: str = Field(default="", max_length=255)


class LandXmlResult(BaseModel):
    surfaces: list[SurfaceOut]
    problems: list[str] = Field(default_factory=list)
    declared_epsg: int | None = None
    project_epsg: int | None = None


class VolumeCreate(BaseModel):
    """New volume: three fields for a beginner, the rest under Advanced options."""

    name: str = Field(min_length=1, max_length=255)
    base_surface_id: uuid.UUID
    compare_surface_id: uuid.UUID
    method: Method = "grid"
    cell_size_m: float | None = Field(default=None, gt=0, le=1000)
    boundary: Ring | None = None
    material: str = Field(default="", max_length=120)
    swell_factor: float = Field(default=1.0, gt=0, le=5)
    shrink_factor: float = Field(default=1.0, gt=0, le=5)
    override_reason: str = Field(default="", max_length=2000)

    @field_validator("boundary")
    @classmethod
    def _ring(cls, v: Ring | None) -> Ring | None:
        if v is not None and len(v) < 3:
            raise ValueError("A boundary needs at least three corners")
        return v


class VolumeUpdate(BaseModel):
    """Recompute a draft with changed parameters."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    method: Method | None = None
    cell_size_m: float | None = Field(default=None, gt=0, le=1000)
    cell_auto: bool | None = None
    boundary: Ring | None = None
    clear_boundary: bool = False
    material: str | None = Field(default=None, max_length=120)
    swell_factor: float | None = Field(default=None, gt=0, le=5)
    shrink_factor: float | None = Field(default=None, gt=0, le=5)
    override_reason: str | None = Field(default=None, max_length=2000)


class VolumeDuplicate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    method: Method | None = None
    cell_size_m: float | None = Field(default=None, gt=0, le=1000)
    swell_factor: float | None = Field(default=None, gt=0, le=5)
    shrink_factor: float | None = Field(default=None, gt=0, le=5)
    material: str | None = Field(default=None, max_length=120)


class VolumeOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    code: str
    name: str
    base_surface_id: uuid.UUID | None = None
    compare_surface_id: uuid.UUID | None = None
    base_name: str = ""
    compare_name: str = ""
    method: str
    cell_size_m: float | None = None
    cell_auto: bool = True
    boundary: list[list[float]] | None = None
    material: str = ""
    swell_factor: float = 1.0
    shrink_factor: float = 1.0
    cut_m3: float = 0.0
    fill_m3: float = 0.0
    net_m3: float = 0.0
    loose_cut_m3: float = 0.0
    fill_bank_m3: float = 0.0
    calc_area_m2: float = 0.0
    covered_area_m2: float = 0.0
    coverage_pct: float = 0.0
    confidence: float | None = None
    crs_epsg: int | None = None
    crs_name: str = ""
    accuracy_tier: str | None = None
    status: str = "draft"
    confirmed_by: uuid.UUID | None = None
    confirmed_by_name: str = ""
    confirmed_at: datetime | None = None
    override_reason: str = ""
    duplicated_from_id: uuid.UUID | None = None
    boq_position_id: uuid.UUID | None = None
    computed_at: datetime | None = None
    created_at: datetime | None = None
    findings: list[Finding] = Field(default_factory=list)


class VolumeDetail(VolumeOut):
    heat: dict[str, Any] | None = None
    sections: list[dict[str, Any]] | None = None


class ConfirmRequest(BaseModel):
    """Warnings must be acknowledged by rule id; errors cannot be."""

    acknowledge: list[str] = Field(default_factory=list, max_length=20)


class SendToBoq(BaseModel):
    position_id: uuid.UUID
    mode: Literal["replace", "add"] = "replace"
    quantity: QuantityKind = "cut"


class SendToBoqResult(BaseModel):
    position_id: uuid.UUID
    ordinal: str
    description: str
    unit: str
    quantity: str
    sent_m3: float
    formula: str
    source: dict[str, Any]
    findings: list[Finding] = Field(default_factory=list)


class RecordProgress(BaseModel):
    position_id: uuid.UUID | None = None
    period_label: str = Field(default="", max_length=20)
    quantity: QuantityKind = "cut"
    notes: str = Field(default="", max_length=1000)


class CertifyQuantity(BaseModel):
    """Offer a measured quantity to the open payment certificate; ``confirm`` is a separate call."""

    position_id: uuid.UUID | None = None
    quantity: QuantityKind = "cut"
    claim_id: uuid.UUID | None = None
    period_label: str = Field(default="", max_length=20)


class RecordProgressResult(BaseModel):
    entry_id: uuid.UUID
    position_id: uuid.UUID
    percent_complete: float
    quantity_m3: float
    period_label: str


class VolumeEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    action: str
    target_type: str = ""
    target_id: str = ""
    quantity: float | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    user_id: uuid.UUID | None = None
    user_name: str = ""
    created_at: datetime | None = None


class VolumeSummary(BaseModel):
    """The KPI band of the Volumes page, over confirmed and sent calculations when any exist."""

    calculations: int = 0
    confirmed: int = 0
    cut_m3: float = 0.0
    fill_m3: float = 0.0
    net_m3: float = 0.0
    coverage_pct: float | None = None
    surfaces: int = 0
    findings: int = 0


class BoqPositionHit(BaseModel):
    id: uuid.UUID
    boq_id: uuid.UUID
    boq_name: str
    ordinal: str
    description: str
    unit: str
    quantity: str


class BoqPositionHitListResponse(BaseModel):
    items: list[BoqPositionHit]
    total: int
    offset: int = 0
    limit: int = 50


class VolumeEventListResponse(BaseModel):
    items: list[VolumeEventOut]
    total: int
    offset: int = 0
    limit: int = 50


class SurfaceListResponse(BaseModel):
    items: list[SurfaceOut]
    total: int
    offset: int = 0
    limit: int = 50


class VolumeListResponse(BaseModel):
    items: list[VolumeOut]
    total: int
    offset: int = 0
    limit: int = 50


# ── Point cloud and staged volumes ─────────────────────────────────────────


class CloudImportResult(BaseModel):
    """A surface gridded from a LAS/LAZ cloud, with what was read."""

    surface: SurfaceOut
    points_read: int
    points_used: int
    ground_points: int
    used_all_classes: bool
    cells: int
    cell_size_m: float
    stat: str
    las_version: str = ""
    compressed: bool = False


class MaterialFactors(BaseModel):
    """Bank to loose and bank to compacted, entered by the user; no default exists."""

    loose: float | None = Field(default=None, gt=0, le=5)
    compacted: float | None = Field(default=None, gt=0, le=5)


class StageIn(BaseModel):
    """A surveyed surface, or a strip of the stage before by ``strip_depth_m``."""

    label: str = Field(default="", max_length=120)
    surface_id: uuid.UUID | None = None
    strip_depth_m: float | None = Field(default=None, gt=0, le=50)
    surveyed_on: str = Field(default="", max_length=10)
    #: What moves between the stage before and this one (topsoil, bulk cut, rock).
    material: str = Field(default="", max_length=120)


class StagedRequest(BaseModel):
    stages: list[StageIn] = Field(min_length=2, max_length=24)
    method: Method = "grid"
    cell_size_m: float | None = Field(default=None, gt=0, le=1000)
    boundary: Ring | None = None
    factors: dict[str, MaterialFactors] = Field(default_factory=dict)


class StageStep(BaseModel):
    index: int
    from_label: str
    to_label: str
    surveyed_on: str = ""
    material: str = ""
    cut_m3: float
    fill_m3: float
    net_m3: float
    coverage_pct: float
    cut_loose_m3: float | None = None
    fill_bank_needed_m3: float | None = None
    cumulative_cut_m3: float
    cumulative_fill_m3: float


class StagedResult(BaseModel):
    steps: list[StageStep]
    total_cut_m3: float
    total_fill_m3: float
    method: str
    findings: list[Finding] = Field(default_factory=list)
