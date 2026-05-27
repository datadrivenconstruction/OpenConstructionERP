"""‌⁠‍Bid Management Pydantic schemas — request/response models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── BidPackage ────────────────────────────────────────────────────────────

_PACKAGE_STATUS = r"^(draft|published|open|closed|cancelled|awarded)$"
_CONFIDENTIALITY = r"^(public|limited|confidential)$"
_INVITATION_STATUS = r"^(pending|sent|opened|submitted|declined|expired)$"
_BIDDER_STATUS = r"^(active|disqualified|withdrawn)$"
_REJECTION_CODE = r"^(price|scope|completeness|qualification|other)$"


class BidPackageCreate(BaseModel):
    """‌⁠‍Create a new bid package."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    tender_id: UUID | None = None
    code: str = Field(..., min_length=1, max_length=64)
    title: str = Field(default="", max_length=500)
    scope_description: str = ""
    instructions_to_bidders: str = ""
    submission_deadline: str | None = Field(default=None, max_length=40)
    decision_due_by: str | None = Field(default=None, max_length=40)
    currency: str = Field(default="", max_length=10)
    total_budget_estimate: Decimal = Decimal("0")
    status: str = Field(default="draft", pattern=_PACKAGE_STATUS)
    confidentiality_level: str = Field(default="limited", pattern=_CONFIDENTIALITY)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BidPackageUpdate(BaseModel):
    """‌⁠‍Partial update for a bid package."""

    model_config = ConfigDict(str_strip_whitespace=True)

    tender_id: UUID | None = None
    title: str | None = Field(default=None, max_length=500)
    scope_description: str | None = None
    instructions_to_bidders: str | None = None
    submission_deadline: str | None = Field(default=None, max_length=40)
    decision_due_by: str | None = Field(default=None, max_length=40)
    currency: str | None = Field(default=None, max_length=10)
    total_budget_estimate: Decimal | None = None
    status: str | None = Field(default=None, pattern=_PACKAGE_STATUS)
    confidentiality_level: str | None = Field(default=None, pattern=_CONFIDENTIALITY)
    metadata: dict[str, Any] | None = None


class BidPackageResponse(BaseModel):
    """Bid package returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    tender_id: UUID | None = None
    code: str
    title: str = ""
    scope_description: str = ""
    instructions_to_bidders: str = ""
    submission_deadline: str | None = None
    decision_due_by: str | None = None
    currency: str = ""
    total_budget_estimate: Decimal = Decimal("0")
    status: str = "draft"
    confidentiality_level: str = "limited"
    published_at: str | None = None
    closed_at: str | None = None
    awarded_at: str | None = None
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── BidPackageLineItem ───────────────────────────────────────────────────


class BidPackageLineItemCreate(BaseModel):
    """Create a scope line within a package."""

    model_config = ConfigDict(str_strip_whitespace=True)

    package_id: UUID
    code: str = Field(default="", max_length=64)
    description: str = ""
    unit: str = Field(default="", max_length=20)
    quantity: Decimal = Decimal("0")
    alternative_allowed: bool = False
    order_index: int = 0
    parent_line_id: UUID | None = None
    spec_attachment_url: str | None = Field(default=None, max_length=1024)
    is_mandatory: bool = True


class BidPackageLineItemUpdate(BaseModel):
    """Partial update for a scope line."""

    model_config = ConfigDict(str_strip_whitespace=True)

    code: str | None = Field(default=None, max_length=64)
    description: str | None = None
    unit: str | None = Field(default=None, max_length=20)
    quantity: Decimal | None = None
    alternative_allowed: bool | None = None
    order_index: int | None = None
    parent_line_id: UUID | None = None
    spec_attachment_url: str | None = Field(default=None, max_length=1024)
    is_mandatory: bool | None = None


class BidPackageLineItemResponse(BaseModel):
    """Scope line returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    package_id: UUID
    code: str = ""
    description: str = ""
    unit: str = ""
    quantity: Decimal = Decimal("0")
    alternative_allowed: bool = False
    order_index: int = 0
    parent_line_id: UUID | None = None
    spec_attachment_url: str | None = None
    is_mandatory: bool = True
    created_at: datetime
    updated_at: datetime


class BidPackageLineItemBulkCreate(BaseModel):
    """Bulk-create lines."""

    items: list[BidPackageLineItemCreate] = Field(default_factory=list)


