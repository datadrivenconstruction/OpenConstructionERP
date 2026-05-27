"""‌⁠‍QMS Pydantic schemas — request / response models.

All UUIDs are :class:`uuid.UUID`; cost amounts use :class:`Decimal`.
Read schemas declare ``from_attributes=True`` so they hydrate directly
from SQLAlchemy ORM rows.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _validate_https_url(value: str | None) -> str | None:
    """‌⁠‍Reject URLs that aren't http(s).

    Rationale: ``certificate_url`` is rendered as a clickable link in
    calibration detail UIs; ``javascript:`` / ``data:`` schemes would
    trigger script execution on click. Restricting to http(s) closes
    that XSS vector at the schema boundary.
    """
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    lowered = stripped.lower()
    if not (lowered.startswith("http://") or lowered.startswith("https://")):
        raise ValueError(
            "URL must use http or https scheme (javascript:/data:/file: rejected)",
        )
    return stripped


# ── ITP Plan ──────────────────────────────────────────────────────────────


class ITPPlanCreate(BaseModel):
    """‌⁠‍Create an Inspection & Test Plan."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    work_type: str = Field(..., min_length=1, max_length=100)
    wbs_ref: str | None = Field(default=None, max_length=100)
    status: str = Field(
        default="draft",
        pattern=r"^(draft|active|superseded|closed)$",
    )
    version: int = Field(default=1, ge=1)


class ITPPlanUpdate(BaseModel):
    """‌⁠‍Partial update for an ITP plan."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    work_type: str | None = Field(default=None, min_length=1, max_length=100)
    wbs_ref: str | None = Field(default=None, max_length=100)
    status: str | None = Field(
        default=None,
        pattern=r"^(draft|active|superseded|closed)$",
    )
    version: int | None = Field(default=None, ge=1)


class ITPPlanRead(BaseModel):
    """ITP plan returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    work_type: str
    wbs_ref: str | None = None
    status: str
    version: int
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


# ── ITP Item ──────────────────────────────────────────────────────────────


class ITPItemCreate(BaseModel):
    """Create a control-point row inside an ITP."""

    model_config = ConfigDict(str_strip_whitespace=True)

    sequence: int = Field(default=0, ge=0)
    control_point_name: str = Field(..., min_length=1, max_length=255)
    criteria: str | None = Field(default=None, max_length=5000)
    frequency: str | None = Field(default=None, max_length=100)
    method: str | None = Field(default=None, max_length=100)
    acceptance_criteria: str | None = Field(default=None, max_length=5000)
    hold_witness_point: str = Field(
        default="review",
        pattern=r"^(hold|witness|review)$",
    )
    responsible_role: str | None = Field(default=None, max_length=100)
    signatories_required: int = Field(default=1, ge=1, le=10)


class ITPItemRead(BaseModel):
    """ITP item returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    itp_plan_id: UUID
    sequence: int
    control_point_name: str
    criteria: str | None = None
    frequency: str | None = None
    method: str | None = None
    acceptance_criteria: str | None = None
    hold_witness_point: str
    responsible_role: str | None = None
    signatories_required: int
    created_at: datetime
    updated_at: datetime


# ── Inspection ────────────────────────────────────────────────────────────


class InspectionCreate(BaseModel):
    """Schedule an inspection event."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    itp_item_id: UUID | None = None
    location_ref: str | None = Field(default=None, max_length=255)
    inspector_user_id: UUID | None = None
    scheduled_at: datetime | None = None
    bim_element_ref: str | None = Field(default=None, max_length=255)
    drawing_ref: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=10000)
    photos_json: list[dict[str, Any]] = Field(default_factory=list)


class InspectionUpdate(BaseModel):
    """Partial update for an inspection event."""

    model_config = ConfigDict(str_strip_whitespace=True)

    location_ref: str | None = Field(default=None, max_length=255)
    inspector_user_id: UUID | None = None
    scheduled_at: datetime | None = None
    performed_at: datetime | None = None
    status: str | None = Field(
        default=None,
        pattern=r"^(scheduled|in_progress|passed|failed|conditional)$",
    )
    bim_element_ref: str | None = Field(default=None, max_length=255)
    drawing_ref: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=10000)
    photos_json: list[dict[str, Any]] | None = None


