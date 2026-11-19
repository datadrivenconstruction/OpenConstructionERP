# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Mine survey request and response schemas.

Volumes travel as JSON numbers rounded to the stored precision (0.001 m3,
0.01 t, 0.01 %); the service keeps Decimal arithmetic underneath.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

UnitType = Literal["pit", "bench", "block", "stope", "drive"]


class Finding(BaseModel):
    rule_id: str
    severity: str
    message: str
    suggestion: str = ""
    element_ref: str | None = None


class UnitCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    unit_type: UnitType = "bench"
    density_t_m3: float | None = Field(default=None, gt=0, le=30)
    note: str = Field(default="", max_length=2000)
    design_ch_from_m: float | None = Field(default=None, ge=0, le=1e7)
    design_ch_to_m: float | None = Field(default=None, ge=0, le=1e7)
    design_area_m2: float | None = Field(default=None, gt=0, le=10000)


class UnitUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    unit_type: UnitType | None = None
    density_t_m3: float | None = Field(default=None, gt=0, le=30)
    note: str | None = Field(default=None, max_length=2000)
    design_ch_from_m: float | None = Field(default=None, ge=0, le=1e7)
    design_ch_to_m: float | None = Field(default=None, ge=0, le=1e7)
    design_area_m2: float | None = Field(default=None, gt=0, le=10000)


class UnitOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    code: str
    name: str
    unit_type: str
    underground: bool
    density_t_m3: float | None
    entry_count: int = 0
    design_ch_from_m: float | None = None
    design_ch_to_m: float | None = None
    design_area_m2: float | None = None


class PeriodCreate(BaseModel):
    """A month, ``label`` as ``YYYY-MM``; the band and the truck check are the period's profile."""

    label: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    band_lo_pct: float | None = Field(default=None, ge=0, le=1000)
    band_hi_pct: float | None = Field(default=None, ge=0, le=1000)
    truck_tolerance_pct: float | None = Field(default=None, ge=0, le=100)
    overbreak_tol_pct: float | None = Field(default=None, ge=0, le=100)
    profile_label: str = Field(default="", max_length=120)
    note: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _band(self) -> PeriodCreate:
        if (self.band_lo_pct is None) != (self.band_hi_pct is None):
            raise ValueError("Set both ends of the compliance band or neither")
        if self.band_lo_pct is not None and self.band_hi_pct is not None and self.band_lo_pct > self.band_hi_pct:
            raise ValueError("The lower end of the band is above the upper end")
        return self


class PeriodUpdate(BaseModel):
    band_lo_pct: float | None = Field(default=None, ge=0, le=1000)
    band_hi_pct: float | None = Field(default=None, ge=0, le=1000)
    truck_tolerance_pct: float | None = Field(default=None, ge=0, le=100)
    overbreak_tol_pct: float | None = Field(default=None, ge=0, le=100)
    profile_label: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=2000)


class EntryCreate(BaseModel):
    """One unit in the period: an existing unit, or a new one by name."""

    unit_id: uuid.UUID | None = None
    unit_name: str = Field(default="", max_length=255)
    unit_type: UnitType = "bench"
    plan_m3: float = Field(ge=0, le=1e10)
    plan_t: float | None = Field(default=None, ge=0, le=1e11)
    plan_advance_m: float | None = Field(default=None, ge=0, le=1e7)
    density_t_m3: float | None = Field(default=None, gt=0, le=30)

    @model_validator(mode="after")
    def _unit(self) -> EntryCreate:
        if self.unit_id is None and not self.unit_name.strip():
            raise ValueError("Pick a unit or give a name")
        return self


class EntryUpdate(BaseModel):
    plan_m3: float | None = Field(default=None, ge=0, le=1e10)
    plan_t: float | None = Field(default=None, ge=0, le=1e11)
    plan_advance_m: float | None = Field(default=None, ge=0, le=1e7)
    actual_advance_m: float | None = Field(default=None, ge=0, le=1e7)
    density_t_m3: float | None = Field(default=None, gt=0, le=30)
    note: str | None = Field(default=None, max_length=2000)


class PlanImport(BaseModel):
    text: str = Field(min_length=1, max_length=2_000_000)
    filename: str = Field(default="", max_length=255)


class PlanImportResult(BaseModel):
    imported: int
    problems: list[str]


