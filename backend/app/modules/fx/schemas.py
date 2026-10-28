# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Currency / FX Pydantic schemas for request/response validation."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, PlainSerializer

# Money and rates are exchanged as strings on the wire so JSON's float bridge
# never silently rounds a precision-critical value (same convention as
# ``app.modules.costs.schemas.DecimalMoney``). Inputs accept any JSON number or
# numeric string; Pydantic v2 promotes them to ``Decimal``. Outputs serialise to
# strings so a 199.99 amount does not become 199.98999999 in a JS client.
DecimalMoney = Annotated[
    Decimal,
    PlainSerializer(lambda v: str(v) if v is not None else None, return_type=str),
]

#: ``live`` tracks the newest rates; ``pinned`` holds a project to one set.
RateMode = Literal["live", "pinned"]


class RateProvenance(BaseModel):
    """Where a rate came from, carried by every response that applies one.

    An estimator asked to defend a number needs to answer three questions about
    the rate behind it: what date it was effective for, who published it, and
    whether it can still change. These fields are those answers.
    """

    as_of: date | None = Field(default=None, description="Date the applied rates are effective for.")
    source: str = Field(default="", description="Who published the rates: ecb | seed | manual | worldbank.")
    origin: str = Field(
        default="",
        description="Where they were read from: rate_set | legacy_cache | seed | worldbank.",
    )
    source_ref: str = Field(default="", description="Feed URL, contract clause or document the figures came from.")
    fetched_at: datetime | None = Field(default=None, description="When the set was captured, if known.")
    rate_set_id: str | None = Field(default=None, description="Identifier of the rate set applied, if any.")
    is_locked: bool = Field(default=False, description="True when the applied set is locked against edits.")
    covers_requested_date: bool = Field(
        default=True,
        description="False when no set was on file for the requested date and an earlier one was applied.",
    )


# ── Convert ────────────────────────────────────────────────────────────────


class ConvertRequest(BaseModel):
    """Request body for ``POST /api/v1/fx/convert/``."""

    amount: Decimal = Field(..., description="Amount to convert. Accepts a JSON number or a numeric string.")
    from_currency: str = Field(..., min_length=3, max_length=3, description="ISO 4217 source currency (e.g. EUR).")
    to_currency: str = Field(..., min_length=3, max_length=3, description="ISO 4217 target currency (e.g. TRY).")
    mode: Literal["market", "ppp"] = Field(
        default="market",
        description="market = published reference rate; ppp = World Bank purchasing-power-parity.",
    )
    on_date: date | None = Field(
        default=None,
        description="Value the amount at the rates that applied on this date. Defaults to the latest rates.",
    )
    project_id: uuid.UUID | None = Field(
        default=None,
        description="Apply this project's FX policy, so a pinned project reprices at its pinned rate set.",
    )
    rate_set_id: uuid.UUID | None = Field(
        default=None,
        description="Use one named rate set, overriding both the date and the project policy.",
    )


class ConvertResponse(RateProvenance):
    """Result of a currency conversion.

    On success ``converted`` and ``rate`` are populated and ``available`` is
    true. When the requested mode has no data (typically a missing PPP factor)
    the endpoint still returns 200 with ``available=false``, null ``converted`` /
    ``rate`` and a plain-language ``note`` - an unavailable mode is an honest
    state, not an error.
    """

    amount: DecimalMoney
    converted: DecimalMoney | None = Field(
        default=None,
        description="Converted amount; null when the requested mode is unavailable.",
    )
    rate: DecimalMoney | None = Field(
        default=None,
        description="Effective source-to-target rate applied; null when unavailable.",
    )
    from_currency: str
    to_currency: str
    mode: Literal["market", "ppp"]
    available: bool = Field(
        default=True,
        description="False when the requested mode has no data (e.g. a missing PPP factor).",
    )
    note: str = Field(default="", description="Human-readable explanation, especially when unavailable.")


# ── Rates ──────────────────────────────────────────────────────────────────


class FxRatesResponse(RateProvenance):
    """Rate map for a base currency (units of each currency per 1 base)."""

    base: str = Field(..., description="Base currency the rates are quoted against.")
    count: int = Field(..., ge=0, description="Number of quoted currencies.")
    rates: dict[str, DecimalMoney] = Field(
        default_factory=dict,
        description="Map of ISO 4217 currency code to units of that currency per 1 base.",
    )
    note: str = Field(default="", description="Set when the rates do not cover the date that was asked for.")


# ── Rate sets ──────────────────────────────────────────────────────────────


