"""Pydantic schemas for the dashboard rollup endpoint.

Each widget has its own concrete shape so the OpenAPI doc is useful, but
the top-level response (``RollupResponse``) keys are dynamic — only the
widgets the caller asked for are populated. Unrequested widgets are
absent (not ``None``) so the frontend can use ``in`` to detect coverage.

All money fields ship as **strings**, never floats, per CLAUDE.md §10:
JS ``Number`` loses precision on currency values > 2^53, and ``orjson``
defaults can stringify-without-rounding nondeterministically.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Widget(BaseModel):
    """Common base — allow extra so we can extend payloads without re-shipping schemas."""

    model_config = ConfigDict(extra="allow")


class BOQByProject(BaseModel):
    project_id: str
    project_name: str
    boq_count: int
    total_value: str = Field(description="Decimal-as-string in project currency.")
    currency: str
    position_count: int
    positions_missing_quantity: int
    positions_zero_price: int


class LastBOQRef(BaseModel):
    """Most-recently-edited BOQ across the caller's projects.

    Powers the "Continue your work" tile + KpiRibbon active-estimates count
    without per-project ``/v1/boq/boqs/`` fan-out.
    """

    id: str
    name: str
    project_id: str
    project_name: str
    currency: str
    status: str | None
    updated_at: str
    position_count: int
    grand_total: str  # Decimal-as-string


class BOQSummaryPayload(_Widget):
    total_boqs: int
    active_boqs: int = Field(
        default=0,
        description=("BOQs whose status is NOT in archived/closed/cancelled/rejected."),
    )
    total_value_eur: str = Field(description="Sum across all projects, **EUR equivalent** as Decimal string.")
    position_count: int
    positions_missing_quantity: int
    positions_zero_price: int
    last_boq: LastBOQRef | None = None
    by_project: list[BOQByProject]


class ValidationByProject(BaseModel):
    project_id: str
    project_name: str
    avg_score: float | None
    passed: int
    warnings: int
    errors: int


class ValidationScorePayload(_Widget):
    avg: float | None = Field(description="Mean of latest-per-project scores (0.0-1.0), None when no reports.")
    passed: int
    warnings: int
    errors: int
    by_project: list[ValidationByProject]


class ClashByProject(BaseModel):
    project_id: str
    project_name: str
    total: int
    open: int
    high: int
    medium: int
    low: int


class ClashHealthPayload(_Widget):
    total: int
    open: int
    high: int
    medium: int
    low: int
    pct_resolved: int
    by_project: list[ClashByProject]


class CriticalTaskItem(BaseModel):
    id: str
    name: str
    project_id: str
    project_name: str
    start_date: str | None
    end_date: str | None
    status: str | None
    is_critical: bool
    total_float: int | None


class ScheduleCriticalPayload(_Widget):
    total_schedules: int = Field(
        default=0,
        description="Total schedule rows across the caller's accessible projects.",
    )
    top: list[CriticalTaskItem]


class RiskItem(BaseModel):
    id: str
    project_id: str
    project_name: str
    title: str
    score: float
    probability: float
    impact_severity: str
    status: str | None


class RiskTopPayload(_Widget):
    top: list[RiskItem]


class HSEByProject(BaseModel):
    project_id: str
    project_name: str
    total: int
    last_30d: int
    near_miss: int
    recordables: int
    days_since_last: int | None


class HSEScorecardPayload(_Widget):
    total: int
    last_30d: int
    near_miss: int
    recordables: int
    days_since_last: int | None
    by_project: list[HSEByProject]


class ProcurementPipelinePayload(_Widget):
    rfqs_pending: int
    pos_issued: int
    pos_received: int


class BudgetByProject(BaseModel):
    project_id: str
    project_name: str
    currency: str
    planned: str  # Decimal-as-string
    actual: str
    variance: str
    pct: int  # percent over (positive) / under (negative)


class BudgetVariancePayload(_Widget):
    over_budget_count: int
    top_over: list[BudgetByProject]


class ChangeOrderItem(BaseModel):
    id: str
    project_id: str
    project_name: str
    code: str | None
    title: str | None
    status: str | None
    cost_impact: str  # Decimal-as-string
    currency: str


class ChangeOrdersPayload(_Widget):
    open_count: int
    total_impact: str  # Decimal-as-string
    currency: str
    top_pending: list[ChangeOrderItem]


class WeatherSitePayload(_Widget):
    project_id: str | None
    project_name: str | None
    city: str | None
    temperature_c: float | None
    conditions: str | None
    source: str | None


# ── Project-detail widget payloads (W23 P0) ──────────────────────────────────
#
# These widgets live on /projects/:id. The rollup endpoint accepts them as
# additional widget keys + a ``project_ids=<id>`` filter, so the frontend
# can replace ~8 parallel per-widget useQuery calls with a single rollup.
# Money fields ship as Decimal strings, same as the wave-2 widgets above.


class ProjectRFIItem(BaseModel):
    id: str
    number: str | None
    subject: str
    status: str
    created_at: str | None = None
    due_date: str | None = None


class ProjectRFIInboxPayload(_Widget):
    items: list[ProjectRFIItem]


class ProjectChangeOrdersPulsePayload(_Widget):
    open_count: int
    pending_count: int
    approved_count: int
    total_value: str
    approved_value: str
    currency: str


class ProjectDiaryItem(BaseModel):
    """Single diary header — shape matches the widget's ``DiaryItem``.

    ``weather_summary`` is a JSONB dict server-side; the widget already
    has a ``formatWeatherSummary`` helper that handles both shapes, so
    we pass the dict through untouched.
    """

    id: str
    diary_date: str | None
    status: str | None
    weather_summary: dict | str | None = None
    manpower_total: int | None = None
    narrative: str | None = None


class ProjectDailyDiaryPayload(_Widget):
    items: list[ProjectDiaryItem]


class ProjectHSEItem(BaseModel):
    id: str
    status: str | None
    severity: str | None


class ProjectHSEIncidentsPayload(_Widget):
    total: int
    high: int
    medium: int
    low: int
    items: list[ProjectHSEItem]


class ProjectVariationItem(BaseModel):
    id: str
    status: str | None
    estimated_value: str  # Decimal-as-string
    disputed: bool


class ProjectVariationsPayload(_Widget):
    open: int
    disputed_value: str  # Decimal-as-string
    currency: str
    items: list[ProjectVariationItem]


class ProjectNCRItem(BaseModel):
    id: str
    status: str | None
    severity: str | None


class ProjectQualityNCRPayload(_Widget):
    open: int
    major: int
    minor: int
    items: list[ProjectNCRItem]


class ProjectComplianceItem(BaseModel):
    id: str
    status: str | None
    expires_at: str | None
    doc_type: str | None


class ProjectComplianceSummaryPayload(_Widget):
    active: int
    expiring: int
    expired: int
    items: list[ProjectComplianceItem]


class ProjectBudgetBurnPayload(_Widget):
    planned_total: str  # Decimal-as-string
    actual_total: str  # Decimal-as-string
    currency: str
    # Per-period series omitted in v1 (kept on the schema so the widget's
    # sparkline glue keeps working when a future endpoint fills it in).
    series: list[dict] = Field(default_factory=list)


class RollupResponse(BaseModel):
    """Top-level rollup response.

    Only requested widget keys are populated. Each value is the
    matching widget payload above (or omitted if the caller didn't
    request it / no data was available).
    """

    # We keep this as an open dict so widgets can be added without
    # touching the schema. OpenAPI doc references concrete payloads
    # for the typed widgets above so frontend type generation still
    # picks them up.
    model_config = ConfigDict(extra="allow")

    boq_summary: BOQSummaryPayload | None = None
    validation_score: ValidationScorePayload | None = None
    clash_health: ClashHealthPayload | None = None
    schedule_critical: ScheduleCriticalPayload | None = None
    risk_top: RiskTopPayload | None = None
    hse_scorecard: HSEScorecardPayload | None = None
    procurement_pipeline: ProcurementPipelinePayload | None = None
    budget_variance: BudgetVariancePayload | None = None
    change_orders: ChangeOrdersPayload | None = None
    weather_site: WeatherSitePayload | None = None

    # Project-detail widgets (W23 P0).
    project_rfi_inbox: ProjectRFIInboxPayload | None = None
    project_change_orders_pulse: ProjectChangeOrdersPulsePayload | None = None
    project_daily_diary: ProjectDailyDiaryPayload | None = None
    project_hse_incidents: ProjectHSEIncidentsPayload | None = None
    project_variations: ProjectVariationsPayload | None = None
    project_quality_ncr: ProjectQualityNCRPayload | None = None
    project_compliance_summary: ProjectComplianceSummaryPayload | None = None
    project_budget_burn: ProjectBudgetBurnPayload | None = None

    # Cache metadata — populated by the router so the frontend can
    # display a "last refreshed Xs ago" stamp without round-tripping
    # headers through React Query's transport layer.
    generated_at: str = Field(description="ISO-8601 timestamp.")
    widgets_requested: list[str] = Field(default_factory=list)
    project_count: int = 0


# ── Widget-config request schemas (used by POST /rollup with body) ─────────
#
# The legacy ``GET /rollup/?widgets=…`` query-string flow takes a flat list
# of widget ids with no per-widget overrides. The richer config-aware path
# accepts a list of ``WidgetConfigItem``s instead so the caller can ask for,
# e.g., ``{"widget_id": "boq_summary", "config": {"max_by_project": 25}}``.
#
# The 422-path is enforced here in Pydantic (rather than in the router) so
# the OpenAPI schema documents which keys + value bounds are accepted per
# widget. The error messages match the patterns ``tests/unit/test_dashboard_
# rollup.py::TestWidgetConfigValidation`` checks.

# Map widget_id → ``{config_key: (type, min, max)}``. ``type`` is the
# Python type the value must coerce to; ``min`` / ``max`` are inclusive
# bounds (``None`` to skip the bound).
_WIDGET_CONFIG_SPEC: dict[str, dict[str, tuple[type, Any, Any]]] = {
    "boq_summary": {
        "show_last_boq": (bool, None, None),
        "max_by_project": (int, 1, 500),
    },
    "validation_score": {
        "target_score": (float, 0.0, 1.0),
    },
    "clash_health": {},
    "schedule_critical": {
        "lookahead_days": (int, 1, 365),
    },
    "risk_top": {
        "limit": (int, 1, 100),
    },
    "hse_scorecard": {},
    "procurement_pipeline": {},
    "budget_variance": {},
    "change_orders": {
        "limit": (int, 1, 100),
    },
    "weather_site": {},
}

_KNOWN_CONFIG_WIDGETS: frozenset[str] = frozenset(_WIDGET_CONFIG_SPEC)


class WidgetConfigItem(BaseModel):
    """One ``(widget_id, config)`` pair from a config-aware rollup request.

    Validates two layers:
      * ``widget_id`` is one of the known configurable widgets (10 of them).
      * Every key in ``config`` is allowed for that widget, with the right
        type and within the documented bounds. Unknown keys reject — we
        don't silently drop them because that has historically caused
        silent regressions when a config key was renamed.
    """

    widget_id: str
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("widget_id")
    @classmethod
    def _validate_widget_id(cls, v: str) -> str:
        if v not in _KNOWN_CONFIG_WIDGETS:
            allowed = ", ".join(sorted(_KNOWN_CONFIG_WIDGETS))
            raise ValueError(f"Unknown widget_id {v!r}. Allowed: {allowed}")
        return v

    @field_validator("config")
    @classmethod
    def _validate_config(cls, v: dict[str, Any], info: Any) -> dict[str, Any]:
        widget_id = info.data.get("widget_id")
        if widget_id is None or widget_id not in _WIDGET_CONFIG_SPEC:
            # widget_id either failed its own validation or is unknown;
            # leave the config alone and let the widget_id error surface.
            return v
        spec = _WIDGET_CONFIG_SPEC[widget_id]
        if not v:
            # Empty config is always valid — no per-widget defaults to apply.
            return v
        for key, value in v.items():
            if key not in spec:
                allowed = ", ".join(sorted(spec)) or "(none)"
                raise ValueError(f"Unknown config key {key!r} for widget_id={widget_id!r}. Allowed: {allowed}")
            expected_type, lo, hi = spec[key]
            # bool is a subclass of int in Python, so check it first.
            if expected_type is bool:
                if not isinstance(value, bool):
                    raise ValueError(f"Config value for {widget_id!r}.{key!r} must be bool")
                continue
            if expected_type is int:
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ValueError(f"Config value for {widget_id!r}.{key!r} must be int")
                if lo is not None and hi is not None and not (lo <= value <= hi):
                    raise ValueError(f"Config value for {widget_id!r}.{key!r} must be between {lo} and {hi}")
                continue
            if expected_type is float:
                if isinstance(value, bool) or not isinstance(value, int | float):
                    raise ValueError(f"Config value for {widget_id!r}.{key!r} must be float")
                fval = float(value)
                if lo is not None and hi is not None and not (lo <= fval <= hi):
                    raise ValueError(f"Config value for {widget_id!r}.{key!r} must be between {lo} and {hi}")
                continue
        return v


class RollupRequest(BaseModel):
    """Config-aware rollup request body (POST flavour).

    Accepts a list of ``WidgetConfigItem``s instead of a CSV string of
    widget ids. The GET endpoint stays the canonical "fast path"; this
    request body is reserved for callers that need per-widget overrides
    (e.g. the dashboard customisation panel).
    """

    widget_configs: list[WidgetConfigItem] = Field(default_factory=list)
    project_ids: list[str] | None = None


__all__ = [
    "BOQByProject",
    "BOQSummaryPayload",
    "BudgetByProject",
    "BudgetVariancePayload",
    "ChangeOrderItem",
    "ChangeOrdersPayload",
    "ClashByProject",
    "ClashHealthPayload",
    "CriticalTaskItem",
    "HSEByProject",
    "HSEScorecardPayload",
    "LastBOQRef",
    "ProcurementPipelinePayload",
    "ProjectBudgetBurnPayload",
    "ProjectChangeOrdersPulsePayload",
    "ProjectComplianceItem",
    "ProjectComplianceSummaryPayload",
    "ProjectDailyDiaryPayload",
    "ProjectDiaryItem",
    "ProjectHSEIncidentsPayload",
    "ProjectHSEItem",
    "ProjectNCRItem",
    "ProjectQualityNCRPayload",
    "ProjectRFIInboxPayload",
    "ProjectRFIItem",
    "ProjectVariationItem",
    "ProjectVariationsPayload",
    "RiskItem",
    "RiskTopPayload",
    "RollupRequest",
    "RollupResponse",
    "ScheduleCriticalPayload",
    "ValidationByProject",
    "ValidationScorePayload",
    "WeatherSitePayload",
    "WidgetConfigItem",
]
