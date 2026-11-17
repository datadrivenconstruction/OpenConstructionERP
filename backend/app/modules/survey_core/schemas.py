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
FileFormat = Literal["csv", "txt", "geojson"]
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


class ImportProblem(BaseModel):
    rule_id: str
    line: int
    point_id: str = ""
    detail: str = ""


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
