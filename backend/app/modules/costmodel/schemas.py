# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""5D Cost Model Pydantic schemas - request/response models.

Defines create, update, and response schemas for cost snapshots,
budget lines, and cash flow entries. v3 §10 - monetary values are
Decimal-in / Decimal-as-string out in JSON; persisted as strings in the
database for SQLite compatibility.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer


# ── v3 §10 money serialisation helper ─────────────────────────────────────
# Mirrors backend/app/modules/boq/schemas.py - money fields are stored /
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
    """Create a new EVM cost snapshot.

    v3 §10 - ``planned_cost`` / ``earned_value`` / ``actual_cost`` are
    money; Decimal-as-string in JSON. SPI/CPI/forecast_eac stay float
    (SPI/CPI are ratios; forecast_eac is a derived metric not yet
    standardised on Decimal - leave for a future pass).
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
    """Partial update for an EVM snapshot."""

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

    v3 §10 - money is Decimal-as-string in JSON.
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

    v3 §10 - money fields are Decimal-as-string in JSON.
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
    # Gap D - the cost-overrun alert threshold (% above planned). Editable via
    # the dedicated PATCH endpoint, but also accepted here for completeness.
    # ``'0'`` disables alerting on the line. ``overrun_alerted_at`` is
    # deliberately NOT updatable through the API - only the subscriber stamps it.
    overrun_alert_threshold_pct: str | None = Field(default=None, max_length=10)
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

    v3 §10 - money fields are Decimal-as-string in JSON.
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
    # EVM earned value (BCWP) - position total x latest progress percent,
    # maintained by the progress module. None = no progress recorded yet.
    earned_amount: Decimal | None = None
    period_start: str | None
    period_end: str | None
    currency: str
    # Gap D - cost-overrun alert configuration. ``overrun_alert_threshold_pct``
    # is the % above planned that arms an alert ('0' = disabled);
    # ``overrun_alerted_at`` is the last alert timestamp (null = never).
    overrun_alert_threshold_pct: str = "0"
    overrun_alerted_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime

    @field_serializer(
        "planned_amount",
        "committed_amount",
        "actual_amount",
        "forecast_amount",
        "earned_amount",
        when_used="json",
    )
    def _ser_money(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)


# ── CashFlow schemas ─────────────────────────────────────────────────────────


class CashFlowCreate(BaseModel):
    """Create a new cash flow entry.

    v3 §10 - money fields are Decimal-as-string in JSON.
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

    v3 §10 - money fields are Decimal-as-string in JSON.
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

    v3 §10 - money fields are Decimal-as-string in JSON. Ratios (SPI/CPI/
    variance_pct) stay float. ``total_forecast`` and ``variance`` are
    aggregate metrics not in the deferred list - kept float for now.
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
    # True when the project's budget lines span more than one currency.
    # The repository converts foreign lines to the project base via
    # ``fx_rates``, but a missing rate leaves a foreign amount unconverted
    # and silently blended into the totals. Surface the flag so the UI can
    # warn instead of presenting a fictitious blended sum (mirrors
    # ``SpineRollupResponse.mixed_currency``).
    mixed_currency: bool = False

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

    v3 §10 - ``cumulative_planned`` / ``cumulative_actual`` are money;
    Decimal-as-string in JSON. ``inflow`` / ``outflow`` are deferred
    (not in the audit list - kept float).
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


# -- Contract exposure (committed vs budget) ---------------------------------