# ── BidInvitation ────────────────────────────────────────────────────────


class BidInvitationCreate(BaseModel):
    """Create an invitation."""

    model_config = ConfigDict(str_strip_whitespace=True)

    package_id: UUID
    bidder_ref_id: UUID | None = None
    invitee_email: str = Field(..., min_length=1, max_length=255)
    invitee_company_name: str = Field(default="", max_length=255)
    status: str = Field(default="pending", pattern=_INVITATION_STATUS)


class BidInvitationUpdate(BaseModel):
    """Partial update for an invitation."""

    model_config = ConfigDict(str_strip_whitespace=True)

    invitee_email: str | None = Field(default=None, max_length=255)
    invitee_company_name: str | None = Field(default=None, max_length=255)
    status: str | None = Field(default=None, pattern=_INVITATION_STATUS)
    decline_reason: str | None = None


class BidInvitationResponse(BaseModel):
    """Invitation returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    package_id: UUID
    bidder_ref_id: UUID | None = None
    invitee_email: str = ""
    invitee_company_name: str = ""
    sent_at: str | None = None
    opened_at: str | None = None
    submission_received_at: str | None = None
    declined_at: str | None = None
    decline_reason: str | None = None
    status: str = "pending"
    # token_hash is intentionally excluded — it is a server-side secret
    # used to authenticate magic-link bidder access and must never be
    # returned to API callers (including owner roles).
    created_at: datetime
    updated_at: datetime


# ── Bidder ───────────────────────────────────────────────────────────────


class BidderCreate(BaseModel):
    """Create a bidder record."""

    model_config = ConfigDict(str_strip_whitespace=True)

    package_id: UUID
    company_name: str = Field(..., min_length=1, max_length=255)
    contact_name: str = Field(default="", max_length=255)
    contact_email: str = Field(default="", max_length=255)
    contact_phone: str = Field(default="", max_length=64)
    country: str = Field(default="", max_length=64)
    status: str = Field(default="active", pattern=_BIDDER_STATUS)
    notes: str = ""


class BidderUpdate(BaseModel):
    """Partial update for a bidder."""

    model_config = ConfigDict(str_strip_whitespace=True)

    company_name: str | None = Field(default=None, max_length=255)
    contact_name: str | None = Field(default=None, max_length=255)
    contact_email: str | None = Field(default=None, max_length=255)
    contact_phone: str | None = Field(default=None, max_length=64)
    country: str | None = Field(default=None, max_length=64)
    status: str | None = Field(default=None, pattern=_BIDDER_STATUS)
    notes: str | None = None
    disqualification_reason: str | None = None


class BidderResponse(BaseModel):
    """Bidder returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    package_id: UUID
    company_name: str
    contact_name: str = ""
    contact_email: str = ""
    contact_phone: str = ""
    country: str = ""
    status: str = "active"
    disqualification_reason: str | None = None
    notes: str = ""
    created_at: datetime
    updated_at: datetime


class BidderDisqualify(BaseModel):
    """Disqualify a bidder."""

    model_config = ConfigDict(str_strip_whitespace=True)

    reason: str = Field(..., min_length=1)


# ── BidSubmission ────────────────────────────────────────────────────────


class BidSubmissionCreate(BaseModel):
    """Create a submission envelope."""

    model_config = ConfigDict(str_strip_whitespace=True)

    invitation_id: UUID
    bidder_id: UUID
    submitted_at: str | None = Field(default=None, max_length=40)
    total_amount: Decimal = Decimal("0")
    currency: str = Field(default="", max_length=10)
    notes_to_owner: str = ""
    exclusions: list[str] = Field(default_factory=list)
    qualifications: list[str] = Field(default_factory=list)
    envelope_payload: dict[str, Any] = Field(default_factory=dict)


class BidSubmissionUpdate(BaseModel):
    """Partial update."""

    model_config = ConfigDict(str_strip_whitespace=True)

    submitted_at: str | None = Field(default=None, max_length=40)
    total_amount: Decimal | None = None
    currency: str | None = Field(default=None, max_length=10)
    notes_to_owner: str | None = None
    exclusions: list[str] | None = None
    qualifications: list[str] | None = None
    envelope_payload: dict[str, Any] | None = None


