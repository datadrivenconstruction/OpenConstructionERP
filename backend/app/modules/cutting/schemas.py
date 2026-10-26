# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cutting optimisation request and response schemas.

Dimensions are millimetres. Money and quantities serialise as strings (the
project's Decimal-as-string contract), never floats.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

JobKind = Literal["linear", "sheet"]
JobStatus = Literal["draft", "optimised", "applied"]

_MAX_MM = Decimal("1000000")


class _DecimalOut(BaseModel):
    """Base for responses; Pydantic writes every Decimal field as a JSON string."""

    model_config = ConfigDict(from_attributes=True)


# ── Pieces and stock ──────────────────────────────────────────────────────


class PieceIn(BaseModel):
    """One demanded piece."""

    model_config = ConfigDict(str_strip_whitespace=True)

    ref: str = Field(..., min_length=1, max_length=64)
    label: str = Field(default="", max_length=255)
    length_mm: Decimal = Field(..., gt=0, le=_MAX_MM)
    width_mm: Decimal | None = Field(default=None, gt=0, le=_MAX_MM)
    quantity: int = Field(default=1, ge=1, le=100000)
    rotatable: bool = True
    source_ref: str | None = Field(default=None, max_length=255)


class PieceOut(_DecimalOut):
    """A stored piece."""

    id: uuid.UUID
    ref: str
    label: str
    length_mm: Decimal
    width_mm: Decimal | None
    quantity: int
    rotatable: bool
    source_ref: str | None


class StockIn(BaseModel):
    """One stock length or sheet on offer."""

    model_config = ConfigDict(str_strip_whitespace=True)

    ref: str = Field(..., min_length=1, max_length=64)
    label: str = Field(default="", max_length=255)
    length_mm: Decimal = Field(..., gt=0, le=_MAX_MM)
    width_mm: Decimal | None = Field(default=None, gt=0, le=_MAX_MM)
    unit_cost: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("100000000"))
    available: int | None = Field(default=None, ge=0, le=1000000)
    is_offcut: bool = False
    inventory_item_id: uuid.UUID | None = None


class StockOut(_DecimalOut):
    """A stored stock entry."""

    id: uuid.UUID
    ref: str
    label: str
    length_mm: Decimal
    width_mm: Decimal | None
    unit_cost: Decimal
    available: int | None
    is_offcut: bool
    inventory_item_id: uuid.UUID | None


# ── Jobs ──────────────────────────────────────────────────────────────────


class JobBase(BaseModel):
    """Fields shared by create and update."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255)
    kind: JobKind = "linear"
    material: str = Field(default="", max_length=120)
    kerf_mm: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("100"))
    trim_mm: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("10000"))
    min_offcut_mm: Decimal = Field(default=Decimal("0"), ge=0, le=_MAX_MM)
    yield_threshold_pct: Decimal = Field(default=Decimal("85"), ge=0, le=100)
    unit_mass_kg: Decimal | None = Field(default=None, gt=0, le=Decimal("100000"))
    currency: str = Field(default="", max_length=10)
    boq_position_id: uuid.UUID | None = None
    procurement_req_item_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=5000)


class JobCreate(JobBase):
    """Create a cutting job, optionally with its pieces and stock."""

    project_id: uuid.UUID
    pieces: list[PieceIn] = Field(default_factory=list, max_length=5000)
    stocks: list[StockIn] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def _sheet_needs_widths(self) -> JobCreate:
        _check_widths(self.kind, self.pieces, self.stocks)
        _check_unique_refs(self.pieces)
        _check_unique_refs(self.stocks)
        return self


class JobUpdate(BaseModel):
    """Patch a cutting job; only fields sent are touched."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    material: str | None = Field(default=None, max_length=120)
    kerf_mm: Decimal | None = Field(default=None, ge=0, le=Decimal("100"))
    trim_mm: Decimal | None = Field(default=None, ge=0, le=Decimal("10000"))
    min_offcut_mm: Decimal | None = Field(default=None, ge=0, le=_MAX_MM)
    yield_threshold_pct: Decimal | None = Field(default=None, ge=0, le=100)
    unit_mass_kg: Decimal | None = Field(default=None, gt=0, le=Decimal("100000"))
    currency: str | None = Field(default=None, max_length=10)
    boq_position_id: uuid.UUID | None = None
    procurement_req_item_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=5000)


class PiecesReplace(BaseModel):
    """Replace a job's pieces wholesale (the editor saves the whole grid)."""

    pieces: list[PieceIn] = Field(default_factory=list, max_length=5000)

    @model_validator(mode="after")
    def _unique(self) -> PiecesReplace:
        _check_unique_refs(self.pieces)
        return self


class StocksReplace(BaseModel):
    """Replace a job's stock wholesale."""

    stocks: list[StockIn] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def _unique(self) -> StocksReplace:
        _check_unique_refs(self.stocks)
        return self


class JobOut(_DecimalOut):
    """A cutting job with its pieces and stock."""

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    kind: str
    material: str
    kerf_mm: Decimal
    trim_mm: Decimal
    min_offcut_mm: Decimal
    yield_threshold_pct: Decimal
    unit_mass_kg: Decimal | None
    currency: str
    source_type: str
    source_ref: str | None
    boq_position_id: uuid.UUID | None
    procurement_req_item_id: uuid.UUID | None
    status: str
    notes: str | None
    created_by: str | None
    created_at: datetime
    updated_at: datetime
    pieces: list[PieceOut] = Field(default_factory=list)
    stocks: list[StockOut] = Field(default_factory=list)


