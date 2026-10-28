# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pydantic schemas for Project Intelligence API requests and responses."""

from typing import Any

from pydantic import BaseModel, Field

# ── Domain state schemas ───────────────────────────────────────────────────


class BOQStateResponse(BaseModel):
    exists: bool = False
    total_items: int = 0
    items_with_zero_price: int = 0
    items_with_zero_quantity: int = 0
    sections_count: int = 0
    resources_linked: int = 0
    resources_total: int = 0
    last_modified: str | None = None
    validation_errors: int = 0
    export_ready: bool = False
    completion_pct: float = 0.0
    # Scope-drift metric: count of priced leaf positions ("position_count")
    # versus the captured scope baseline ("baseline_position_count"). The
    # Estimation Dashboard's Scope-coverage widget reads these directly; the
    # field names are kept stable for that contract.
    position_count: int = 0
    baseline_position_count: int = 0
    baseline_source: str = "none"  # "metadata" | "snapshot" | "current" | "none"


class ScheduleStateResponse(BaseModel):
    exists: bool = False
    activities_count: int = 0
    linked_to_boq: bool = False
    has_critical_path: bool = False
    baseline_set: bool = False
    duration_days: int | None = None
    start_date: str | None = None
    end_date: str | None = None
    completion_pct: float = 0.0
    # Real progress signals for the dashboard Schedule-health KPI. Both are
    # 0..100. ``baseline_adherence_pct`` is the share of activities tracking
    # on or ahead of their planned (time-elapsed) progress; ``progress_pct``
    # is the mean actual percent-complete across activities. The KPI card
    # reads these field names directly.
    progress_pct: float = 0.0
    baseline_adherence_pct: float = 0.0


class TakeoffStateResponse(BaseModel):
    files_uploaded: int = 0
    files_processed: int = 0
    formats: list[str] = Field(default_factory=list)
    quantities_extracted: int = 0
    linked_to_boq: bool = False
    completion_pct: float = 0.0


class ValidationStateResponse(BaseModel):
    last_run: str | None = None
    total_errors: int = 0
    critical_errors: int = 0
    warnings: int = 0
    passed_rules: int = 0
    total_rules: int = 0
    completion_pct: float = 0.0
    # Stable aliases consumed by the dashboard's Real-time validation widget.
    # They mirror the canonical fields above (rules_passed == passed_rules,
    # rules_total == total_rules, errors == critical_errors) so the widget
    # renders the real last-validation report instead of falling back to
    # anomaly-derived counts.
    rules_passed: int = 0
    rules_total: int = 0
    errors: int = 0


class RiskStateResponse(BaseModel):
    register_exists: bool = False
    total_risks: int = 0
    high_severity_unmitigated: int = 0
    contingency_set: bool = False
    completion_pct: float = 0.0


class TenderingStateResponse(BaseModel):
    bid_packages: int = 0
    bids_received: int = 0
    bids_compared: bool = False
    completion_pct: float = 0.0


class DocumentsStateResponse(BaseModel):
    total_files: int = 0
    categories_covered: list[str] = Field(default_factory=list)
    completion_pct: float = 0.0


class ReportsStateResponse(BaseModel):
    reports_generated: int = 0
    last_report: str | None = None
    completion_pct: float = 0.0


class CostModelStateResponse(BaseModel):
    budget_set: bool = False
    baseline_exists: bool = False
    actuals_linked: bool = False
    earned_value_active: bool = False
    completion_pct: float = 0.0
    forecast_eac: str | None = None
    forecast_vac: str | None = None
    forecast_alert_active: bool = False


# ── Full state response ───────────────────────────────────────────────────


class ProjectStateResponse(BaseModel):
    project_id: str = ""
    project_type: str = ""
    project_name: str = ""
    region: str = ""
    standard: str = ""
    currency: str = ""
    created_at: str = ""
    collected_at: str = ""

    boq: BOQStateResponse = Field(default_factory=BOQStateResponse)
    schedule: ScheduleStateResponse = Field(default_factory=ScheduleStateResponse)
    takeoff: TakeoffStateResponse = Field(default_factory=TakeoffStateResponse)
    validation: ValidationStateResponse = Field(default_factory=ValidationStateResponse)
    risk: RiskStateResponse = Field(default_factory=RiskStateResponse)
    tendering: TenderingStateResponse = Field(default_factory=TenderingStateResponse)
    documents: DocumentsStateResponse = Field(default_factory=DocumentsStateResponse)
    reports: ReportsStateResponse = Field(default_factory=ReportsStateResponse)
    cost_model: CostModelStateResponse = Field(default_factory=CostModelStateResponse)


# ── Score response ─────────────────────────────────────────────────────────


class CriticalGapResponse(BaseModel):
    id: str
    domain: str
    severity: str
    title: str
    description: str
    impact: str
    action_id: str | None = None
    affected_count: int | None = None


class AchievementResponse(BaseModel):
    domain: str
    title: str
    description: str


class ProjectScoreResponse(BaseModel):
    overall: float = 0.0
    overall_grade: str = "F"
    domain_scores: dict[str, float] = Field(default_factory=dict)
    critical_gaps: list[CriticalGapResponse] = Field(default_factory=list)
    achievements: list[AchievementResponse] = Field(default_factory=list)