class ComputeActual(BaseModel):
    """Start and end of the period: two surfaces already in the register, or two point files read on the spot."""

    start_surface_id: uuid.UUID | None = None
    end_surface_id: uuid.UUID | None = None
    start_text: str = Field(default="", max_length=6_000_000)
    start_filename: str = Field(default="", max_length=255)
    end_text: str = Field(default="", max_length=6_000_000)
    end_filename: str = Field(default="", max_length=255)
    cell_size_m: float | None = Field(default=None, gt=0, le=1000)

    @model_validator(mode="after")
    def _both(self) -> ComputeActual:
        if not (self.start_surface_id or self.start_text.strip()) or not (self.end_surface_id or self.end_text.strip()):
            raise ValueError("Give the start and the end surface")
        return self


class ConfirmActual(BaseModel):
    acknowledge: list[str] = Field(default_factory=list, max_length=20)


class TruckLoadsImport(BaseModel):
    text: str = Field(min_length=1, max_length=2_000_000)
    filename: str = Field(default="", max_length=255)


class AddToClaim(BaseModel):
    position_id: uuid.UUID
    notes: str = Field(default="", max_length=1000)


class ClaimResult(BaseModel):
    entry_id: uuid.UUID
    progress_entry_id: uuid.UUID
    position_id: uuid.UUID
    quantity_m3: float
    period_label: str
    percent_complete: float


class ActualOut(BaseModel):
    volume_id: uuid.UUID
    code: str
    status: str
    method: str
    cell_size_m: float | None
    coverage_pct: float
    crs_epsg: int | None
    confirmed_by_name: str = ""
    confirmed_at: datetime | None = None


class EntryOut(BaseModel):
    id: uuid.UUID
    period_id: uuid.UUID
    unit_id: uuid.UUID
    unit_code: str
    unit_name: str
    unit_type: str
    underground: bool
    plan_m3: float
    plan_t: float | None
    plan_advance_m: float | None
    actual_advance_m: float | None
    advance_pct: float | None
    density_t_m3: float | None
    actual_m3: float | None
    actual: ActualOut | None
    compliance_pct: float | None
    survey_t: float | None
    truck_loads: int
    truck_t: float | None
    truck_factor_pct: float | None
    truck_source: str
    claim_entry_id: uuid.UUID | None
    claimed_m3: float | None
    claimed_by_name: str
    claimed_at: datetime | None
    note: str
    findings: list[Finding]
    #: Truck-count tonnes as a percentage of survey tonnes (100 % = they agree).
    truck_ratio_pct: float | None = None
    material_split: MaterialSplitOut | None = None
    drive: DriveSummary | None = None


class Totals(BaseModel):
    plan_m3: float
    actual_m3: float | None
    compliance_pct: float | None
    survey_t: float | None
    truck_t: float | None
    truck_factor_pct: float | None
    units: int


class PeriodOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    label: str
    period_start: date
    period_end: date
    band_lo_pct: float | None
    band_hi_pct: float | None
    truck_tolerance_pct: float | None
    profile_label: str
    note: str
    entry_count: int = 0
    overbreak_tol_pct: float | None = None


class PeriodDetail(PeriodOut):
    entries: list[EntryOut]
    totals: Totals


class PeriodListResponse(BaseModel):
    items: list[PeriodOut]
    total: int
    offset: int = 0
    limit: int = 50


class UnitListResponse(BaseModel):
    items: list[UnitOut]
    total: int
    offset: int = 0
    limit: int = 50


# ── v2: material split, drive profiles, blast patterns ─────────────────────

Material = Literal["ore", "waste", "low_grade", "other"]
Ring2 = list[tuple[float, float]]


class MaterialIn(BaseModel):
    material: Material = "ore"
    name: str = Field(default="", max_length=255)
    density_t_m3: float | None = Field(default=None, gt=0, le=30)
    ring: Ring2 = Field(min_length=3, max_length=5000)


class MaterialImport(BaseModel):
    """GeoJSON polygons (``material``, ``name``, ``density_t_m3`` properties), or polylines of a drawing."""

    text: str = Field(default="", max_length=20_000_000)
    filename: str = Field(default="", max_length=255)
    #: A drawing already converted by the drawings module (DDC cad2data), and its layers per material.
    drawing_id: uuid.UUID | None = None
    layers: dict[str, Material] = Field(default_factory=dict, max_length=50)
    densities: dict[str, float] = Field(default_factory=dict, max_length=10)
    replace: bool = False


class MaterialOut(BaseModel):
    id: uuid.UUID
    unit_id: uuid.UUID
    material: str
    name: str
    density_t_m3: float | None
    ring: Ring2
    area_m2: float
    source: str
    source_filename: str


