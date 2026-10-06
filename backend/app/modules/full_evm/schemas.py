# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Full EVM Pydantic schemas - request/response models.

Money on the wire is a **string**, not a JSON number. Every amount is a
:class:`~decimal.Decimal` server-side and is serialised through
``field_serializer`` so a JavaScript client, whose numbers are IEEE doubles,
cannot silently round a budget. Dimensionless indices follow the same rule for
consistency and because ``null`` (undefined) must survive the trip intact.

``null`` on an index means the index is **undefined** - a zero denominator -
never zero. See :mod:`app.modules.full_evm.metrics`.
"""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, get_args
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.core.currency_registry import minor_units as currency_minor_units
from app.modules.full_evm.metrics import EAC_METHODS
from app.modules.full_evm.models import BASELINE_STATUSES, MEASURE_SOURCES

# ── Shared value types ──────────────────────────────────────────────────────

#: An EAC formula name. ``auto`` picks the richest computable variant.
EacMethod = Literal["auto", "remaining", "cpi", "combined"]

#: Lifecycle state of a baseline.
BaselineStatus = Literal["draft", "approved", "superseded", "archived"]

#: Where a measurement's observations came from.
MeasureSource = Literal["manual", "finance_snapshot", "import"]


def _check_vocabulary(name: str, runtime: tuple[str, ...], literal: object) -> None:
    """Fail loudly at import if a Literal drifted from its runtime tuple.

    The ``Literal`` types above restate vocabularies that also exist as tuples
    on the model and in :mod:`app.modules.eac.evm`. Adding a value to one and
    not the other would surface as a puzzling 422 in production; here it is an
    immediate, named import error.

    Raises:
        RuntimeError: If the two definitions do not describe the same set.
    """
    declared = set(get_args(literal))
    if declared != set(runtime):
        msg = f"{name} vocabulary drifted: schema declares {sorted(declared)}, source of truth has {sorted(runtime)}"
        raise RuntimeError(msg)


_check_vocabulary("EAC method", EAC_METHODS, EacMethod)
_check_vocabulary("Baseline status", BASELINE_STATUSES, BaselineStatus)
_check_vocabulary("Measure source", MEASURE_SOURCES, MeasureSource)


def _parse_money(value: Any, field: str) -> Decimal:
    """Coerce an inbound amount to a finite ``Decimal`` or raise ``ValueError``."""
    if isinstance(value, Decimal):
        parsed = value
    else:
        try:
            parsed = Decimal(str(value).strip())
        except (InvalidOperation, ValueError, TypeError):
            msg = f"{field} must be a number such as 1200.50, got {value!r}"
            raise ValueError(msg) from None
    if not parsed.is_finite():
        msg = f"{field} must be a finite amount, got {value!r}"
        raise ValueError(msg)
    return parsed


# ── EVM Forecast (legacy text-amount surface) ───────────────────────────────


class EVMForecastCreate(BaseModel):
    """Manually create an EVM forecast record.

    The amounts stay strings to match the legacy ``oe_evm_forecast`` columns,
    but they are parsed on the way in: a forecast row carrying ``"banana"``
    where the EAC belongs would break every consumer that reads it back.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    forecast_date: str = Field(..., max_length=20)
    etc: str = Field(default="0", max_length=50, alias="etc_")
    eac: str = Field(default="0", max_length=50)
    vac: str = Field(default="0", max_length=50)
    tcpi: str = Field(default="0", max_length=50)
    forecast_method: str = Field(default="cpi", max_length=50)
    confidence_range_low: str | None = Field(default=None, max_length=50)
    confidence_range_high: str | None = Field(default=None, max_length=50)
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("etc", "eac", "vac", "confidence_range_low", "confidence_range_high")
    @classmethod
    def _amounts_are_numeric(cls, value: str | None) -> str | None:
        """Reject an amount that is not a finite number."""
        if value is None:
            return None
        _parse_money(value, "amount")
        return value

    @field_validator("tcpi")
    @classmethod
    def _tcpi_is_numeric_or_sentinel(cls, value: str) -> str:
        """Accept a number or the legacy ``inf`` sentinel for an unreachable TCPI."""
        if value == "inf":
            return value
        _parse_money(value, "tcpi")
        return value

    @field_validator("forecast_date")
    @classmethod
    def _forecast_date_is_iso(cls, value: str) -> str:
        """Require an ISO 8601 date so lexical ordering equals chronological order."""
        try:
            date.fromisoformat(value)
        except ValueError:
            msg = f"forecast_date must be an ISO 8601 date such as 2026-04-30, got {value!r}"
            raise ValueError(msg) from None
        return value