class InspectionRead(BaseModel):
    """Inspection event returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    itp_item_id: UUID | None = None
    location_ref: str | None = None
    inspector_user_id: UUID | None = None
    scheduled_at: datetime | None = None
    performed_at: datetime | None = None
    status: str
    bim_element_ref: str | None = None
    drawing_ref: str | None = None
    notes: str | None = None
    photos_json: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


# ── Inspection Signature ──────────────────────────────────────────────────


class InspectionSignatureCreate(BaseModel):
    """Sign-off entry against an inspection."""

    model_config = ConfigDict(str_strip_whitespace=True)

    signer_user_id: UUID
    signer_role: str = Field(
        ...,
        pattern=r"^(GC|designer|client|subcontractor|inspector|other)$",
    )
    signature_method: str = Field(
        default="electronic",
        pattern=r"^(electronic|wet|biometric)$",
    )
    comments: str | None = Field(default=None, max_length=2000)


class InspectionSignatureRead(BaseModel):
    """Signature returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    inspection_id: UUID
    signer_user_id: UUID
    signer_role: str
    signed_at: datetime | None = None
    signature_method: str
    comments: str | None = None
    created_at: datetime
    updated_at: datetime


# ── NCR ───────────────────────────────────────────────────────────────────


class NCRCreate(BaseModel):
    """Raise a QMS NCR."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    title: str = Field(..., min_length=1, max_length=500)
    description: str = Field(..., min_length=1, max_length=10000)
    severity: str = Field(
        default="minor",
        pattern=r"^(minor|major|critical)$",
    )
    root_cause: str | None = Field(default=None, max_length=5000)
    cost_impact_currency: str = Field(default="", max_length=3)
    cost_impact_amount: Decimal | None = Field(default=None, ge=0)
    linked_inspection_id: UUID | None = None


class NCRUpdate(BaseModel):
    """Partial update for an NCR."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, min_length=1, max_length=10000)
    severity: str | None = Field(
        default=None,
        pattern=r"^(minor|major|critical)$",
    )
    root_cause: str | None = Field(default=None, max_length=5000)
    status: str | None = Field(
        default=None,
        pattern=r"^(open|action_pending|verifying|closed|cancelled)$",
    )
    cost_impact_currency: str | None = Field(default=None, max_length=3)
    cost_impact_amount: Decimal | None = Field(default=None, ge=0)
    linked_variation_id: UUID | None = None
    linked_inspection_id: UUID | None = None


class NCRRead(BaseModel):
    """NCR returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    raised_by: UUID | None = None
    raised_at: datetime | None = None
    title: str
    description: str
    severity: str
    root_cause: str | None = None
    status: str
    cost_impact_currency: str
    cost_impact_amount: Decimal | None = None
    linked_variation_id: UUID | None = None
    linked_inspection_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


# ── NCR Action ────────────────────────────────────────────────────────────


class NCRActionCreate(BaseModel):
    """Assign a corrective action against an NCR."""

    model_config = ConfigDict(str_strip_whitespace=True)

    description: str = Field(..., min_length=1, max_length=5000)
    responsible_user_id: UUID | None = None
    due_date: datetime | None = None
    verification_method: str | None = Field(default=None, max_length=255)


class NCRActionUpdate(BaseModel):
    """Partial update for an NCR action."""

    model_config = ConfigDict(str_strip_whitespace=True)

    description: str | None = Field(default=None, min_length=1, max_length=5000)
    responsible_user_id: UUID | None = None
    due_date: datetime | None = None
    status: str | None = Field(
        default=None,
        pattern=r"^(assigned|in_progress|done)$",
    )
    verification_method: str | None = Field(default=None, max_length=255)


class NCRActionRead(BaseModel):
    """Corrective action returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    ncr_id: UUID
    description: str
    responsible_user_id: UUID | None = None
    due_date: datetime | None = None
    status: str
    verification_method: str | None = None
    verified_by: UUID | None = None
    verified_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


