"""‌⁠‍5D Cost Model Pydantic schemas — request/response models.

Defines create, update, and response schemas for cost snapshots,
budget lines, and cash flow entries. v3 §10 — monetary values are
Decimal-in / Decimal-as-string out in JSON; persisted as strings in the
database for SQLite compatibility.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer


# ── v3 §10 money serialisation helper ─────────────────────────────────────
# Mirrors backend/app/modules/boq/schemas.py — money fields are stored /
# accepted as Decimal but emitted as plain decimal strings in JSON.
def _serialise_money(v: Decimal | None) -> str | None:
    if v is None:
        return None
    if not isinstance(v, Decimal):
        try:
            v = Decimal(str(v))
        except (InvalidOperation, ValueError):
            return "0"
    if not v.is_finite():
        return "0"
    return format(v, "f")


# ── CostSnapshot schemas ─────────────────────────────────────────────────────


class SnapshotCreate(BaseModel):
    """‌⁠‍Create a new EVM cost snapshot.

    v3 §10 — ``planned_cost`` / ``earned_value`` / ``actual_cost`` are
    money; Decimal-as-string in JSON. SPI/CPI/forecast_eac stay float
    (SPI/CPI are ratios; forecast_eac is a derived metric not yet
    standardised on Decimal — leave for a future pass).
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID | None = None  # Set from URL path
    period: str = Field(..., min_length=7, max_length=10, pattern=r"^\d{4}-\d{2}$")
    planned_cost: Decimal = Decimal("0")
    earned_value: Decimal = Decimal("0")
    actual_cost: Decimal = Decimal("0")
    forecast_eac: float = 0.0
    spi: float = 0.0
    cpi: float = 0.0
    notes: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_serializer("planned_cost", "earned_value", "actual_cost", when_used="json")
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class SnapshotUpdate(BaseModel):
    """‌⁠‍Partial update for an EVM snapshot."""

    model_config = ConfigDict(str_strip_whitespace=True)

    planned_cost: Decimal | None = None
    earned_value: Decimal | None = None
    actual_cost: Decimal | None = None
    forecast_eac: float | None = None
    spi: float | None = None
    cpi: float | None = None
    notes: str | None = None
    metadata: dict[str, Any] | None = None

    @field_serializer("planned_cost", "earned_value", "actual_cost", when_used="json")
    def _ser_money(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)


class SnapshotResponse(BaseModel):
    """Cost snapshot returned from the API.

    v3 §10 — money is Decimal-as-string in JSON.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    period: str
    planned_cost: Decimal = Decimal("0")
    earned_value: Decimal = Decimal("0")
    actual_cost: Decimal = Decimal("0")
    forecast_eac: float = 0.0
    spi: float = 0.0
    cpi: float = 0.0
    notes: str
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime

    @field_serializer("planned_cost", "earned_value", "actual_cost", when_used="json")
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)


# ── BudgetLine schemas ───────────────────────────────────────────────────────


class BudgetLineCreate(BaseModel):
    """Create a new budget line.

    v3 §10 — money fields are Decimal-as-string in JSON.
    """

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
    planned_amount: Decimal = Decimal("0")
    committed_amount: Decimal = Decimal("0")
    actual_amount: Decimal = Decimal("0")
    forecast_amount: Decimal = Decimal("0")
    period_start: str | None = Field(default=None, max_length=20)
    period_end: str | None = Field(default=None, max_length=20)
    currency: str = Field(default="", max_length=10)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_serializer(
        "planned_amount",
        "committed_amount",
        "actual_amount",
        "forecast_amount",
        when_used="json",
    )
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class BudgetLineUpdate(BaseModel):
    """Partial update for a budget line."""

    model_config = ConfigDict(str_strip_whitespace=True)

    boq_position_id: UUID | None = None
    activity_id: UUID | None = None
    category: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    planned_amount: Decimal | None = None
    committed_amount: Decimal | None = None
    actual_amount: Decimal | None = None
    forecast_amount: Decimal | None = None
    period_start: str | None = None
    period_end: str | None = None
    currency: str | None = Field(default=None, max_length=10)
    metadata: dict[str, Any] | None = None

    @field_serializer(
        "planned_amount",
        "committed_amount",
        "actual_amount",
        "forecast_amount",
        when_used="json",
    )
    def _ser_money(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)


class BudgetLineResponse(BaseModel):
    """Budget line returned from the API.

    v3 §10 — money fields are Decimal-as-string in JSON.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    boq_position_id: UUID | None
    activity_id: UUID | None
    category: str
    description: str
    planned_amount: Decimal = Decimal("0")
    committed_amount: Decimal = Decimal("0")
    actual_amount: Decimal = Decimal("0")
    forecast_amount: Decimal = Decimal("0")
    period_start: str | None
    period_end: str | None
    currency: str
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime

    @field_serializer(
        "planned_amount",
        "committed_amount",
        "actual_amount",
        "forecast_amount",
        when_used="json",
    )
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)


# ── CashFlow schemas ─────────────────────────────────────────────────────────


