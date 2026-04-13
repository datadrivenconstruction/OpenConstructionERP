"""5D Cost Model Pydantic schemas — request/response models.

Defines create, update, and response schemas for cost snapshots,
budget lines, and cash flow entries.  Monetary values are exposed as
floats in the API but stored as strings in the database.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── CostSnapshot schemas ─────────────────────────────────────────────────────


class SnapshotCreate(BaseModel):
    """Create a new EVM cost snapshot."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID | None = None  # Set from URL path
    period: str = Field(..., min_length=7, max_length=10, pattern=r"^\d{4}-\d{2}$")
    planned_cost: float = 0.0
    earned_value: float = 0.0
    actual_cost: float = 0.0
    forecast_eac: float = 0.0
    spi: float = 0.0
    cpi: float = 0.0
    notes: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class SnapshotUpdate(BaseModel):
    """Partial update for an EVM snapshot."""

    model_config = ConfigDict(str_strip_whitespace=True)

    planned_cost: float | None = None
    earned_value: float | None = None
    actual_cost: float | None = None
    forecast_eac: float | None = None
    spi: float | None = None
    cpi: float | None = None
    notes: str | None = None
    metadata: dict[str, Any] | None = None


class SnapshotResponse(BaseModel):
    """Cost snapshot returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    period: str
    planned_cost: float
    earned_value: float
    actual_cost: float
    forecast_eac: float
    spi: float
    cpi: float
    notes: str
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── BudgetLine schemas ───────────────────────────────────────────────────────


class BudgetLineCreate(BaseModel):
    """Create a new budget line."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID | None = None  # Set from URL path
    boq_position_id: UUID | None = None
    activity_id: UUID | None = None
    category: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="material, labor, equipment, subcontractor, overhead, contingency",
    )
    description: str = Field(default="", max_length=500)
    planned_amount: float = 0.0
    committed_amount: float = 0.0
    actual_amount: float = 0.0
    forecast_amount: float = 0.0
    period_start: str | None = Field(default=None, max_length=20)
    period_end: str | None = Field(default=None, max_length=20)
    currency: str = Field(default="", max_length=10)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BudgetLineUpdate(BaseModel):
    """Partial update for a budget line."""

    model_config = ConfigDict(str_strip_whitespace=True)

    boq_position_id: UUID | None = None
    activity_id: UUID | None = None
    category: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    planned_amount: float | None = None
    committed_amount: float | None = None
    actual_amount: float | None = None
    forecast_amount: float | None = None
    period_start: str | None = None
    period_end: str | None = None
    currency: str | None = Field(default=None, max_length=10)
    metadata: dict[str, Any] | None = None


class BudgetLineResponse(BaseModel):
    """Budget line returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    boq_position_id: UUID | None
    activity_id: UUID | None
    category: str
    description: str
    planned_amount: float
    committed_amount: float
    actual_amount: float
    forecast_amount: float
    period_start: str | None
    period_end: str | None
    currency: str
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── CashFlow schemas ─────────────────────────────────────────────────────────


class CashFlowCreate(BaseModel):
    """Create a new cash flow entry."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID | None = None  # Set from URL path
    period: str = Field(..., min_length=7, max_length=10, pattern=r"^\d{4}-\d{2}$")
    category: str = Field(default="total", max_length=100)
    planned_inflow: float = 0.0
    planned_outflow: float = 0.0
    actual_inflow: float = 0.0
    actual_outflow: float = 0.0
    cumulative_planned: float = 0.0
    cumulative_actual: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class CashFlowUpdate(BaseModel):
    """Partial update for a cash flow entry."""

    model_config = ConfigDict(str_strip_whitespace=True)

    category: str | None = Field(default=None, max_length=100)
    planned_inflow: float | None = None
    planned_outflow: float | None = None
    actual_inflow: float | None = None
    actual_outflow: float | None = None
    cumulative_planned: float | None = None
    cumulative_actual: float | None = None
    metadata: dict[str, Any] | None = None