# ── Punch Item ────────────────────────────────────────────────────────────


class PunchItemCreate(BaseModel):
    """Add a punch list entry."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    title: str = Field(..., min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=10000)
    room_ref: str | None = Field(default=None, max_length=255)
    drawing_ref: str | None = Field(default=None, max_length=255)
    bim_element_ref: str | None = Field(default=None, max_length=255)
    severity: str = Field(
        default="minor",
        pattern=r"^(minor|major|critical)$",
    )
    assigned_to: UUID | None = None
    due_date: datetime | None = None
    photos_json: list[dict[str, Any]] = Field(default_factory=list)
    source: str = Field(
        default="manual",
        pattern=r"^(manual|inspection|walkthrough)$",
    )
    category: str | None = Field(
        default=None,
        pattern=r"^(architectural|mechanical|electrical|finishes|structure)$",
    )


class PunchItemUpdate(BaseModel):
    """Partial update for a punch item."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=10000)
    room_ref: str | None = Field(default=None, max_length=255)
    drawing_ref: str | None = Field(default=None, max_length=255)
    bim_element_ref: str | None = Field(default=None, max_length=255)
    status: str | None = Field(
        default=None,
        pattern=r"^(open|assigned|in_progress|ready_for_inspection|closed|rejected)$",
    )
    severity: str | None = Field(
        default=None,
        pattern=r"^(minor|major|critical)$",
    )
    assigned_to: UUID | None = None
    due_date: datetime | None = None
    photos_json: list[dict[str, Any]] | None = None
    category: str | None = Field(
        default=None,
        pattern=r"^(architectural|mechanical|electrical|finishes|structure)$",
    )


class PunchItemRead(BaseModel):
    """Punch item returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    raised_at: datetime | None = None
    raised_by: UUID | None = None
    title: str
    description: str | None = None
    room_ref: str | None = None
    drawing_ref: str | None = None
    bim_element_ref: str | None = None
    status: str
    severity: str
    assigned_to: UUID | None = None
    due_date: datetime | None = None
    closed_at: datetime | None = None
    photos_json: list[dict[str, Any]] = Field(default_factory=list)
    source: str
    category: str | None = None
    created_at: datetime
    updated_at: datetime


# ── Audit ─────────────────────────────────────────────────────────────────


class AuditCreate(BaseModel):
    """Plan a quality audit."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    audit_type: str = Field(
        default="internal",
        pattern=r"^(internal|external|supplier)$",
    )
    planned_date: datetime | None = None
    auditor_user_id: UUID | None = None
    audit_scope: str | None = Field(default=None, max_length=5000)
    standard_ref: str | None = Field(default=None, max_length=64)


class AuditUpdate(BaseModel):
    """Partial update for an audit."""

    model_config = ConfigDict(str_strip_whitespace=True)

    audit_type: str | None = Field(
        default=None,
        pattern=r"^(internal|external|supplier)$",
    )
    planned_date: datetime | None = None
    performed_at: datetime | None = None
    auditor_user_id: UUID | None = None
    audit_scope: str | None = Field(default=None, max_length=5000)
    standard_ref: str | None = Field(default=None, max_length=64)
    status: str | None = Field(
        default=None,
        pattern=r"^(planned|in_progress|completed|closed)$",
    )
    overall_rating: int | None = Field(default=None, ge=1, le=5)


