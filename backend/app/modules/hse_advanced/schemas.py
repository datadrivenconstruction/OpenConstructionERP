"""‌⁠‍HSE Advanced Pydantic schemas — request/response models."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _validate_safe_url(value: str | None) -> str | None:
    """Reject javascript:/data:/file: URLs in user-supplied evidence/report links.

    Allowed schemes: ``http``, ``https``, or scheme-less relative paths
    (e.g. ``/uploads/photos/abc.jpg``). Anything else is rejected so a
    finding's ``evidence_url`` cannot become a stored-XSS vector when
    rendered as an ``<a href>`` in the dashboard.
    """
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    lower = stripped.lower()
    if lower.startswith(("http://", "https://", "/")):
        return stripped
    # Anything containing a scheme (``foo:bar``) that isn't whitelisted
    # is rejected — keeps relative paths working but blocks javascript:.
    if ":" in stripped.split("/", 1)[0]:
        raise ValueError(
            "URL must use http(s):// or be a relative path; javascript:/data:/file: URIs are not allowed",
        )
    return stripped


# ── Investigation ────────────────────────────────────────────────────────────


class InvestigationCreate(BaseModel):
    """‌⁠‍Create a new incident investigation."""

    model_config = ConfigDict(str_strip_whitespace=True)

    incident_ref: UUID
    investigation_lead: UUID | None = None
    started_at: datetime
    method: str = Field(default="5_whys", pattern=r"^(5_whys|fishbone|timeline|swot)$")
    findings: str = Field(default="", max_length=20000)
    recommendations: str = Field(default="", max_length=20000)
    status: str = Field(default="in_progress", pattern=r"^(in_progress|completed|abandoned)$")
    report_url: str | None = Field(default=None, max_length=1000)

    @field_validator("report_url")
    @classmethod
    def _check_report_url(cls, value: str | None) -> str | None:
        return _validate_safe_url(value)


class InvestigationUpdate(BaseModel):
    """‌⁠‍Partial update for an investigation."""

    model_config = ConfigDict(str_strip_whitespace=True)

    investigation_lead: UUID | None = None
    completed_at: datetime | None = None
    method: str | None = Field(default=None, pattern=r"^(5_whys|fishbone|timeline|swot)$")
    findings: str | None = Field(default=None, max_length=20000)
    recommendations: str | None = Field(default=None, max_length=20000)
    status: str | None = Field(default=None, pattern=r"^(in_progress|completed|abandoned)$")
    report_url: str | None = Field(default=None, max_length=1000)


class InvestigationResponse(BaseModel):
    """Investigation returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    incident_ref: UUID
    investigation_lead: UUID | None = None
    started_at: datetime
    completed_at: datetime | None = None
    method: str
    findings: str
    recommendations: str
    status: str
    report_url: str | None = None
    created_at: datetime
    updated_at: datetime


# ── JSA ──────────────────────────────────────────────────────────────────────


class JSAHazardEntry(BaseModel):
    """A single hazard within a JSA."""

    step: str = Field(..., min_length=1, max_length=500)
    hazard: str = Field(..., min_length=1, max_length=500)
    severity: int = Field(default=1, ge=1, le=5)
    likelihood: int = Field(default=1, ge=1, le=5)
    controls: str = Field(default="", max_length=2000)


class JSACreate(BaseModel):
    """Create a new JSA."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    task_description: str = Field(..., min_length=1, max_length=5000)
    location: str | None = Field(default=None, max_length=500)
    work_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    prepared_by: UUID | None = None
    hazards: list[JSAHazardEntry] = Field(default_factory=list)
    required_ppe: list[str] = Field(default_factory=list)
    status: str = Field(
        default="draft",
        pattern=r"^(draft|under_review|approved|active|archived)$",
    )


class JSAUpdate(BaseModel):
    """Partial update for a JSA."""

    model_config = ConfigDict(str_strip_whitespace=True)

    task_description: str | None = Field(default=None, min_length=1, max_length=5000)
    location: str | None = Field(default=None, max_length=500)
    work_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    hazards: list[JSAHazardEntry] | None = None
    required_ppe: list[str] | None = None
    status: str | None = Field(
        default=None,
        pattern=r"^(draft|under_review|approved|active|archived)$",
    )


class JSAResponse(BaseModel):
    """JSA returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    task_description: str
    location: str | None = None
    work_date: str
    prepared_by: UUID | None = None
    approved_by: UUID | None = None
    approved_at: datetime | None = None
    status: str
    hazards: list[dict[str, Any]] = Field(default_factory=list)
    required_ppe: list[str] = Field(default_factory=list)
    risk_score: int = 0
    created_at: datetime
    updated_at: datetime


