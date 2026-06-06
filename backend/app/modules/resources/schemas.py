"""‌⁠‍Resources Pydantic schemas - request/response models (Pydantic v2)."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── Resource ─────────────────────────────────────────────────────────────


class ResourceCreate(BaseModel):
    """‌⁠‍Create a new resource."""

    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=255)
    resource_type: str = Field(
        default="person",
        pattern=r"^(person|crew|equipment|subcontractor)$",
    )
    home_project_id: UUID | None = None
    contact_id: UUID | None = None
    default_cost_rate: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str = Field(default="", max_length=3)
    # Max concurrent allocation percent the resource can absorb per bucket.
    # None => capacity unknown (leveling will not flag over-allocation).
    capacity_percent: int | None = Field(default=None, ge=0, le=10000)
    status: str = Field(
        default="active",
        pattern=r"^(active|inactive|on_leave)$",
    )
    avatar_url: str | None = Field(default=None, max_length=1024)
    notes: str = Field(default="", max_length=5000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResourceUpdate(BaseModel):
    """‌⁠‍Partial update for a resource."""

    model_config = ConfigDict(str_strip_whitespace=True)

    code: str | None = Field(default=None, min_length=1, max_length=50)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    resource_type: str | None = Field(
        default=None,
        pattern=r"^(person|crew|equipment|subcontractor)$",
    )
    home_project_id: UUID | None = None
    contact_id: UUID | None = None
    default_cost_rate: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=3)
    capacity_percent: int | None = Field(default=None, ge=0, le=10000)
    status: str | None = Field(
        default=None,
        pattern=r"^(active|inactive|on_leave)$",
    )
    avatar_url: str | None = Field(default=None, max_length=1024)
    notes: str | None = Field(default=None, max_length=5000)
    metadata: dict[str, Any] | None = None


class ResourceResponse(BaseModel):
    """Resource returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    code: str
    name: str
    resource_type: str
    home_project_id: UUID | None = None
    contact_id: UUID | None = None
    default_cost_rate: Decimal = Decimal("0")
    currency: str = ""
    capacity_percent: int | None = None
    status: str = "active"
    avatar_url: str | None = None
    notes: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Skill ────────────────────────────────────────────────────────────────