class BidSubmissionResponse(BaseModel):
    """Submission returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    invitation_id: UUID
    bidder_id: UUID
    submitted_at: str | None = None
    total_amount: Decimal = Decimal("0")
    currency: str = ""
    completeness_score: Decimal = Decimal("0")
    notes_to_owner: str = ""
    exclusions: list[Any] = Field(default_factory=list)
    qualifications: list[Any] = Field(default_factory=list)
    is_valid: bool = False
    open_after_deadline: bool = False
    envelope_payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


# ── BidSubmissionLine ────────────────────────────────────────────────────


_INCLUSION_STATUS = r"^(included|excluded|clarification_needed|alternative|noted)$"


class BidSubmissionLineCreate(BaseModel):
    """Create a priced line within a submission."""

    model_config = ConfigDict(str_strip_whitespace=True)

    submission_id: UUID
    line_item_id: UUID
    unit_price: Decimal = Decimal("0")
    quantity_priced: Decimal = Decimal("0")
    alternative_offered: bool = False
    alternative_description: str = ""
    comment: str = ""
    inclusion_status: str = Field(default="included", pattern=_INCLUSION_STATUS)
    prevailing_wage_applicable: bool = False


class BidSubmissionLineUpdate(BaseModel):
    """Partial update for a priced line."""

    model_config = ConfigDict(str_strip_whitespace=True)

    unit_price: Decimal | None = None
    quantity_priced: Decimal | None = None
    alternative_offered: bool | None = None
    alternative_description: str | None = None
    comment: str | None = None
    inclusion_status: str | None = Field(default=None, pattern=_INCLUSION_STATUS)
    prevailing_wage_applicable: bool | None = None


class BidSubmissionLineResponse(BaseModel):
    """Priced line returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    submission_id: UUID
    line_item_id: UUID
    unit_price: Decimal = Decimal("0")
    quantity_priced: Decimal = Decimal("0")
    total_price: Decimal = Decimal("0")
    alternative_offered: bool = False
    alternative_description: str = ""
    comment: str = ""
    inclusion_status: str = "included"
    prevailing_wage_applicable: bool = False
    created_at: datetime
    updated_at: datetime


class BidSubmissionLineBulkCreate(BaseModel):
    """Bulk-create priced lines."""

    items: list[BidSubmissionLineCreate] = Field(default_factory=list)


# ── BidQA ────────────────────────────────────────────────────────────────


class BidQACreate(BaseModel):
    """Ask a question on a package."""

    model_config = ConfigDict(str_strip_whitespace=True)

    package_id: UUID
    bidder_id: UUID | None = None
    question: str = Field(..., min_length=1)
    asked_at: str | None = Field(default=None, max_length=40)
    asked_by_email: str = Field(default="", max_length=255)
    is_public: bool = False
    visible_to_bidder_ids: list[str] = Field(default_factory=list)


class BidQAAnswer(BaseModel):
    """Answer a question."""

    model_config = ConfigDict(str_strip_whitespace=True)

    answer: str = Field(..., min_length=1)
    answered_by: str | None = Field(default=None, max_length=36)
    is_public: bool | None = None
    visible_to_bidder_ids: list[str] | None = None


class BidQAUpdate(BaseModel):
    """Partial update for a Q&A."""

    model_config = ConfigDict(str_strip_whitespace=True)

    question: str | None = None
    answer: str | None = None
    is_public: bool | None = None
    visible_to_bidder_ids: list[str] | None = None


class BidQAResponse(BaseModel):
    """Q&A returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    package_id: UUID
    bidder_id: UUID | None = None
    question: str = ""
    asked_at: str | None = None
    asked_by_email: str = ""
    answer: str = ""
    answered_at: str | None = None
    answered_by: str | None = None
    is_public: bool = False
    visible_to_bidder_ids: list[Any] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


# ── BidComparison / BidLeveling ──────────────────────────────────────────


class BidComparisonCreate(BaseModel):
    """Create a comparison header."""

    model_config = ConfigDict(str_strip_whitespace=True)

    package_id: UUID
    technical_scoring_rule: dict[str, Any] = Field(default_factory=dict)
    commercial_weight_pct: int = Field(default=100, ge=0, le=100)
    technical_weight_pct: int = Field(default=0, ge=0, le=100)


class BidComparisonUpdate(BaseModel):
    """Partial update for a comparison."""

    model_config = ConfigDict(str_strip_whitespace=True)

    technical_scoring_rule: dict[str, Any] | None = None
    commercial_weight_pct: int | None = Field(default=None, ge=0, le=100)
    technical_weight_pct: int | None = Field(default=None, ge=0, le=100)
    recommended_bidder_id: UUID | None = None
    recommended_reason: str | None = None


class BidComparisonResponse(BaseModel):
    """Comparison returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    package_id: UUID
    computed_at: str | None = None
    normalized_low: Decimal = Decimal("0")
    normalized_high: Decimal = Decimal("0")
    technical_scoring_rule: dict[str, Any] = Field(default_factory=dict)
    commercial_weight_pct: int = 100
    technical_weight_pct: int = 0
    recommended_bidder_id: UUID | None = None
    recommended_reason: str = ""
    created_at: datetime
    updated_at: datetime


