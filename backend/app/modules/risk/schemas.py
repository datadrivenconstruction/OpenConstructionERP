# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Risk Register Pydantic schemas - request/response models.

Defines create, update, and response schemas for risk register items.
Numeric values (probability, impact_cost, risk_score, response_cost) are stored
as strings in SQLite-compatible models; v3 §10 money fields
(``impact_cost``, ``response_cost``, ``total_exposure``) are emitted as
Decimal-as-string in JSON.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


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


# Upper bound for money fields. Far above any realistic construction amount yet
# well within Decimal's 28-digit precision, so a downstream exposure rollup /
# quantize on a stored value never raises InvalidOperation on an otherwise-
# "valid" huge input (e.g. '1e400'). Mirrors changeorders/schemas.py:_MONEY_MAX.
_MONEY_MAX = Decimal("1e15")


def _bound_money(v: Decimal | None) -> Decimal | None:
    """Reject non-finite / absurd-magnitude money so one bad row cannot poison
    the project-wide exposure rollup or 500 the summary / simulation.

    Pydantic already rejects NaN/Infinity for a ``Decimal`` field, but NOT a
    finite-but-absurd magnitude like ``1e400``; ``ge=0`` lets it through and it
    later overflows ``float()``/``quantize()`` in the rollup. This closes that
    gap (the ``is_finite`` check is kept as defence-in-depth)."""
    if v is None:
        return v
    if not v.is_finite():
        raise ValueError("amount must be a finite number (no NaN/Infinity)")
    if abs(v) >= _MONEY_MAX:
        raise ValueError("amount is outside the supported range")
    return v


# ── Shared controlled vocabularies (single source of truth) ──────────────
#
# These tuples are the canonical vocabularies for risk severity and status.
# `service.py` builds its numeric scoring maps (SEVERITY_NUMERIC /
# IMPACT_SCORE_MAP) from SEVERITY_LEVELS so the request schema and the
# service-side mapping can never drift apart again (F-PFO-RISK-03 /
# F-PFO-RISK-05). schemas.py is imported by service.py (one direction
# only), so keeping the vocabulary here avoids a circular import.

# Canonical PMBOK 5-level severity scale, low→critical, ordered by rank.
SEVERITY_CANONICAL: tuple[str, ...] = (
    "very_low",
    "low",
    "medium",
    "high",
    "critical",
)
# Legacy / alternate enum spellings that map onto the canonical scale at
# the same rank (negligible≈very_low … catastrophic≈critical). Accepted on
# input so existing seed / demo / imported data keeps validating.
SEVERITY_ALIASES: tuple[str, ...] = (
    "negligible",
    "minor",
    "moderate",
    "major",
    "catastrophic",
)
SEVERITY_LEVELS: tuple[str, ...] = SEVERITY_CANONICAL + SEVERITY_ALIASES
_SEVERITY_PATTERN = r"^(?:" + "|".join(SEVERITY_LEVELS) + r")$"

# Risk lifecycle status vocabulary. The model default is "identified".
# Seed / demo rows are written with "open", "monitoring" and "mitigated"
# (see core/demo_projects.py), so those MUST be a subset of what
# RiskCreate / RiskUpdate accept or seeded risks become un-editable.
STATUS_VALUES: tuple[str, ...] = (
    "identified",
    "assessed",
    "mitigating",
    "monitoring",
    "mitigated",
    "open",
    "closed",
    "occurred",
)
_STATUS_PATTERN = r"^(?:" + "|".join(STATUS_VALUES) + r")$"

# ── Risk schemas ─────────────────────────────────────────────────────────


