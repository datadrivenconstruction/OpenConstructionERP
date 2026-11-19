# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Survey register request and response schemas.

Coordinates travel as JSON numbers with up to four decimals (0.1 mm); the
screen shows three.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PointKind = Literal["control", "benchmark", "topo", "stake", "asbuilt"]
FileFormat = Literal["csv", "txt", "geojson", "gsi", "jobxml", "landxml"]
LinearUnit = Literal["m", "ft", "ftUS"]
FootDefinition = Literal["", "ft", "ftUS"]
DuplicatePolicy = Literal["keep_first", "keep_last", "skip"]
ColumnField = Literal["", "point_id", "e", "n", "z", "code", "description", "kind", "sigma"]


class CrsInfoOut(BaseModel):
    epsg: int
    name: str
    kind: str
    unit: str
    is_geographic: bool
    area: str = ""


class CrsSuggestion(CrsInfoOut):
    """A system offered in the picker, with why it is offered."""

    reason: Literal["project_location", "pack", "detected", "geographic"]
    confidence: float | None = None
    pack_country: str = ""
    #: National systems only: primary | zone | legacy, the country's height system and geoid model.
    role: str = ""
    note: str = ""
    vertical_epsg: int | None = None
    vertical_name: str = ""
    geoid_grid: str = ""


class ProjectCrsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: uuid.UUID
    horizontal_epsg: int | None = None
    horizontal_name: str = ""
    vertical_mode: str = "same_as_source"
    vertical_epsg: int | None = None
    is_local_grid: bool = False
    local_origin_e: float | None = None
    local_origin_n: float | None = None
    local_rotation_deg: float | None = None
    local_scale_factor: float | None = None
    source: str = "user"
    detected_confidence: float | None = None
    confirmed_by: uuid.UUID | None = None
    confirmed_at: datetime | None = None


class ProjectCrsState(BaseModel):
    """The project CRS (``None`` until set), what the picker suggests, and how many points depend on it."""

    crs: ProjectCrsOut | None = None
    suggestions: list[CrsSuggestion] = Field(default_factory=list)
    point_count: int = 0


class ProjectCrsSet(BaseModel):
    horizontal_epsg: int | None = Field(default=None, ge=1000, le=999999)
    vertical_mode: Literal["same_as_source", "epsg"] = "same_as_source"
    vertical_epsg: int | None = Field(default=None, ge=1000, le=999999)
    is_local_grid: bool = False
    local_origin_e: float | None = None
    local_origin_n: float | None = None
    local_rotation_deg: float | None = Field(default=None, ge=-360, le=360)
    local_scale_factor: float | None = Field(default=None, gt=0.9, lt=1.1)
    source: Literal["user", "detected"] = "user"
    detected_confidence: float | None = Field(default=None, ge=0, le=1)
    #: Changing the CRS once points exist needs the new EPSG code typed again.
    confirm_text: str = Field(default="", max_length=20)


class PointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    point_set_id: uuid.UUID
    point_id: str
    e: float
    n: float
    z: float | None = None
    code: str = ""
    kind: str = "topo"
    sigma: float | None = None
    description: str = ""
    #: How a computed point was made; "" for a measured point.
    method: str = ""


class PointListResponse(BaseModel):
    items: list[PointOut]
    total: int


class PointSetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    source_filename: str = ""
    file_format: str = "csv"
    column_preset: str = ""
    instrument: str = ""
    surveyed_by: str = ""
    survey_date: date | None = None
    source_epsg: int | None = None
    stored_epsg: int | None = None
    transformed: bool = False
    duplicate_policy: str = "keep_first"
    rows_read: int = 0
    point_count: int = 0
    note: str = ""
    created_at: datetime | None = None