class ContractExposureGroup(BaseModel):
    """Committed-vs-budget contract exposure for a single cost group.

    v3 section 10 - money fields are Decimal-as-string in JSON. The commitment
    ratio is a unitless committed/budget fraction and follows the module's ratio
    convention (float), or null when the budget is zero or absent.
    """

    group: str
    budgeted: Decimal = Decimal("0")
    committed: Decimal = Decimal("0")
    remaining_to_commit: Decimal = Field(
        default=Decimal("0"),
        description="budgeted - committed (negative when overcommitted)",
    )
    commitment_ratio: float | None = Field(
        default=None,
        description="committed / budgeted; null when the budget is zero or absent",
    )
    overcommitted: bool = Field(
        default=False,
        description="True when committed is strictly above budgeted",
    )

    @field_serializer("budgeted", "committed", "remaining_to_commit", when_used="json")
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class ContractExposureResponse(BaseModel):
    """Project-wide contract-exposure view: committed vs budget by cost group.

    Budgeted is the planned budget; committed is the value already committed to
    contracts (subcontracts, purchase orders, awarded values); remaining to
    commit is the budget still free to commit. The rollup mirrors the sibling
    money surfaces (dashboard / EVM) by carrying the project base ``currency``
    and a ``mixed_currency`` flag (True when the budget lines span more than one
    currency, so a missing fx rate may have blended the totals).

    v3 section 10 - money fields are Decimal-as-string in JSON.
    """

    currency: str = ""
    mixed_currency: bool = False
    total_budgeted: Decimal = Decimal("0")
    total_committed: Decimal = Decimal("0")
    total_remaining_to_commit: Decimal = Decimal("0")
    total_commitment_ratio: float | None = Field(
        default=None,
        description="total committed / total budgeted; null when the total budget is zero",
    )
    overcommitted: bool = Field(
        default=False,
        description="True when total committed is strictly above total budgeted",
    )
    overcommitted_group_count: int = Field(
        default=0,
        description="How many groups are individually overcommitted",
    )
    groups: list[ContractExposureGroup] = Field(default_factory=list)

    @field_serializer("total_budgeted", "total_committed", "total_remaining_to_commit", when_used="json")
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)


# ── EVM (Earned Value Management) schemas ────────────────────────────────────