class CashFlowResponse(BaseModel):
    """Cash flow entry returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    period: str
    category: str
    planned_inflow: float
    planned_outflow: float
    actual_inflow: float
    actual_outflow: float
    cumulative_planned: float
    cumulative_actual: float
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Aggregated / composite response schemas ──────────────────────────────────


class DashboardResponse(BaseModel):
    """Aggregated 5D cost dashboard KPIs."""

    total_budget: float = 0.0
    total_committed: float = 0.0
    total_actual: float = 0.0
    total_forecast: float = 0.0
    variance: float = 0.0
    variance_pct: float = 0.0
    spi: float = 0.0
    cpi: float = 0.0
    status: str = "on_budget"
    currency: str = "EUR"


class SCurvePeriod(BaseModel):
    """Single period data point for S-curve chart."""

    period: str
    planned: float = 0.0
    earned: float = 0.0
    actual: float = 0.0


class SCurveData(BaseModel):
    """Time series data for S-curve visualisation."""

    periods: list[SCurvePeriod] = Field(default_factory=list)


class CashFlowPeriod(BaseModel):
    """Single period data point for cash flow chart."""

    period: str
    inflow: float = 0.0
    outflow: float = 0.0
    cumulative_planned: float = 0.0
    cumulative_actual: float = 0.0


class CashFlowData(BaseModel):
    """Aggregated cash flow data for chart display."""

    periods: list[CashFlowPeriod] = Field(default_factory=list)


class BudgetCategoryRow(BaseModel):
    """Budget summary for a single cost category."""

    category: str
    planned: float = 0.0
    committed: float = 0.0
    actual: float = 0.0
    forecast: float = 0.0
    variance_pct: float = 0.0


class BudgetSummary(BaseModel):
    """Budget summary grouped by cost category."""

    categories: list[BudgetCategoryRow] = Field(default_factory=list)


# ── EVM (Earned Value Management) schemas ────────────────────────────────────


class EVMResponse(BaseModel):
    """Full Earned Value Management calculation result.

    All standard EVM metrics computed from budget lines and schedule progress.
    """

    bac: float = Field(0.0, description="Budget At Completion — total planned budget")
    pv: float = Field(0.0, description="Planned Value — budget x time_elapsed%")
    ev: float = Field(0.0, description="Earned Value — budget x schedule_progress%")
    ac: float = Field(0.0, description="Actual Cost — sum of actual costs")
    sv: float = Field(0.0, description="Schedule Variance — EV - PV")
    cv: float = Field(0.0, description="Cost Variance — EV - AC")
    spi: float = Field(0.0, description="Schedule Performance Index — EV / PV")
    cpi: float = Field(0.0, description="Cost Performance Index — EV / AC")
    eac: float = Field(0.0, description="Estimate At Completion — BAC / CPI")
    etc: float = Field(0.0, description="Estimate To Complete — EAC - AC")
    vac: float = Field(0.0, description="Variance At Completion — BAC - EAC")
    tcpi: float = Field(0.0, description="To-Complete Performance Index — (BAC - EV) / (BAC - AC)")
    time_elapsed_pct: float = Field(0.0, description="Percentage of project duration elapsed (0.0 - 100.0)")
    schedule_progress_pct: float = Field(0.0, description="Weighted average schedule progress (0.0 - 100.0)")
    status: str = Field(
        "unknown",
        description="Overall project health: on_track, at_risk, critical, unknown",
    )
    spi_capped: bool = Field(
        False,
        description="True when SPI was clamped to the safe [0, 5] range (e.g. project "
        "has not started yet, making PV approximate). Treat the value as indicative only.",
    )


class WhatIfAdjustments(BaseModel):
    """Adjustments to apply for a what-if scenario.

    Each value is a percentage change relative to current values.
    Positive values increase costs/duration, negative values decrease.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=200, description="Scenario display name")
    material_cost_pct: float = Field(0.0, ge=-100.0, le=100.0, description="Material cost adjustment (-100% to +100%)")
    labor_cost_pct: float = Field(0.0, ge=-100.0, le=100.0, description="Labor cost adjustment (-100% to +100%)")
    duration_pct: float = Field(0.0, ge=-100.0, le=100.0, description="Duration adjustment (-100% to +100%)")


class WhatIfResult(BaseModel):
    """Result of a what-if scenario calculation.

    Contains the original and adjusted EAC values plus the created snapshot.
    """

    scenario_name: str
    original_bac: float = 0.0
    adjusted_bac: float = 0.0
    original_eac: float = 0.0
    adjusted_eac: float = 0.0
    delta: float = Field(0.0, description="adjusted_eac - original_eac")
    delta_pct: float = Field(0.0, description="Percentage change in EAC")
    adjustments_applied: dict[str, float] = Field(default_factory=dict)
    snapshot_id: UUID | None = Field(None, description="ID of the snapshot created for this scenario")