class ImportRequest(BaseModel):
    """A point file as text plus how to read it. Preview and import take the same body."""

    text: str = Field(max_length=6_000_000)
    file_format: FileFormat = "csv"
    filename: str = Field(default="", max_length=255)
    delimiter: str = Field(default="", max_length=2)
    columns: list[ColumnField] = Field(default_factory=list, max_length=30)
    column_preset: str = Field(default="", max_length=20)
    has_header: bool = False
    default_kind: PointKind = "topo"
    #: EPSG the file is written in; empty = the project CRS (GeoJSON: its own, else WGS 84).
    source_epsg: int | None = Field(default=None, ge=1000, le=999999)
    name: str = Field(default="", max_length=255)
    instrument: str = Field(default="", max_length=255)
    surveyed_by: str = Field(default="", max_length=255)
    survey_date: date | None = None
    duplicate_policy: DuplicatePolicy = "keep_first"
    note: str = Field(default="", max_length=2000)
    #: A file in feet for a metre project needs the foot named (SRV-031); never guessed.
    foot_definition: FootDefinition = ""
    #: Height system the file's Z is in; with the project's vertical EPSG, heights go through the geoid.
    source_vertical_epsg: int | None = Field(default=None, ge=1000, le=999999)
    #: ``local``: the file is in the site grid and goes through the project's local grid tie first.
    coords: Literal["grid", "local"] = "grid"


class ImportProblem(BaseModel):
    rule_id: str
    line: int
    point_id: str = ""
    detail: str = ""
    message: str = ""


class PreviewRow(BaseModel):
    line: int
    point_id: str
    e: float
    n: float
    z: float | None = None
    code: str = ""
    kind: str = "topo"


class GuessOut(BaseModel):
    value: str
    confidence: float


class ImportPreview(BaseModel):
    rows_read: int
    problem_count: int
    problems: list[ImportProblem]
    rows: list[PreviewRow]
    delimiter: GuessOut | None = None
    preset: GuessOut | None = None
    header: list[str] = Field(default_factory=list)
    sample: list[list[str]] = Field(default_factory=list)
    points_to_import: int
    source_epsg: int | None = None
    target_epsg: int | None = None
    will_transform: bool = False
    detected_crs: CrsSuggestion | None = None
    existing_conflicts: int = 0
    file_unit: str = "m"
    project_unit: str = "m"
    unit_converted: bool = False
    heights_converted: bool = False
    missing_grids: list[str] = Field(default_factory=list)
    local_grid_applied: bool = False


class ImportResult(BaseModel):
    point_set: PointSetOut
    imported: int
    problems: list[ImportProblem]


class TransformRequest(BaseModel):
    source_epsg: int = Field(ge=1000, le=999999)
    target_epsg: int = Field(ge=1000, le=999999)
    points: list[tuple[float, float] | tuple[float, float, float | None]] = Field(max_length=10_000)


class TransformResponse(BaseModel):
    source: CrsInfoOut
    target: CrsInfoOut
    points: list[tuple[float, float, float | None]]


class Finding(BaseModel):
    rule_id: str
    severity: str
    message: str
    suggestion: str | None = None
    element_ref: str | None = None


class ValidationReportOut(BaseModel):
    status: str
    error_count: int = 0
    warning_count: int = 0
    info_count: int = 0
    findings: list[Finding] = Field(default_factory=list)


class RegisterSummary(BaseModel):
    points: int = 0
    control: int = 0
    point_sets: int = 0
    findings: int = 0
    last_import: datetime | None = None


class TraverseCreate(BaseModel):
    """A closed traverse from its legs file, or a level run from its misclosure."""

    name: str = Field(min_length=1, max_length=255)
    kind: Literal["traverse", "level"] = "traverse"
    text: str = Field(default="", max_length=500_000)
    distance_km: float | None = Field(default=None, ge=0, le=10_000)
    misclosure_mm: float | None = Field(default=None, ge=-100_000, le=100_000)
    k_mm: float | None = Field(default=None, gt=0, le=1_000)
    note: str = Field(default="", max_length=2000)


class TraverseLegOut(BaseModel):
    leg: str
    start: str = Field(default="", serialization_alias="from")
    end: str = Field(default="", serialization_alias="to")
    length_m: float
    d_e: float
    d_n: float
    c_e: float
    c_n: float


class TraverseOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    kind: str
    method: str
    legs: list[TraverseLegOut] = Field(default_factory=list)
    length_m: float
    f_e: float | None = None
    f_n: float | None = None
    misclosure_m: float | None = None
    ratio: int | None = None
    profile_ratio: int | None = None
    distance_km: float | None = None
    misclosure_mm: float | None = None
    k_mm: float | None = None
    allowed_mm: float | None = None
    verdict: str
    profile_label: str = ""
    note: str = ""
    created_at: datetime | None = None
    angle_count: int | None = None
    ang_misclosure_sec: float | None = None
    ang_k_sec: float | None = None
    ang_allowed_sec: float | None = None
    #: Field observations and their reduction (field traverse stations or level book rows).
    observations: dict | None = None


class SurveyProfileIn(BaseModel):
    label: str = Field(default="", max_length=255)
    traverse_min_ratio: int | None = Field(default=None, ge=100, le=10_000_000)
    level_k_mm: float | None = Field(default=None, gt=0, le=1_000)
    coverage_min_pct: float | None = Field(default=None, ge=0, le=100)
    angular_k_sec: float | None = Field(default=None, gt=0, le=3600)


class SurveyProfileOut(SurveyProfileIn):
    """The profile in force for a project; ``scope`` says where it was found."""

    scope: Literal["project", "workspace", "none"] = "none"
    source: str = "user"


class PointSetListResponse(BaseModel):
    items: list[PointSetOut]
    total: int
    offset: int = 0
    limit: int = 50


class TraverseListResponse(BaseModel):
    items: list[TraverseOut]
    total: int
    offset: int = 0
    limit: int = 50


class CrsInfoListResponse(BaseModel):
    items: list[CrsInfoOut]
    total: int
    offset: int = 0
    limit: int = 50


# ── Geodesy: linear unit, local grid, grid/ground ─────────────────────────────────────────────────────────────────


class LocalGridPointIn(BaseModel):
    """A point known in the site grid (x, y) and the national grid (e, n)."""

    point_id: str = Field(min_length=1, max_length=64)
    x: float
    y: float
    e: float
    n: float
    use: bool = True


class LocalGridResidualOut(BaseModel):
    point_id: str
    de_mm: float
    dn_mm: float
    r_mm: float
    used: bool


class LocalGridSolveRequest(BaseModel):
    points: list[LocalGridPointIn] = Field(max_length=200)


class LocalGridSolution(BaseModel):
    """Scale, rotation and shift of the site grid in the national grid, with each point's residual."""

    scale: float
    scale_ppm: float
    rotation_deg: float
    te: float
    tn: float
    rms_mm: float
    fitted: int
    residuals: list[LocalGridResidualOut]


class GeodesyIn(BaseModel):
    """Per-project geodesy settings; tolerances are config with no core default."""

    linear_unit: Literal["", "m", "ft", "ftUS"] = ""
    local_grid_epsg: int | None = Field(default=None, ge=1000, le=999999)
    local_points: list[LocalGridPointIn] = Field(default_factory=list, max_length=200)
    apply_local_grid: bool = False
    residual_tol_mm: float | None = Field(default=None, gt=0, le=100000)
    scale_tol_ppm: float | None = Field(default=None, gt=0, le=1_000_000)
    csf_height_m: float | None = Field(default=None, ge=-500, le=9000)
    reference_distance_m: float | None = Field(default=None, gt=0, le=100000)


class ScaleFactorOut(BaseModel):
    """Grid and ground at the project: CSF = k * R / (R + h)."""

    epsg: int
    e: float
    n: float
    height_m: float
    k: float
    elevation_factor: float
    csf: float
    distance_m: float
    grid_m: float
    ground_m: float
    diff_mm: float
    height_source: Literal["setting", "points", "none"]


class GeodesyOut(GeodesyIn):
    project_id: uuid.UUID
    effective_unit: LinearUnit = "m"
    solution: LocalGridSolution | None = None
    scale: ScaleFactorOut | None = None