class RiskCreate(BaseModel):
    """Create a new risk item."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    title: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=5000)
    category: str = Field(
        default="technical",
        pattern=r"^(technical|financial|schedule|regulatory|environmental|safety|procurement)$",
    )
    probability: float = Field(default=0.5, ge=0.0, le=1.0)
    impact_cost: Decimal = Field(default=Decimal("0"), ge=0)
    impact_schedule_days: int = Field(default=0, ge=0)
    impact_severity: str = Field(
        default="medium",
        pattern=_SEVERITY_PATTERN,
    )
    status: str = Field(
        default="identified",
        pattern=_STATUS_PATTERN,
    )
    mitigation_strategy: str = Field(default="", max_length=5000)
    contingency_plan: str = Field(default="", max_length=5000)
    owner_name: str = Field(default="", max_length=255)
    owner_user_id: UUID | None = None
    response_cost: Decimal = Field(default=Decimal("0"), ge=0)
    # Currency is data-driven: resolved from the owning project at create
    # time (see RiskService.create_risk). An explicit value here overrides
    # the project default; "" means "inherit from project / unknown".
    currency: str = Field(default="", max_length=10)
    # Per-risk override of the auto-escalation threshold (1-25 PMBOK product
    # scale). None inherits the project/global default (16 == critical tier).
    escalation_threshold: int | None = Field(default=None, ge=1, le=25)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_serializer("impact_cost", "response_cost", when_used="json")
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)

    @field_validator("impact_cost", "response_cost")
    @classmethod
    def _bound_money_fields(cls, v: Decimal | None) -> Decimal | None:
        return _bound_money(v)


class RiskUpdate(BaseModel):
    """Partial update for a risk item."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    category: str | None = Field(
        default=None,
        pattern=r"^(technical|financial|schedule|regulatory|environmental|safety|procurement)$",
    )
    probability: float | None = Field(default=None, ge=0.0, le=1.0)
    impact_cost: Decimal | None = Field(default=None, ge=0)
    impact_schedule_days: int | None = Field(default=None, ge=0)
    impact_severity: str | None = Field(
        default=None,
        pattern=_SEVERITY_PATTERN,
    )
    status: str | None = Field(
        default=None,
        pattern=_STATUS_PATTERN,
    )
    mitigation_strategy: str | None = Field(default=None, max_length=5000)
    contingency_plan: str | None = Field(default=None, max_length=5000)
    owner_name: str | None = Field(default=None, max_length=255)
    owner_user_id: UUID | None = None
    response_cost: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=10)
    escalation_threshold: int | None = Field(default=None, ge=1, le=25)
    metadata: dict[str, Any] | None = None

    @field_serializer("impact_cost", "response_cost", when_used="json")
    def _ser_money(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)

    @field_validator("impact_cost", "response_cost")
    @classmethod
    def _bound_money_fields(cls, v: Decimal | None) -> Decimal | None:
        return _bound_money(v)


