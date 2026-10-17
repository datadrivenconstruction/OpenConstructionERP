# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Pydantic v2 schemas for the BI Dashboards module."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.bi_dashboards.kpi_spec import KPI_SCOPES as _KPI_SCOPES

# ── Canonical enumerations ─────────────────────────────────────────────

KPI_UNITS: tuple[str, ...] = (
    "currency",
    "percent",
    "days",
    "count",
    "ratio",
    "m2",
    "m3",
    "hours",
)
KPI_AGGREGATIONS: tuple[str, ...] = (
    "sum",
    "avg",
    "min",
    "max",
    "last",
    "derive",
)
KPI_CATEGORIES: tuple[str, ...] = (
    "financial",
    "schedule",
    "quality",
    "safety",
    "sustainability",
    "operational",
)
#: What one computed KPI value is a value OF. Defined in ``kpi_spec``
#: because that module is what knows which entities can carry which scope,
#: and a second spelling here would be a second answer to the same question.
KPI_SCOPES = _KPI_SCOPES
DASHBOARD_SCOPES: tuple[str, ...] = ("personal", "role", "global", "project")
REPORT_SCOPES: tuple[str, ...] = ("personal", "role", "global")
WIDGET_TYPES: tuple[str, ...] = (
    "kpi_card",
    "line_chart",
    "bar_chart",
    "pie",
    "table",
    "heatmap",
    "gauge",
    "timeline",
)
REPORT_FREQUENCIES: tuple[str, ...] = (
    "daily",
    "weekly",
    "monthly",
    "quarterly",
)
OUTPUT_FORMATS: tuple[str, ...] = ("pdf", "xlsx", "csv", "json")
ALERT_CONDITIONS: tuple[str, ...] = (
    "above",
    "below",
    "equals",
    "not_equals",
    "changed_by_more_than",
)
ALERT_SEVERITIES: tuple[str, ...] = ("info", "warning", "critical")
ALERT_CHANNELS: tuple[str, ...] = ("in_app", "email", "webhook")


# ── KPI Definition ─────────────────────────────────────────────────────


class KPIDefinitionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    description: str = ""
    formula_ref: str
    source_modules: list[str] = Field(default_factory=list)
    unit: str = "ratio"
    target_default: Decimal | None = None
    aggregation: str = "last"
    category: str = "operational"
    is_system: bool = False
    spec_json: dict[str, Any] = Field(default_factory=dict)
    project_id: UUID | None = None
    scope: str = "project"
    created_at: datetime
    updated_at: datetime


class KPIDefinitionCreate(BaseModel):
    """Payload for registering a custom KPI.

    Deliberately minimal, and deliberately missing two fields the read
    model has. ``formula_ref`` is not accepted because it binds a code to
    a Python function: letting a caller set it would let them register
    ``my_margin`` pointing at the built-in ``cpi`` and call the result
    their own. ``is_system`` is not accepted because the starter pack
    tells its own rows apart by it. Both are set by the server.

    ``spec`` is the whole definition of what the KPI measures. It is
    checked against the entity / field / aggregation whitelist in
    :mod:`app.modules.bi_dashboards.kpi_spec` at creation time, and the
    rejection names the part of the spec that failed.
    """

    code: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    unit: str = "ratio"
    target_default: Decimal | None = None
    aggregation: str = "last"
    category: str = "operational"
    project_id: UUID | None = None
    # What one value of this KPI is a value OF. "project" is the default and
    # is what every definition registered before this field existed means.
    # "estimate" is refused at creation when the spec's entity has no
    # estimate of its own, rather than accepted and found unanswerable later.
    scope: str = "project"
    spec: dict[str, Any] = Field(...)

    @field_validator("unit")
    @classmethod
    def _known_unit(cls, value: str) -> str:
        if value not in KPI_UNITS:
            raise ValueError(f"unknown unit {value!r}. Allowed: {', '.join(KPI_UNITS)}.")
        return value

    @field_validator("aggregation")
    @classmethod
    def _known_aggregation(cls, value: str) -> str:
        # This is the trend aggregation - how successive stored values of
        # the KPI roll up over time. What the KPI measures in the first
        # place is ``spec.aggregation``, a different vocabulary.
        if value not in KPI_AGGREGATIONS:
            raise ValueError(f"unknown aggregation {value!r}. Allowed: {', '.join(KPI_AGGREGATIONS)}.")
        return value

    @field_validator("category")
    @classmethod
    def _known_category(cls, value: str) -> str:
        if value not in KPI_CATEGORIES:
            raise ValueError(f"unknown category {value!r}. Allowed: {', '.join(KPI_CATEGORIES)}.")
        return value

    @field_validator("scope")
    @classmethod
    def _known_scope(cls, value: str) -> str:
        if value not in KPI_SCOPES:
            raise ValueError(f"unknown scope {value!r}. Allowed: {', '.join(KPI_SCOPES)}.")
        return value


