# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pydantic v2 request/response schemas for the Service & Maintenance module.

Status / priority / frequency enums are enforced via regex patterns so
validation works the same on Pydantic v2 and any downstream OpenAPI consumer.

Status transitions are NOT validated here - they belong in the service layer
where we know the *current* state. Schemas only enforce that the requested
status is one of the legal labels.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── Reusable enum patterns ─────────────────────────────────────────────────

PRIORITY_PATTERN = r"^(low|med|high|critical)$"
TICKET_STATUS_PATTERN = r"^(new|assigned|in_progress|resolved|closed|cancelled)$"
TICKET_SOURCE_PATTERN = r"^(manual|portal|email|api|auto_ppm)$"
WO_STATUS_PATTERN = r"^(scheduled|dispatched|in_progress|completed|billed|cancelled)$"
CONTRACT_STATUS_PATTERN = r"^(draft|active|expired|terminated)$"
ASSET_STATUS_PATTERN = r"^(active|decommissioned|maintenance)$"
SCHEDULE_FREQ_PATTERN = r"^(weekly|monthly|quarterly|semiannual|annual)$"
WO_ITEM_TYPE_PATTERN = r"^(labor|material|travel|fee)$"

# Loose ISO 8601 datetime - full string, validated again at the service layer.
ISO_DATETIME_PATTERN = r"^\d{4}-\d{2}-\d{2}(T| )\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+\-]\d{2}:?\d{2})?$"
ISO_DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"


# ── ServiceContract ────────────────────────────────────────────────────────


class ServiceContractCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    customer_id: UUID
    project_id: UUID | None = None
    title: str = Field(default="", max_length=255)
    description: str = Field(default="", max_length=10_000)
    period_start: str = Field(..., pattern=ISO_DATE_PATTERN)
    period_end: str = Field(..., pattern=ISO_DATE_PATTERN)
    sla_definition_id: UUID | None = None
    sla_tier: str = Field(default="standard", max_length=50)
    status: str = Field(default="draft", pattern=CONTRACT_STATUS_PATTERN)
    value: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    currency: str = Field(default="", max_length=10)
    auto_renew: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ServiceContractUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID | None = None
    title: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)
    period_start: str | None = Field(default=None, pattern=ISO_DATE_PATTERN)
    period_end: str | None = Field(default=None, pattern=ISO_DATE_PATTERN)
    sla_definition_id: UUID | None = None
    sla_tier: str | None = Field(default=None, max_length=50)
    status: str | None = Field(default=None, pattern=CONTRACT_STATUS_PATTERN)
    value: Decimal | None = Field(default=None, ge=Decimal("0"))
    currency: str | None = Field(default=None, max_length=10)
    auto_renew: bool | None = None
    metadata: dict[str, Any] | None = None


class ServiceContractResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    customer_id: UUID
    project_id: UUID | None = None
    contract_number: str
    title: str = ""
    description: str = ""
    period_start: str
    period_end: str
    sla_definition_id: UUID | None = None
    sla_tier: str = "standard"
    status: str = "draft"
    value: Decimal = Decimal("0")
    currency: str = ""
    auto_renew: bool = False
    created_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── ServiceAsset ───────────────────────────────────────────────────────────


class ServiceAssetCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    contract_id: UUID
    asset_tag: str | None = Field(default=None, max_length=64)
    asset_type: str = Field(..., min_length=1, max_length=64)
    name: str = Field(default="", max_length=255)
    location: str | None = Field(default=None, max_length=500)
    manufacturer: str | None = Field(default=None, max_length=255)
    model: str | None = Field(default=None, max_length=255)
    serial: str | None = Field(default=None, max_length=255)
    install_date: str | None = Field(default=None, pattern=ISO_DATE_PATTERN)
    warranty_until: str | None = Field(default=None, pattern=ISO_DATE_PATTERN)
    status: str = Field(default="active", pattern=ASSET_STATUS_PATTERN)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ServiceAssetUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    asset_tag: str | None = Field(default=None, max_length=64)
    asset_type: str | None = Field(default=None, max_length=64)
    name: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=500)
    manufacturer: str | None = Field(default=None, max_length=255)
    model: str | None = Field(default=None, max_length=255)
    serial: str | None = Field(default=None, max_length=255)
    install_date: str | None = Field(default=None, pattern=ISO_DATE_PATTERN)
    warranty_until: str | None = Field(default=None, pattern=ISO_DATE_PATTERN)
    status: str | None = Field(default=None, pattern=ASSET_STATUS_PATTERN)
    metadata: dict[str, Any] | None = None


class ServiceAssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    contract_id: UUID
    asset_tag: str | None = None
    asset_type: str
    name: str = ""
    location: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    serial: str | None = None
    install_date: str | None = None
    warranty_until: str | None = None
    status: str = "active"
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── ServiceTicket ──────────────────────────────────────────────────────────


class ServiceTicketCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    contract_id: UUID
    asset_id: UUID | None = None
    title: str = Field(default="", max_length=500)
    description: str = Field(default="", max_length=10_000)
    priority: str = Field(default="med", pattern=PRIORITY_PATTERN)
    # If omitted, the service layer uses utcnow().
    reported_at: str | None = Field(default=None, pattern=ISO_DATETIME_PATTERN)
    reported_by: str | None = Field(default=None, max_length=36)
    assigned_to: str | None = Field(default=None, max_length=36)
    # Channel the ticket came in on. Internal endpoints default to ``manual``;
    # portal-intake endpoints force this to ``portal``; PPM cron forces ``auto_ppm``.
    source: str = Field(default="manual", pattern=TICKET_SOURCE_PATTERN)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ServiceTicketUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    asset_id: UUID | None = None
    title: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=10_000)
    priority: str | None = Field(default=None, pattern=PRIORITY_PATTERN)
    # Status updates routed via dedicated endpoints (dispatch/resolve/close) so
    # only allow it here for admin-style corrections.
    status: str | None = Field(default=None, pattern=TICKET_STATUS_PATTERN)
    assigned_to: str | None = Field(default=None, max_length=36)
    sla_due_at: str | None = Field(default=None, pattern=ISO_DATETIME_PATTERN)
    metadata: dict[str, Any] | None = None


class ServiceTicketResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    contract_id: UUID
    asset_id: UUID | None = None
    ticket_number: str
    title: str = ""
    description: str = ""
    priority: str = "med"
    reported_at: str
    sla_due_at: str | None = None
    # Two-clock SLA tracking: deadlines for first response and resolution,
    # plus the timestamp the SLA clock was paused (awaiting_customer state).
    response_due_at: str | None = None
    resolution_due_at: str | None = None
    awaiting_customer_since: str | None = None
    status: str = "new"
    source: str = "manual"
    reported_by: str | None = None
    assigned_to: str | None = None
    resolved_at: str | None = None
    closed_at: str | None = None
    sla_breach_notified_at: str | None = None
    # T10: ground-truth breach marker (set by check_breaches()) + link to
    # the recurring schedule that materialised this ticket (NULL ⇒ ad-hoc).
    sla_breached_at: str | None = None
    recurring_schedule_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class TicketDispatchRequest(BaseModel):
    """Body for POST /tickets/{id}/dispatch."""

    technician_id: str = Field(..., min_length=1, max_length=36)
    scheduled_for: str | None = Field(default=None, pattern=ISO_DATETIME_PATTERN)
    notes: str = Field(default="", max_length=2000)


class TicketReopenRequest(BaseModel):
    """Body for POST /tickets/{id}/reopen."""

    reason: str = Field(..., min_length=1, max_length=2000)


class TicketAwaitCustomerRequest(BaseModel):
    """Body for POST /tickets/{id}/await-customer."""

    note: str = Field(default="", max_length=2000)


# ── WorkOrder + items ──────────────────────────────────────────────────────


class WorkOrderItemCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    item_type: str = Field(default="labor", pattern=WO_ITEM_TYPE_PATTERN)
    description: str = Field(default="", max_length=2000)
    quantity: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    unit: str = Field(default="", max_length=20)
    unit_rate: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    total: Decimal | None = Field(default=None, ge=Decimal("0"))
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkOrderItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    work_order_id: UUID
    item_type: str
    description: str = ""
    quantity: Decimal = Decimal("0")
    unit: str = ""
    unit_rate: Decimal = Decimal("0")
    total: Decimal = Decimal("0")
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class WorkOrderCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    ticket_id: UUID
    scheduled_for: str | None = Field(default=None, pattern=ISO_DATETIME_PATTERN)
    technician_id: str | None = Field(default=None, max_length=36)
    status: str = Field(default="scheduled", pattern=WO_STATUS_PATTERN)
    items: list[WorkOrderItemCreate] = Field(default_factory=list)
    currency: str = Field(default="", max_length=10)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkOrderUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    scheduled_for: str | None = Field(default=None, pattern=ISO_DATETIME_PATTERN)
    technician_id: str | None = Field(default=None, max_length=36)
    status: str | None = Field(default=None, pattern=WO_STATUS_PATTERN)
    debrief_summary: str | None = Field(default=None, max_length=10_000)
    currency: str | None = Field(default=None, max_length=10)
    metadata: dict[str, Any] | None = None


class WorkOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    ticket_id: UUID
    work_order_number: str
    scheduled_for: str | None = None
    technician_id: str | None = None
    status: str = "scheduled"
    debrief_summary: str = ""
    customer_signature: str | None = None
    billed_amount: Decimal = Decimal("0")
    currency: str = ""
    completed_at: str | None = None
    billed_at: str | None = None
    items: list[WorkOrderItemResponse] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class ServiceTicketListResponse(BaseModel):
    """One page of service tickets plus the size of the matching set.

    ``total`` counts the rows the query matched, not the length of ``items``.
    The contract or project scope and the status and priority filters are all
    applied before the count is taken, so a zero here means this question found
    nothing rather than the queue holding nothing.
    """

    model_config = ConfigDict(from_attributes=True)

    items: list[ServiceTicketResponse]
    total: int
    offset: int
    limit: int


class WorkOrderListResponse(BaseModel):
    """One page of work orders plus the size of the matching set.

    ``total`` counts the rows the query matched, not the length of ``items``.
    The project scope and the status and technician filters are applied before
    the count is taken, so a zero here means this question found nothing rather
    than the board holding nothing.
    """

    model_config = ConfigDict(from_attributes=True)

    items: list[WorkOrderResponse]
    total: int
    offset: int
    limit: int


# ── Debrief (P-C-S) ────────────────────────────────────────────────────────


class DebriefReportCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    problem: str = Field(default="", max_length=10_000)
    cause: str = Field(default="", max_length=10_000)
    solution: str = Field(default="", max_length=10_000)
    root_cause_category: str | None = Field(default=None, max_length=64)
    follow_up_required: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class DebriefReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    work_order_id: UUID
    problem: str = ""
    cause: str = ""
    solution: str = ""
    root_cause_category: str | None = None
    follow_up_required: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class WorkOrderCompleteRequest(BaseModel):
    """Body for POST /work-orders/{id}/complete."""

    debrief: DebriefReportCreate
    customer_signature: str | None = Field(default=None, max_length=200_000)


# ── SLA definitions ───────────────────────────────────────────────────────


class SLADefinitionCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    response_time_minutes: int = Field(default=240, ge=1)
    resolution_time_minutes: int = Field(default=1440, ge=1)
    severity_levels: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class SLADefinitionUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    response_time_minutes: int | None = Field(default=None, ge=1)
    resolution_time_minutes: int | None = Field(default=None, ge=1)
    severity_levels: dict[str, Any] | None = None
    is_active: bool | None = None
    metadata: dict[str, Any] | None = None


class SLADefinitionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    name: str
    description: str = ""
    response_time_minutes: int = 240
    resolution_time_minutes: int = 1440
    severity_levels: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Schedules / Checklists ────────────────────────────────────────────────


class ServiceScheduleCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    asset_id: UUID
    frequency: str = Field(default="quarterly", pattern=SCHEDULE_FREQ_PATTERN)
    next_due_date: str = Field(..., pattern=ISO_DATE_PATTERN)
    checklist_template_id: UUID | None = None
    is_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class ServiceScheduleUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    frequency: str | None = Field(default=None, pattern=SCHEDULE_FREQ_PATTERN)
    next_due_date: str | None = Field(default=None, pattern=ISO_DATE_PATTERN)
    last_completed_at: str | None = Field(default=None, pattern=ISO_DATETIME_PATTERN)
    checklist_template_id: UUID | None = None
    is_active: bool | None = None
    metadata: dict[str, Any] | None = None


class ServiceScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    asset_id: UUID
    frequency: str
    next_due_date: str
    last_completed_at: str | None = None
    checklist_template_id: UUID | None = None
    is_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class AssetChecklistCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=2000)
    asset_type: str | None = Field(default=None, max_length=64)
    items: list[dict[str, Any]] = Field(default_factory=list)
    is_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssetChecklistUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    asset_type: str | None = Field(default=None, max_length=64)
    items: list[dict[str, Any]] | None = None
    is_active: bool | None = None
    metadata: dict[str, Any] | None = None


class AssetChecklistResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    name: str
    description: str = ""
    asset_type: str | None = None
    items: list[dict[str, Any]] = Field(default_factory=list)
    is_active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Dashboard summary ─────────────────────────────────────────────────────


class ContractDashboardResponse(BaseModel):
    """Aggregate KPIs for a single contract's dashboard widget."""

    contract_id: UUID
    contract_number: str
    customer_id: UUID
    status: str
    open_tickets: int = 0
    in_progress_tickets: int = 0
    sla_breaches: int = 0
    scheduled_work_orders: int = 0
    completed_work_orders_30d: int = 0
    billed_amount_total: Decimal = Decimal("0")
    monthly_revenue: Decimal = Decimal("0")
    currency: str = ""
    upcoming_ppm_30d: int = 0


# ── SLA escalation + NCR-from-WO ──────────────────────────────────────────


class SLABreachEntry(BaseModel):
    """One row in an SLA-breach scan result."""

    ticket_id: UUID
    ticket_number: str
    contract_id: UUID
    priority: str
    sla_due_at: str
    minutes_overdue: int
    assigned_to: str | None = None


