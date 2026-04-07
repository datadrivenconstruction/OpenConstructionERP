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
    created_at: datetime
    updated_at: datetime


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