class KPIComputeRequest(BaseModel):
    kpi_code: str | None = None  # path param wins; body version optional
    project_id: UUID | None = None
    # Narrow the reading to one estimate. The estimate is resolved to the
    # project that owns it and THAT project is access-checked, so this is
    # not a second, unguarded way to name a row set - see the router.
    boq_id: UUID | None = None
    period_start: date | None = None
    period_end: date | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    persist: bool = False


class KPIComputeResponse(BaseModel):
    kpi_code: str
    # ``None`` only with ``unavailable_reason`` set: a ratio over a zero
    # denominator or over several units has no value, and 0 would read as one.
    value: Decimal | None
    unit: str
    source_record_count: int = 0
    unavailable_reason: str | None = None
    computed_at: datetime
    breakdown: dict[str, Any] = Field(default_factory=dict)
    trend: list[dict[str, Any]] = Field(default_factory=list)
    benchmark: dict[str, Any] = Field(default_factory=dict)


# ── Dashboard ──────────────────────────────────────────────────────────


class DashboardCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    scope: str = "personal"
    role_ref: str | None = None
    project_id: UUID | None = None
    layout_json: dict[str, Any] = Field(default_factory=dict)
    is_default: bool = False
    refresh_interval_seconds: int = Field(default=300, ge=10, le=86400)
    cross_filter_enabled: bool = False


class DashboardUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    scope: str | None = None
    role_ref: str | None = None
    project_id: UUID | None = None
    layout_json: dict[str, Any] | None = None
    is_default: bool | None = None
    refresh_interval_seconds: int | None = Field(default=None, ge=10, le=86400)
    cross_filter_enabled: bool | None = None


class DashboardRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str = ""
    owner_user_id: UUID | None = None
    scope: str = "personal"
    role_ref: str | None = None
    project_id: UUID | None = None
    layout_json: dict[str, Any] = Field(default_factory=dict)
    is_default: bool = False
    refresh_interval_seconds: int = 300
    cross_filter_enabled: bool = False
    created_at: datetime
    updated_at: datetime


# ── Widget ─────────────────────────────────────────────────────────────


class WidgetCreate(BaseModel):
    dashboard_id: UUID
    widget_type: str = "kpi_card"
    kpi_code: str | None = None
    config_json: dict[str, Any] = Field(default_factory=dict)
    position_x: int = 0
    position_y: int = 0
    width: int = Field(default=3, ge=1, le=12)
    height: int = Field(default=2, ge=1, le=12)
    order_seq: int = 0
    drill_path: dict[str, Any] | None = None


class WidgetUpdate(BaseModel):
    widget_type: str | None = None
    kpi_code: str | None = None
    config_json: dict[str, Any] | None = None
    position_x: int | None = None
    position_y: int | None = None
    width: int | None = Field(default=None, ge=1, le=12)
    height: int | None = Field(default=None, ge=1, le=12)
    order_seq: int | None = None
    drill_path: dict[str, Any] | None = None


class WidgetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    dashboard_id: UUID
    widget_type: str
    kpi_code: str | None = None
    config_json: dict[str, Any] = Field(default_factory=dict)
    position_x: int = 0
    position_y: int = 0
    width: int = 3
    height: int = 2
    order_seq: int = 0
    drill_path: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class WidgetRenderResult(BaseModel):
    widget: WidgetRead
    value: Decimal | None = None
    unit: str | None = None
    breakdown: dict[str, Any] = Field(default_factory=dict)
    from_cache: bool = False


class DashboardRenderResponse(BaseModel):
    dashboard: DashboardRead
    widgets: list[WidgetRenderResult]
    rendered_at: datetime


# ── Report ─────────────────────────────────────────────────────────────


class ReportDefinitionCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    source_modules: list[str] = Field(default_factory=list)
    query_spec_json: dict[str, Any] = Field(default_factory=dict)
    output_format: str = "pdf"
    template_ref: str | None = None
    scope: str = "personal"
    project_id: UUID | None = None


class ReportDefinitionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    source_modules: list[str] | None = None
    query_spec_json: dict[str, Any] | None = None
    output_format: str | None = None
    template_ref: str | None = None
    scope: str | None = None
    project_id: UUID | None = None


class ReportDefinitionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    description: str = ""
    owner_user_id: UUID | None = None
    source_modules: list[str] = Field(default_factory=list)
    query_spec_json: dict[str, Any] = Field(default_factory=dict)
    output_format: str = "pdf"
    template_ref: str | None = None
    scope: str = "personal"
    project_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class ReportRunResponse(BaseModel):
    report_id: UUID
    file_url: str | None = None
    rows: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    output_format: str
    generated_at: datetime


# ── Report Schedule ────────────────────────────────────────────────────


class ReportScheduleCreate(BaseModel):
    report_definition_id: UUID
    frequency: str = "daily"
    day_of_week: int | None = Field(default=None, ge=0, le=6)
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    time_of_day: str = Field(default="08:00", pattern=r"^\d{2}:\d{2}$")
    timezone: str = "UTC"
    recipients_json: list[dict[str, Any]] = Field(default_factory=list)
    enabled: bool = True
    filter_overrides_json: dict[str, Any] = Field(default_factory=dict)
    project_id: UUID | None = None


class ReportScheduleUpdate(BaseModel):
    frequency: str | None = None
    day_of_week: int | None = Field(default=None, ge=0, le=6)
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    time_of_day: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    timezone: str | None = None
    recipients_json: list[dict[str, Any]] | None = None
    enabled: bool | None = None
    filter_overrides_json: dict[str, Any] | None = None
    project_id: UUID | None = None


class ReportScheduleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    report_definition_id: UUID
    frequency: str
    day_of_week: int | None = None
    day_of_month: int | None = None
    time_of_day: str
    timezone: str
    recipients_json: list[dict[str, Any]] = Field(default_factory=list)
    enabled: bool
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    filter_overrides_json: dict[str, Any] = Field(default_factory=dict)
    project_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


# ── Alert Rule ─────────────────────────────────────────────────────────


class AlertRuleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    kpi_code: str = Field(..., min_length=1, max_length=64)
    condition: str = "below"
    threshold_value: Decimal = Decimal("0")
    threshold_unit: str | None = None
    severity: str = "warning"
    scope_project_id: UUID | None = None
    recipients_json: list[dict[str, Any]] = Field(default_factory=list)
    channels_json: list[str] = Field(default_factory=lambda: ["in_app"])
    throttle_seconds: int = Field(default=3600, ge=0)
    enabled: bool = True
    expression_json: dict[str, Any] = Field(default_factory=dict)


class AlertRuleUpdate(BaseModel):
    name: str | None = None
    condition: str | None = None
    threshold_value: Decimal | None = None
    threshold_unit: str | None = None
    severity: str | None = None
    scope_project_id: UUID | None = None
    recipients_json: list[dict[str, Any]] | None = None
    channels_json: list[str] | None = None
    throttle_seconds: int | None = Field(default=None, ge=0)
    enabled: bool | None = None
    expression_json: dict[str, Any] | None = None


class AlertRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    kpi_code: str
    condition: str
    threshold_value: Decimal
    threshold_unit: str | None = None
    severity: str
    scope_project_id: UUID | None = None
    recipients_json: list[dict[str, Any]] = Field(default_factory=list)
    channels_json: list[str] = Field(default_factory=list)
    throttle_seconds: int = 3600
    last_triggered_at: datetime | None = None
    enabled: bool = True
    expression_json: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


# ── Saved Filter ───────────────────────────────────────────────────────


class SavedFilterCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    scope: str = "personal"
    module: str = Field(..., min_length=1, max_length=64)
    filter_json: dict[str, Any] = Field(default_factory=dict)
    is_default: bool = False
    shared_with_user_ids: list[UUID] = Field(default_factory=list)
    project_id: UUID | None = None


class SavedFilterShareRequest(BaseModel):
    user_ids: list[UUID] = Field(..., min_length=1)


class SavedFilterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    owner_user_id: UUID | None = None
    scope: str
    module: str
    filter_json: dict[str, Any] = Field(default_factory=dict)
    is_default: bool = False
    shared_with_user_ids_json: list[Any] = Field(default_factory=list)
    project_id: UUID | None = None
    created_at: datetime