class SkillCreate(BaseModel):
    """Create a new skill."""

    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=255)
    category: str = Field(
        default="trade",
        pattern=r"^(trade|certification|language|other)$",
    )
    description: str = Field(default="", max_length=5000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SkillUpdate(BaseModel):
    """Partial update for a skill."""

    model_config = ConfigDict(str_strip_whitespace=True)

    code: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    category: str | None = Field(
        default=None,
        pattern=r"^(trade|certification|language|other)$",
    )
    description: str | None = Field(default=None, max_length=5000)
    metadata: dict[str, Any] | None = None


class SkillResponse(BaseModel):
    """Skill returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    code: str
    name: str
    category: str = "trade"
    description: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── ResourceSkill ────────────────────────────────────────────────────────


class ResourceSkillCreate(BaseModel):
    """Attach a skill to a resource."""

    skill_id: UUID
    level: str = Field(default="competent", pattern=r"^(basic|competent|expert)$")
    acquired_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    expires_at: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    notes: str = Field(default="", max_length=2000)


class ResourceSkillResponse(BaseModel):
    """ResourceSkill returned from the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    resource_id: UUID
    skill_id: UUID
    level: str = "competent"
    acquired_at: str | None = None
    expires_at: str | None = None
    notes: str = ""
    created_at: datetime
    updated_at: datetime


# ── Certification ───────────────────────────────────────────────────────


class CertificationCreate(BaseModel):
    """Create a certification."""

    model_config = ConfigDict(str_strip_whitespace=True)

    resource_id: UUID
    cert_type: str = Field(..., min_length=1, max_length=128)
    cert_number: str | None = Field(default=None, max_length=128)
    issued_by: str | None = Field(default=None, max_length=255)
    issue_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    valid_until: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    document_url: str | None = Field(default=None, max_length=1024)
    status: str = Field(default="valid", pattern=r"^(valid|expired|revoked)$")
    notes: str = Field(default="", max_length=5000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CertificationUpdate(BaseModel):
    """Partial update for a certification."""

    model_config = ConfigDict(str_strip_whitespace=True)

    cert_type: str | None = Field(default=None, min_length=1, max_length=128)
    cert_number: str | None = Field(default=None, max_length=128)
    issued_by: str | None = Field(default=None, max_length=255)
    issue_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    valid_until: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    document_url: str | None = Field(default=None, max_length=1024)
    status: str | None = Field(default=None, pattern=r"^(valid|expired|revoked)$")
    notes: str | None = Field(default=None, max_length=5000)
    metadata: dict[str, Any] | None = None


class CertificationResponse(BaseModel):
    """Certification returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    resource_id: UUID
    cert_type: str
    cert_number: str | None = None
    issued_by: str | None = None
    issue_date: str | None = None
    valid_until: str | None = None
    document_url: str | None = None
    status: str = "valid"
    notes: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── AvailabilityWindow ──────────────────────────────────────────────────


class AvailabilityWindowCreate(BaseModel):
    """Create an availability window."""

    model_config = ConfigDict(str_strip_whitespace=True)

    resource_id: UUID
    window_type: str = Field(
        default="available",
        pattern=r"^(available|unavailable|holiday|sick)$",
    )
    start_at: datetime
    end_at: datetime
    recurrence_rule: str | None = Field(default=None, max_length=512)
    note: str = Field(default="", max_length=2000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AvailabilityWindowUpdate(BaseModel):
    """Partial update for an availability window."""

    model_config = ConfigDict(str_strip_whitespace=True)

    window_type: str | None = Field(
        default=None,
        pattern=r"^(available|unavailable|holiday|sick)$",
    )
    start_at: datetime | None = None
    end_at: datetime | None = None
    recurrence_rule: str | None = Field(default=None, max_length=512)
    note: str | None = Field(default=None, max_length=2000)
    metadata: dict[str, Any] | None = None


class AvailabilityWindowResponse(BaseModel):
    """AvailabilityWindow returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    resource_id: UUID
    window_type: str = "available"
    start_at: datetime
    end_at: datetime
    recurrence_rule: str | None = None
    note: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Assignment ──────────────────────────────────────────────────────────


class AssignmentCreate(BaseModel):
    """Create an assignment directly (skips propose workflow)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    resource_id: UUID
    project_id: UUID | None = None
    task_id: UUID | None = None
    work_order_id: str | None = Field(default=None, max_length=36)
    start_at: datetime
    end_at: datetime
    allocation_percent: int = Field(default=100, ge=0, le=100)
    status: str = Field(
        default="proposed",
        pattern=r"^(proposed|confirmed|in_progress|completed|cancelled)$",
    )
    cost_rate: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str = Field(default="", max_length=3)
    notes: str = Field(default="", max_length=5000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssignmentUpdate(BaseModel):
    """Partial update for an assignment."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID | None = None
    task_id: UUID | None = None
    work_order_id: str | None = Field(default=None, max_length=36)
    start_at: datetime | None = None
    end_at: datetime | None = None
    allocation_percent: int | None = Field(default=None, ge=0, le=100)
    status: str | None = Field(
        default=None,
        pattern=r"^(proposed|confirmed|in_progress|completed|cancelled)$",
    )
    cost_rate: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=3)
    notes: str | None = Field(default=None, max_length=5000)
    metadata: dict[str, Any] | None = None


class AssignmentResponse(BaseModel):
    """Assignment returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    resource_id: UUID
    project_id: UUID | None = None
    # Human-readable project / task labels resolved for the dispatcher board so
    # the UI can render a clickable assignment row instead of a bare UUID. They
    # are populated by the board endpoint only; other endpoints leave them blank.
    project_name: str = ""
    task_id: UUID | None = None
    task_name: str = ""
    work_order_id: str | None = None
    start_at: datetime
    end_at: datetime
    allocation_percent: int = 100
    status: str = "proposed"
    cost_rate: Decimal = Decimal("0")
    currency: str = ""
    notes: str = ""
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class AssignmentProposeRequest(BaseModel):
    """Request to propose an assignment with conflict + skill checks."""

    model_config = ConfigDict(str_strip_whitespace=True)

    resource_id: UUID
    project_id: UUID | None = None
    task_id: UUID | None = None
    work_order_id: str | None = Field(default=None, max_length=36)
    start_at: datetime
    end_at: datetime
    allocation_percent: int = Field(default=100, ge=0, le=100)
    required_skills: list[UUID] = Field(default_factory=list)
    cost_rate: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str = Field(default="", max_length=3)
    notes: str = Field(default="", max_length=5000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConflictDetail(BaseModel):
    """Detail of an assignment conflict."""

    resource_id: UUID
    conflicting_assignment_id: UUID | None = None
    reason: str
    overlap_start: datetime | None = None
    overlap_end: datetime | None = None
    total_allocation_percent: int | None = None


# ── Portfolio capacity planning ─────────────────────────────────────────


class PortfolioBucket(BaseModel):
    """A time bucket on the portfolio capacity heatmap."""

    index: int
    start: datetime
    end: datetime
    label: str


class PortfolioCellProject(BaseModel):
    """Per-project share of a resource's allocation inside one bucket."""

    project_id: UUID | None = None
    project_name: str
    allocation_percent: int


class PortfolioCell(BaseModel):
    """One resource × one bucket: total allocation + per-project breakdown."""

    bucket_index: int
    allocation_percent: int
    over_allocated: bool = False
    cross_project: bool = False
    projects: list[PortfolioCellProject] = Field(default_factory=list)


class PortfolioResourceRow(BaseModel):
    """A resource row across all buckets in the heatmap."""

    resource_id: UUID
    code: str
    name: str
    resource_type: str
    is_floating: bool
    peak_allocation_percent: int
    has_conflict: bool
    cells: list[PortfolioCell] = Field(default_factory=list)


class PortfolioCapacityResponse(BaseModel):
    """Org-wide resource utilization heatmap for capacity planning."""

    start: datetime
    end: datetime
    bucket: str
    buckets: list[PortfolioBucket]
    resources: list[PortfolioResourceRow]
    total_resources: int
    floating_resources: int
    conflict_resources: int


# ── Portfolio resource leveling ─────────────────────────────────────────


class LevelingBooking(BaseModel):
    """A single assignment contributing to an over-allocated bucket.

    Identifies the booking a planner could shift or spread to relieve the
    overload. Read-only - no mutation is performed by the leveling endpoint.
    """

    assignment_id: UUID
    project_id: UUID | None = None
    project_name: str
    allocation_percent: int
    status: str
    start_at: datetime
    end_at: datetime


class LevelingSuggestion(BaseModel):
    """A human-confirmed leveling action proposed for one overloaded bucket.

    ``action`` is advisory only:
        * ``shift``  - move the smallest contributing booking out of the bucket.
        * ``spread`` - reduce the booking's allocation so the bucket fits capacity.
    """

    action: str
    bucket_index: int
    target_assignment_id: UUID
    target_project_id: UUID | None = None
    target_project_name: str
    overflow_percent: int
    suggested_allocation_percent: int
    rationale: str


class LevelingCell(BaseModel):
    """One resource x one bucket in the leveling grid."""

    bucket_index: int
    allocation_percent: int
    capacity_percent: int | None = None
    # True only when capacity is known AND total > capacity.
    over_allocated: bool = False
    # True when the resource has no declared capacity for this bucket.
    capacity_unknown: bool = False
    cross_project: bool = False
    bookings: list[LevelingBooking] = Field(default_factory=list)


class LevelingResourceRow(BaseModel):
    """A resource row across all buckets in the leveling grid."""

    resource_id: UUID
    code: str
    name: str
    resource_type: str
    is_floating: bool
    capacity_percent: int | None = None
    capacity_unknown: bool
    peak_allocation_percent: int
    overload_bucket_count: int
    has_overload: bool
    cells: list[LevelingCell] = Field(default_factory=list)
    suggestions: list[LevelingSuggestion] = Field(default_factory=list)


class PortfolioLevelingResponse(BaseModel):
    """Org-wide (or project-scoped) resource-leveling grid with overload flags.

    Read-only aggregation. Over-allocation is flagged only against a resource's
    declared ``capacity_percent``; resources without a capacity are surfaced as
    ``capacity_unknown`` and are never counted as overloaded.
    """

    start: datetime
    end: datetime
    bucket: str
    project_id: UUID | None = None
    buckets: list[PortfolioBucket]
    resources: list[LevelingResourceRow]
    total_resources: int
    overloaded_resources: int
    capacity_unknown_resources: int
    total_suggestions: int


# ── ResourceRequest ─────────────────────────────────────────────────────


class ResourceRequestCreate(BaseModel):
    """Create a resource request."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    title: str = Field(..., min_length=1, max_length=500)
    description: str = Field(default="", max_length=5000)
    required_skills: list[UUID] = Field(default_factory=list)
    start_at: datetime
    end_at: datetime
    quantity: int = Field(default=1, ge=1, le=999)
    priority: str = Field(
        default="med",
        pattern=r"^(low|med|high|critical)$",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResourceRequestUpdate(BaseModel):
    """Partial update for a resource request."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=5000)
    required_skills: list[UUID] | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    quantity: int | None = Field(default=None, ge=1, le=999)
    priority: str | None = Field(
        default=None,
        pattern=r"^(low|med|high|critical)$",
    )
    status: str | None = Field(
        default=None,
        pattern=r"^(open|fulfilled|cancelled)$",
    )
    metadata: dict[str, Any] | None = None


class ResourceRequestResponse(BaseModel):
    """ResourceRequest returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    requested_by: str | None = None
    title: str
    description: str = ""
    required_skills: list[UUID] = Field(default_factory=list)
    start_at: datetime
    end_at: datetime
    quantity: int = 1
    priority: str = "med"
    status: str = "open"
    fulfilled_assignment_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class ResourceRequestFulfill(BaseModel):
    """Fulfill a resource request by attaching a resource."""

    resource_id: UUID
    cost_rate: Decimal = Field(default=Decimal("0"), ge=0)
    currency: str = Field(default="", max_length=3)
    allocation_percent: int = Field(default=100, ge=0, le=100)
    notes: str = Field(default="", max_length=5000)


# ── ResourceLink ────────────────────────────────────────────────────────


class ResourceLinkCreate(BaseModel):
    """Create a link between two resources."""

    model_config = ConfigDict(str_strip_whitespace=True)

    primary_resource_id: UUID
    secondary_resource_id: UUID
    link_type: str = Field(
        default="buddy",
        pattern=r"^(operator|buddy|crew_member)$",
    )
    notes: str = Field(default="", max_length=2000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResourceLinkUpdate(BaseModel):
    """Partial update for a resource link."""

    model_config = ConfigDict(str_strip_whitespace=True)

    link_type: str | None = Field(
        default=None,
        pattern=r"^(operator|buddy|crew_member)$",
    )
    notes: str | None = Field(default=None, max_length=2000)
    metadata: dict[str, Any] | None = None


class ResourceLinkResponse(BaseModel):
    """ResourceLink returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    primary_resource_id: UUID
    secondary_resource_id: UUID
    link_type: str = "buddy"
    notes: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Dashboard / Utilization / Board ─────────────────────────────────────


class UtilizationResponse(BaseModel):
    """Utilization metrics for a resource over a period."""

    resource_id: UUID
    period_start: datetime
    period_end: datetime
    utilization_percent: float = 0.0
    hours_assigned: float = 0.0
    hours_available: float = 0.0


class ResourceDashboardResponse(BaseModel):
    """Dashboard payload for a single resource."""

    resource: ResourceResponse
    active_assignments: list[AssignmentResponse] = Field(default_factory=list)
    upcoming_assignments: list[AssignmentResponse] = Field(default_factory=list)
    certifications: list[CertificationResponse] = Field(default_factory=list)
    skills: list[ResourceSkillResponse] = Field(default_factory=list)
    expiring_certifications_count: int = 0
    utilization_30d: UtilizationResponse | None = None


class BoardEntry(BaseModel):
    """A single resource + its assignments in the dispatcher window."""

    resource: ResourceResponse
    assignments: list[AssignmentResponse] = Field(default_factory=list)


class BoardResponse(BaseModel):
    """Flat dispatcher-board response."""

    period_start: datetime
    period_end: datetime
    project_id: UUID | None = None
    entries: list[BoardEntry] = Field(default_factory=list)


class BoardConflict(BaseModel):
    """A resource-level conflict in the dispatcher window."""

    resource_id: UUID
    resource_name: str
    conflicts: list[ConflictDetail] = Field(default_factory=list)
