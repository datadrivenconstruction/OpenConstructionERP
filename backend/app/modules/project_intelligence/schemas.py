"""Pydantic schemas for Project Intelligence API requests and responses."""

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