# ── KPI History / drill-down ───────────────────────────────────────────


class KPIHistoryPoint(BaseModel):
    period_start: date
    period_end: date
    value: Decimal
    unit: str
    source_record_count: int = 0


class KPIHistoryResponse(BaseModel):
    kpi_code: str
    history: list[KPIHistoryPoint] = Field(default_factory=list)


class DrillDownRequest(BaseModel):
    project_id: UUID | None = None
    period_start: date | None = None
    period_end: date | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    depth: int = Field(default=1, ge=1, le=5)
    limit: int = Field(default=100, ge=1, le=1000)


class DrillDownResponse(BaseModel):
    kpi_code: str
    records: list[dict[str, Any]] = Field(default_factory=list)
    record_count: int = 0
    aggregate_value: Decimal | None = None
    aggregate_unit: str | None = None


# ── Cross-filter evaluate (Wave 4 / T11) ───────────────────────────────


class DashboardEvaluateRequest(BaseModel):
    """Request body for ``POST /dashboards/{id}/evaluate``.

    ``filters`` is a free-form dict of ``{field_name: value}`` pairs the
    caller would like every widget on the dashboard to be scoped by.
    Unknown keys are ignored gracefully (each KPI defines its own
    compatible filter fields). When the dashboard's
    ``cross_filter_enabled`` flag is False the dict is ignored entirely.
    """

    filters: dict[str, Any] = Field(default_factory=dict)


class WidgetEvaluateResult(BaseModel):
    id: UUID
    kpi_code: str | None = None
    widget_type: str
    value: Decimal | None = None
    unit: str | None = None
    series: list[dict[str, Any]] = Field(default_factory=list)
    drill_path: dict[str, Any] | None = None
    breakdown: dict[str, Any] = Field(default_factory=dict)


class DashboardEvaluateResponse(BaseModel):
    dashboard_id: UUID
    cross_filter_enabled: bool
    applied_filters: dict[str, Any] = Field(default_factory=dict)
    widgets: list[WidgetEvaluateResult] = Field(default_factory=list)
    evaluated_at: datetime


class ReportRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    report_definition_id: UUID
    schedule_id: UUID | None = None
    triggered_by_user_id: UUID | None = None
    started_at: datetime
    finished_at: datetime | None = None
    output_format: str
    file_size_bytes: int
    row_count: int
    status: str
    error_message: str | None = None


# ── Cross-project performance benchmark ────────────────────────────────


#: The statistics a benchmark may lead with; see ``performance.headline``.
BENCHMARK_STATISTICS: tuple[str, ...] = ("weighted", "mean", "median")
#: Who sees a benchmark set: its owner only, or everyone who reads KPIs.
BENCHMARK_SET_SCOPES: tuple[str, ...] = ("personal", "shared")

_MAX_COHORT_VALUES = 50
_MAX_ROW_FILTERS = 10


def _clean_values(value: list[str]) -> list[str]:
    """Trim, drop blanks and duplicates, keep order; refuse an over-long value."""
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if not text:
            continue
        if len(text) > 255:
            raise ValueError("a filter value is at most 255 characters")
        if text not in out:
            out.append(text)
    return out