class SLABreachScanResponse(BaseModel):
    """Result of a manager-triggered SLA scan over open tickets."""

    scanned_at: str
    total_open: int
    breaches: list[SLABreachEntry] = Field(default_factory=list)
    newly_notified: int = 0


class NCRFromWorkOrderRequest(BaseModel):
    """Body for POST /work-orders/{id}/file-ncr.

    Creates a real NCR on the parent project. The project_id is derived from
    the work-order → ticket → contract chain; if the contract has no project,
    a 409 is returned (NCR requires a project).
    """

    title: str = Field(..., min_length=1, max_length=500)
    description: str = Field(..., min_length=1, max_length=10_000)
    ncr_type: str = Field(default="quality", max_length=50)
    severity: str = Field(default="medium", max_length=20)
    location_description: str | None = Field(default=None, max_length=500)


class NCRFromWorkOrderResponse(BaseModel):
    """NCR creation response - minimal payload pointing at the new NCR."""

    ncr_id: UUID
    ncr_number: str
    project_id: UUID
    work_order_id: UUID


# ── Recurring schedules (RRULE-driven) ─────────────────────────────────────


# Loose RRULE pattern: must contain FREQ= and use only RFC 5545-ish tokens
# (no surrounding RRULE: prefix, no line folds). Strict parsing happens in
# the service layer where we already iterate the RRULE.
RRULE_PATTERN = r"^[A-Z][A-Z0-9=;,+\-:/ TZ]{2,199}$"


class RecurringScheduleCreate(BaseModel):
    """Payload for POST /service/recurring-schedules/."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=200)
    rrule: str = Field(..., pattern=RRULE_PATTERN)
    # Project / contract scope - both optional so tenant-wide fleet schedules
    # work too. The materialiser requires ``contract_id`` either here OR in
    # ``template_ticket_data`` to create a ticket.
    project_id: UUID | None = None
    contract_id: UUID | None = None
    # ServiceTicketCreate-shaped JSON. Required key: ``contract_id`` (unless
    # set at the schedule level). Optional: title, description, priority,
    # asset_id, metadata. Strict validation deferred to materialise time so
    # callers can iterate templates without re-validating an empty draft.
    template_ticket_data: dict[str, Any] = Field(default_factory=dict)
    # Optional first-run override. If omitted, computed from RRULE.
    next_run_at: str | None = Field(default=None, pattern=ISO_DATETIME_PATTERN)
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class RecurringScheduleUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=200)
    rrule: str | None = Field(default=None, pattern=RRULE_PATTERN)
    project_id: UUID | None = None
    contract_id: UUID | None = None
    template_ticket_data: dict[str, Any] | None = None
    next_run_at: str | None = Field(default=None, pattern=ISO_DATETIME_PATTERN)
    enabled: bool | None = None
    metadata: dict[str, Any] | None = None


class RecurringScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID | None = None
    contract_id: UUID | None = None
    name: str
    rrule: str
    template_ticket_data: dict[str, Any] = Field(default_factory=dict)
    next_run_at: str | None = None
    last_run_at: str | None = None
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    created_at: datetime
    updated_at: datetime


class RecurringScheduleMaterializeResponse(BaseModel):
    """Result of POST /service/recurring-schedules/{id}/materialize."""

    schedule_id: UUID
    ticket_id: UUID | None = None
    ticket_number: str | None = None
    next_run_at: str | None = None
    materialized: bool = False
    reason: str | None = None


# ── SLA-breach check (T10) ────────────────────────────────────────────────


class SLABreachCheckResponse(BaseModel):
    """Result of POST /service/tickets/check-breaches.

    Distinct from ``SLABreachScanResponse`` (the long-running scan that also
    emits events) - this one is the simple admin trigger that flips
    ``sla_breached_at`` for every now-overdue ticket and returns the count.
    """

    checked_at: str
    newly_breached: int = 0
    total_breached: int = 0
    breached_ticket_ids: list[UUID] = Field(default_factory=list)


# ── SLA overdue summary (get_sla_overdue) ────────────────────────────────────


class SLAOverdueReport(BaseModel):
    """Single ticket overdue on response or resolution SLA."""

    ticket_id: UUID
    ticket_number: str
    contract_id: UUID
    priority: str
    status: str
    response_due_at: str | None = None
    resolution_due_at: str | None = None
    response_overdue_minutes: int = 0
    resolution_overdue_minutes: int = 0


class SLAOverdueSummaryResponse(BaseModel):
    """Summary returned by GET /service/sla/overdue."""

    checked_at: str
    total_open: int = 0
    response_overdue: list[SLAOverdueReport] = Field(default_factory=list)
    resolution_overdue: list[SLAOverdueReport] = Field(default_factory=list)
