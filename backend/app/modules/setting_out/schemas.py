# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Setting-out request and response schemas.

Coordinates travel as JSON numbers in metres (four decimals stored, three shown);
deltas and tolerances in millimetres with one decimal.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ItemType = Literal["column", "wall", "pile", "anchor_bolt", "kerb", "centreline", "grid_line", "other"]
RefType = Literal["", "boq", "bim", "cad"]
VerdictOut = Literal["pass", "fail", "no_tolerance", "open"]


class ToleranceValue(BaseModel):
    h_mm: float = Field(gt=0, le=10000)
    v_mm: float | None = Field(default=None, gt=0, le=10000)


class ToleranceProfileOut(BaseModel):
    key: str
    name: str
    source: Literal["demo", "pack", "project"]
    country: str = ""
    reference: str = ""
    items: dict[str, ToleranceValue]


class ToleranceProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    reference: str = Field(default="", max_length=255)
    items: dict[str, ToleranceValue] = Field(min_length=1)


class RequestCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=255)
    item_type: ItemType = "other"
    tolerance_key: str = Field(default="", max_length=80)
    #: Advanced: override the profile's value for this request only.
    tol_h_mm: float | None = Field(default=None, gt=0, le=10000)
    tol_v_mm: float | None = Field(default=None, gt=0, le=10000)
    element_ref_type: RefType = ""
    element_ref_id: str = Field(default="", max_length=255)
    element_ref_label: str = Field(default="", max_length=255)
    instrument: str = Field(default="", max_length=255)
    control_ref: str = Field(default="", max_length=255)
    note: str = Field(default="", max_length=5000)


class RequestUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    item_type: ItemType | None = None
    tolerance_key: str | None = Field(default=None, max_length=80)
    tol_h_mm: float | None = Field(default=None, gt=0, le=10000)
    tol_v_mm: float | None = Field(default=None, gt=0, le=10000)
    element_ref_type: RefType | None = None
    element_ref_id: str | None = Field(default=None, max_length=255)
    element_ref_label: str | None = Field(default=None, max_length=255)
    instrument: str | None = Field(default=None, max_length=255)
    control_ref: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=5000)


class RecordOut(BaseModel):
    id: uuid.UUID
    point_id: uuid.UUID
    measured_e: float
    measured_n: float
    measured_z: float | None
    de_mm: float
    dn_mm: float
    d_mm: float
    dz_mm: float | None
    tol_h_mm: float | None
    tol_v_mm: float | None
    verdict: Literal["pass", "fail", "no_tolerance"]
    instrument: str
    control_ref: str
    measured_by: str
    measured_at: datetime
    note: str
    ncr_id: str | None


class StakeOut(BaseModel):
    id: uuid.UUID
    point_id: str
    design_e: float
    design_n: float
    design_z: float | None
    chainage: float | None
    offset_m: float | None
    code: str
    verdict: VerdictOut
    latest: RecordOut | None = None
    record_count: int = 0


class RequestOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    code: str
    name: str
    item_type: str
    tolerance_key: str
    tolerance_label: str
    tolerance_source: str
    tol_h_mm: float | None
    tol_v_mm: float | None
    element_ref_type: str
    element_ref_id: str
    element_ref_label: str
    alignment: dict | None
    instrument: str
    control_ref: str
    source_filename: str
    note: str
    created_at: datetime
    point_count: int = 0
    open_count: int = 0
    pass_count: int = 0
    fail_count: int = 0


class RequestDetail(RequestOut):
    stakes: list[StakeOut] = []


class DesignImport(BaseModel):
    """A design file: CSV/TXT of stakes, or LandXML with CgPoints and/or an alignment."""

    text: str = Field(min_length=1, max_length=5_000_000)
    filename: str = Field(default="", max_length=255)
    file_format: Literal["csv", "landxml"] = "csv"
    alignment_name: str = Field(default="", max_length=255)
    #: ``replace`` drops the request's stakes without records first; ``add`` keeps them.
    mode: Literal["add", "replace"] = "add"


class ImportProblem(BaseModel):
    line: int
    point_id: str = ""
    message: str


class DesignPreview(BaseModel):
    rows_read: int
    points: list[dict]
    alignment: dict | None
    problems: list[ImportProblem]
    problem_count: int


class StakeCreate(BaseModel):
    """One stake typed in: either E/N, or chainage/offset on the request's alignment."""

    model_config = ConfigDict(str_strip_whitespace=True)

    point_id: str = Field(min_length=1, max_length=64)
    e: float | None = None
    n: float | None = None
    z: float | None = None
    chainage: float | None = None
    offset_m: float | None = None
    code: str = Field(default="", max_length=64)


class RecordCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    measured_e: float
    measured_n: float
    measured_z: float | None = None
    instrument: str | None = Field(default=None, max_length=255)
    control_ref: str | None = Field(default=None, max_length=255)
    note: str = Field(default="", max_length=1000)


class MeasuredImport(BaseModel):
    text: str = Field(min_length=1, max_length=5_000_000)
    filename: str = Field(default="", max_length=255)


class MeasuredImportResult(BaseModel):
    recorded: int
    passed: int
    failed: int
    problems: list[ImportProblem]


class NcrDraftOut(BaseModel):
    ncr_id: str
    ncr_number: str
    record_id: uuid.UUID


class Finding(BaseModel):
    rule_id: str
    severity: str
    message: str
    suggestion: str | None = None
    element_ref: str | None = None


class ValidationReportOut(BaseModel):
    status: str
    error_count: int
    warning_count: int
    info_count: int
    findings: list[Finding]


class SettingOutSummary(BaseModel):
    requests: int
    open: int
    passed: int
    failed: int
    ncr_drafts: int


class ChainageQuery(BaseModel):
    """Calculator: E/N from chainage/offset, or chainage/offset from E/N, on a request's alignment."""

    chainage: float | None = None
    offset_m: float | None = None
    e: float | None = None
    n: float | None = None


class ChainageAnswer(BaseModel):
    e: float
    n: float
    chainage: float
    offset_m: float


class RecordListResponse(BaseModel):
    items: list[RecordOut]
    total: int
    offset: int = 0
    limit: int = 50


class ToleranceProfileListResponse(BaseModel):
    items: list[ToleranceProfileOut]
    total: int
    offset: int = 0
    limit: int = 50


class RequestListResponse(BaseModel):
    items: list[RequestOut]
    total: int
    offset: int = 0
    limit: int = 50