class RiskResponse(BaseModel):
    """Risk item returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    code: str
    title: str
    description: str
    category: str
    probability: float = 0.5
    impact_cost: Decimal = Decimal("0")
    impact_schedule_days: int = 0
    impact_severity: str = "medium"
    risk_score: float = 0.0
    # 5x5 PMBOK matrix scoring - computed server-side from probability +
    # impact_severity. The frontend heatmap depends on these being present.
    probability_score: int | None = None
    impact_score_cost: int | None = None
    impact_score_time: int | None = None
    risk_tier: str | None = None
    status: str = "identified"
    mitigation_strategy: str = ""
    contingency_plan: str = ""
    owner_name: str = ""
    owner_user_id: UUID | None = None
    response_cost: Decimal = Decimal("0")
    currency: str = ""
    # ── Auto-escalation (TOP-30 #24) ──────────────────────────────────────
    escalated: bool = False
    escalated_at: datetime | None = None
    escalation_trigger: str | None = None
    escalation_threshold: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    @field_serializer("impact_cost", "response_cost", when_used="json")
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class RiskListResponse(BaseModel):
    """One page of a project's risk register plus the size of the whole set.

    ``total`` counts the risks the status, category and severity filters
    matched, not the length of ``items``. The register is sorted by score by
    default, so a truncated page hides the tail of the register - which is
    where the accepted and monitored risks sit, and exactly what a reviewer
    scrolls for when they ask whether anything has been left unowned.

    Distinct from :class:`RiskSummary`, which aggregates the whole project and
    never pages.
    """

    items: list[RiskResponse] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 50


# ── Summary schema ───────────────────────────────────────────────────────


class TopRisk(BaseModel):
    """A high-scoring risk for display in stats."""

    title: str
    score: float


class RiskSummary(BaseModel):
    """Aggregated risk stats for a project."""

    total: int = 0
    total_risks: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    by_tier: dict[str, int] = Field(default_factory=dict)
    by_category: dict[str, int] = Field(default_factory=dict)
    high_critical_count: int = 0
    avg_risk_score: float = 0.0
    total_exposure: Decimal = Decimal("0")
    with_mitigation: int = 0
    without_mitigation: int = 0
    mitigated_count: int = 0
    top_risks: list[TopRisk] = Field(default_factory=list)
    # Project currency (data-driven, resolved from the owning project).
    # "" means unknown - the UI must render a currency-less number rather
    # than mislabelling, e.g., AED exposure as EUR.
    currency: str = ""
    # Per-currency exposure breakdown. `total_exposure` is only meaningful
    # when every risk shares one currency; when they don't (mixed imports)
    # this map keeps each currency's exposure separate instead of summing
    # heterogeneous amounts under one last-wins label (F-PFO-RISK-04).
    exposure_by_currency: dict[str, float] = Field(default_factory=dict)

    @field_serializer("total_exposure", when_used="json")
    def _ser_total_exposure(self, v: Decimal) -> str | None:
        return _serialise_money(v)


# ── Risk Matrix schema ───────────────────────────────────────────────────


class RiskMatrixCell(BaseModel):
    """Single cell in the 5x5 risk matrix."""

    probability_level: str
    impact_level: str
    count: int = 0
    risk_ids: list[UUID] = Field(default_factory=list)


class RiskMatrixResponse(BaseModel):
    """5x5 risk matrix data."""

    cells: list[RiskMatrixCell] = Field(default_factory=list)


# ── Auto-escalation (TOP-30 #24) ─────────────────────────────────────────


class RiskEscalationSweepRequest(BaseModel):
    """Body for a manual escalation sweep over a project's risks.

    ``threshold`` overrides the default product threshold (1-25 PMBOK
    scale) for this run only. The same sweep is what the central scheduler
    calls on an interval; this endpoint lets a manager run it on demand.
    """

    threshold: int | None = Field(default=None, ge=1, le=25)


class RiskEscalationSweepResult(BaseModel):
    """Summary of an escalation sweep run."""

    scanned: int = 0
    escalated: int = 0
    # Count of escalations by trigger ("severity" / "review_lapsed").
    triggers: dict[str, int] = Field(default_factory=dict)


# ── Monte Carlo simulation (v3.11 - T1) ──────────────────────────────────


class RiskSimulateRequest(BaseModel):
    """Request body for ``POST /v1/risk/projects/{id}/simulate``.

    ``iterations`` is bounded so a misconfigured client can't accidentally
    DoS the worker; 100 000 samples per risk is plenty for stable
    P50/P80/P95 estimates and finishes in well under a second on a typical
    project (fewer than ~50 risks).
    """

    iterations: int = Field(default=10000, ge=1000, le=100000)
    mode: Literal["cost", "schedule", "both"] = "both"


class RiskTornadoEntry(BaseModel):
    """One bar in the tornado / sensitivity chart.

    ``contribution`` is the mean probability-weighted impact this risk
    contributed across the simulation - i.e. the expected value the risk
    adds to the project's contingency. Sorted descending in the response
    so the frontend can take the top N for the chart without re-sorting.
    """

    risk_id: UUID
    code: str
    contribution: Decimal


class RiskHistogramBin(BaseModel):
    """One bin in the 10-bin contingency histogram."""

    lower: Decimal
    upper: Decimal
    count: int


class RiskSimulationResult(BaseModel):
    """Persisted-style Monte Carlo result for a project.

    ``currency`` is data-driven (resolved from the owning project) - the
    UI must render currency-less totals when this is empty rather than
    silently mislabelling, e.g., AED exposure as EUR.
    """

    iterations: int
    risk_count: int
    mode: Literal["cost", "schedule", "both"]
    p50_cost: Decimal | None = None
    p80_cost: Decimal | None = None
    p95_cost: Decimal | None = None
    p50_schedule_days: int | None = None
    p80_schedule_days: int | None = None
    p95_schedule_days: int | None = None
    histogram_bins: list[RiskHistogramBin] = Field(default_factory=list)
    tornado: list[RiskTornadoEntry] = Field(default_factory=list)
    currency: str = ""
    # True when the project's cost-bearing risks span more than one currency;
    # the cost percentiles / histogram are then suppressed (None / empty) rather
    # than blended under a single mislabelled currency. Schedule is unaffected.
    mixed_currency: bool = False


# ── Risk-based contingency (EMV vs the finance contingency line) ─────────


class ContingencyLineOut(BaseModel):
    """One finance budget line in the contingency category, in its own currency."""

    budget_id: UUID
    wbs_id: str | None = None
    currency: str = ""
    allocated: Decimal = Decimal("0")
    drawn: Decimal = Decimal("0")
    remaining: Decimal = Decimal("0")
    # False when the line's currency has no FX rate to the project currency,
    # so it is shown on its own and left out of the totals.
    converted: bool = True

    @field_serializer("allocated", "drawn", "remaining", when_used="json")
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class ContingencyDrawdownOut(BaseModel):
    """A confirmed drawdown, amount in the currency of the line it was drawn from.

    The risk's code and title are a snapshot taken at confirmation, so the
    record still reads correctly after the risk itself was deleted.
    """

    risk_id: UUID | None = None
    risk_code: str = ""
    risk_title: str = ""
    budget_id: UUID
    amount: Decimal
    currency: str = ""
    confirmed_by: str | None = None
    confirmed_at: str | None = None
    note: str = ""

    @field_serializer("amount", when_used="json")
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class ContingencyPendingOut(BaseModel):
    """An occurred risk whose drawdown a person has not confirmed yet.

    ``proposed_amount`` is the cost impact expressed in the currency of the
    line the drawdown would land on by default. It prefills the dialog and is
    never recorded on its own.
    """

    risk_id: UUID
    risk_code: str = ""
    risk_title: str = ""
    impact_cost: Decimal = Decimal("0")
    currency: str = ""
    proposed_amount: Decimal | None = None
    proposed_currency: str = ""
    proposed_budget_id: UUID | None = None

    @field_serializer("impact_cost", "proposed_amount", when_used="json")
    def _ser_money(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)


class ContingencyPosition(BaseModel):
    """Risk-based contingency against the contingency the finance budget holds.

    Totals are in ``currency`` (the project currency). ``emv`` is the sum of
    probability x cost impact over risks that can still happen (closed and
    occurred risks, and risks already drawn down, are out). ``p50``/``p80``
    are deterministic percentiles of the same register; ``percentile_method``
    says whether they are exact or a normal approximation. ``remaining`` is
    allocated minus drawn, and ``coverage_gap`` is remaining minus EMV
    (negative means the contingency left does not cover the open exposure).
    """

    currency: str = ""
    emv: Decimal = Decimal("0")
    p50: Decimal = Decimal("0")
    p80: Decimal = Decimal("0")
    percentile_method: Literal["exact", "normal_approximation"] = "exact"
    emv_by_currency: dict[str, Decimal] = Field(default_factory=dict)
    allocated: Decimal = Decimal("0")
    drawn: Decimal = Decimal("0")
    remaining: Decimal = Decimal("0")
    coverage_gap: Decimal = Decimal("0")
    state: Literal["no_allocation", "covered", "shortfall", "overdrawn"] = "no_allocation"
    active_risk_count: int = 0
    excluded_closed_count: int = 0
    excluded_drawn_count: int = 0
    unconverted_emv: dict[str, Decimal] = Field(default_factory=dict)
    missing_fx_rates: list[str] = Field(default_factory=list)
    lines: list[ContingencyLineOut] = Field(default_factory=list)
    drawdowns: list[ContingencyDrawdownOut] = Field(default_factory=list)
    pending: list[ContingencyPendingOut] = Field(default_factory=list)

    @field_serializer("emv", "p50", "p80", "allocated", "drawn", "remaining", "coverage_gap", when_used="json")
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)

    @field_serializer("emv_by_currency", "unconverted_emv", when_used="json")
    def _ser_money_map(self, v: dict[str, Decimal]) -> dict[str, str | None]:
        return {k: _serialise_money(x) for k, x in v.items()}


class ContingencyDrawdownRequest(BaseModel):
    """A person confirming a drawdown for a risk that occurred.

    ``amount`` is in the currency of the chosen contingency line.
    ``budget_id`` may be left out when the project has one contingency line
    (or one in the project currency); with several it is required.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    amount: Decimal = Field(..., gt=0)
    budget_id: UUID | None = None
    note: str = Field(default="", max_length=1000)

    @field_validator("amount")
    @classmethod
    def _bound_amount(cls, v: Decimal) -> Decimal:
        return _bound_money(v) or v