# ── Combined summary ──────────────────────────────────────────────────────


class ProjectSummaryResponse(BaseModel):
    state: ProjectStateResponse
    score: ProjectScoreResponse


# ── Recommendation request ────────────────────────────────────────────────


class RecommendationRequest(BaseModel):
    role: str = "estimator"
    language: str = "en"


class ChatRequest(BaseModel):
    question: str
    role: str = "estimator"
    language: str = "en"


class ExplainGapRequest(BaseModel):
    gap_id: str
    language: str = "en"


# ── Action response ───────────────────────────────────────────────────────


class ActionResponse(BaseModel):
    success: bool
    message: str
    redirect_url: str | None = None
    data: dict[str, Any] | None = None


class ActionDefinitionResponse(BaseModel):
    id: str
    label: str
    description: str
    icon: str
    requires_confirmation: bool = False
    confirmation_message: str = ""
    navigate_to: str | None = None
    has_backend_action: bool = False


class ScopeBaselineResponse(BaseModel):
    """Result of capturing the current BOQ scope as the project baseline."""

    project_id: str
    baseline_position_count: int
    captured_at: str


# ── Forecast alerts (TOP-30 #19) ──────────────────────────────────────────


class ForecastSnapshotPoint(BaseModel):
    """A single EVM snapshot point for the SPI/CPI/EAC sparklines."""

    date: str
    spi: float = 0.0
    cpi: float = 0.0
    eac: float = 0.0
    ev: float = 0.0
    ac: float = 0.0


class ForecastAlertRow(BaseModel):
    """A forecast row carrying an active (triggered/snoozed) alert."""

    forecast_id: str
    forecast_date: str
    alert_status: str
    triggered_at: str | None = None
    snoozed_until: str | None = None
    severity: str = "warning"
    eac: str = "0"
    vac: str = "0"
    tcpi: str = "0"
    summary: str = ""


class LatestForecast(BaseModel):
    """The most recent forecast for a project, with the EVM inputs."""

    forecast_id: str
    forecast_date: str
    method: str = "cpi"
    etc: str = "0"
    eac: str = "0"
    vac: str = "0"
    tcpi: str = "0"
    bac: str = "0"
    spi: str = "0"
    cpi: str = "0"
    eac_over_bac: float = 0.0
    alert_status: str | None = None


class ForecastsResponse(BaseModel):
    """Payload for the Forecasts tab: latest forecast + alerts + sparklines."""

    project_id: str
    currency: str = ""
    latest_forecast: LatestForecast | None = None
    active_alerts: list[ForecastAlertRow] = Field(default_factory=list)
    sparkline: list[ForecastSnapshotPoint] = Field(default_factory=list)


class SnoozeForecastRequest(BaseModel):
    """Snooze a forecast alert for a number of hours (1-720, default 24)."""

    hours: int = Field(default=24, ge=1, le=720)


# ── Predictive forecast analytics (TOP-30 #19) ────────────────────────────
#
# These power GET /{project_id}/forecast - the live, read-only predictive
# cost + schedule + risk analytics. Distinct from the persisted-forecast
# alert surface above (ForecastsResponse), which reads stored EVMForecast
# rows. This one recomputes the canonical EVM math live, never writing.


class CostForecastResponse(BaseModel):
    """Earned-value cost forecast (CPI/SPI/EAC/ETC/VAC/TCPI)."""

    available: bool = False
    reason: str | None = None
    currency: str = ""
    snapshot_date: str | None = None
    bac: str | None = None
    ev: str | None = None
    ac: str | None = None
    pv: str | None = None
    cpi: float | None = None
    spi: float | None = None
    eac: str | None = None
    etc: str | None = None
    vac: str | None = None
    tcpi: str | None = None
    eac_over_bac: float | None = None


class ScheduleSlipResponse(BaseModel):
    """Forward projection of the schedule finish-date variance."""

    available: bool = False
    reason: str | None = None
    activities_total: int = 0
    activities_complete: int = 0
    planned_pct_complete: float | None = None
    actual_pct_complete: float | None = None
    baseline_finish: str | None = None
    forecast_finish: str | None = None
    finish_variance_days: int | None = None
    at_risk_task_count: int = 0


class CostOverrunRiskResponse(BaseModel):
    """Deterministic cost-overrun risk score with confidence + rationale."""

    score: float = 0.0
    band: str = "green"
    confidence: float = 0.0
    rationale: list[str] = Field(default_factory=list)


class ProjectForecastResponse(BaseModel):
    """Full predictive-analytics payload for a project (forecast - review required)."""

    project_id: str = ""
    project_name: str = ""
    currency: str = ""
    generated_at: str = ""
    cost: CostForecastResponse = Field(default_factory=CostForecastResponse)
    schedule: ScheduleSlipResponse = Field(default_factory=ScheduleSlipResponse)
    risk: CostOverrunRiskResponse = Field(default_factory=CostOverrunRiskResponse)
    review_required: bool = True
