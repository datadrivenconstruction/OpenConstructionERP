"""‌⁠‍Risk Register Pydantic schemas — request/response models.

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
    """‌⁠‍Create a new risk item."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    title: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=5000)
    category: str = Field(
        default="technical",
        pattern=r"^(technical|financial|schedule|regulatory|environmental|safety)$",
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
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_serializer("impact_cost", "response_cost", when_used="json")
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)


class RiskUpdate(BaseModel):
    """‌⁠‍Partial update for a risk item."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    category: str | None = Field(
        default=None,
        pattern=r"^(technical|financial|schedule|regulatory|environmental|safety)$",
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
    metadata: dict[str, Any] | None = None

    @field_serializer("impact_cost", "response_cost", when_used="json")
    def _ser_money(self, v: Decimal | None) -> str | None:
        return _serialise_money(v)


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
    # 5x5 PMBOK matrix scoring — computed server-side from probability +
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
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    @field_serializer("impact_cost", "response_cost", when_used="json")
    def _ser_money(self, v: Decimal) -> str | None:
        return _serialise_money(v)


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
    # "" means unknown — the UI must render a currency-less number rather
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


# ── Monte Carlo simulation (v3.11 — T1) ──────────────────────────────────


class RiskSimulateRequest(BaseModel):
    """‌⁠‍Request body for ``POST /v1/risk/projects/{id}/simulate``.

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
    contributed across the simulation — i.e. the expected value the risk
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

    ``currency`` is data-driven (resolved from the owning project) — the
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