# ── PTW ──────────────────────────────────────────────────────────────────────


class PermitCreate(BaseModel):
    """Create a new permit-to-work."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    permit_number: str = Field(..., min_length=1, max_length=50)
    permit_type: str = Field(
        ...,
        pattern=(
            r"^(hot_work|confined_space|work_at_height|electrical|excavation"
            r"|lifting|lockout_tagout|other)$"
        ),
    )
    description: str = Field(default="", max_length=5000)
    location: str | None = Field(default=None, max_length=500)
    work_start: datetime
    work_end: datetime
    applicant_id: UUID | None = None
    supervisor_id: UUID | None = None
    jsa_id: UUID | None = None
    conditions: str = Field(default="", max_length=5000)


class PermitUpdate(BaseModel):
    """Partial update for a permit."""

    model_config = ConfigDict(str_strip_whitespace=True)

    description: str | None = Field(default=None, max_length=5000)
    location: str | None = Field(default=None, max_length=500)
    work_start: datetime | None = None
    work_end: datetime | None = None
    supervisor_id: UUID | None = None
    jsa_id: UUID | None = None
    conditions: str | None = Field(default=None, max_length=5000)


class PermitClosurePayload(BaseModel):
    """Payload for closing a permit."""

    closure_checklist_passed: bool = True
    closure_notes: str = Field(default="", max_length=5000)


class PermitApprovalPayload(BaseModel):
    """Payload for approving a permit."""

    conditions: str = Field(default="", max_length=5000)


class PermitResponse(BaseModel):
    """Permit returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    permit_number: str
    permit_type: str
    description: str
    location: str | None = None
    work_start: datetime
    work_end: datetime
    applicant_id: UUID | None = None
    supervisor_id: UUID | None = None
    jsa_id: UUID | None = None
    status: str
    approved_at: datetime | None = None
    approved_by: UUID | None = None
    conditions: str
    closure_checklist_passed: bool
    closure_notes: str
    prereq_jsa_approved: bool = False
    prereq_supervisor_present: bool = False
    prereq_fire_watch_assigned: bool = False
    prereq_extinguisher_present: bool = False
    prereq_atmospheric_test_passed: bool = False
    created_at: datetime
    updated_at: datetime


class PermitPrerequisitesPayload(BaseModel):
    """Update one or more PTW prerequisite flags."""

    model_config = ConfigDict(str_strip_whitespace=True)

    prereq_jsa_approved: bool | None = None
    prereq_supervisor_present: bool | None = None
    prereq_fire_watch_assigned: bool | None = None
    prereq_extinguisher_present: bool | None = None
    prereq_atmospheric_test_passed: bool | None = None


class PermitPrerequisiteStatus(BaseModel):
    """The result of a PTW prerequisite validation."""

    permit_id: UUID
    permit_type: str
    prereqs_required: list[str]
    prereqs_met: list[str]
    prereqs_missing: list[str]
    ready_to_activate: bool


class JSATemplateCreate(BaseModel):
    """Create a tenant-level JSA template."""

    model_config = ConfigDict(str_strip_whitespace=True)

    trade: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    task_description: str = Field(..., min_length=1, max_length=10000)
    hazards: list[Any] = Field(default_factory=list)
    required_ppe: list[str] = Field(default_factory=list)
    region: str | None = Field(default=None, max_length=32)
    is_active: bool = True
    version: int = Field(default=1, ge=1)