class AuditRead(BaseModel):
    """Audit returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    audit_type: str
    planned_date: datetime | None = None
    performed_at: datetime | None = None
    auditor_user_id: UUID | None = None
    audit_scope: str | None = None
    standard_ref: str | None = None
    status: str
    overall_rating: int | None = None
    created_at: datetime
    updated_at: datetime


# ── Audit Finding ─────────────────────────────────────────────────────────


class AuditFindingCreate(BaseModel):
    """Record a finding inside an audit."""

    model_config = ConfigDict(str_strip_whitespace=True)

    finding_type: str = Field(
        default="observation",
        pattern=r"^(observation|minor|major|critical)$",
    )
    description: str = Field(..., min_length=1, max_length=5000)
    clause_ref: str | None = Field(default=None, max_length=64)
    corrective_action_required: str | None = Field(default=None, max_length=5000)
    due_date: datetime | None = None


class AuditFindingUpdate(BaseModel):
    """Partial update for an audit finding."""

    model_config = ConfigDict(str_strip_whitespace=True)

    finding_type: str | None = Field(
        default=None,
        pattern=r"^(observation|minor|major|critical)$",
    )
    description: str | None = Field(default=None, min_length=1, max_length=5000)
    clause_ref: str | None = Field(default=None, max_length=64)
    corrective_action_required: str | None = Field(default=None, max_length=5000)
    status: str | None = Field(
        default=None,
        pattern=r"^(open|in_progress|verified|closed)$",
    )
    due_date: datetime | None = None


class AuditFindingRead(BaseModel):
    """Audit finding returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    audit_id: UUID
    finding_type: str
    description: str
    clause_ref: str | None = None
    corrective_action_required: str | None = None
    status: str
    due_date: datetime | None = None
    closed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


# ── Analytics ─────────────────────────────────────────────────────────────


class COPQReport(BaseModel):
    """Cost of Poor Quality report payload."""

    project_id: UUID
    ncr_cost_total: Decimal
    open_punch_count: int
    rework_cost_estimate: Decimal
    copq_total: Decimal
    currency: str = ""


class FirstPassYieldReport(BaseModel):
    """First-pass yield analytics."""

    project_id: UUID
    inspections_total: int
    inspections_passed_first_time: int
    first_pass_yield: float  # 0.0 .. 1.0


class FPYTrendBucket(BaseModel):
    """One period bucket in a first-pass-yield trend."""

    period_start: str = Field(description="ISO date YYYY-MM-DD")
    period_end: str = Field(description="ISO date YYYY-MM-DD")
    inspections_total: int
    inspections_passed_first_time: int
    first_pass_yield: float


class FPYTrendReport(BaseModel):
    """First-pass yield trend report, bucketed by period."""

    project_id: UUID
    work_type: str | None = None
    period_days: int
    buckets: list[FPYTrendBucket] = Field(default_factory=list)


class COPQDetailed(BaseModel):
    """Detailed Cost of Poor Quality including warranty, delay, and rework."""

    project_id: UUID
    ncr_cost_total: Decimal
    open_punch_count: int
    rework_cost_estimate: Decimal
    warranty_cost: Decimal
    delay_penalty_cost: Decimal
    copq_total: Decimal
    currency: str = ""


# ── ITP Template (tenant-level library) ───────────────────────────────────


class ITPTemplateItemSpec(BaseModel):
    """A single control-point spec in an ITP template."""

    model_config = ConfigDict(str_strip_whitespace=True)

    sequence: int = Field(default=0, ge=0)
    control_point_name: str = Field(..., min_length=1, max_length=255)
    criteria: str | None = Field(default=None, max_length=5000)
    frequency: str | None = Field(default=None, max_length=100)
    method: str | None = Field(default=None, max_length=100)
    acceptance_criteria: str | None = Field(default=None, max_length=5000)
    hold_witness_point: str = Field(
        default="review",
        pattern=r"^(hold|witness|review)$",
    )
    responsible_role: str | None = Field(default=None, max_length=100)
    signatories_required: int = Field(default=1, ge=1, le=10)


class ITPTemplateCreate(BaseModel):
    """Create a reusable ITP template (tenant-level)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    csi_division: str = Field(..., min_length=1, max_length=16)
    work_type: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    standard_ref: str | None = Field(default=None, max_length=64)
    items: list[ITPTemplateItemSpec] = Field(default_factory=list)
    is_active: bool = True
    version: int = Field(default=1, ge=1)


class ITPTemplateUpdate(BaseModel):
    """Partial update for an ITP template."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    standard_ref: str | None = Field(default=None, max_length=64)
    items: list[ITPTemplateItemSpec] | None = None
    is_active: bool | None = None
    version: int | None = Field(default=None, ge=1)