class CashFlowCreate(BaseModel):
    """Create a new cash flow entry.

    v3 §10 — money fields are Decimal-as-string in JSON.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID | None = None  # Set from URL path
    period: str = Field(..., min_length=7, max_length=10, pattern=r"^\d{4}-\d{2}$")
    category: str = Field(default="total", max_length=100)
    planned_inflow: Decimal = Decimal("0")
    planned_outflow: Decimal = Decimal("0")
    actual_inflow: Decimal = Decimal("0")
    actual_outflow: Decimal = Decimal("0")
    cumulative_planned: Decimal = Decimal("0")
    cumulative_actual: Decimal = Decimal("0")
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_serializer(
        "planned_inflow",
        "planned_outflow",
        "actual_inflow",
        "actual_outflow",
        "cumulative_planned",
        "cumulative_actual",
        when_used="json",
    )
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class CashFlowUpdate(BaseModel):
    """Partial update for a cash flow entry."""

    model_config = ConfigDict(str_strip_whitespace=True)

    category: str | None = Field(default=None, max_length=100)
    planned_inflow: Decimal | None = None
    planned_outflow: Decimal | None = None
    actual_inflow: Decimal | None = None
    actual_outflow: Decimal | None = None
    cumulative_planned: Decimal | None = None
    cumulative_actual: Decimal | None = None
    metadata: dict[str, Any] | None = None

    @field_serializer(
        "planned_inflow",
        "planned_outflow",
        "actual_inflow",
        "actual_outflow",
        "cumulative_planned",
        "cumulative_actual",
        when_used="json",
    )
    def _ser_money(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)


class CashFlowResponse(BaseModel):
    """Cash flow entry returned from the API.

    v3 §10 — money fields are Decimal-as-string in JSON.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    period: str
    category: str
    planned_inflow: Decimal = Decimal("0")
    planned_outflow: Decimal = Decimal("0")
    actual_inflow: Decimal = Decimal("0")
    actual_outflow: Decimal = Decimal("0")
    cumulative_planned: Decimal = Decimal("0")
    cumulative_actual: Decimal = Decimal("0")
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime

    @field_serializer(
        "planned_inflow",
        "planned_outflow",
        "actual_inflow",
        "actual_outflow",
        "cumulative_planned",
        "cumulative_actual",
        when_used="json",
    )
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)


# ── Aggregated / composite response schemas ──────────────────────────────────


class DashboardResponse(BaseModel):
    """Aggregated 5D cost dashboard KPIs.

    v3 §10 — money fields are Decimal-as-string in JSON. Ratios (SPI/CPI/
    variance_pct) stay float. ``total_forecast`` and ``variance`` are
    aggregate metrics not in the deferred list — kept float for now.
    """

    total_budget: Decimal = Decimal("0")
    total_committed: Decimal = Decimal("0")
    total_actual: Decimal = Decimal("0")
    total_forecast: float = 0.0
    variance: float = 0.0
    variance_pct: float = 0.0
    spi: float = 0.0
    cpi: float = 0.0
    status: str = "on_budget"
    currency: str = ""

    @field_serializer("total_budget", "total_committed", "total_actual", when_used="json")
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)


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
    """Single period data point for cash flow chart.

    v3 §10 — ``cumulative_planned`` / ``cumulative_actual`` are money;
    Decimal-as-string in JSON. ``inflow`` / ``outflow`` are deferred
    (not in the audit list — kept float).
    """

    period: str
    inflow: float = 0.0
    outflow: float = 0.0
    cumulative_planned: Decimal = Decimal("0")
    cumulative_actual: Decimal = Decimal("0")

    @field_serializer("cumulative_planned", "cumulative_actual", when_used="json")
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)


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
    variance: float = Field(0.0, description="planned - forecast (absolute currency)")
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
    tcpi: float | None = Field(
        None,
        description=(
            "To-Complete Performance Index — (BAC - EV) / (BAC - AC). "
            "Returns ``null`` when BAC <= AC: the denominator is zero or "
            "negative (project is already at-or-over budget), making TCPI "
            "mathematically undefined. Pre-audit this case was masked as "
            "``0.0`` which dashboards mis-rendered as 'perfect efficiency'."
        ),
    )
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


# ── Project Intelligence (RFC 25) ───────────────────────────────────────────


class VarianceResponse(BaseModel):
    """Budget variance KPI payload for the Estimation Dashboard hero.

    Budget is derived from the BOQ baseline (unit_rate * quantity across all
    positions of the project's primary BOQ, summed before any overrides).
    Current is the live BOQ total. Variance is expressed both in absolute
    currency and as a percentage of budget.

    v3 §10 — ``budget`` / ``variance_abs`` are money; Decimal-as-string in
    JSON. ``current`` and ``red_line`` are not in the deferred audit list
    so they stay float (``current`` is a derived display value, ``red_line``
    is a configurable percentage threshold).
    """

    budget: Decimal = Decimal("0")
    current: float = 0.0
    variance_abs: Decimal = Field(default=Decimal("0"), description="current - budget")
    variance_pct: float = Field(0.0, description="(current - budget) / budget * 100 — 0.0 when budget is 0")
    red_line: float = Field(5.0, description="Absolute % threshold that flips the KPI to red")
    currency: str = ""

    @field_serializer("budget", "variance_abs", when_used="json")
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)