class RateSetSummary(BaseModel):
    """A stored rate set without its individual quotes."""

    id: str
    base_currency: str
    rate_date: date = Field(..., description="Date the rates are effective for.")
    source: str = Field(..., description="Who published them: ecb | seed | manual.")
    source_ref: str = Field(default="", description="Feed URL, contract clause or document reference.")
    fetched_at: datetime | None = Field(default=None, description="When the set was captured.")
    is_locked: bool = Field(default=False, description="A locked set can no longer be rewritten or deleted.")
    note: str = Field(default="")
    quote_count: int = Field(..., ge=0, description="Number of currencies quoted in the set.")
    currencies: list[str] = Field(default_factory=list, description="Currency codes the set quotes.")


class RateSetDetail(RateSetSummary):
    """A stored rate set with every quote it carries."""

    rates: dict[str, DecimalMoney] = Field(
        default_factory=dict,
        description="Map of currency code to units per one base currency.",
    )


class RateSetListResponse(BaseModel):
    """A page of stored rate sets, newest first."""

    total: int = Field(..., ge=0, description="Total number of sets matching the filter.")
    items: list[RateSetSummary] = Field(default_factory=list)


class RateSetCreateRequest(BaseModel):
    """Record a hand-entered rate set: a contract rate, a bank quote, treasury.

    The rate a project is held to is often not a central bank's. Recording it
    here gives it the same provenance, point-in-time behaviour and lockability
    as the feed, instead of leaving it in somebody's spreadsheet.
    """

    base_currency: str = Field(
        default="EUR",
        min_length=3,
        max_length=3,
        description="ISO 4217 base the rates are quoted against.",
    )
    rate_date: date = Field(..., description="Date the rates are effective for.")
    rates: dict[str, Decimal] = Field(
        ...,
        min_length=1,
        description="Map of ISO 4217 currency code to units of that currency per 1 base.",
    )
    source: str = Field(default="manual", max_length=30, description="Provenance key; defaults to manual.")
    source_ref: str = Field(default="", max_length=500, description="Contract clause, bank reference or document id.")
    note: str = Field(default="", max_length=500)
    lock: bool = Field(
        default=False,
        description="Lock the set immediately so it can never be rewritten. Pin only to locked sets.",
    )


class RateSetLockRequest(BaseModel):
    """Lock or unlock a rate set."""

    locked: bool = Field(..., description="True to lock the set against further edits.")


# ── Project policy ─────────────────────────────────────────────────────────


class FxPolicyRequest(BaseModel):
    """A project's currency policy.

    The three currencies are the three a cost manager actually deals with: the
    estimate is built in one, commitments are placed in a second and the client
    is reported to in a third.
    """

    estimating_currency: str = Field(
        default="EUR", min_length=3, max_length=3, description="Currency the estimate is built in."
    )
    procurement_currency: str = Field(
        default="EUR", min_length=3, max_length=3, description="Currency commitments are placed in."
    )
    reporting_currency: str = Field(
        default="EUR", min_length=3, max_length=3, description="Currency the client is reported to in."
    )
    rate_mode: RateMode = Field(
        default="live",
        description="live tracks the newest rates; pinned holds the project to one rate set.",
    )
    pinned_rate_set_id: uuid.UUID | None = Field(
        default=None,
        description="The rate set to pin to. Required when rate_mode is pinned.",
    )
    max_rate_age_days: int = Field(
        default=30,
        ge=0,
        le=3650,
        description="How old the backing rates may get before validation warns.",
    )
    note: str = Field(default="", max_length=500)


class FxPolicyResponse(BaseModel):
    """A project's stored currency policy, with its pinned set resolved."""

    project_id: str
    estimating_currency: str
    procurement_currency: str
    reporting_currency: str
    rate_mode: RateMode
    pinned_rate_set_id: str | None = None
    pinned_rate_set: RateSetSummary | None = None
    max_rate_age_days: int
    note: str = ""


# ── Revaluation ────────────────────────────────────────────────────────────


class RevaluationLineRequest(BaseModel):
    """One figure to revalue, in its own currency, at two points in time."""

    currency: str = Field(..., min_length=3, max_length=3, description="ISO 4217 currency the figure is held in.")
    baseline_amount: Decimal = Field(..., description="The amount when the baseline was set.")
    current_amount: Decimal = Field(..., description="The amount now. Equal to the baseline when only rates moved.")
    ref: str = Field(default="", max_length=100, description="Your identifier for the line (package, order, WBS).")
    description: str = Field(default="", max_length=300)


class RevaluationRequest(BaseModel):
    """Revalue a set of figures between two rate dates and attribute the movement."""

    reporting_currency: str = Field(..., min_length=3, max_length=3, description="Currency to report every value in.")
    lines: list[RevaluationLineRequest] = Field(..., min_length=1, description="The figures to revalue.")
    baseline_date: date | None = Field(default=None, description="Date of the baseline rates.")
    current_date: date | None = Field(default=None, description="Date of the current rates; defaults to latest.")
    baseline_rate_set_id: uuid.UUID | None = Field(default=None, description="Name the baseline set explicitly.")
    current_rate_set_id: uuid.UUID | None = Field(default=None, description="Name the current set explicitly.")
    project_id: uuid.UUID | None = Field(
        default=None,
        description="Apply this project's FX policy to the current rates.",
    )