class JSATemplateUpdate(BaseModel):
    """Partial update for a JSA template."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=255)
    task_description: str | None = Field(default=None, min_length=1, max_length=10000)
    hazards: list[Any] | None = None
    required_ppe: list[str] | None = None
    region: str | None = Field(default=None, max_length=32)
    is_active: bool | None = None
    version: int | None = Field(default=None, ge=1)


class JSATemplateResponse(BaseModel):
    """JSA template returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    trade: str
    name: str
    task_description: str
    hazards_json: list[dict[str, Any]] = Field(default_factory=list)
    required_ppe_json: list[str] = Field(default_factory=list)
    region: str | None = None
    is_active: bool
    version: int
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime


class JSATemplateCloneRequest(BaseModel):
    """Deep-clone a JSA template into a project."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    work_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    location: str | None = Field(default=None, max_length=500)
    prepared_by: UUID | None = None


# ── Toolbox talk + attendance ───────────────────────────────────────────────


class ToolboxAttendanceEntry(BaseModel):
    """A single attendee in a record-toolbox-talk payload."""

    attendee_name: str = Field(..., min_length=1, max_length=255)
    attendee_company: str | None = Field(default=None, max_length=255)
    attendee_role: str = Field(default="worker", pattern=r"^(worker|foreman|visitor)$")
    signature_ref: str | None = Field(default=None, max_length=500)
    signed_at: datetime | None = None
    attendance_status: str = Field(default="present", pattern=r"^(present|absent|late)$")


class ToolboxTalkCreate(BaseModel):
    """Create / record a toolbox talk."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    topic_code: str = Field(..., min_length=1, max_length=50)
    topic_title: str = Field(..., min_length=1, max_length=500)
    conducted_at: datetime
    conducted_by: UUID | None = None
    language: str = Field(default="en", max_length=10)
    notes: str = Field(default="", max_length=10000)
    library_topic_ref: UUID | None = None
    attendance: list[ToolboxAttendanceEntry] = Field(default_factory=list)


class ToolboxTalkUpdate(BaseModel):
    """Partial update for a toolbox talk (no attendance changes)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    topic_title: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=10000)
    language: str | None = Field(default=None, max_length=10)


class ToolboxTalkResponse(BaseModel):
    """Toolbox talk returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    topic_code: str
    topic_title: str
    conducted_at: datetime
    conducted_by: UUID | None = None
    language: str
    attendance_count: int
    notes: str
    library_topic_ref: UUID | None = None
    created_at: datetime
    updated_at: datetime


class ToolboxAttendanceResponse(BaseModel):
    """Attendance row returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    toolbox_talk_id: UUID
    attendee_name: str
    attendee_company: str | None = None
    attendee_role: str
    signature_ref: str | None = None
    signed_at: datetime | None = None
    attendance_status: str
    created_at: datetime
    updated_at: datetime


# ── Toolbox topic library ───────────────────────────────────────────────────


class ToolboxTopicCreate(BaseModel):
    """Create a toolbox topic in the library."""

    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(..., min_length=1, max_length=50)
    title: str = Field(..., min_length=1, max_length=500)
    content: str = Field(default="", max_length=50000)
    category: str = Field(
        default="general",
        pattern=r"^(general|hazard_specific|regulatory)$",
    )
    language: str = Field(default="en", max_length=10)
    duration_minutes: int = Field(default=5, ge=1, le=240)
    version: str = Field(default="1.0", max_length=20)
    is_active: bool = True


class ToolboxTopicUpdate(BaseModel):
    """Partial update for a toolbox topic."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=500)
    content: str | None = Field(default=None, max_length=50000)
    category: str | None = Field(
        default=None,
        pattern=r"^(general|hazard_specific|regulatory)$",
    )
    language: str | None = Field(default=None, max_length=10)
    duration_minutes: int | None = Field(default=None, ge=1, le=240)
    version: str | None = Field(default=None, max_length=20)
    is_active: bool | None = None


class ToolboxTopicResponse(BaseModel):
    """Toolbox topic returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    title: str
    content: str
    category: str
    language: str
    duration_minutes: int
    version: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


# ── PPE issue ───────────────────────────────────────────────────────────────


class PPEIssueCreate(BaseModel):
    """Create a PPE issuance record."""

    model_config = ConfigDict(str_strip_whitespace=True)

    recipient_user_id: UUID | None = None
    recipient_name: str | None = Field(default=None, max_length=255)
    recipient_company: str | None = Field(default=None, max_length=255)
    issued_at: datetime
    issued_by: UUID | None = None
    ppe_type: str = Field(
        ...,
        pattern=(
            r"^(hard_hat|safety_boots|gloves|harness|respirator|hi_vis"
            r"|glasses|other)$"
        ),
    )
    size: str | None = Field(default=None, max_length=50)
    brand: str | None = Field(default=None, max_length=100)
    serial: str | None = Field(default=None, max_length=100)
    valid_until: date | None = None
    status: str = Field(
        default="issued",
        pattern=r"^(issued|in_use|returned|lost|damaged)$",
    )


class PPEIssueUpdate(BaseModel):
    """Partial update for a PPE issuance."""

    model_config = ConfigDict(str_strip_whitespace=True)

    size: str | None = Field(default=None, max_length=50)
    brand: str | None = Field(default=None, max_length=100)
    serial: str | None = Field(default=None, max_length=100)
    valid_until: date | None = None
    returned_at: datetime | None = None
    status: str | None = Field(
        default=None,
        pattern=r"^(issued|in_use|returned|lost|damaged)$",
    )


class PPEIssueResponse(BaseModel):
    """PPE issuance returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    recipient_user_id: UUID | None = None
    recipient_name: str | None = None
    recipient_company: str | None = None
    issued_at: datetime
    issued_by: UUID | None = None
    ppe_type: str
    size: str | None = None
    brand: str | None = None
    serial: str | None = None
    valid_until: date | None = None
    returned_at: datetime | None = None
    status: str
    created_at: datetime
    updated_at: datetime


# ── Audit ───────────────────────────────────────────────────────────────────


class AuditCreate(BaseModel):
    """Create a safety audit."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    audit_type: str = Field(
        default="internal",
        pattern=r"^(internal|external|regulatory|site_walk)$",
    )
    conducted_at: datetime
    conducted_by: UUID | None = None
    status: str = Field(
        default="scheduled",
        pattern=r"^(scheduled|in_progress|completed|cancelled)$",
    )
    summary: str = Field(default="", max_length=10000)
    checklist_template_ref: UUID | None = None


class AuditUpdate(BaseModel):
    """Partial update for an audit."""

    model_config = ConfigDict(str_strip_whitespace=True)

    audit_type: str | None = Field(
        default=None,
        pattern=r"^(internal|external|regulatory|site_walk)$",
    )
    conducted_at: datetime | None = None
    score_total: Decimal | None = None
    max_score: Decimal | None = None
    status: str | None = Field(
        default=None,
        pattern=r"^(scheduled|in_progress|completed|cancelled)$",
    )
    summary: str | None = Field(default=None, max_length=10000)


class AuditFindingPayload(BaseModel):
    """A single audit finding payload."""

    item_description: str = Field(..., min_length=1, max_length=2000)
    category: str = Field(
        default="other",
        pattern=(r"^(PPE|permit|housekeeping|electrical|fire|environmental|other)$"),
    )
    severity: str = Field(default="low", pattern=r"^(low|med|high|critical)$")
    is_passed: bool = True
    evidence_url: str | None = Field(default=None, max_length=1000)

    @field_validator("evidence_url")
    @classmethod
    def _check_evidence_url(cls, value: str | None) -> str | None:
        return _validate_safe_url(value)


class AuditFindingCreate(AuditFindingPayload):
    """Create a finding scoped to an audit."""

    pass


class AuditFindingResponse(BaseModel):
    """Audit finding returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    audit_id: UUID
    item_description: str
    category: str
    severity: str
    is_passed: bool
    evidence_url: str | None = None
    corrective_action_ref: UUID | None = None
    created_at: datetime
    updated_at: datetime


class AuditResponse(BaseModel):
    """Audit returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    audit_type: str
    conducted_at: datetime
    conducted_by: UUID | None = None
    score_total: Decimal | None = None
    max_score: Decimal | None = None
    status: str
    summary: str
    checklist_template_ref: UUID | None = None
    created_at: datetime
    updated_at: datetime


class AuditScoreResponse(BaseModel):
    """Computed audit score result."""

    audit_id: UUID
    passed_count: int = 0
    failed_count: int = 0
    score: Decimal = Field(default=Decimal("0"))
    max_score: Decimal = Field(default=Decimal("0"))
    percentage: float = 0.0


# ── CAPA ────────────────────────────────────────────────────────────────────


class CAPACreate(BaseModel):
    """Create a corrective / preventive action."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    source_type: str = Field(
        ...,
        pattern=r"^(incident|jsa|permit|audit|observation)$",
    )
    source_ref: UUID | None = None
    title: str = Field(..., min_length=1, max_length=500)
    description: str = Field(default="", max_length=10000)
    owner_user_id: UUID | None = None
    target_date: date
    status: str = Field(
        default="open",
        pattern=r"^(open|in_progress|completed|overdue|cancelled)$",
    )
    root_cause_category: str | None = Field(
        default=None,
        pattern=(r"^(manpower|method|material|machine|environment|management|other)$"),
    )


class CAPAUpdate(BaseModel):
    """Partial update for a CAPA."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=10000)
    owner_user_id: UUID | None = None
    target_date: date | None = None
    status: str | None = Field(
        default=None,
        pattern=r"^(open|in_progress|completed|overdue|cancelled)$",
    )
    verification_notes: str | None = Field(default=None, max_length=10000)
    root_cause_category: str | None = Field(
        default=None,
        pattern=(r"^(manpower|method|material|machine|environment|management|other)$"),
    )


class CAPAVerificationPayload(BaseModel):
    """Payload when closing a CAPA."""

    verification_notes: str = Field(default="", max_length=10000)


class FiveWhyStep(BaseModel):
    """A single 'why → answer' pair in a 5-Whys root-cause chain."""

    model_config = ConfigDict(str_strip_whitespace=True)

    why: str = Field(..., min_length=1, max_length=2000)
    answer: str = Field(..., min_length=1, max_length=2000)


class CAPAFiveWhysPayload(BaseModel):
    """Set the 5-Whys structured root-cause chain on a CAPA."""

    model_config = ConfigDict(str_strip_whitespace=True)

    steps: list[FiveWhyStep] = Field(default_factory=list)
    root_cause_category: str | None = Field(
        default=None,
        pattern=(r"^(manpower|method|material|machine|environment|management|other)$"),
    )


class CAPAEffectivenessPayload(BaseModel):
    """Verify the effectiveness of a closed CAPA (ISO 9001 §10.2.1 fol-low-up)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    effective: bool = True
    notes: str = Field(default="", max_length=10000)


class CAPAResponse(BaseModel):
    """CAPA returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    source_type: str
    source_ref: UUID | None = None
    title: str
    description: str
    owner_user_id: UUID | None = None
    target_date: date
    status: str
    completed_at: datetime | None = None
    verification_notes: str
    root_cause_category: str | None = None
    five_whys: list[dict[str, Any]] | None = None
    effectiveness_verified_at: datetime | None = None
    effectiveness_verified_by: UUID | None = None
    created_at: datetime
    updated_at: datetime


# ── Incident escalation matrix ────────────────────────────────────────────


class IncidentEscalationEntry(BaseModel):
    """A single row in an incident escalation matrix."""

    severity: str
    notify_roles: list[str]
    notify_within_hours: int
    regulation_ref: str | None = None


class IncidentEscalationMatrix(BaseModel):
    """Severity → role → SLA mapping computed for a regulatory regime."""

    regime: str = Field(description="One of 'osha', 'hse_uk', 'dguv', 'iso45001'")
    entries: list[IncidentEscalationEntry] = Field(default_factory=list)


# ── Certification ───────────────────────────────────────────────────────────


class CertificationCreate(BaseModel):
    """Create a safety certification."""

    model_config = ConfigDict(str_strip_whitespace=True)

    owner_user_id: UUID | None = None
    owner_name: str | None = Field(default=None, max_length=255)
    owner_company: str | None = Field(default=None, max_length=255)
    cert_type: str = Field(..., min_length=1, max_length=100)
    issued_by: str | None = Field(default=None, max_length=255)
    issue_date: date
    valid_until: date
    document_url: str | None = Field(default=None, max_length=1000)
    status: str = Field(default="valid", pattern=r"^(valid|expired|revoked)$")


class CertificationUpdate(BaseModel):
    """Partial update for a certification."""

    model_config = ConfigDict(str_strip_whitespace=True)

    owner_name: str | None = Field(default=None, max_length=255)
    owner_company: str | None = Field(default=None, max_length=255)
    issued_by: str | None = Field(default=None, max_length=255)
    valid_until: date | None = None
    document_url: str | None = Field(default=None, max_length=1000)
    status: str | None = Field(default=None, pattern=r"^(valid|expired|revoked)$")


class CertificationResponse(BaseModel):
    """Certification returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_user_id: UUID | None = None
    owner_name: str | None = None
    owner_company: str | None = None
    cert_type: str
    issued_by: str | None = None
    issue_date: date
    valid_until: date
    document_url: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime


# ── KPI + Dashboards ────────────────────────────────────────────────────────


class RiskScoreResponse(BaseModel):
    """Pure risk-score response (severity × likelihood)."""

    severity: int
    likelihood: int
    risk_score: int
    tier: str


class KPIResponse(BaseModel):
    """KPI dashboard response — TRIR, LTIFR, days without LTI."""

    project_id: UUID
    period_start: date | None = None
    period_end: date | None = None
    hours_worked: Decimal = Field(default=Decimal("0"))
    recordable_count: int = 0
    lti_count: int = 0
    trir: Decimal = Field(default=Decimal("0"))
    ltifr: Decimal = Field(default=Decimal("0"))
    days_without_lti: int | None = None


class PermitDashboardEntry(BaseModel):
    """A permit summary line on the dashboard."""

    permit_id: UUID
    permit_number: str
    permit_type: str
    status: str
    work_start: datetime
    work_end: datetime


class PermitDashboardResponse(BaseModel):
    """Active / pending permits summary."""

    project_id: UUID
    active: list[PermitDashboardEntry] = Field(default_factory=list)
    pending: list[PermitDashboardEntry] = Field(default_factory=list)
    closed_today: list[PermitDashboardEntry] = Field(default_factory=list)


class HSEDashboardResponse(BaseModel):
    """Combined HSE dashboard for a project."""

    project_id: UUID
    jsa_count: int = 0
    active_permits: int = 0
    overdue_capas: int = 0
    open_capas: int = 0
    audits_completed: int = 0
    toolbox_talks_this_month: int = 0
    expiring_certs_30d: int = 0
    avg_audit_score: float | None = None


# ── OSHA 300 + slim CorrectiveAction FSM (T6 / v3086) ───────────────────────


class OshaLogQuery(BaseModel):
    """Query parameters for the OSHA Form 300 CSV export."""

    project_id: UUID
    year: int = Field(..., ge=1900, le=2100)


class CorrectiveActionCreate(BaseModel):
    """Create a slim incident-scoped corrective action."""

    model_config = ConfigDict(str_strip_whitespace=True)

    incident_id: UUID
    description: str = Field(..., min_length=1, max_length=10000)
    assigned_to_user_id: UUID | None = None
    due_date: date | None = None
    status: str = Field(
        default="pending",
        pattern=r"^(pending|in_progress|verified|closed)$",
    )


class CorrectiveActionUpdate(BaseModel):
    """Partial update for a slim corrective action (no status changes)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    description: str | None = Field(default=None, min_length=1, max_length=10000)
    assigned_to_user_id: UUID | None = None
    due_date: date | None = None


class CATransitionRequest(BaseModel):
    """Body for ``POST /corrective-actions/{id}/transition``.

    The FSM is intentionally strict — ``pending → in_progress → verified
    → closed`` — so any other ``to_status`` is rejected with a 409.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    to_status: str = Field(
        ...,
        pattern=r"^(pending|in_progress|verified|closed)$",
    )
    verification_notes: str | None = Field(default=None, max_length=10000)


class CorrectiveActionResponse(BaseModel):
    """Slim corrective action returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    incident_id: UUID
    description: str
    assigned_to_user_id: UUID | None = None
    due_date: date | None = None
    status: str
    verified_by_user_id: UUID | None = None
    verified_at: datetime | None = None
    verification_notes: str | None = None
    created_at: datetime
    updated_at: datetime