def _check_name(value: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError("name must not be blank")
    return text


def _check_choice(value: str, allowed: tuple[str, ...], name: str) -> str:
    if value not in allowed:
        raise ValueError(f"{name} must be one of {', '.join(allowed)}")
    return value


def _check_kpis(value: list[str]) -> list[str]:
    out = _clean_values(value)
    if not out:
        raise ValueError("name at least one KPI")
    if any(len(k) > 100 for k in out):
        raise ValueError("a KPI id is at most 100 characters")
    return out


class BenchmarkCohort(BaseModel):
    """Which projects and which rows a benchmark reads.

    Every list narrows: a project must be in ``project_ids`` (when given) AND
    have one of the ``clients`` AND one of the ``regions`` AND one of the
    ``project_types``. ``row_filters`` are whitelisted KPI filters a row must
    pass, typically ``{"field": "classification.din276", "op": "eq",
    "value": "330"}``; they are checked against each KPI's entity when the set
    is saved. The result is always intersected with the projects the reader
    may open.
    """

    model_config = ConfigDict(extra="forbid")

    project_ids: list[UUID] = Field(default_factory=list, max_length=500)
    clients: list[str] = Field(default_factory=list, max_length=_MAX_COHORT_VALUES)
    regions: list[str] = Field(default_factory=list, max_length=_MAX_COHORT_VALUES)
    project_types: list[str] = Field(default_factory=list, max_length=_MAX_COHORT_VALUES)
    row_filters: list[dict[str, Any]] = Field(default_factory=list, max_length=_MAX_ROW_FILTERS)
    period_start: date | None = None
    period_end: date | None = None

    @field_validator("project_ids")
    @classmethod
    def _dedupe(cls, value: list[UUID]) -> list[UUID]:
        return list(dict.fromkeys(value))

    @field_validator("clients", "regions", "project_types")
    @classmethod
    def _clean(cls, value: list[str]) -> list[str]:
        return _clean_values(value)

    @model_validator(mode="after")
    def _period_in_order(self) -> BenchmarkCohort:
        if self.period_start and self.period_end and self.period_start > self.period_end:
            raise ValueError("period_start must not be after period_end")
        return self


class PerformanceBenchmarkRequest(BenchmarkCohort):
    """One KPI, read per project over a cohort.

    Exactly one of ``kpi`` (a preset id or a stored custom KPI code) and
    ``spec`` (a whitelisted spec, validated like ``POST /kpis``). An empty
    ``project_ids`` means every project the caller can open, narrowed by the
    other cohort filters.

    ``convert_units`` merges readings in compatible units (m2 and ft2) into
    one group and lists each conversion; off, every unit is its own group.
    ``min_projects`` and ``min_records`` mark a group with less evidence as
    not a reliable benchmark; ``statistic`` picks the figure each group leads
    with.
    """

    kpi: str | None = Field(default=None, min_length=1, max_length=100)
    spec: dict[str, Any] | None = None
    convert_units: bool = False
    min_projects: int = Field(default=0, ge=0, le=500)
    min_records: int = Field(default=0, ge=0, le=1_000_000)
    statistic: str = "weighted"

    @field_validator("statistic")
    @classmethod
    def _known_statistic(cls, value: str) -> str:
        return _check_choice(value, BENCHMARK_STATISTICS, "statistic")

    @model_validator(mode="after")
    def _one_kpi(self) -> PerformanceBenchmarkRequest:
        if (self.kpi is None) == (self.spec is None):
            raise ValueError("name exactly one of 'kpi' or 'spec'")
        return self


class PerformanceProjectRow(BaseModel):
    project_id: UUID
    value: Decimal | None
    numerator: Decimal | None = None
    denominator: Decimal | None = None
    records: int = 0
    unavailable_reason: str | None = None
    #: Units this project's rows were converted from to land in the group.
    converted_from: list[str] = Field(default_factory=list)


class PerformanceBenchmarkFigures(BaseModel):
    #: Ratio of the summed numerators to the summed denominators for a ratio
    #: or weighted average; record-weighted mean for an average; ``None``
    #: with a reason for a sum, count, min or max.
    weighted: Decimal | None
    weighted_unavailable_reason: str | None = None
    #: Arithmetic mean of the per-project values: every project counts once.
    mean: Decimal | None = None
    median: Decimal | None
    p25: Decimal | None
    p75: Decimal | None
    min: Decimal | None
    max: Decimal | None


class PerformanceEvidence(BaseModel):
    projects_with_data: int
    projects_with_value: int
    records: int
    records_with_value: int = 0


class PerformanceConversion(BaseModel):
    """``1 from_unit = factor to_unit``, applied to land rows in this group."""

    from_unit: str
    to_unit: str
    factor: Decimal


class PerformanceGroup(BaseModel):
    key: str
    dimensions: dict[str, str | None]
    rows: list[PerformanceProjectRow]
    benchmark: PerformanceBenchmarkFigures
    evidence: PerformanceEvidence
    #: Projects with a value in this group over projects selected.
    coverage: Decimal
    conversions: list[PerformanceConversion] = Field(default_factory=list)
    #: The figure this group leads with, and which statistic it is. The
    #: statistic can differ from the one asked for when that one does not
    #: exist for the KPI (a sum has no weighted figure); the label follows
    #: what was delivered.
    headline: Decimal | None = None
    headline_statistic: str = "weighted"
    #: False when the group misses ``min_projects`` or ``min_records``; the
    #: figures are still served, but are not to be read as a benchmark.
    sufficient: bool = True
    shortfall: list[str] = Field(default_factory=list)


class PerformanceProjectLabel(BaseModel):
    project_id: UUID
    name: str
    currency: str


class PerformanceBenchmarkResponse(BaseModel):
    kpi: str | None
    spec: dict[str, Any]
    aggregation: str
    projects_selected: int
    projects: list[PerformanceProjectLabel]
    groups: list[PerformanceGroup]
    convert_units: bool = False
    min_projects: int = 0
    min_records: int = 0
    statistic: str = "weighted"


class PerformancePreset(BaseModel):
    key: str
    spec: dict[str, Any]


class PerformanceCohortOptions(BaseModel):
    """Filter values present on the projects the caller may open."""

    clients: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    project_types: list[str] = Field(default_factory=list)


class BenchmarkSetBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=4000)
    scope: str = "personal"
    kpis: list[str] = Field(..., min_length=1, max_length=8)
    cohort: BenchmarkCohort = Field(default_factory=BenchmarkCohort)
    statistic: str = "weighted"
    min_projects: int = Field(default=3, ge=0, le=500)
    min_records: int = Field(default=0, ge=0, le=1_000_000)
    convert_units: bool = True

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _check_name(value)

    @field_validator("scope")
    @classmethod
    def _scope(cls, value: str) -> str:
        return _check_choice(value, BENCHMARK_SET_SCOPES, "scope")

    @field_validator("statistic")
    @classmethod
    def _statistic(cls, value: str) -> str:
        return _check_choice(value, BENCHMARK_STATISTICS, "statistic")

    @field_validator("kpis")
    @classmethod
    def _kpis(cls, value: list[str]) -> list[str]:
        return _check_kpis(value)