class EVMForecastResponse(BaseModel):
    """EVM forecast returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    forecast_date: str
    etc: str = Field(default="0", validation_alias="etc_")
    eac: str = "0"
    vac: str = "0"
    tcpi: str = "0"
    forecast_method: str = "cpi"
    confidence_range_low: str | None = None
    confidence_range_high: str | None = None
    notes: str | None = None
    alert_status: str | None = None
    triggered_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class EVMForecastListResponse(BaseModel):
    """Paginated list of EVM forecasts."""

    items: list[EVMForecastResponse]
    total: int


class EVMCalculateRequest(BaseModel):
    """Request to calculate an EVM forecast from the latest finance snapshot.

    ``forecast_method`` is validated against the supported set. An unknown name
    is rejected rather than quietly treated as the default, because the standard
    EAC formulas disagree and a silent substitution misreports the forecast.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    forecast_method: str = Field(
        default="cpi",
        max_length=50,
        description="cpi, spi_cpi (legacy alias of combined), remaining, combined or auto",
    )


class ForecastSnoozeRequest(BaseModel):
    """Request to snooze a triggered forecast alert."""

    hours: int = Field(default=24, ge=1, le=8760, description="Snooze duration in hours (max one year)")


class SCurveDataResponse(BaseModel):
    """S-curve data for charting."""

    model_config = ConfigDict(from_attributes=True)

    project_id: UUID
    snapshots: list[dict[str, Any]] = Field(default_factory=list)
    forecasts: list[dict[str, Any]] = Field(default_factory=list)


# ── Validation report ───────────────────────────────────────────────────────


class ValidationFinding(BaseModel):
    """One failing validation result, as stored on a baseline or measurement row."""

    rule_id: str
    severity: str
    message: str
    element_ref: str | None = None
    suggestion: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ValidationReportResponse(BaseModel):
    """Outcome of running the ``full_evm`` rule set over a row."""

    status: str = Field(description="passed, warnings, errors, info, skipped or pending")
    score: float | None = Field(
        default=None,
        description="Severity-weighted quality score, or null when nothing was actually checked",
    )
    findings: list[ValidationFinding] = Field(default_factory=list)


# ── Baseline periods ────────────────────────────────────────────────────────


class BaselinePeriodWrite(BaseModel):
    """One point on the cumulative planned-value curve, as submitted."""

    model_config = ConfigDict(str_strip_whitespace=True)

    period_end: date
    label: str = Field(default="", max_length=64)
    planned_value: Decimal = Field(description="Cumulative planned value at period_end, not the period's own amount")
    planned_quantity: Decimal | None = Field(
        default=None,
        description="Cumulative planned physical quantity at period_end",
    )

    @field_validator("planned_value", "planned_quantity", mode="before")
    @classmethod
    def _coerce_amounts(cls, value: Any) -> Any:
        """Parse strings and floats into exact Decimals before validation."""
        if value is None or isinstance(value, Decimal):
            return value
        return _parse_money(value, "amount")

    @field_validator("planned_value")
    @classmethod
    def _planned_value_non_negative(cls, value: Decimal) -> Decimal:
        """A cumulative planned value cannot be negative."""
        if value < 0:
            msg = f"planned_value is cumulative and cannot be negative, got {value}"
            raise ValueError(msg)
        return value

    @field_serializer("planned_value", "planned_quantity")
    def _serialize_amounts(self, value: Decimal | None) -> str | None:
        return None if value is None else str(value)


