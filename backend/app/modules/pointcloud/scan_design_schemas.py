# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Request and response shapes of the scan-to-surface, scan-vs-design and cloud-to-quantity routes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.modules.surfaces_volumes.schemas import Finding

CellStat = Literal["min", "mean", "max"]


class ScanSurfaceRequest(BaseModel):
    """Grid a stored scan into a survey surface (the thinning is the cell size)."""

    name: str = Field(default="", max_length=255)
    cell_size_m: float = Field(default=0.5, gt=0, le=100)
    stat: CellStat = "min"
    ground_only: bool = True


class DeviationRequest(BaseModel):
    """Compare a stored scan against a design surface with a tolerance profile from setting-out."""

    surface_id: uuid.UUID
    tolerance_key: str = Field(default="demo", min_length=1, max_length=120)
    item_type: str = Field(default="other", max_length=40)
    ground_only: bool = True
    threshold_pct: float = Field(default=5.0, ge=0, le=100)


class ToleranceUsed(BaseModel):
    key: str
    label: str
    source: str
    item_type: str
    v_mm: float
    reference: str = ""


class DeviationBands(BaseModel):
    far_low: int = 0
    low: int = 0
    within: int = 0
    high: int = 0
    far_high: int = 0
    none: int = 0


class DeviationStatsOut(BaseModel):
    """Lengths in mm, shares in percent; ``None`` when no point lies over the design."""

    points_read: int
    points_compared: int
    points_outside: int
    tolerance_mm: float
    mean_mm: float | None = None
    rms_mm: float | None = None
    std_mm: float | None = None
    p95_mm: float | None = None
    min_mm: float | None = None
    max_mm: float | None = None
    within_pct: float | None = None
    high_pct: float | None = None
    low_pct: float | None = None
    out_count: int = 0
    coverage_pct: float = 0.0
    bands: DeviationBands = Field(default_factory=DeviationBands)


class DeviationReportOut(BaseModel):
    """One stored comparison of a scan against a design surface."""

    id: uuid.UUID
    scan_id: uuid.UUID
    project_id: uuid.UUID
    surface_id: uuid.UUID
    surface_code: str
    surface_name: str
    tolerance: ToleranceUsed
    threshold_pct: float
    ground_only: bool
    used_all_classes: bool = False
    stats: DeviationStatsOut
    severity: str
    findings: list[Finding] = Field(default_factory=list)
    heat: dict[str, Any] | None = None
    created_at: datetime | None = None


class DeviationReportList(BaseModel):
    items: list[DeviationReportOut]
    total: int


class CutFillRequest(BaseModel):
    """Cut and fill between the scan (gridded) and a design surface."""

    surface_id: uuid.UUID
    cell_size_m: float = Field(default=0.5, gt=0, le=100)
    stat: CellStat = "min"
    ground_only: bool = True
    method: Literal["grid", "tin"] = "grid"
    name: str = Field(default="", max_length=255)


class CutFillPreview(BaseModel):
    """What the draft volume would hold; nothing is stored yet."""

    surface_id: uuid.UUID
    surface_name: str
    method: str
    cell_size_m: float
    cut_m3: float
    fill_m3: float
    net_m3: float
    coverage_pct: float
    points_read: int
    cells: int
    used_all_classes: bool


class CutFillCreated(BaseModel):
    """The scan surface and the draft volume, ready for confirm and send-to-BOQ."""

    scan_surface_id: uuid.UUID
    scan_surface_code: str
    volume_id: uuid.UUID
    volume_code: str
    status: str
    cut_m3: float
    fill_m3: float
    net_m3: float
    coverage_pct: float
    findings: list[Finding] = Field(default_factory=list)


__all__ = [
    "CutFillCreated",
    "CutFillPreview",
    "CutFillRequest",
    "DeviationBands",
    "DeviationReportList",
    "DeviationReportOut",
    "DeviationRequest",
    "DeviationStatsOut",
    "ScanSurfaceRequest",
    "ToleranceUsed",
]