class BenchmarkSetCreate(BenchmarkSetBase):
    """A new benchmark set. Its KPIs and row filters are checked on save."""


class BenchmarkSetUpdate(BaseModel):
    """A partial edit; only the owner may make it."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    scope: str | None = None
    kpis: list[str] | None = Field(default=None, min_length=1, max_length=8)
    cohort: BenchmarkCohort | None = None
    statistic: str | None = None
    min_projects: int | None = Field(default=None, ge=0, le=500)
    min_records: int | None = Field(default=None, ge=0, le=1_000_000)
    convert_units: bool | None = None

    @model_validator(mode="after")
    def _same_rules(self) -> BenchmarkSetUpdate:
        # One rule set for create and edit: re-run the base validators on
        # whatever this edit carries.
        if self.name is not None:
            self.name = _check_name(self.name)
        if self.scope is not None:
            _check_choice(self.scope, BENCHMARK_SET_SCOPES, "scope")
        if self.statistic is not None:
            _check_choice(self.statistic, BENCHMARK_STATISTICS, "statistic")
        if self.kpis is not None:
            self.kpis = _check_kpis(self.kpis)
        return self


class BenchmarkSetRead(BaseModel):
    id: UUID
    name: str
    description: str
    owner_user_id: UUID | None = None
    scope: str
    kpis: list[str]
    cohort: BenchmarkCohort
    statistic: str
    min_projects: int
    min_records: int
    convert_units: bool
    #: Whether the caller may edit or delete it.
    is_owner: bool = False
    created_at: datetime
    updated_at: datetime


class BenchmarkSetPage(BaseModel):
    """One page of the benchmark sets a caller sees, ordered by name."""

    items: list[BenchmarkSetRead]
    total: int
    offset: int
    limit: int


class BenchmarkSetEvaluateRequest(BaseModel):
    """Which of the set's KPIs to read; the first when omitted."""

    model_config = ConfigDict(extra="forbid")

    kpi: str | None = Field(default=None, min_length=1, max_length=100)


class PerformanceCheckRequest(BaseModel):
    """Where an estimate sits against a benchmark set's history.

    Either a ``value`` in ``unit`` and ``currency`` typed by the estimator,
    or a ``boq_position_id`` whose own estimate is read (its unit rate, or
    the labour hours per unit of its resource split). Nothing is written.
    """

    model_config = ConfigDict(extra="forbid")

    kpi: str | None = Field(default=None, min_length=1, max_length=100)
    value: Decimal | None = Field(default=None, gt=0, max_digits=24, decimal_places=8)
    unit: str | None = Field(default=None, max_length=30)
    currency: str | None = Field(default=None, max_length=10)
    boq_position_id: UUID | None = None

    @model_validator(mode="after")
    def _one_source(self) -> PerformanceCheckRequest:
        if (self.value is None) == (self.boq_position_id is None):
            raise ValueError("give exactly one of 'value' or 'boq_position_id'")
        return self