class BidLevelingResponse(BaseModel):
    """Leveling row returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    comparison_id: UUID
    bidder_id: UUID
    raw_total: Decimal = Decimal("0")
    normalized_total: Decimal = Decimal("0")
    commercial_score: Decimal = Decimal("0")
    technical_score: Decimal = Decimal("0")
    total_score: Decimal = Decimal("0")
    rank: int = 0
    manual_adjustment: Decimal = Decimal("0")
    manual_adjustment_reason: str = ""
    created_at: datetime
    updated_at: datetime


class LevelingTableResponse(BaseModel):
    """Computed leveling table for a comparison."""

    comparison_id: UUID
    package_id: UUID
    computed_at: str | None = None
    rows: list[BidLevelingResponse] = Field(default_factory=list)
    recommended_bidder_id: UUID | None = None
    recommended_reason: str = ""


# ── BidAward / BidRejection ──────────────────────────────────────────────


class BidAwardCreate(BaseModel):
    """Create an award record."""

    model_config = ConfigDict(str_strip_whitespace=True)

    package_id: UUID
    awarded_bidder_id: UUID
    awarded_amount: Decimal = Decimal("0")
    currency: str = Field(default="", max_length=10)
    decision_summary: str = ""
    decision_signed_by: str | None = Field(default=None, max_length=36)
    decision_signed_at: str | None = Field(default=None, max_length=40)
    contract_template_ref: str = Field(default="", max_length=255)


class BidAwardUpdate(BaseModel):
    """Partial update for an award."""

    model_config = ConfigDict(str_strip_whitespace=True)

    awarded_amount: Decimal | None = None
    currency: str | None = Field(default=None, max_length=10)
    decision_summary: str | None = None
    decision_signed_by: str | None = Field(default=None, max_length=36)
    decision_signed_at: str | None = Field(default=None, max_length=40)
    contract_template_ref: str | None = Field(default=None, max_length=255)
    notified_others_at: str | None = Field(default=None, max_length=40)


class BidAwardResponse(BaseModel):
    """Award returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    package_id: UUID
    awarded_bidder_id: UUID
    awarded_amount: Decimal = Decimal("0")
    currency: str = ""
    decision_summary: str = ""
    decision_signed_by: str | None = None
    decision_signed_at: str | None = None
    contract_template_ref: str = ""
    notified_others_at: str | None = None
    created_at: datetime
    updated_at: datetime


class BidRejectionCreate(BaseModel):
    """Create a rejection record."""

    model_config = ConfigDict(str_strip_whitespace=True)

    package_id: UUID
    bidder_id: UUID
    rejection_code: str = Field(default="other", pattern=_REJECTION_CODE)
    rejection_reason: str = ""


class BidRejectionUpdate(BaseModel):
    """Partial update for a rejection."""

    model_config = ConfigDict(str_strip_whitespace=True)

    rejection_code: str | None = Field(default=None, pattern=_REJECTION_CODE)
    rejection_reason: str | None = None
    notified_at: str | None = Field(default=None, max_length=40)


class BidRejectionResponse(BaseModel):
    """Rejection returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    package_id: UUID
    bidder_id: UUID
    rejection_code: str = "other"
    rejection_reason: str = ""
    notified_at: str | None = None
    created_at: datetime
    updated_at: datetime


# ── Dashboards / Analytics ───────────────────────────────────────────────


class BidPackageDashboard(BaseModel):
    """Dashboard widget for a single bid package."""

    package_id: UUID
    code: str
    title: str
    status: str
    invitations_count: int = 0
    submissions_count: int = 0
    declined_count: int = 0
    open_questions_count: int = 0
    answered_questions_count: int = 0
    leveling_computed: bool = False
    awarded_bidder_id: UUID | None = None


class SubmissionAnalyticsResponse(BaseModel):
    """Aggregate stats across a package's submissions."""

    package_id: UUID
    count: int = 0
    min_total: Decimal | None = None
    max_total: Decimal | None = None
    average_total: Decimal | None = None
    std_dev_total: Decimal | None = None
    completeness_avg: Decimal | None = None
    valid_count: int = 0
    late_count: int = 0


# ── Bid leveling matrix (line-level) ────────────────────────────────────


class LevelingMatrixCell(BaseModel):
    """One cell in the bid-leveling matrix."""

    bidder_id: UUID
    company_name: str = ""
    unit_price: Decimal = Decimal("0")
    quantity_priced: Decimal = Decimal("0")
    total_price: Decimal = Decimal("0")
    inclusion_status: str = "included"
    alternative_offered: bool = False
    comment: str = ""
    prevailing_wage_applicable: bool = False
    is_low: bool = False  # Whether this is the lowest price for the line


class LevelingMatrixRow(BaseModel):
    """One row (= one package line) in the bid-leveling matrix."""

    line_item_id: UUID
    line_item_code: str = ""
    description: str = ""
    unit: str = ""
    quantity: Decimal = Decimal("0")
    is_mandatory: bool = True
    cells: list[LevelingMatrixCell] = Field(default_factory=list)
    excluded_count: int = 0
    clarification_count: int = 0


class LevelingMatrixResponse(BaseModel):
    """Side-by-side bid-leveling matrix for a package."""

    package_id: UUID
    bidder_ids: list[UUID] = Field(default_factory=list)
    bidder_names: list[str] = Field(default_factory=list)
    rows: list[LevelingMatrixRow] = Field(default_factory=list)


# ── Q&A board (bidder-portal view) ──────────────────────────────────────


class BidderQAEntry(BaseModel):
    """Q&A entry as seen by one bidder on the portal."""

    id: UUID
    question: str
    answer: str = ""
    asked_at: str | None = None
    answered_at: str | None = None
    is_public: bool = False


class BidderQABoardResponse(BaseModel):
    """Q&A board for one bidder."""

    package_id: UUID
    bidder_id: UUID | None = None
    entries: list[BidderQAEntry] = Field(default_factory=list)


# ── Invitation email pipeline ───────────────────────────────────────────


class InvitationEmailTemplate(BaseModel):
    """Tenant-configurable invitation email template (one per language)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    language: str = Field(default="en", max_length=10)
    subject: str = Field(..., min_length=1, max_length=500)
    body: str = Field(..., min_length=1)


class InvitationEmailPreview(BaseModel):
    """Rendered email — subject + body — for one invitee."""

    invitee_email: str
    invitee_company_name: str
    subject: str
    body: str
    language: str = "en"


class InvitationEmailDispatchRequest(BaseModel):
    """Payload for the /send-emails endpoint."""

    model_config = ConfigDict(str_strip_whitespace=True)

    templates: list[InvitationEmailTemplate] = Field(default_factory=list)
    invitation_ids: list[UUID] | None = None
    sender_name: str = Field(default="", max_length=255)
    sender_email: str = Field(default="", max_length=255)


class InvitationEmailDispatchResponse(BaseModel):
    """Result of an invitation-email send batch."""

    package_id: UUID
    invitations_sent: int = 0
    previews: list[InvitationEmailPreview] = Field(default_factory=list)
    skipped: int = 0


# ── Subcontractor scorecard ─────────────────────────────────────────────


class SubcontractorScorecardCreate(BaseModel):
    """Post-award subcontractor performance scorecard.

    Each pillar scores 0..100 (clamped server-side). Composite is the
    straight average of the four pillars. ``notes`` is optional rationale.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    bidder_id: UUID
    on_time_score: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    quality_score: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    safety_score: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    commercial_score: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    notes: str = ""


class SubcontractorScorecardResponse(BaseModel):
    """Scorecard payload that gets persisted onto package metadata."""

    bidder_id: UUID
    on_time_score: Decimal
    quality_score: Decimal
    safety_score: Decimal
    commercial_score: Decimal
    composite_score: Decimal
    notes: str = ""
    recorded_at: str | None = None
