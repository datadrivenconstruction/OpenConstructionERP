"""Reporting & Dashboards Pydantic schemas — request/response models."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── KPI Snapshot schemas ─────────────────────────────────────────────────


class KPISnapshotCreate(BaseModel):
    """Create a new KPI snapshot for a project."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    snapshot_date: str = Field(..., max_length=20, description="ISO date string (YYYY-MM-DD)")
    cpi: str | None = Field(default=None, max_length=20)
    spi: str | None = Field(default=None, max_length=20)
    budget_consumed_pct: str | None = Field(default=None, max_length=20)
    open_defects: int = 0
    open_observations: int = 0
    schedule_progress_pct: str | None = Field(default=None, max_length=20)
    open_rfis: int = 0
    open_submittals: int = 0
    risk_score_avg: str | None = Field(default=None, max_length=20)
    metadata: dict[str, Any] = Field(default_factory=dict)


class KPISnapshotResponse(BaseModel):
    """KPI snapshot returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    snapshot_date: str
    cpi: str | None = None
    spi: str | None = None
    budget_consumed_pct: str | None = None
    open_defects: int = 0
    open_observations: int = 0
    schedule_progress_pct: str | None = None
    open_rfis: int = 0
    open_submittals: int = 0
    risk_score_avg: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Report Template schemas ──────────────────────────────────────────────


class ReportTemplateCreate(BaseModel):
    """Create a custom report template."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255)
    name_translations: dict[str, str] | None = None
    report_type: str = Field(
        ...,
        pattern=r"^(project_status|cost_report|schedule_status|safety_report|inspection_report|portfolio_summary)$",
    )
    description: str | None = None
    template_data: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReportTemplateResponse(BaseModel):
    """Report template returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    name: str
    name_translations: dict[str, str] | None = None
    report_type: str
    description: str | None = None
    template_data: dict[str, Any] = Field(default_factory=dict)
    is_system: bool = False
    created_by: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    # Schedule fields (v2.3.0)
    schedule_cron: str | None = None
    recipients: list[str] = Field(default_factory=list)
    is_scheduled: bool = False
    last_run_at: str | None = None
    next_run_at: str | None = None
    project_id_scope: UUID | None = None
    created_at: datetime
    updated_at: datetime


# ── Schedule Request / Response (v2.3.0) ────────────────────────────────


class ReportScheduleRequest(BaseModel):
    """Turn a template into a scheduled report.

    Passing ``schedule_cron=None`` turns scheduling off without clearing
    the recipient list — the worker then skips the template on its
    next-due scan.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    schedule_cron: str | None = Field(
        default=None,
        max_length=100,
        description="5-field POSIX cron expression (e.g. '0 9 * * 1' for 09:00 every Mon)",
    )
    recipients: list[str] = Field(
        default_factory=list,
        description="Email addresses or user IDs that receive the rendered report",
    )
    project_id_scope: UUID | None = Field(
        default=None,
        description="Scope the report to one project; None = portfolio-wide",
    )
    is_scheduled: bool = Field(
        default=True,
        description="Pass False to pause without clearing the cron expression",
    )


# ── Generated Report schemas ─────────────────────────────────────────────


class GenerateReportRequest(BaseModel):
    """Request to generate a report."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    template_id: UUID | None = None
    report_type: str = Field(
        ...,
        pattern=r"^(project_status|cost_report|schedule_status|safety_report|inspection_report|portfolio_summary)$",
    )
    title: str = Field(..., min_length=1, max_length=500)
    format: str = Field(
        default="pdf",
        pattern=r"^(pdf|excel|html)$",
    )
    data_snapshot: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GeneratedReportResponse(BaseModel):
    """Generated report returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    template_id: UUID | None = None
    report_type: str
    title: str
    generated_at: str
    generated_by: UUID | None = None
    format: str = "pdf"
    storage_key: str | None = None
    data_snapshot: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime
