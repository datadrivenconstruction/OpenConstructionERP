# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠QMS Pydantic schemas - request / response models.

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

# Upper bound for money fields - far above any realistic NCR cost yet within
# Decimal's precision and the Numeric(18,2) column, so one absurd value cannot
# overflow the column (500 on write) or poison the project-wide COPQ rollup.
# Mirrors changeorders/schemas.py:_MONEY_MAX.
_MONEY_MAX = Decimal("1e15")


def _bound_money(v: Decimal | None) -> Decimal | None:
    """Reject non-finite / absurd-magnitude money. Pydantic already blocks
    NaN/Infinity for a ``Decimal`` field; this adds the missing magnitude bound
    so a finite-but-absurd value can't overflow the column or inflate COPQ."""
    if v is None:
        return v
    if not v.is_finite():
        raise ValueError("amount must be a finite number (no NaN/Infinity)")
    if abs(v) >= _MONEY_MAX:
        raise ValueError("amount is outside the supported range")
    return v


def _validate_https_url(value: str | None) -> str | None:
    """Reject URLs that aren't http(s).

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
    """Create an Inspection & Test Plan."""

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
    """Partial update for an ITP plan."""

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
    # Spec linkage + hold-point sequencing (item 12). All optional so an
    # item can be created bare and linked later.
    boq_position_id: UUID | None = None
    csi_section_ref: str | None = Field(default=None, max_length=64)
    spec_drawing_ref: str | None = Field(default=None, max_length=255)
    bim_element_id: str | None = Field(default=None, max_length=255)
    predecessor_itp_item_id: UUID | None = None


class ITPItemLinkSpec(BaseModel):
    """Link an ITP control point to its spec sources and a predecessor.

    Every field is optional; an omitted field leaves the existing value
    untouched. Passing an explicit ``null`` clears the link.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    boq_position_id: UUID | None = None
    csi_section_ref: str | None = Field(default=None, max_length=64)
    spec_drawing_ref: str | None = Field(default=None, max_length=255)
    bim_element_id: str | None = Field(default=None, max_length=255)
    predecessor_itp_item_id: UUID | None = None


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
    boq_position_id: UUID | None = None
    csi_section_ref: str | None = None
    spec_drawing_ref: str | None = None
    bim_element_id: str | None = None
    predecessor_itp_item_id: UUID | None = None
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
    attachment_document_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


# ── Inspection Signature ──────────────────────────────────────────────────


class InspectionSignatureCreate(BaseModel):
    """Sign-off entry against an inspection.

    ``signer_user_id`` is optional: when omitted the API fills it from the
    authenticated caller (the normal "sign as me" flow). It may be set
    explicitly to record a sign-off on behalf of another project member.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    signer_user_id: UUID | None = None
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
    # Non-repudiation context (item 12). Populated at sign time when the
    # request carries the client metadata; NULL for older signatures.
    timestamp_utc: str | None = None
    signer_ip: str | None = None
    signer_user_agent: str | None = None
    created_at: datetime
    updated_at: datetime


class InspectionSignaturesEnvelope(BaseModel):
    """Signatures collected on an inspection plus how many are required.

    ``required`` is inherited from the linked ITP item's
    ``signatories_required`` (default 1) so the UI can render a
    ``collected/required`` indicator and gate the Complete action.
    """

    inspection_id: UUID
    required: int
    collected: int
    signatures: list[InspectionSignatureRead] = Field(default_factory=list)


# ── Inspection evidence attachments (item 12) ─────────────────────────────


class InspectionAttachmentCreate(BaseModel):
    """Link an already-stored document to an inspection as evidence.

    The document itself is uploaded via the existing
    ``POST /inspections/{id}/attachments`` (or the documents module); this
    endpoint records the auditable link with an optional integrity hash.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    document_id: UUID
    caption: str | None = Field(default=None, max_length=500)
    file_hash_sha256: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-fA-F]{64}$",
    )


class InspectionAttachmentRead(BaseModel):
    """Inspection evidence attachment returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    inspection_id: UUID
    document_id: UUID
    caption: str | None = None
    file_hash_sha256: str | None = None
    uploaded_by: UUID | None = None
    attached_at: str | None = None
    created_at: datetime
    updated_at: datetime


# ── Hold-point sequencing + release (item 12) ─────────────────────────────


class HoldPointStatus(BaseModel):
    """Predecessor / hold-point gate status for an inspection.

    ``blocked`` is True when the linked ITP item declares a predecessor
    whose own inspection has not yet passed - the dependent inspection must
    not be completed until then. ``released`` mirrors whether a manual
    hold-point release record exists.
    """

    inspection_id: UUID
    itp_item_id: UUID | None = None
    is_hold_point: bool = False
    predecessor_itp_item_id: UUID | None = None
    predecessor_passed: bool = True
    blocked: bool = False
    blocking_reason: str | None = None
    released: bool = False


class HoldPointReleaseCreate(BaseModel):
    """Release a passed hold point so dependent work can proceed."""

    model_config = ConfigDict(str_strip_whitespace=True)

    justification: str = Field(..., min_length=1, max_length=2000)
    approval_route_id: UUID | None = None


class HoldPointReleaseRead(BaseModel):
    """Hold-point release record returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    inspection_id: UUID
    released_by: UUID | None = None
    released_at: str | None = None
    justification: str | None = None
    approval_route_id: UUID | None = None
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

    @field_validator("cost_impact_amount")
    @classmethod
    def _bound_cost_impact(cls, v: Decimal | None) -> Decimal | None:
        return _bound_money(v)


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

    @field_validator("cost_impact_amount")
    @classmethod
    def _bound_cost_impact(cls, v: Decimal | None) -> Decimal | None:
        return _bound_money(v)


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


# ── Rework provenance ─────────────────────────────────────────────────────
# ``rework_cost_estimate`` carries only the recorded punch-item rework money
# already denominated in the report ``currency`` - that is the only part that
# can honestly be folded into ``copq_total``. The fields below travel with it
# so a reader can tell the empty states apart:
#
#   recorded            - priced punch items exist in the report currency
#   override            - caller supplied a per-punch rate; count x rate
#   no_open_punch_items - the project has no open punch items at all
#   none_priced         - open punch items exist, none carries a cost
#   currency_mismatch   - money was recorded, none of it in this currency
#   currency_unknown    - the report currency could not be resolved
#   source_unavailable  - the punchlist module is absent or unreadable
#
# Only "no_open_punch_items" means there was nothing to measure. Every other
# empty figure means something was measured and deliberately left out, which
# is a different sentence from "the cost of poor quality is zero".
class _ReworkProvenance(BaseModel):
    """Where the rework term of a COPQ figure came from, and what it omits."""

    rework_cost_basis: str = ""
    rework_priced_count: int = 0
    rework_unpriced_count: int = 0
    rework_unreadable_count: int = 0
    rework_by_currency: dict[str, Decimal] = Field(default_factory=dict)
    rework_currency_mixed: bool = False


class COPQReport(_ReworkProvenance):
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


class COPQDetailed(_ReworkProvenance):
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
    # ``open_punch_count`` counts the QMS punch register while ``copq_total``
    # prices the punchlist one, and the rework term is dropped entirely when
    # it is unrecorded or denominated in another currency. Without this, the
    # report would show open punch items beside a total that excludes their
    # cost and offer the reader no way to tell. See ``_ReworkProvenance``.
    rework_cost_basis: str = ""
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


# ── Paged list envelopes ─────────────────────────────────────────────────
#
# `total` is the count that matched the filter, never the length of `items`.
#
# Five of these registers cap at 200 rows and the quality page asks for
# exactly 200, so a project past that ceiling was handed a full page with
# nothing to say it was one. An NCR register that stops at 200 and reads as
# complete is the shape that matters most here: closing out a project against
# a list of nonconformities that quietly omits the rest is how a defect
# survives handover.
#
# Grouped at the end of the module rather than next to each row class,
# because this file imports annotations from __future__: every envelope
# resolving after every row it names removes the ordering question rather
# than answering it eight times.
#
# ITPItemListResponse, NCRActionListResponse and InspectionAttachmentListResponse
# describe queries that take no offset or limit and are not capped in the
# repository, so their routes report `total` and `limit` as the length of what
# they returned. That is a true claim of completeness rather than a default
# carried over from a paged sibling, and it is the reason those three have no
# meaningful class-level default to declare.


class ITPPlanListResponse(BaseModel):
    """One page of ITP plans plus the size of the whole set."""

    items: list[ITPPlanRead] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 50


class ITPItemListResponse(BaseModel):
    """Every control point of one ITP plan. Unpaged, so `total` is the count."""

    items: list[ITPItemRead] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 0


class InspectionListResponse(BaseModel):
    """One page of inspections plus the size of the whole set."""

    items: list[InspectionRead] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 50


class InspectionAttachmentListResponse(BaseModel):
    """Every evidence attachment of one inspection. Unpaged."""

    items: list[InspectionAttachmentRead] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 0


class NCRListResponse(BaseModel):
    """One page of nonconformity reports plus the size of the whole set."""

    items: list[NCRRead] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 50


class NCRActionListResponse(BaseModel):
    """Every corrective action of one NCR. Unpaged, so `total` is the count."""

    items: list[NCRActionRead] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 0


class PunchItemListResponse(BaseModel):
    """One page of punch items plus the size of the whole set."""

    items: list[PunchItemRead] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 50


class AuditListResponse(BaseModel):
    """One page of quality audits plus the size of the whole set."""

    items: list[AuditRead] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 50