class MaterialImportResult(BaseModel):
    items: list[MaterialOut]
    problems: list[str]


class MaterialPartOut(BaseModel):
    material: str
    name: str
    volume_m3: float
    density_t_m3: float | None
    tonnes: float | None


class MaterialSplitOut(BaseModel):
    parts: list[MaterialPartOut]
    total_m3: float
    assigned_m3: float
    unassigned_m3: float
    coverage_pct: float | None
    tonnes: float | None


class FaceIn(BaseModel):
    chainage_m: float = Field(ge=0, le=1e7)
    picked_on: date | None = None
    period_id: uuid.UUID | None = None
    note: str = Field(default="", max_length=1000)


class FaceOut(BaseModel):
    id: uuid.UUID
    unit_id: uuid.UUID
    period_id: uuid.UUID | None
    chainage_m: float
    picked_on: date | None
    note: str


class ProfileIn(BaseModel):
    """A measured profile: its area, or the (offset, height) ring it was measured as."""

    chainage_m: float = Field(ge=0, le=1e7)
    actual_area_m2: float | None = Field(default=None, gt=0, le=10000)
    ring: Ring2 = Field(default_factory=list, max_length=5000)
    design_area_m2: float | None = Field(default=None, gt=0, le=10000)
    period_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _area(self) -> ProfileIn:
        if self.actual_area_m2 is None and len(self.ring) < 3:
            raise ValueError("Give the profile area or at least three points of its outline")
        return self


class ProfileImport(BaseModel):
    """CSV ``chainage,area`` (optional ``design_area``)."""

    text: str = Field(min_length=1, max_length=2_000_000)
    period_id: uuid.UUID | None = None


class ProfileOut(BaseModel):
    id: uuid.UUID
    unit_id: uuid.UUID
    period_id: uuid.UUID | None
    chainage_m: float
    actual_area_m2: float
    design_area_m2: float | None
    overbreak_pct: float | None
    inside_design: bool | None


class DriveSummary(BaseModel):
    faces: int
    advance_m: float | None
    profiles: int
    design_area_m2: float | None
    mean_actual_m2: float | None
    overbreak_pct: float | None
    excess_m3: float | None
    excess_t: float | None
    under_count: int = 0


class DriveDetail(BaseModel):
    unit: UnitOut
    faces: list[FaceOut]
    profiles: list[ProfileOut]
    summary: DriveSummary
    findings: list[Finding]


class HoleIn(BaseModel):
    hole_id: str = Field(min_length=1, max_length=64)
    e: float
    n: float
    z: float | None = None
    depth_m: float | None = Field(default=None, ge=0, le=1000)


class PatternCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    unit_id: uuid.UUID | None = None
    collar_tol_m: float | None = Field(default=None, gt=0, le=100)
    depth_tol_m: float | None = Field(default=None, gt=0, le=100)
    note: str = Field(default="", max_length=2000)
    #: Design collars as CSV ``hole,e,n,z,depth``.
    design_text: str = Field(default="", max_length=5_000_000)


class PatternUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    collar_tol_m: float | None = Field(default=None, gt=0, le=100)
    depth_tol_m: float | None = Field(default=None, gt=0, le=100)
    note: str | None = Field(default=None, max_length=2000)


class DrilledImport(BaseModel):
    """As-drilled CSV ``hole,e,n,z,depth``; holes are matched by id."""

    text: str = Field(min_length=1, max_length=5_000_000)
    drilled_on: date | None = None


class HoleOut(BaseModel):
    id: uuid.UUID
    hole_id: str
    design_e: float
    design_n: float
    design_z: float | None
    design_depth_m: float | None
    drilled_e: float | None
    drilled_n: float | None
    drilled_z: float | None
    drilled_depth_m: float | None
    collar_offset_m: float | None
    depth_diff_m: float | None
    collar_ok: bool | None
    depth_ok: bool | None


class PatternOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    unit_id: uuid.UUID | None
    code: str
    name: str
    collar_tol_m: float | None
    depth_tol_m: float | None
    note: str
    holes: int
    drilled: int
    failed: int


class PatternDetail(PatternOut):
    items: list[HoleOut]
    findings: list[Finding]
    problems: list[str] = Field(default_factory=list)


class PatternListResponse(BaseModel):
    items: list[PatternOut]
    total: int


EntryOut.model_rebuild()
PeriodDetail.model_rebuild()
