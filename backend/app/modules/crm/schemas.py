"""‌⁠‍CRM Pydantic schemas — request/response models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── PipelineStage ─────────────────────────────────────────────────────────


class PipelineStageCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=255)
    display_order: int = Field(default=0, ge=0)
    default_probability_percent: int = Field(default=0, ge=0, le=100)
    is_final: bool = False
    is_won: bool = False
    is_lost: bool = False
    color: str = Field(default="", max_length=16)


class PipelineStageUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=255)
    display_order: int | None = Field(default=None, ge=0)
    default_probability_percent: int | None = Field(default=None, ge=0, le=100)
    is_final: bool | None = None
    is_won: bool | None = None
    is_lost: bool | None = None
    color: str | None = Field(default=None, max_length=16)


class PipelineStageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    display_order: int
    default_probability_percent: int
    is_final: bool
    is_won: bool
    is_lost: bool
    color: str
    created_at: datetime
    updated_at: datetime


# ── WinLossReason ─────────────────────────────────────────────────────────


class WinLossReasonCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(..., min_length=1, max_length=64)
    label: str = Field(..., min_length=1, max_length=255)
    category: str = Field(
        default="other",
        pattern=r"^(price|timing|relationship|scope|competitor|other)$",
    )
    is_win_reason: bool = False
    is_loss_reason: bool = True


class WinLossReasonUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    label: str | None = Field(default=None, max_length=255)
    category: str | None = Field(
        default=None,
        pattern=r"^(price|timing|relationship|scope|competitor|other)$",
    )
    is_win_reason: bool | None = None
    is_loss_reason: bool | None = None


class WinLossReasonResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    label: str
    category: str
    is_win_reason: bool
    is_loss_reason: bool
    created_at: datetime
    updated_at: datetime


# ── Account ───────────────────────────────────────────────────────────────


class AccountCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255)
    industry: str | None = Field(default=None, max_length=128)
    size_category: str = Field(default="sme", pattern=r"^(sme|mid|enterprise)$")
    country: str | None = Field(default=None, max_length=64)
    website: str | None = Field(default=None, max_length=500)
    primary_contact_id: UUID | None = None
    description: str = Field(default="", max_length=10000)
    status: str = Field(default="active", pattern=r"^(active|dormant|lost)$")
    owner_user_id: UUID | None = None
    tags: list[str] = Field(default_factory=list)


class AccountUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=255)
    industry: str | None = Field(default=None, max_length=128)
    size_category: str | None = Field(default=None, pattern=r"^(sme|mid|enterprise)$")
    country: str | None = Field(default=None, max_length=64)
    website: str | None = Field(default=None, max_length=500)
    primary_contact_id: UUID | None = None
    description: str | None = Field(default=None, max_length=10000)
    status: str | None = Field(default=None, pattern=r"^(active|dormant|lost)$")
    owner_user_id: UUID | None = None
    tags: list[str] | None = None


class AccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    industry: str | None
    size_category: str
    country: str | None
    website: str | None
    primary_contact_id: UUID | None
    description: str
    status: str
    owner_user_id: UUID | None
    tags: list[str]
    created_at: datetime
    updated_at: datetime


# ── Lead ──────────────────────────────────────────────────────────────────


class LeadCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    account_id: UUID | None = None
    contact_name: str = Field(..., min_length=1, max_length=255)
    contact_email: str | None = Field(default=None, max_length=255)
    contact_phone: str | None = Field(default=None, max_length=64)
    source: str = Field(
        default="inbound",
        pattern=r"^(web|referral|event|cold_outreach|inbound)$",
    )
    status: str = Field(
        default="new",
        pattern=r"^(new|qualifying|qualified|disqualified|converted)$",
    )
    assigned_to: UUID | None = None
    qualification_notes: str = Field(default="", max_length=10000)


class LeadUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    account_id: UUID | None = None
    contact_name: str | None = Field(default=None, max_length=255)
    contact_email: str | None = Field(default=None, max_length=255)
    contact_phone: str | None = Field(default=None, max_length=64)
    source: str | None = Field(
        default=None,
        pattern=r"^(web|referral|event|cold_outreach|inbound)$",
    )
    status: str | None = Field(
        default=None,
        pattern=r"^(new|qualifying|qualified|disqualified|converted)$",
    )
    assigned_to: UUID | None = None
    qualification_notes: str | None = Field(default=None, max_length=10000)


class LeadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    account_id: UUID | None
    contact_name: str
    contact_email: str | None
    contact_phone: str | None
    source: str
    status: str
    assigned_to: UUID | None
    qualification_notes: str
    qualified_at: str | None
    converted_at: str | None
    converted_opportunity_id: UUID | None
    created_at: datetime
    updated_at: datetime


class LeadQualifyRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    qualification_notes: str = Field(default="", max_length=10000)


class LeadConvertRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    account_id: UUID
    title: str = Field(..., min_length=1, max_length=500)
    estimated_value: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str = Field(default="", max_length=8)
    expected_close_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    stage_id: UUID
    probability_percent: int = Field(default=0, ge=0, le=100)
    description: str = Field(default="", max_length=10000)


# ── Opportunity ───────────────────────────────────────────────────────────


class OpportunityCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    account_id: UUID
    title: str = Field(..., min_length=1, max_length=500)
    description: str = Field(default="", max_length=10000)
    estimated_value: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str = Field(default="", max_length=8)
    expected_close_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    probability_percent: int = Field(default=0, ge=0, le=100)
    stage_id: UUID
    source: str = Field(
        default="inbound",
        pattern=r"^(web|referral|event|cold_outreach|inbound)$",
    )
    owner_user_id: UUID | None = None
    status: str = Field(
        default="open",
        pattern=r"^(open|won|lost|abandoned)$",
    )
    notes: str = Field(default="", max_length=20000)
    primary_contact_id: UUID | None = None
    project_id: UUID | None = None
    competitor_names: list[str] = Field(default_factory=list)


class OpportunityUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=10000)
    estimated_value: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=8)
    expected_close_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    probability_percent: int | None = Field(default=None, ge=0, le=100)
    stage_id: UUID | None = None
    source: str | None = Field(
        default=None,
        pattern=r"^(web|referral|event|cold_outreach|inbound)$",
    )
    owner_user_id: UUID | None = None
    status: str | None = Field(
        default=None,
        pattern=r"^(open|won|lost|abandoned)$",
    )
    notes: str | None = Field(default=None, max_length=20000)
    primary_contact_id: UUID | None = None
    project_id: UUID | None = None
    competitor_names: list[str] | None = None


class OpportunityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    account_id: UUID
    title: str
    description: str
    estimated_value: Decimal
    currency: str
    expected_close_date: str | None
    probability_percent: int
    stage_id: UUID
    weighted_value: Decimal
    source: str
    owner_user_id: UUID | None
    status: str
    won_at: str | None
    lost_at: str | None
    lost_reason_code: str | None
    notes: str
    primary_contact_id: UUID | None
    project_id: UUID | None
    competitor_names: list[str]
    created_at: datetime
    updated_at: datetime


class OpportunityMoveStageRequest(BaseModel):
    to_stage_id: UUID
    override_probability_percent: int | None = Field(default=None, ge=0, le=100)


class OpportunityWinRequest(BaseModel):
    won_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    win_reason_code: str | None = Field(default=None, max_length=64)


class OpportunityLoseRequest(BaseModel):
    lost_reason_code: str = Field(..., min_length=1, max_length=64)
    lost_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


# ── Activity ──────────────────────────────────────────────────────────────


class ActivityCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    owner_user_id: UUID | None = None
    account_id: UUID | None = None
    opportunity_id: UUID | None = None
    lead_id: UUID | None = None
    kind: str = Field(
        default="note",
        pattern=r"^(call|meeting|email|task|note)$",
    )
    subject: str = Field(default="", max_length=500)
    body: str = Field(default="", max_length=20000)
    due_at: str | None = Field(default=None, max_length=40)
    completed_at: str | None = Field(default=None, max_length=40)
    outcome: str | None = Field(
        default=None,
        pattern=r"^(no_answer|voicemail|positive|negative|neutral)$",
    )
    external_calendar_event_id: str | None = Field(default=None, max_length=255)


class ActivityUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    kind: str | None = Field(default=None, pattern=r"^(call|meeting|email|task|note)$")
    subject: str | None = Field(default=None, max_length=500)
    body: str | None = Field(default=None, max_length=20000)
    due_at: str | None = Field(default=None, max_length=40)
    completed_at: str | None = Field(default=None, max_length=40)
    outcome: str | None = Field(
        default=None,
        pattern=r"^(no_answer|voicemail|positive|negative|neutral)$",
    )
    external_calendar_event_id: str | None = Field(default=None, max_length=255)


class ActivityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_user_id: UUID | None
    account_id: UUID | None
    opportunity_id: UUID | None
    lead_id: UUID | None
    kind: str
    subject: str
    body: str
    due_at: str | None
    completed_at: str | None
    outcome: str | None
    external_calendar_event_id: str | None
    created_at: datetime
    updated_at: datetime


# ── Forecast ──────────────────────────────────────────────────────────────


class ForecastResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    period: str
    owner_user_id: UUID | None
    pipeline_value: Decimal
    weighted_value: Decimal
    won_value: Decimal
    committed_value: Decimal
    computed_at: str | None
    created_at: datetime
    updated_at: datetime


# ── Aggregates / dashboard ───────────────────────────────────────────────


class PipelineMetricsResponse(BaseModel):
    open_count: int = 0
    weighted_value: Decimal = Decimal("0")
    total_value: Decimal = Decimal("0")
    by_stage: dict[str, dict[str, Any]] = Field(default_factory=dict)
    win_rate_30d: Decimal = Decimal("0")


class KanbanColumnResponse(BaseModel):
    stage_id: UUID
    code: str
    name: str
    display_order: int
    color: str
    opportunities: list[OpportunityResponse] = Field(default_factory=list)


class KanbanBoardResponse(BaseModel):
    columns: list[KanbanColumnResponse] = Field(default_factory=list)


class WinLossAnalyticsResponse(BaseModel):
    period_start: str | None = None
    period_end: str | None = None
    won_count: int = 0
    lost_count: int = 0
    abandoned_count: int = 0
    win_rate: Decimal = Decimal("0")
    average_sales_cycle_days: int = 0
    lost_reasons_breakdown: dict[str, int] = Field(default_factory=dict)
    won_value: Decimal = Decimal("0")
    lost_value: Decimal = Decimal("0")


class CrmDashboardResponse(BaseModel):
    open_opportunities: int = 0
    weighted_value: Decimal = Decimal("0")
    pipeline_value: Decimal = Decimal("0")
    leads_open: int = 0
    activities_due_soon: int = 0
    win_rate_30d: Decimal = Decimal("0")
    by_stage: dict[str, dict[str, Any]] = Field(default_factory=dict)


class StageHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    opportunity_id: UUID
    from_stage_id: UUID | None
    to_stage_id: UUID
    changed_at: str | None
    changed_by: UUID | None
    duration_in_previous_seconds: int | None
    created_at: datetime