class JobSummary(_DecimalOut):
    """A job row in the list, with its latest plan figures."""

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    kind: str
    material: str
    status: str
    source_type: str
    piece_count: int
    stock_count: int
    latest_plan_id: uuid.UUID | None = None
    latest_yield_pct: Decimal | None = None
    latest_waste_pct: Decimal | None = None
    latest_cost: Decimal | None = None
    updated_at: datetime


class JobList(BaseModel):
    """A page of job rows."""

    items: list[JobSummary]
    total: int
    offset: int
    limit: int


# ── Imports ───────────────────────────────────────────────────────────────


class RebarImportRequest(BaseModel):
    """Pull pieces from a stored bending schedule, one bar diameter per job."""

    import_id: uuid.UUID
    diameter_mm: Decimal = Field(..., gt=0, le=Decimal("100"))
    replace: bool = True


class TakeoffImportRequest(BaseModel):
    """Pull pieces from linear takeoff measurements of the job's project."""

    group_name: str | None = Field(default=None, max_length=100)
    document_id: str | None = Field(default=None, max_length=255)
    replace: bool = True


class BoqImportRequest(BaseModel):
    """Split a BOQ line's quantity into pieces of a known size."""

    position_id: uuid.UUID
    piece_length_mm: Decimal = Field(..., gt=0, le=_MAX_MM)
    piece_width_mm: Decimal | None = Field(default=None, gt=0, le=_MAX_MM)
    replace: bool = True


class ImportResult(BaseModel):
    """Outcome of a cut-list import."""

    imported: int
    skipped: int = 0
    messages: list[str] = Field(default_factory=list)
    job: JobOut


class InventoryOffcut(_DecimalOut):
    """An offcut held in site inventory that a job may reuse."""

    inventory_item_id: uuid.UUID
    name: str
    material: str
    kind: str
    length_mm: Decimal
    width_mm: Decimal | None
    on_hand: int


class InventoryStockRequest(BaseModel):
    """Add inventory offcuts to a job's stock."""

    inventory_item_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)


# ── Plans ─────────────────────────────────────────────────────────────────


class PlanOut(_DecimalOut):
    """One optimiser run with its layout and validation."""

    id: uuid.UUID
    job_id: uuid.UUID
    project_id: uuid.UUID
    kind: str
    algorithm: str
    stock_count: int
    pieces_placed: int
    pieces_unplaced: int
    stock_total: Decimal
    pieces_total: Decimal
    offcut_total: Decimal
    scrap_total: Decimal
    yield_pct: Decimal
    waste_pct: Decimal
    cost: Decimal
    currency: str
    exact: bool
    proven_optimal: bool
    elapsed_ms: int
    layout: dict[str, Any]
    stock_usage: list[dict[str, Any]]
    offcuts: list[dict[str, Any]]
    unplaced: list[dict[str, Any]]
    validation: dict[str, Any]
    settings: dict[str, Any]
    inventory_synced_at: datetime | None
    applied_at: datetime | None
    created_by: str | None
    created_at: datetime


class PlanSummary(_DecimalOut):
    """A plan row in a job's history."""

    id: uuid.UUID
    algorithm: str
    stock_count: int
    pieces_unplaced: int
    yield_pct: Decimal
    waste_pct: Decimal
    cost: Decimal
    currency: str
    proven_optimal: bool
    applied_at: datetime | None
    inventory_synced_at: datetime | None
    created_at: datetime


class ValidationOut(BaseModel):
    """A validation report for a job (and its latest plan when given)."""

    status: str
    score: float | None
    errors: int
    warnings: int
    infos: int
    results: list[dict[str, Any]]


# ── Proposal / apply ──────────────────────────────────────────────────────


class LineProposal(_DecimalOut):
    """A proposed quantity for one BOQ line or requisition item."""

    target: Literal["boq_position", "requisition_item"]
    target_id: uuid.UUID
    label: str
    unit: str
    current_quantity: Decimal
    proposed_quantity: Decimal
    basis: str
    appliable: bool
    reason: str | None = None


class PlanProposal(_DecimalOut):
    """What applying a plan would write, for the user to confirm."""

    plan_id: uuid.UUID
    waste_factor: Decimal
    waste_pct: Decimal
    yield_pct: Decimal
    confidence: float
    lines: list[LineProposal]


class ApplyRequest(BaseModel):
    """Confirmed application of a plan's proposal."""

    apply_boq: bool = True
    apply_procurement: bool = True


class ApplyLineResult(_DecimalOut):
    """Outcome per target line."""

    target: str
    target_id: uuid.UUID
    applied: bool
    reason: str | None = None
    old_quantity: Decimal | None = None
    new_quantity: Decimal | None = None


class ApplyResponse(BaseModel):
    """Result of applying a plan."""

    plan_id: uuid.UUID
    results: list[ApplyLineResult]


class ReturnOffcutsRequest(BaseModel):
    """Return a plan's reusable offcuts to site inventory."""

    location_id: uuid.UUID | None = None


class ReturnOffcutsResponse(BaseModel):
    """Inventory movements written for a plan."""

    plan_id: uuid.UUID
    returned: int
    consumed: int
    item_ids: list[uuid.UUID]


def _check_widths(kind: str, pieces: list[PieceIn], stocks: list[StockIn]) -> None:
    """A sheet job needs a width on every piece and every stock entry."""
    if kind != "sheet":
        return
    if any(p.width_mm is None for p in pieces) or any(s.width_mm is None for s in stocks):
        raise ValueError("Sheet jobs need width_mm on every piece and stock entry")


def _check_unique_refs(rows: list[PieceIn] | list[StockIn]) -> None:
    """Refs identify a row on the plan and the diagram, so they must be unique within a job."""
    seen: set[str] = set()
    for row in rows:
        if row.ref in seen:
            raise ValueError(f"Duplicate ref {row.ref!r}")
        seen.add(row.ref)
