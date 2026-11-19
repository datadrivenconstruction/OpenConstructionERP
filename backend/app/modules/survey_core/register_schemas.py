# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Point register schemas: point detail, bulk actions, export and control checks."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.modules.survey_core.schemas import PointKind, PointOut

BulkAction = Literal["set_code", "set_kind", "move_to_set", "delete"]
ExportFormat = Literal["csv", "dxf", "landxml"]
Verdict = Literal["pass", "fail", "no_tolerance"]


class UsedBy(BaseModel):
    """A result built from the point's set; a confirmed one locks the point."""

    kind: str
    code: str
    name: str = ""
    locked: bool = False


class PointDetail(PointOut):
    set_name: str = ""
    source_filename: str = ""
    source_line: int | None = None
    survey_date: date | None = None
    stored_epsg: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    used_by: list[UsedBy] = Field(default_factory=list)
    locked: bool = False


class PointUpdate(BaseModel):
    point_id: str | None = Field(default=None, min_length=1, max_length=64)
    e: float | None = Field(default=None, ge=-1e10, le=1e10)
    n: float | None = Field(default=None, ge=-1e10, le=1e10)
    z: float | None = Field(default=None, ge=-1e6, le=1e6)
    clear_z: bool = False
    code: str | None = Field(default=None, max_length=64)
    kind: PointKind | None = None
    description: str | None = Field(default=None, max_length=255)
    sigma: float | None = Field(default=None, ge=0, le=1e4)


class BulkRequest(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=5000)
    action: BulkAction
    value: str = Field(default="", max_length=64)
    target_set_id: uuid.UUID | None = None


class BulkResult(BaseModel):
    action: BulkAction
    affected: int
    skipped_locked: int = 0


class ExportRequest(BaseModel):
    """Empty ``ids`` exports the whole register."""

    ids: list[uuid.UUID] = Field(default_factory=list, max_length=200_000)
    format: ExportFormat = "csv"
    preset: Literal["PNEZD", "PENZD"] = "PNEZD"
    delimiter: Literal[",", ";", "\t", " "] = ","
    header: bool = False


class ControlCheckIn(BaseModel):
    """A check shot: either a measured register point, or the coordinates typed in."""

    control_point_id: uuid.UUID
    measured_point_id: uuid.UUID | None = None
    e: float | None = Field(default=None, ge=-1e10, le=1e10)
    n: float | None = Field(default=None, ge=-1e10, le=1e10)
    z: float | None = Field(default=None, ge=-1e6, le=1e6)
    note: str = Field(default="", max_length=255)


class ControlCheckOut(BaseModel):
    id: uuid.UUID
    control_point_id: uuid.UUID
    measured_point_id: uuid.UUID | None = None
    e: float
    n: float
    z: float | None = None
    de_mm: float
    dn_mm: float
    dz_mm: float | None = None
    d2d_mm: float
    verdict: Verdict
    note: str = ""
    created_at: datetime | None = None


class ControlRow(BaseModel):
    point: PointOut
    checks: list[ControlCheckOut] = Field(default_factory=list)
    latest: ControlCheckOut | None = None


class ControlListResponse(BaseModel):
    items: list[ControlRow]
    total: int
    tolerance_mm: float | None = None
    profile_label: str = ""
    failing: int = 0
