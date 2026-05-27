# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Pydantic v2 schemas for the BI Dashboards module."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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
    created_at: datetime
    updated_at: datetime


class KPIDefinitionCreate(BaseModel):
    code: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    formula_ref: str = Field(..., min_length=1, max_length=128)
    source_modules: list[str] = Field(default_factory=list)
    unit: str = "ratio"
    target_default: Decimal | None = None
    aggregation: str = "last"
    category: str = "operational"
    is_system: bool = False


class KPIComputeRequest(BaseModel):
    kpi_code: str | None = None  # path param wins; body version optional
    project_id: UUID | None = None
    period_start: date | None = None
    period_end: date | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    persist: bool = False


class KPIComputeResponse(BaseModel):
    kpi_code: str
    value: Decimal
    unit: str
    source_record_count: int = 0
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


class ReportDefinitionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    source_modules: list[str] | None = None
    query_spec_json: dict[str, Any] | None = None
    output_format: str | None = None
    template_ref: str | None = None
    scope: str | None = None


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


class ReportScheduleUpdate(BaseModel):
    frequency: str | None = None
    day_of_week: int | None = Field(default=None, ge=0, le=6)
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    time_of_day: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    timezone: str | None = None
    recipients_json: list[dict[str, Any]] | None = None
    enabled: bool | None = None
    filter_overrides_json: dict[str, Any] | None = None


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