class RevaluationLineResult(BaseModel):
    """One revalued figure, with its movement split into scope and rate.

    ``scope_delta + rate_delta + joint_delta`` equals ``total_delta`` exactly.
    ``joint_delta`` is the interaction - new scope valued at the movement in the
    rate - and also absorbs the rounding residual, so the three parts always add
    up rather than nearly adding up.
    """

    ref: str = ""
    description: str = ""
    currency: str
    baseline_amount: DecimalMoney
    current_amount: DecimalMoney
    baseline_rate: DecimalMoney | None = None
    current_rate: DecimalMoney | None = None
    baseline_value: DecimalMoney | None = Field(default=None, description="Baseline amount in the reporting currency.")
    current_value: DecimalMoney | None = Field(default=None, description="Current amount in the reporting currency.")
    total_delta: DecimalMoney | None = None
    scope_delta: DecimalMoney | None = Field(default=None, description="Movement caused by the amount changing.")
    rate_delta: DecimalMoney | None = Field(default=None, description="Movement caused by the exchange rate changing.")
    joint_delta: DecimalMoney | None = Field(default=None, description="Interaction of the two, plus rounding.")
    available: bool = True
    note: str = ""


class RateSetRef(BaseModel):
    """Which rates a side of a revaluation used."""

    as_of: date | None = None
    source: str = ""
    origin: str = ""
    source_ref: str = ""
    rate_set_id: str | None = None
    is_locked: bool = False
    covers_requested_date: bool = True


class RevaluationResponse(BaseModel):
    """Revaluation of a set of figures, per line and in total."""

    reporting_currency: str
    baseline: RateSetRef
    current: RateSetRef
    lines: list[RevaluationLineResult] = Field(default_factory=list)
    priced_lines: int = Field(..., ge=0, description="Lines both rate sets could price.")
    unpriced_lines: int = Field(..., ge=0, description="Lines in a currency one of the sets does not quote.")
    baseline_value: DecimalMoney
    current_value: DecimalMoney
    total_delta: DecimalMoney
    scope_delta: DecimalMoney
    rate_delta: DecimalMoney
    joint_delta: DecimalMoney
    note: str = ""


# ── Validation ─────────────────────────────────────────────────────────────


class FxValidationFinding(BaseModel):
    """One validation finding, ready to render as a row under a traffic light."""

    rule_id: str
    rule_name: str
    severity: str
    category: str
    message: str
    element_ref: str | None = None
    suggestion: str | None = None


class FxValidationResponse(BaseModel):
    """Validation report for a project's FX setup."""

    project_id: str
    status: str = Field(..., description="passed | warnings | errors | info | skipped | unsupported.")
    score: float | None = Field(default=None, description="Quality score 0-1; null when nothing was checked.")
    checked: int = Field(..., ge=0, description="Number of checks that actually ran.")
    errors: list[FxValidationFinding] = Field(default_factory=list)
    warnings: list[FxValidationFinding] = Field(default_factory=list)


# ── Status ─────────────────────────────────────────────────────────────────


class FxStatusResponse(BaseModel):
    """Health and freshness of the FX subsystem."""

    source: str = Field(..., description="Who published the active rates: ecb | seed | manual.")
    origin: str = Field(default="", description="Where they were read from: rate_set | legacy_cache | seed.")
    rates_as_of: date | None = Field(default=None, description="Effective date of the active rates.")
    cached_currencies: int = Field(..., ge=0, description="Currencies held in the legacy latest-rate cache.")
    currencies: list[str] = Field(
        default_factory=list,
        description="Currency codes available for conversion right now.",
    )
    ppp_countries: int = Field(default=0, ge=0, description="Countries with a cached PPP factor.")
    rate_sets: int = Field(default=0, ge=0, description="Published rate sets held in the register.")
    network_ok: bool = Field(..., description="Whether the ECB feed was reachable on the last probe.")


# ── Refresh ────────────────────────────────────────────────────────────────


class RefreshResponse(BaseModel):
    """Result of a manual refresh from the live ECB feed."""

    updated: int = Field(..., ge=0, description="Number of currencies written to the register.")
    source: str = Field(..., description="ecb when the live feed was used, seed on network fallback.")
    as_of: date | None = Field(default=None, description="Effective date of the rates written.")
    rate_set_id: str | None = Field(default=None, description="The rate set that was written, if any.")
    network_ok: bool = Field(..., description="Whether the ECB feed was reachable.")
    note: str = Field(default="", description="Human-readable summary of what happened.")