class ITPTemplateRead(BaseModel):
    """ITP template returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    csi_division: str
    work_type: str
    name: str
    description: str | None = None
    standard_ref: str | None = None
    items_json: list[dict[str, Any]] = Field(default_factory=list)
    is_active: bool
    version: int
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


class ITPTemplateCloneRequest(BaseModel):
    """Request to clone a template into a project as a new ITPPlan."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    wbs_ref: str | None = Field(default=None, max_length=100)
    name_override: str | None = Field(default=None, max_length=255)


# ── Calibration ───────────────────────────────────────────────────────────


class CalibrationCreate(BaseModel):
    """Create a calibration certificate entry."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID | None = None
    instrument_id: str = Field(..., min_length=1, max_length=100)
    instrument_name: str = Field(..., min_length=1, max_length=255)
    instrument_type: str = Field(..., min_length=1, max_length=100)
    serial_number: str | None = Field(default=None, max_length=100)
    manufacturer: str | None = Field(default=None, max_length=255)
    calibration_date: date
    valid_until: date
    calibrated_by: str | None = Field(default=None, max_length=255)
    certificate_url: str | None = Field(default=None, max_length=2000)
    reference_standard: str | None = Field(default=None, max_length=255)
    measurement_uncertainty: str | None = Field(default=None, max_length=255)
    owner_user_id: UUID | None = None
    notes: str | None = Field(default=None, max_length=5000)

    _validate_cert_url = field_validator("certificate_url")(_validate_https_url)


class CalibrationUpdate(BaseModel):
    """Partial update of a calibration certificate."""

    model_config = ConfigDict(str_strip_whitespace=True)

    instrument_name: str | None = Field(default=None, min_length=1, max_length=255)
    serial_number: str | None = Field(default=None, max_length=100)
    manufacturer: str | None = Field(default=None, max_length=255)
    calibration_date: date | None = None
    valid_until: date | None = None
    calibrated_by: str | None = Field(default=None, max_length=255)
    certificate_url: str | None = Field(default=None, max_length=2000)
    reference_standard: str | None = Field(default=None, max_length=255)
    measurement_uncertainty: str | None = Field(default=None, max_length=255)
    owner_user_id: UUID | None = None
    status: str | None = Field(
        default=None,
        pattern=r"^(valid|expired|withdrawn)$",
    )
    notes: str | None = Field(default=None, max_length=5000)

    _validate_cert_url = field_validator("certificate_url")(_validate_https_url)


class CalibrationRead(BaseModel):
    """Calibration record returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID | None = None
    instrument_id: str
    instrument_name: str
    instrument_type: str
    serial_number: str | None = None
    manufacturer: str | None = None
    calibration_date: date
    valid_until: date
    calibrated_by: str | None = None
    certificate_url: str | None = None
    reference_standard: str | None = None
    measurement_uncertainty: str | None = None
    owner_user_id: UUID | None = None
    status: str
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


# ── Management Review (ISO 9001:2015 clause 9.3) ──────────────────────────


class ManagementReviewRequest(BaseModel):
    """Request payload for a management-review report."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    period_from: date
    period_to: date
    currency: str = Field(default="", max_length=3)


class ManagementReviewReport(BaseModel):
    """ISO 9001:2015 §9.3 management-review summary."""

    project_id: UUID
    period_from: date
    period_to: date
    audits_completed: int
    findings_open: int
    findings_closed: int
    ncrs_raised: int
    ncrs_closed: int
    first_pass_yield: float
    copq_total: Decimal
    currency: str
    inspections_total: int
    inspections_passed: int
    inspections_failed: int
    open_punch_count: int
    recommendations: list[str] = Field(default_factory=list)


# ── Supplier audit linkage ────────────────────────────────────────────────


class SupplierAuditLink(BaseModel):
    """Result of linking an audit to a supplier rating."""

    model_config = ConfigDict(str_strip_whitespace=True)

    audit_id: UUID
    subcontractor_id: UUID
    rating_delta: int = Field(
        default=0,
        ge=-5,
        le=5,
        description="Adjustment to the subcontractor's quality rating (-5..+5)",
    )
