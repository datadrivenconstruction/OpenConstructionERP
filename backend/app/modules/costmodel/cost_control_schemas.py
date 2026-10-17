# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost control request and response models.

Money goes out as plain decimal strings, like every other cost-domain
response, so a client never parses a float.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, PlainSerializer, field_validator

from app.modules.costmodel.cost_control import COST_STAGES
from app.modules.costmodel.schemas import _serialise_money

Money = Annotated[Decimal, PlainSerializer(_serialise_money, return_type=str, when_used="json")]
OptionalMoney = Annotated[Decimal | None, PlainSerializer(_serialise_money, return_type=str | None, when_used="json")]

RowKind = Literal["cost_line", "contract", "unassigned", "changes_without_contract", "other", "remaining", "allowance"]


class ForecastOverrideInfo(BaseModel):
    """A manual forecast; ``closed_at`` is empty while it is the one in force."""

    id: UUID
    amount: Money
    reason: str
    document_ref: str = ""
    document_id: UUID | None = None
    created_by: str | None = None
    created_at: datetime | None = None
    closed_at: datetime | None = None


class CostControlRow(BaseModel):
    """One row of the report: a cost line, a contract, or money with no cost line."""

    key: str
    kind: RowKind
    code: str = ""
    description: str = ""
    account_id: str | None = None
    status: str = ""
    budget: Money = Decimal("0")
    estimate: Money = Decimal("0")
    planned: Money = Decimal("0")
    awarded: Money = Decimal("0")
    changes: Money = Decimal("0")
    committed: Money = Decimal("0")
    certified: Money = Decimal("0")
    paid: Money = Decimal("0")
    pending_changes: Money = Decimal("0")
    forecast: Money = Decimal("0")
    forecast_source: str = "none"
    automatic_forecast: Money = Decimal("0")
    automatic_source: str = "none"
    variance: Money = Decimal("0")
    variance_pct: OptionalMoney = None
    override: ForecastOverrideInfo | None = None


class CostControlAccount(BaseModel):
    """A control account the cost lines are grouped under."""

    id: str
    code: str
    name: str
    # The account's own title; empty when its code list has none (then ``name`` is shown).
    title: str = ""
    parent_id: str | None = None
    level: int = 1
    # Money planned on the account itself; it also appears as an ``allowance`` row.
    own_amount: Money = Decimal("0")


class CostControlFinding(BaseModel):
    """Something worth a look, produced by the ``cost_control`` validation rules."""

    rule_id: str
    severity: Literal["warning", "info"]
    line_key: str | None = None
    code: str = ""
    amount: Money = Decimal("0")
    details: dict[str, str] = Field(default_factory=dict)


class SnapshotSummary(BaseModel):
    """A saved snapshot, without its rows."""

    id: UUID
    taken_on: str
    stage: str
    label: str = ""
    note: str = ""
    currency: str = ""
    totals: dict[str, str] = Field(default_factory=dict)
    created_by: str | None = None
    created_at: datetime | None = None


class SnapshotPage(BaseModel):
    """Saved forecasts, oldest first, in the paging envelope every register uses."""

    items: list[SnapshotSummary] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 0


class CostControlReport(BaseModel):
    """The cost control report for one project, along one axis."""

    project_id: UUID
    currency: str
    axis: Literal["cost_line", "contract"]
    as_of: str
    totals: dict[str, str]
    rows: list[CostControlRow]
    accounts: list[CostControlAccount] = Field(default_factory=list)
    findings: list[CostControlFinding] = Field(default_factory=list)
    last_snapshot: SnapshotSummary | None = None


class SnapshotCreateRequest(BaseModel):
    """Save the report as it stands today."""

    stage: str = "forecast"
    label: str = Field(default="", max_length=200)
    note: str = Field(default="", max_length=4000)

    @field_validator("stage")
    @classmethod
    def _known_stage(cls, v: str) -> str:
        if v not in COST_STAGES:
            raise ValueError(f"stage must be one of {', '.join(COST_STAGES)}")
        return v


class SnapshotDetail(SnapshotSummary):
    """A saved snapshot with its rows."""

    rows: list[dict[str, str]] = Field(default_factory=list)


class ForecastOverrideRequest(BaseModel):
    """A person's forecast for one cost line. The reason is required."""

    amount: Decimal = Field(..., max_digits=18, decimal_places=2)
    reason: str = Field(..., min_length=3, max_length=2000)
    document_ref: str = Field(default="", max_length=255)
    document_id: UUID | None = None

    @field_validator("reason")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3:
            raise ValueError("Give a short reason for the forecast")
        return v

    @field_validator("amount")
    @classmethod
    def _finite(cls, v: Decimal) -> Decimal:
        if not v.is_finite():
            raise ValueError("amount must be a finite number")
        return v


class LineHistoryPoint(BaseModel):
    """The line as a saved snapshot recorded it."""

    snapshot_id: UUID
    taken_on: str
    stage: str
    label: str = ""
    forecast: Money = Decimal("0")
    forecast_source: str = "none"
    committed: Money = Decimal("0")
    certified: Money = Decimal("0")


class LineChangeEvent(BaseModel):
    """An approved change that moved money on this line."""

    approved_on: str | None = None
    source_kind: str
    source_code: str = ""
    contract_code: str = ""
    amount: Money = Decimal("0")


class LineHistory(BaseModel):
    """Why a line's forecast is what it is: snapshots, changes and manual forecasts."""

    cost_line_id: UUID
    code: str
    description: str = ""
    currency: str = ""
    current: CostControlRow
    snapshots: list[LineHistoryPoint] = Field(default_factory=list)
    changes: list[LineChangeEvent] = Field(default_factory=list)
    overrides: list[ForecastOverrideInfo] = Field(default_factory=list)


class UnassignedItem(BaseModel):
    """A contract line or order item whose money is on no cost line yet."""

    kind: Literal["contract_line", "po_item"]
    id: UUID
    group_id: UUID
    group_code: str = ""
    group_title: str = ""
    code: str = ""
    description: str = ""
    amount: Money


class UnassignedPage(BaseModel):
    """Unassigned lines, one page of them, contract lines first."""

    items: list[UnassignedItem]
    total: int
    offset: int
    limit: int


class AssignTarget(BaseModel):
    kind: Literal["contract_line", "po_item"]
    id: UUID


class AssignRequest(BaseModel):
    """Put these lines on one cost line."""

    cost_line_id: UUID
    items: list[AssignTarget] = Field(min_length=1, max_length=500)


class AssignResult(BaseModel):
    assigned: int