class BaselinePeriodResponse(BaseModel):
    """One point on the cumulative planned-value curve, as returned."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    ordinal: int
    period_end: date
    label: str
    planned_value: Decimal
    planned_quantity: Decimal | None = None

    @field_serializer("planned_value", "planned_quantity")
    def _serialize_amounts(self, value: Decimal | None) -> str | None:
        return None if value is None else str(value)


class BaselinePeriodsReplace(BaseModel):
    """Replace a baseline's whole planned-value curve in one write.

    Whole-curve replacement rather than per-row edits, because the curve's
    invariants (monotonic, ending at BAC) are properties of the set: a
    row-by-row edit path would spend most of its life in a state the rules
    correctly reject.
    """

    periods: list[BaselinePeriodWrite] = Field(default_factory=list, max_length=2000)


# ── Baseline ────────────────────────────────────────────────────────────────


class BaselineCreate(BaseModel):
    """Create a performance measurement baseline."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    bac: Decimal = Field(description="Budget At Completion for the scope this baseline measures")
    currency: str | None = Field(default=None, min_length=3, max_length=3, description="ISO 4217 code, label only")
    minor_units: int = Field(
        default_factory=lambda data: currency_minor_units(data.get("currency")),
        ge=0,
        le=4,
        description="Decimal places; defaults to the currency registry unless explicitly supplied",
    )
    start_date: date | None = None
    finish_date: date | None = None
    periods: list[BaselinePeriodWrite] = Field(default_factory=list, max_length=2000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("bac", mode="before")
    @classmethod
    def _coerce_bac(cls, value: Any) -> Any:
        """Parse the budget from a string or float into an exact Decimal."""
        if isinstance(value, Decimal):
            return value
        return _parse_money(value, "bac")

    @field_validator("bac")
    @classmethod
    def _bac_non_negative(cls, value: Decimal) -> Decimal:
        """A budget cannot be negative. Zero is allowed while drafting."""
        if value < 0:
            msg = f"bac cannot be negative, got {value}"
            raise ValueError(msg)
        return value

    @field_validator("currency")
    @classmethod
    def _currency_is_uppercase(cls, value: str | None) -> str | None:
        """Normalise the ISO 4217 label to upper case."""
        return None if value is None else value.upper()

    @field_serializer("bac")
    def _serialize_bac(self, value: Decimal) -> str:
        return str(value)


class BaselineUpdate(BaseModel):
    """Patch a baseline. Every field is optional; omitted fields are untouched."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    bac: Decimal | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    minor_units: int | None = Field(default=None, ge=0, le=4)
    start_date: date | None = None
    finish_date: date | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("bac", mode="before")
    @classmethod
    def _coerce_bac(cls, value: Any) -> Any:
        """Parse the budget from a string or float into an exact Decimal."""
        if value is None or isinstance(value, Decimal):
            return value
        return _parse_money(value, "bac")

    @field_validator("bac")
    @classmethod
    def _bac_non_negative(cls, value: Decimal | None) -> Decimal | None:
        """A budget cannot be negative."""
        if value is not None and value < 0:
            msg = f"bac cannot be negative, got {value}"
            raise ValueError(msg)
        return value

    @field_validator("currency")
    @classmethod
    def _currency_is_uppercase(cls, value: str | None) -> str | None:
        """Normalise the ISO 4217 label to upper case."""
        return None if value is None else value.upper()

    @field_serializer("bac")
    def _serialize_bac(self, value: Decimal | None) -> str | None:
        return None if value is None else str(value)


class BaselineResponse(BaseModel):
    """A baseline with its full planned-value curve."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    name: str
    description: str | None = None
    status: BaselineStatus
    bac: Decimal
    currency: str | None = None
    minor_units: int
    start_date: date | None = None
    finish_date: date | None = None
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    validation_status: str
    validation_findings: list[dict[str, Any]] = Field(default_factory=list)
    validation_score: float | None = None
    periods: list[BaselinePeriodResponse] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    @field_serializer("bac")
    def _serialize_bac(self, value: Decimal) -> str:
        return str(value)


class BaselineListResponse(BaseModel):
    """Paginated list of baselines."""

    items: list[BaselineResponse]
    total: int


# ── Measurement ─────────────────────────────────────────────────────────────


class MeasureCreate(BaseModel):
    """Record an EVM measurement for one data date.

    ``pv`` is optional: when omitted it is read from the baseline's curve at
    ``data_date``, which is the whole reason the curve is stored. Supplying it
    is an explicit override and is reported as such by
    ``full_evm.measure_pv_follows_baseline``.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    data_date: date
    ev: Decimal = Field(description="Cumulative earned value at the data date")
    ac: Decimal = Field(description="Cumulative actual cost at the data date")
    pv: Decimal | None = Field(default=None, description="Override for the baseline curve value at this date")
    bac: Decimal | None = Field(default=None, description="Override for the baseline budget in force at this date")
    planned_quantity: Decimal | None = None
    actual_quantity: Decimal | None = None
    eac_method: EacMethod = Field(default="auto", description="Which EAC formula to headline")
    source: MeasureSource = "manual"
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("ev", "ac", "pv", "bac", "planned_quantity", "actual_quantity", mode="before")
    @classmethod
    def _coerce_amounts(cls, value: Any) -> Any:
        """Parse strings and floats into exact Decimals before validation."""
        if value is None or isinstance(value, Decimal):
            return value
        return _parse_money(value, "amount")

    @field_validator("ev", "ac", "pv", "bac")
    @classmethod
    def _amounts_non_negative(cls, value: Decimal | None) -> Decimal | None:
        """Cumulative money totals cannot be negative."""
        if value is not None and value < 0:
            msg = f"cumulative amounts cannot be negative, got {value}"
            raise ValueError(msg)
        return value

    @field_serializer("ev", "ac", "pv", "bac", "planned_quantity", "actual_quantity")
    def _serialize_amounts(self, value: Decimal | None) -> str | None:
        return None if value is None else str(value)


class MeasureResponse(BaseModel):
    """A measurement with its full derived metric set.

    Every index is nullable and ``null`` means **undefined** - the denominator
    was zero - never zero.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    baseline_id: UUID
    project_id: UUID
    data_date: date
    source: str
    currency: str | None = None

    bac: Decimal
    pv: Decimal
    ev: Decimal
    ac: Decimal
    planned_quantity: Decimal | None = None
    actual_quantity: Decimal | None = None

    sv: Decimal
    cv: Decimal
    spi: Decimal | None = None
    cpi: Decimal | None = None
    percent_complete: Decimal | None = None
    percent_spent: Decimal | None = None

    eac_method: str
    eac_method_effective: str
    eac: Decimal | None = None
    etc: Decimal | None = Field(default=None, validation_alias="etc_")
    vac: Decimal | None = None
    tcpi_bac: Decimal | None = None
    tcpi_eac: Decimal | None = None
    eac_variants: dict[str, str | None] = Field(default_factory=dict)

    notes: str | None = None
    validation_status: str
    validation_findings: list[dict[str, Any]] = Field(default_factory=list)
    validation_score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime

    @field_serializer(
        "bac",
        "pv",
        "ev",
        "ac",
        "planned_quantity",
        "actual_quantity",
        "sv",
        "cv",
        "spi",
        "cpi",
        "percent_complete",
        "percent_spent",
        "eac",
        "etc",
        "vac",
        "tcpi_bac",
        "tcpi_eac",
    )
    def _serialize_amounts(self, value: Decimal | None) -> str | None:
        return None if value is None else str(value)


class MeasureListResponse(BaseModel):
    """Paginated list of measurements."""

    items: list[MeasureResponse]
    total: int


# ── Baseline S-curve ────────────────────────────────────────────────────────


class SCurvePoint(BaseModel):
    """One plotted point: the plan, and what actually happened by that date."""

    as_of: date = Field(description="The date this point describes")
    label: str = ""
    planned_value: str
    earned_value: str | None = None
    actual_cost: str | None = None
    forecast: str | None = Field(default=None, description="EAC in force at this date, when a measurement exists")


class BaselineSCurveResponse(BaseModel):
    """Plan-versus-actual curve for one baseline."""

    baseline_id: UUID
    project_id: UUID
    currency: str | None = None
    bac: str
    points: list[SCurvePoint] = Field(default_factory=list)


# ── Glossary ────────────────────────────────────────────────────────────────


class MetricGlossaryEntry(BaseModel):
    """One EVM code with its full name and a one-line plain-language meaning."""

    code: str
    label: str
    explanation: str


class MetricGlossaryResponse(BaseModel):
    """The EVM vocabulary, so a cryptic three-letter code is never unexplained."""

    metrics: list[MetricGlossaryEntry] = Field(default_factory=list)
    eac_methods: list[dict[str, str]] = Field(
        default_factory=list,
        description="Each supported EAC formula with its algebra and when to use it",
    )
    supported_methods: list[str] = Field(
        default_factory=list,
        description="Method names accepted by the eac_method field",
    )


__all__ = [
    "BaselineCreate",
    "BaselineListResponse",
    "BaselinePeriodResponse",
    "BaselinePeriodWrite",
    "BaselinePeriodsReplace",
    "BaselineResponse",
    "BaselineSCurveResponse",
    "BaselineStatus",
    "BaselineUpdate",
    "EVMCalculateRequest",
    "EVMForecastCreate",
    "EVMForecastListResponse",
    "EVMForecastResponse",
    "EacMethod",
    "ForecastSnoozeRequest",
    "MeasureCreate",
    "MeasureListResponse",
    "MeasureResponse",
    "MeasureSource",
    "MetricGlossaryEntry",
    "MetricGlossaryResponse",
    "SCurveDataResponse",
    "SCurvePoint",
    "ValidationFinding",
    "ValidationReportResponse",
]