class PerformanceAdHocCheckRequest(PerformanceBenchmarkRequest):
    """A check against a cohort described in the request rather than a saved set.

    Same cohort, KPI and reading options as ``POST /performance/benchmark``,
    plus the estimate: a ``value`` in ``unit`` and ``currency``, or a
    ``boq_position_id``. Nothing is written.
    """

    value: Decimal | None = Field(default=None, gt=0, max_digits=24, decimal_places=8)
    unit: str | None = Field(default=None, max_length=30)
    currency: str | None = Field(default=None, max_length=10)
    boq_position_id: UUID | None = None

    @model_validator(mode="after")
    def _one_source(self) -> PerformanceAdHocCheckRequest:
        if (self.value is None) == (self.boq_position_id is None):
            raise ValueError("give exactly one of 'value' or 'boq_position_id'")
        return self


class PerformanceCheckResponse(BaseModel):
    """A suggestion for a person to weigh; nothing was changed by it.

    ``status`` is ``ok`` or why there is no reading (``no_comparable_group``,
    ``kpi_not_per_unit``, ``no_estimate_value``). ``value`` is the estimate in
    the group's unit, ``input_value`` and ``input_unit`` what was checked, and
    ``unit_factor`` the conversion between them when one was applied.
    """

    kpi: str
    status: str
    input_value: Decimal | None = None
    input_unit: str | None = None
    input_currency: str | None = None
    value: Decimal | None = None
    unit_factor: Decimal | None = None
    group: PerformanceGroup | None = None
    headline: Decimal | None = None
    statistic: str | None = None
    variance: Decimal | None = None
    percentile_rank: Decimal | None = None
    band: str | None = None
    confidence: str | None = None
    shortfall: list[str] = Field(default_factory=list)


__all__ = [
    "ALERT_CHANNELS",
    "ALERT_CONDITIONS",
    "ALERT_SEVERITIES",
    "AlertRuleCreate",
    "AlertRuleRead",
    "AlertRuleUpdate",
    "DASHBOARD_SCOPES",
    "DashboardCreate",
    "DashboardEvaluateRequest",
    "DashboardEvaluateResponse",
    "DashboardRead",
    "DashboardRenderResponse",
    "DashboardUpdate",
    "DrillDownRequest",
    "DrillDownResponse",
    "KPIComputeRequest",
    "KPIComputeResponse",
    "KPIDefinitionCreate",
    "KPIDefinitionRead",
    "KPIHistoryPoint",
    "KPIHistoryResponse",
    "KPI_AGGREGATIONS",
    "KPI_CATEGORIES",
    "KPI_UNITS",
    "OUTPUT_FORMATS",
    "BENCHMARK_SET_SCOPES",
    "BENCHMARK_STATISTICS",
    "BenchmarkCohort",
    "BenchmarkSetCreate",
    "BenchmarkSetEvaluateRequest",
    "BenchmarkSetPage",
    "BenchmarkSetRead",
    "BenchmarkSetUpdate",
    "PerformanceAdHocCheckRequest",
    "PerformanceBenchmarkFigures",
    "PerformanceBenchmarkRequest",
    "PerformanceBenchmarkResponse",
    "PerformanceCheckRequest",
    "PerformanceCheckResponse",
    "PerformanceCohortOptions",
    "PerformanceConversion",
    "PerformanceEvidence",
    "PerformanceGroup",
    "PerformancePreset",
    "PerformanceProjectLabel",
    "PerformanceProjectRow",
    "REPORT_FREQUENCIES",
    "REPORT_SCOPES",
    "ReportDefinitionCreate",
    "ReportDefinitionRead",
    "ReportDefinitionUpdate",
    "ReportRunResponse",
    "ReportScheduleCreate",
    "ReportScheduleRead",
    "ReportScheduleUpdate",
    "SavedFilterCreate",
    "SavedFilterRead",
    "WIDGET_TYPES",
    "WidgetCreate",
    "WidgetEvaluateResult",
    "WidgetRead",
    "WidgetRenderResult",
    "WidgetUpdate",
]