class EVMResponse(BaseModel):
    """Full Earned Value Management calculation result.

    All standard EVM metrics computed from budget lines and schedule progress.
    """

    bac: float = Field(0.0, description="Budget At Completion - total planned budget")
    pv: float = Field(0.0, description="Planned Value - budget x time_elapsed%")
    ev: float = Field(0.0, description="Earned Value - budget x schedule_progress%")
    ac: float = Field(0.0, description="Actual Cost - sum of actual costs")
    sv: float = Field(0.0, description="Schedule Variance - EV - PV")
    cv: float = Field(0.0, description="Cost Variance - EV - AC")
    spi: float = Field(0.0, description="Schedule Performance Index - EV / PV")
    cpi: float = Field(0.0, description="Cost Performance Index - EV / AC")
    eac: float = Field(0.0, description="Estimate At Completion - BAC / CPI")
    etc: float = Field(0.0, description="Estimate To Complete - EAC - AC")
    vac: float = Field(0.0, description="Variance At Completion - BAC - EAC")
    tcpi: float | None = Field(
        None,
        description=(
            "To-Complete Performance Index - (BAC - EV) / (BAC - AC). "
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
    currency: str = Field(
        "",
        description="Project base currency for all EVM amounts (bac/ac/eac/etc/vac).",
    )
    mixed_currency: bool = Field(
        False,
        description="True when the budget lines span more than one currency, so a "
        "missing fx_rate may have blended unconverted foreign amounts into BAC/AC. "
        "Treat the absolute figures as indicative when set (mirrors the dashboard "
        "and spine-rollup flags).",
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

    v3 §10 - ``budget`` / ``variance_abs`` are money; Decimal-as-string in
    JSON. ``current`` and ``red_line`` are not in the deferred audit list
    so they stay float (``current`` is a derived display value, ``red_line``
    is a configurable percentage threshold).
    """

    budget: Decimal = Decimal("0")
    current: float = 0.0
    variance_abs: Decimal = Field(default=Decimal("0"), description="current - budget")
    variance_pct: float = Field(0.0, description="(current - budget) / budget * 100 - 0.0 when budget is 0")
    red_line: float = Field(5.0, description="Absolute % threshold that flips the KPI to red")
    currency: str = ""

    @field_serializer("budget", "variance_abs", when_used="json")
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)


# ── Cost Spine (v6.4) ─────────────────────────────────────────────────────────


class ControlAccountCreate(BaseModel):
    """Create a control account in the Cost Breakdown Structure."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID | None = None  # Set from URL path
    parent_id: UUID | None = None
    code: str = Field(..., min_length=1, max_length=80)
    name: str = Field(..., min_length=1, max_length=255)
    classification_standard: str = Field(default="", max_length=40)
    status: str = Field(default="open", max_length=40)
    sort_order: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class ControlAccountUpdate(BaseModel):
    """Partial update for a control account."""

    model_config = ConfigDict(str_strip_whitespace=True)

    parent_id: UUID | None = None
    code: str | None = Field(default=None, min_length=1, max_length=80)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    classification_standard: str | None = Field(default=None, max_length=40)
    status: str | None = Field(default=None, max_length=40)
    sort_order: int | None = None
    metadata: dict[str, Any] | None = None


class ControlAccountResponse(BaseModel):
    """Control account returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    parent_id: UUID | None
    code: str
    name: str
    classification_standard: str
    status: str
    sort_order: int
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime


class CostLineCreate(BaseModel):
    """Create a cost line in the Cost Spine.

    v3 §10 - ``estimate_*`` money/quantity fields are Decimal-as-string in JSON.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID | None = None  # Set from URL path
    control_account_id: UUID | None = None
    code: str | None = Field(
        default=None,
        max_length=80,
        description="Unique within the project. Auto-generated when omitted.",
    )
    description: str = Field(default="", max_length=2000)
    unit: str | None = Field(default=None, max_length=20)
    source: str = Field(default="manual", max_length=40)
    boq_position_id: UUID | None = None
    boq_id: UUID | None = None
    estimate_quantity: Decimal = Decimal("0")
    estimate_unit_rate: Decimal = Decimal("0")
    estimate_amount: Decimal = Decimal("0")
    currency: str = Field(default="", max_length=10)
    status: str = Field(default="active", max_length=40)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_serializer("estimate_quantity", "estimate_unit_rate", "estimate_amount", when_used="json")
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class CostLineUpdate(BaseModel):
    """Partial update for a cost line."""

    model_config = ConfigDict(str_strip_whitespace=True)

    control_account_id: UUID | None = None
    code: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=2000)
    unit: str | None = Field(default=None, max_length=20)
    source: str | None = Field(default=None, max_length=40)
    boq_position_id: UUID | None = None
    boq_id: UUID | None = None
    estimate_quantity: Decimal | None = None
    estimate_unit_rate: Decimal | None = None
    estimate_amount: Decimal | None = None
    currency: str | None = Field(default=None, max_length=10)
    status: str | None = Field(default=None, max_length=40)
    metadata: dict[str, Any] | None = None

    @field_serializer("estimate_quantity", "estimate_unit_rate", "estimate_amount", when_used="json")
    def _ser_money(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)


class CostLineResponse(BaseModel):
    """Cost line returned from the API.

    v3 §10 - money/quantity fields are Decimal-as-string in JSON.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    control_account_id: UUID | None
    code: str
    description: str
    unit: str | None
    source: str
    boq_position_id: UUID | None
    boq_id: UUID | None
    estimate_quantity: Decimal = Decimal("0")
    estimate_unit_rate: Decimal = Decimal("0")
    estimate_amount: Decimal = Decimal("0")
    currency: str
    status: str
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime

    @field_serializer("estimate_quantity", "estimate_unit_rate", "estimate_amount", when_used="json")
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class CostLineLinks(BaseModel):
    """Every cross-module reference pointing at one cost line."""

    boq_position_ids: list[str] = Field(default_factory=list)
    budget_line_ids: list[str] = Field(default_factory=list)
    po_item_ids: list[str] = Field(default_factory=list)
    contract_line_ids: list[str] = Field(default_factory=list)
    rfq_ids: list[str] = Field(default_factory=list)


class CostLineRollupResponse(BaseModel):
    """Single cost line with its money rolled up across every linked entity.

    All money values are FX-converted into the cost line currency (the project
    base when blank) and emitted as Decimal-as-string in JSON.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    cost_line_id: UUID
    code: str
    control_account_id: UUID | None = None
    description: str = ""
    currency: str = ""
    estimate_amount: Decimal = Decimal("0")
    budget_planned: Decimal = Decimal("0")
    budget_committed: Decimal = Decimal("0")
    budget_actual: Decimal = Decimal("0")
    po_committed: Decimal = Decimal("0")
    contracted_value: Decimal = Decimal("0")
    claimed_to_date: Decimal = Decimal("0")
    variance_estimate_vs_budget: Decimal = Decimal("0")
    links: CostLineLinks = Field(default_factory=CostLineLinks)

    @field_serializer(
        "estimate_amount",
        "budget_planned",
        "budget_committed",
        "budget_actual",
        "po_committed",
        "contracted_value",
        "claimed_to_date",
        "variance_estimate_vs_budget",
        when_used="json",
    )
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class SpineRollupResponse(BaseModel):
    """Project-wide Cost Spine rollup.

    ``mixed_currency`` follows the existing flag convention: it is True when
    the linked rows carry more than one distinct ISO currency (so summing may
    have crossed missing fx_rates) and the client should warn rather than
    treat the totals as clean.
    """

    currency: str = ""
    mixed_currency: bool = False
    accounts: list[ControlAccountResponse] = Field(default_factory=list)
    lines: list[CostLineRollupResponse] = Field(default_factory=list)
    totals: dict[str, str] = Field(default_factory=dict)


class SpineGenerationResult(BaseModel):
    """Outcome of generating the spine from a BOQ.

    Idempotent: re-running only fills gaps, so the counters report what was
    newly created or wired on this call.
    """

    project_id: UUID
    boq_id: UUID
    accounts_created: int = 0
    cost_lines_created: int = 0
    positions_linked: int = 0
    budget_lines_linked: int = 0


class SpineLinkRequest(BaseModel):
    """Link or unlink a downstream entity to a cost line."""

    model_config = ConfigDict(str_strip_whitespace=True)

    target_type: str = Field(
        ...,
        description="One of: boq_position, budget_line, po_item, contract_line, rfq",
    )
    target_id: UUID


# ── Position actuals ──────────────────────────────────────────────────────────


class PositionActualsRow(BaseModel):
    """One bill position with everything the site has recorded against it.

    The Cost Spine rollup answers the same question keyed by cost line, in the
    language of money. This is the estimator's side of it: one row per item of
    work, carrying the position's own ordinal and unit, with physical progress
    and material consumption beside the money.

    ``on_cost_spine`` distinguishes the two reasons a money column reads zero.
    False means the position has no cost line, so nothing could have been
    attributed to it; true means nothing has been.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    boq_position_id: UUID
    ordinal: str = ""
    description: str = ""
    unit: str = ""
    cost_line_id: UUID | None = None
    cost_line_code: str = ""
    on_cost_spine: bool = False

    #: The production norm this line was priced from, empty on a line that was
    #: not (issue #457). Carried here so a reader looking at one item of work can
    #: see which norm predicted it without going back to the bill. The
    #: comparison across every line priced from the same norm is one grain up,
    #: at ``GET /api/v1/postcalc/projects/{id}/norm-outturn``.
    norm_id: str = ""
    norm_work_key: str = ""

    estimate_quantity: Decimal = Decimal("0")
    estimate_unit_rate: Decimal = Decimal("0")
    estimate_amount: Decimal = Decimal("0")

    budget_planned: Decimal = Decimal("0")
    budget_actual: Decimal = Decimal("0")
    committed_amount: Decimal = Decimal("0")
    contracted_amount: Decimal = Decimal("0")
    claimed_amount: Decimal = Decimal("0")
    uncommitted_amount: Decimal = Decimal("0")

    #: None when the crew has never reported on this position, which is not the
    #: same as reporting zero and must not be drawn as a 0 percent bar.
    installed_percent: Decimal | None = None
    installed_amount: Decimal = Decimal("0")

    consumed_quantity: Decimal = Decimal("0")
    consumed_amount: Decimal = Decimal("0")

    #: Net hours booked against this position on approved, unreversed field
    #: timesheets. Labour and plant stay apart: only labour compares with a
    #: productivity norm.
    labour_hours: Decimal = Decimal("0")
    plant_hours: Decimal = Decimal("0")
    #: Labour hours per unit of work actually IN PLACE, or None when no progress
    #: has been reported for the position. Deliberately not hours over the
    #: billed quantity, which would make a half-built item read as twice as
    #: productive as it is and an untouched one as the best on the project.
    labour_hours_per_installed_unit: Decimal | None = None

    @field_serializer(
        "estimate_quantity",
        "estimate_unit_rate",
        "estimate_amount",
        "budget_planned",
        "budget_actual",
        "committed_amount",
        "contracted_amount",
        "claimed_amount",
        "uncommitted_amount",
        "installed_percent",
        "installed_amount",
        "consumed_quantity",
        "consumed_amount",
        "labour_hours",
        "plant_hours",
        "labour_hours_per_installed_unit",
        when_used="json",
    )
    def _ser_money(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)


class PositionActualsResponse(BaseModel):
    """Position actuals for a project, with the totals over the rows returned.

    ``positions_off_spine`` counts the rows whose money is zero because they
    carry no cost line. It is reported rather than left to be counted, because
    a page of zeros has two causes and this is the one the reader can act on by
    generating the spine from the bill.
    """

    currency: str = ""
    rows: list[PositionActualsRow] = Field(default_factory=list)
    totals: dict[str, str] = Field(default_factory=dict)
    positions_off_spine: int = 0
