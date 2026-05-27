"""‌⁠‍Business logic for the Service & Maintenance module.

Houses:
    - State-machine helpers (pure functions, independently testable).
    - ``ServiceService`` orchestrator that composes the repos.

The state machines are deliberately implemented as plain dicts of allowed
transitions so unit tests stay trivial and the contract is visible at a glance.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.service.models import (
    AssetInspectionChecklist,
    DebriefReport,
    ServiceAsset,
    ServiceContract,
    ServiceRecurringSchedule,
    ServiceSchedule,
    ServiceTicket,
    ServiceWorkOrder,
    ServiceWorkOrderItem,
    SLADefinition,
)
from app.modules.service.repository import (
    AssetRepository,
    ChecklistRepository,
    ContractRepository,
    DebriefRepository,
    RecurringScheduleRepository,
    ScheduleRepository,
    SLADefinitionRepository,
    TicketRepository,
    WorkOrderItemRepository,
    WorkOrderRepository,
)
from app.modules.service.schemas import (
    AssetChecklistCreate,
    AssetChecklistUpdate,
    ContractDashboardResponse,
    NCRFromWorkOrderRequest,
    NCRFromWorkOrderResponse,
    RecurringScheduleCreate,
    RecurringScheduleMaterializeResponse,
    RecurringScheduleUpdate,
    ServiceAssetCreate,
    ServiceAssetUpdate,
    ServiceContractCreate,
    ServiceContractUpdate,
    ServiceScheduleCreate,
    ServiceScheduleUpdate,
    ServiceTicketCreate,
    ServiceTicketUpdate,
    SLABreachCheckResponse,
    SLABreachEntry,
    SLABreachScanResponse,
    SLADefinitionCreate,
    SLADefinitionUpdate,
    SLAOverdueReport,
    SLAOverdueSummaryResponse,
    TicketAwaitCustomerRequest,
    TicketDispatchRequest,
    TicketReopenRequest,
    WorkOrderCompleteRequest,
    WorkOrderCreate,
    WorkOrderItemCreate,
    WorkOrderUpdate,
)

logger = logging.getLogger(__name__)


# ── State-machine helpers (pure functions) ────────────────────────────────

_TICKET_TRANSITIONS: dict[str, set[str]] = {
    "new": {"assigned", "in_progress", "cancelled"},
    "assigned": {"in_progress", "awaiting_customer", "cancelled", "new"},
    "in_progress": {"resolved", "awaiting_customer", "cancelled"},
    # awaiting_customer: tech is waiting on the customer (access, confirmation,
    # spare-parts delivery). The ticket can resume to in_progress or be cancelled.
    "awaiting_customer": {"in_progress", "cancelled"},
    "resolved": {"closed", "in_progress"},
    # closed → in_progress is the reopen path. The window gate is enforced
    # in reopen_ticket(); assert_transition() only checks the graph.
    "closed": {"in_progress"},
    "cancelled": set(),
}

# How many days after closed_at a ticket may be reopened via POST /reopen.
# Past this window the ticket is immutable and a new ticket must be filed.
TICKET_REOPEN_WINDOW_DAYS: int = 30

_WORK_ORDER_TRANSITIONS: dict[str, set[str]] = {
    "scheduled": {"dispatched", "cancelled"},
    "dispatched": {"in_progress", "cancelled"},
    "in_progress": {"completed", "cancelled"},
    # R7: verified = supervisor sign-off before billing/closing
    "completed": {"verified", "billed"},  # billed kept for legacy callers
    "verified": {"billed", "closed"},
    "billed": {"closed"},
    "closed": set(),  # terminal
    "cancelled": {"scheduled"},  # allow re-opening a cancelled WO
}

# States where a WO is effectively done for the purposes of sub-task cascade
_WO_TERMINAL_LIKE: frozenset[str] = frozenset({"completed", "verified", "billed", "closed", "cancelled"})

_CONTRACT_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"active", "terminated"},
    "active": {"expired", "terminated"},
    "expired": {"active", "terminated"},
    "terminated": set(),
}


def allowed_ticket_transitions(current: str) -> set[str]:
    """‌⁠‍Return the set of legal next statuses for a ticket in ``current`` state."""
    return _TICKET_TRANSITIONS.get(current, set())


def allowed_work_order_transitions(current: str) -> set[str]:
    """‌⁠‍Return the set of legal next statuses for a work order in ``current`` state."""
    return _WORK_ORDER_TRANSITIONS.get(current, set())


def allowed_contract_transitions(current: str) -> set[str]:
    """Return the set of legal next statuses for a contract in ``current`` state."""
    return _CONTRACT_TRANSITIONS.get(current, set())


def assert_transition(current: str, target: str, *, machine: str) -> None:
    """Raise HTTPException 409 if ``current → target`` is not a legal transition."""
    if machine == "ticket":
        allowed = allowed_ticket_transitions(current)
    elif machine == "work_order":
        allowed = allowed_work_order_transitions(current)
    elif machine == "contract":
        allowed = allowed_contract_transitions(current)
    else:  # pragma: no cover — caller bug
        raise ValueError(f"Unknown state machine: {machine}")

    if target == current:
        return
    if target not in allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Invalid {machine} transition: '{current}' → '{target}'. "
                f"Allowed: {sorted(allowed) or 'none (terminal state)'}"
            ),
        )


def compute_sla_due_at(
    reported_at: datetime,
    sla: SLADefinition | None,
    *,
    priority: str = "med",
) -> datetime | None:
    """Compute ticket.sla_due_at = reported_at + response_time(priority).

    Priority-aware override: when ``sla.severity_levels`` contains an entry
    for ``priority`` with ``response_time_minutes``, that wins; otherwise we
    fall back to the SLA's default ``response_time_minutes``.
    """
    if sla is None:
        return None

    minutes: int = sla.response_time_minutes
    severity_overrides = sla.severity_levels or {}
    if isinstance(severity_overrides, dict):
        override = severity_overrides.get(priority)
        if isinstance(override, dict):
            candidate = override.get("response_time_minutes")
            if isinstance(candidate, int) and candidate > 0:
                minutes = candidate
        elif isinstance(override, int) and override > 0:
            minutes = override

    return reported_at + timedelta(minutes=minutes)


# ── T10: priority-driven SLA lookup ───────────────────────────────────────

# Hours-from-reported until breach, by priority. Both the historical
# (low/med/high/critical) vocabulary used by the existing ticket schema and
# the ServiceTitan-style (low/normal/high/urgent) vocabulary used by the
# T10 spec resolve through the same table so the two stay interchangeable.
_PRIORITY_SLA_HOURS: dict[str, int] = {
    "urgent": 4,
    "critical": 4,
    "high": 8,
    "normal": 24,
    "med": 24,
    "low": 72,
}


def priority_sla_minutes(priority: str | None) -> int:
    """Return the SLA window (minutes) for ``priority``.

    Unknown priorities fall back to the ``normal`` bucket (24h) rather than
    raising — a stray UI value should never make a ticket SLA-immortal.
    """
    if priority is None:
        return _PRIORITY_SLA_HOURS["normal"] * 60
    return _PRIORITY_SLA_HOURS.get(priority.lower(), _PRIORITY_SLA_HOURS["normal"]) * 60


def compute_sla_due(ticket: ServiceTicket) -> datetime:
    """T10: priority-driven SLA due-at, independent of any SLADefinition.

    Used by ``check_breaches()`` and by the recurring-schedule materialiser,
    both of which need to stamp ``sla_due_at`` without first looking up the
    parent contract's optional SLA tier. The full SLADefinition-aware path
    is still :func:`compute_sla_due_at` (kept for create_ticket()).
    """
    reported = ticket.reported_at
    if not reported:
        reported_dt = datetime.now(UTC)
    else:
        reported_dt = _parse_iso(reported)
    return reported_dt + timedelta(minutes=priority_sla_minutes(ticket.priority))


def compute_sla_response_and_resolution(
    reported_at: datetime,
    sla: SLADefinition | None,
    *,
    priority: str = "med",
) -> tuple[datetime | None, datetime | None]:
    """Return ``(response_due_at, resolution_due_at)`` for a ticket.

    Unlike the legacy :func:`compute_sla_due_at` (which only tracked the
    first-response deadline), this helper surfaces BOTH clocks so the UI
    and :meth:`ServiceService.get_sla_overdue` can independently report
    "response overdue" vs "resolution overdue".

    Returns ``(None, None)`` when no SLA definition is attached to the contract.
    """
    if sla is None:
        return None, None

    def _pick(key: str, default: int) -> int:
        overrides = sla.severity_levels or {}
        if isinstance(overrides, dict):
            override = overrides.get(priority)
            if isinstance(override, dict):
                candidate = override.get(key)
                if isinstance(candidate, int) and candidate > 0:
                    return candidate
            elif isinstance(override, int) and override > 0:
                if key == "response_time_minutes":
                    return override
        return default

    response_minutes = _pick("response_time_minutes", sla.response_time_minutes)
    resolution_minutes = _pick("resolution_time_minutes", sla.resolution_time_minutes)
    return (
        reported_at + timedelta(minutes=response_minutes),
        reported_at + timedelta(minutes=resolution_minutes),
    )


def compute_work_order_total(items: list[ServiceWorkOrderItem]) -> Decimal:
    """Sum of ``item.total`` across a work order's items, rounded to 2dp."""
    total = Decimal("0")
    for item in items:
        total += Decimal(item.total or 0)
    return total.quantize(Decimal("0.01"))


# Number-allocation retry cap. ``next_*_number()`` reads ``COUNT(*)`` then
# concatenates, so two concurrent inserts can produce the same number. The
# DB-level unique index on the number column then raises IntegrityError; we
# rollback + re-read + retry up to this many times before bailing 503.
_MAX_NUMBER_RETRIES: int = 5


# Ticket fields that require ``service.dispatch`` permission to mutate via
# PATCH /tickets/{id}. Without this gate, an EDITOR (``service.update``) can
# (a) self-assign internal tickets, (b) push ``assigned_to`` to a customer-
# portal user, (c) silence SLA-breach alerts by pushing ``sla_due_at`` to
# the year 2099. The dispatch / dispatch-revoke endpoints already gate on
# ``service.dispatch``; the same check needs to apply on the umbrella PATCH.
TICKET_DISPATCH_PROTECTED_FIELDS: frozenset[str] = frozenset(
    {
        "assigned_to",
        "sla_due_at",
        "response_due_at",
        "resolution_due_at",
        "sla_breach_notified_at",
        "sla_breached_at",
    }
)


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parse_iso(ts: str) -> datetime:
    """Parse an ISO datetime string. Adds UTC if naïve."""
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


# ── ServiceService ────────────────────────────────────────────────────────


class ServiceService:
    """Business logic for the Service & Maintenance module."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.contract_repo = ContractRepository(session)
        self.asset_repo = AssetRepository(session)
        self.ticket_repo = TicketRepository(session)
        self.work_order_repo = WorkOrderRepository(session)
        self.work_order_item_repo = WorkOrderItemRepository(session)
        self.debrief_repo = DebriefRepository(session)
        self.sla_repo = SLADefinitionRepository(session)
        self.schedule_repo = ScheduleRepository(session)
        self.checklist_repo = ChecklistRepository(session)
        self.recurring_repo = RecurringScheduleRepository(session)

    # ── Contract ─────────────────────────────────────────────────────────

    async def create_contract(
        self,
        data: ServiceContractCreate,
        user_id: str | None = None,
    ) -> ServiceContract:
        # A contract is only ever born draft or active; expired/terminated are
        # outcomes reached via the state machine, never an initial value.
        allowed_initial = {"draft", "active"}
        if data.status not in allowed_initial:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"A contract cannot be created in '{data.status}' state. "
                    f"Allowed initial states: {sorted(allowed_initial)}."
                ),
            )
        if data.period_end < data.period_start:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="period_end must be on or after period_start.",
            )
        # Race-safe contract number allocation. Retry on the unique-index
        # IntegrityError if two requests raced past the same COUNT(*).
        contract: ServiceContract | None = None
        last_exc: IntegrityError | None = None
        contract_number: str = ""
        for _attempt in range(_MAX_NUMBER_RETRIES):
            contract_number = await self.contract_repo.next_contract_number()
            candidate = ServiceContract(
                customer_id=data.customer_id,
                project_id=data.project_id,
                contract_number=contract_number,
                title=data.title,
                description=data.description,
                period_start=data.period_start,
                period_end=data.period_end,
                sla_definition_id=data.sla_definition_id,
                sla_tier=data.sla_tier,
                status=data.status,
                value=data.value,
                currency=data.currency,
                auto_renew=data.auto_renew,
                created_by=user_id,
                metadata_=data.metadata,
            )
            try:
                contract = await self.contract_repo.create(candidate)
                break
            except IntegrityError as exc:
                last_exc = exc
                await self.session.rollback()
        if contract is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Could not allocate a unique contract number after "
                    f"{_MAX_NUMBER_RETRIES} attempts (concurrent contention)."
                ),
            ) from last_exc
        logger.info("Service contract created: %s for customer %s", contract_number, data.customer_id)
        event_bus.publish_detached(
            "service.contract.created",
            {
                "contract_id": str(contract.id),
                "contract_number": contract_number,
                "customer_id": str(data.customer_id),
                "status": data.status,
            },
            source_module="service",
        )
        return contract

    async def get_contract(self, contract_id: uuid.UUID) -> ServiceContract:
        contract = await self.contract_repo.get_by_id(contract_id)
        if contract is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Service contract not found",
            )
        return contract

    async def update_contract(
        self,
        contract_id: uuid.UUID,
        data: ServiceContractUpdate,
    ) -> ServiceContract:
        contract = await self.get_contract(contract_id)
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if "status" in fields:
            assert_transition(contract.status, fields["status"], machine="contract")

        # Re-check period ordering against the *merged* state so a PATCH that
        # touches only one bound can't invert the period.
        new_start = fields.get("period_start", contract.period_start)
        new_end = fields.get("period_end", contract.period_end)
        if ("period_start" in fields or "period_end" in fields) and new_end < new_start:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="period_end must be on or after period_start.",
            )

        if not fields:
            return contract

        await self.contract_repo.update_fields(contract_id, **fields)
        await self.session.refresh(contract)
        return contract

    async def close_contract(self, contract_id: uuid.UUID) -> ServiceContract:
        """Manager-only: move a contract to ``terminated``."""
        contract = await self.get_contract(contract_id)
        assert_transition(contract.status, "terminated", machine="contract")
        await self.contract_repo.update_fields(contract_id, status="terminated")
        await self.session.refresh(contract)
        event_bus.publish_detached(
            "service.contract.terminated",
            {"contract_id": str(contract_id), "contract_number": contract.contract_number},
            source_module="service",
        )
        return contract

    async def delete_contract(self, contract_id: uuid.UUID) -> None:
        await self.get_contract(contract_id)
        await self.contract_repo.delete(contract_id)

    # ── Asset ────────────────────────────────────────────────────────────

    async def create_asset(self, data: ServiceAssetCreate) -> ServiceAsset:
        # Validates that the contract exists, so we get a clean 404 instead
        # of a foreign-key error from the DB.
        await self.get_contract(data.contract_id)
        asset = ServiceAsset(
            contract_id=data.contract_id,
            asset_tag=data.asset_tag,
            asset_type=data.asset_type,
            name=data.name,
            location=data.location,
            manufacturer=data.manufacturer,
            model=data.model,
            serial=data.serial,
            install_date=data.install_date,
            warranty_until=data.warranty_until,
            status=data.status,
            metadata_=data.metadata,
        )
        return await self.asset_repo.create(asset)

    async def get_asset(self, asset_id: uuid.UUID) -> ServiceAsset:
        asset = await self.asset_repo.get_by_id(asset_id)
        if asset is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Service asset not found",
            )
        return asset

    async def update_asset(self, asset_id: uuid.UUID, data: ServiceAssetUpdate) -> ServiceAsset:
        asset = await self.get_asset(asset_id)
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
        if not fields:
            return asset
        await self.asset_repo.update_fields(asset_id, **fields)
        await self.session.refresh(asset)
        return asset

    async def delete_asset(self, asset_id: uuid.UUID) -> None:
        await self.get_asset(asset_id)
        await self.asset_repo.delete(asset_id)

    # ── Ticket ───────────────────────────────────────────────────────────

    async def create_ticket(
        self,
        data: ServiceTicketCreate,
        user_id: str | None = None,
    ) -> ServiceTicket:
        """Create a ticket, compute its SLA-due, emit an event."""
        contract = await self.get_contract(data.contract_id)

        # Optional asset validation
        if data.asset_id is not None:
            asset = await self.asset_repo.get_by_id(data.asset_id)
            if asset is None or asset.contract_id != contract.id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="asset_id does not belong to this contract",
                )

        reported_at_dt = _parse_iso(data.reported_at) if data.reported_at else datetime.now(UTC)

        sla: SLADefinition | None = None
        if contract.sla_definition_id is not None:
            sla = await self.sla_repo.get_by_id(contract.sla_definition_id)

        sla_due_dt = compute_sla_due_at(reported_at_dt, sla, priority=data.priority)
        response_due_dt, resolution_due_dt = compute_sla_response_and_resolution(
            reported_at_dt,
            sla,
            priority=data.priority,
        )

        # Race-safe ticket number allocation, scoped per contract. See
        # ``create_contract`` for the rationale — concurrent /tickets/ POSTs
        # against the same contract previously raced past COUNT(*) and
        # produced duplicate T-NNNNN labels.
        ticket: ServiceTicket | None = None
        last_exc: IntegrityError | None = None
        ticket_number: str = ""
        for _attempt in range(_MAX_NUMBER_RETRIES):
            ticket_number = await self.ticket_repo.next_ticket_number(contract.id)
            candidate = ServiceTicket(
                contract_id=data.contract_id,
                asset_id=data.asset_id,
                ticket_number=ticket_number,
                title=data.title,
                description=data.description,
                priority=data.priority,
                reported_at=reported_at_dt.isoformat(),
                sla_due_at=sla_due_dt.isoformat() if sla_due_dt else None,
                response_due_at=response_due_dt.isoformat() if response_due_dt else None,
                resolution_due_at=resolution_due_dt.isoformat() if resolution_due_dt else None,
                status="new",
                source=data.source,
                reported_by=data.reported_by or user_id,
                assigned_to=data.assigned_to,
                metadata_=data.metadata,
            )
            # If the create payload pre-supplied an assignee, the ticket is born
            # in the 'assigned' state, mirroring the dispatcher click-flow.
            if data.assigned_to:
                candidate.status = "assigned"
            try:
                ticket = await self.ticket_repo.create(candidate)
                break
            except IntegrityError as exc:
                last_exc = exc
                await self.session.rollback()
        if ticket is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Could not allocate a unique ticket number after "
                    f"{_MAX_NUMBER_RETRIES} attempts (concurrent contention)."
                ),
            ) from last_exc
        logger.info(
            "Service ticket created: %s (contract=%s, priority=%s, sla_due=%s)",
            ticket_number,
            data.contract_id,
            data.priority,
            ticket.sla_due_at,
        )
        event_bus.publish_detached(
            "service.ticket.created",
            {
                "ticket_id": str(ticket.id),
                "ticket_number": ticket_number,
                "contract_id": str(data.contract_id),
                "priority": data.priority,
                "sla_due_at": ticket.sla_due_at,
                "source": data.source,
                "reported_by": data.reported_by or user_id,
            },
            source_module="service",
        )
        # A ticket born with an assignee is effectively dispatched on create;
        # emit the same event the explicit /dispatch endpoint does so
        # technician-assignment subscribers don't miss born-assigned tickets.
        if ticket.status == "assigned" and ticket.assigned_to:
            event_bus.publish_detached(
                "service.ticket.dispatched",
                {
                    "ticket_id": str(ticket.id),
                    "ticket_number": ticket_number,
                    "technician_id": ticket.assigned_to,
                    "scheduled_for": None,
                },
                source_module="service",
            )
        return ticket

    async def get_ticket(self, ticket_id: uuid.UUID) -> ServiceTicket:
        ticket = await self.ticket_repo.get_by_id(ticket_id)
        if ticket is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Service ticket not found",
            )
        return ticket

    async def update_ticket(
        self,
        ticket_id: uuid.UUID,
        data: ServiceTicketUpdate,
        *,
        has_dispatch_permission: bool = False,
    ) -> ServiceTicket:
        """Patch ticket fields with dispatch-permission gating.

        ``has_dispatch_permission`` is supplied by the router after a live
        check against the JWT payload. When False, mutating
        :data:`TICKET_DISPATCH_PROTECTED_FIELDS` (``assigned_to``,
        ``sla_due_at``, ``sla_breach_notified_at``, ``sla_breached_at``)
        raises 403 — closing the privilege-escalation hole where an EDITOR
        with ``service.update`` could self-assign internal techs or silence
        SLA-breach alerts by pushing ``sla_due_at`` into the future.
        """
        ticket = await self.get_ticket(ticket_id)
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        # Dispatch-permission gate. Catches both the "field present but
        # unchanged" case (refused) and the "field set to None to clear"
        # case (also refused) so callers can't unassign over the PATCH.
        protected_touched = TICKET_DISPATCH_PROTECTED_FIELDS & set(fields.keys())
        if protected_touched and not has_dispatch_permission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Missing permission: service.dispatch (required to mutate {sorted(protected_touched)} via PATCH)"
                ),
            )

        # Asset-belongs-to-contract gate on PATCH. ``create_ticket`` already
        # enforces this; without the same check on PATCH a caller could
        # re-target a ticket at another contract's asset.
        if "asset_id" in fields and fields["asset_id"] is not None:
            asset = await self.asset_repo.get_by_id(fields["asset_id"])
            if asset is None or asset.contract_id != ticket.contract_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="asset_id does not belong to this ticket's contract",
                )

        if "status" in fields:
            new_status = fields["status"]
            assert_transition(ticket.status, new_status, machine="ticket")
            # Keep lifecycle timestamps consistent with the dedicated
            # resolve/close endpoints when an admin corrects status via PATCH —
            # otherwise a 'closed' ticket can end up with closed_at = NULL.
            if new_status == "resolved" and ticket.status != "resolved" and ticket.resolved_at is None:
                fields["resolved_at"] = _utcnow_iso()
            if new_status == "closed" and ticket.status != "closed" and ticket.closed_at is None:
                fields["closed_at"] = _utcnow_iso()
            logger.info(
                "Service ticket status patched: %s %s → %s",
                ticket.ticket_number,
                ticket.status,
                new_status,
            )

        if not fields:
            return ticket

        await self.ticket_repo.update_fields(ticket_id, **fields)
        await self.session.refresh(ticket)
        return ticket

    async def dispatch_ticket(
        self,
        ticket_id: uuid.UUID,
        body: TicketDispatchRequest,
    ) -> ServiceTicket:
        """Assign a ticket to a technician and emit ``service.ticket.dispatched``.

        Validates the state-machine transition new → assigned (or
        assigned → assigned, treated as re-assignment) and requires that
        ``technician_id`` be present.
        """
        if not body.technician_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="technician_id is required for dispatch",
            )
        ticket = await self.get_ticket(ticket_id)
        # Re-assignment on already-assigned tickets is allowed but doesn't move state.
        if ticket.status not in ("assigned",):
            assert_transition(ticket.status, "assigned", machine="ticket")

        await self.ticket_repo.update_fields(
            ticket_id,
            status="assigned",
            assigned_to=body.technician_id,
        )
        await self.session.refresh(ticket)
        logger.info(
            "Service ticket dispatched: %s → technician %s",
            ticket.ticket_number,
            body.technician_id,
        )
        event_bus.publish_detached(
            "service.ticket.dispatched",
            {
                "ticket_id": str(ticket_id),
                "ticket_number": ticket.ticket_number,
                "technician_id": body.technician_id,
                "scheduled_for": body.scheduled_for,
            },
            source_module="service",
        )
        return ticket

    async def resolve_ticket(self, ticket_id: uuid.UUID) -> ServiceTicket:
        ticket = await self.get_ticket(ticket_id)
        assert_transition(ticket.status, "resolved", machine="ticket")
        prior_status = ticket.status
        await self.ticket_repo.update_fields(
            ticket_id,
            status="resolved",
            resolved_at=_utcnow_iso(),
        )
        await self.session.refresh(ticket)

        # Epic H — universal audit trail.
        from app.core.audit_log import log_activity as _log_activity

        await _log_activity(
            self.session,
            actor_id=None,
            entity_type="service_ticket",
            entity_id=str(ticket_id),
            action="status_changed",
            from_status=prior_status,
            to_status="resolved",
            reason="Service ticket resolved",
            metadata={"ticket_number": ticket.ticket_number},
            module="service",
            before_state={"status": prior_status},
            after_state={"status": "resolved"},
        )

        event_bus.publish_detached(
            "service.ticket.resolved",
            {
                "ticket_id": str(ticket_id),
                "ticket_number": ticket.ticket_number,
                "reported_by": ticket.reported_by,
            },
            source_module="service",
        )
        return ticket

    async def close_ticket(self, ticket_id: uuid.UUID) -> ServiceTicket:
        ticket = await self.get_ticket(ticket_id)
        assert_transition(ticket.status, "closed", machine="ticket")
        prior_status = ticket.status
        await self.ticket_repo.update_fields(
            ticket_id,
            status="closed",
            closed_at=_utcnow_iso(),
        )
        await self.session.refresh(ticket)

        # Epic H — universal audit trail.
        from app.core.audit_log import log_activity as _log_activity

        await _log_activity(
            self.session,
            actor_id=None,
            entity_type="service_ticket",
            entity_id=str(ticket_id),
            action="status_changed",
            from_status=prior_status,
            to_status="closed",
            reason="Service ticket closed",
            metadata={"ticket_number": ticket.ticket_number},
            module="service",
            before_state={"status": prior_status},
            after_state={"status": "closed"},
        )

        event_bus.publish_detached(
            "service.ticket.closed",
            {"ticket_id": str(ticket_id), "ticket_number": ticket.ticket_number},
            source_module="service",
        )
        return ticket

    async def reopen_ticket(
        self,
        ticket_id: uuid.UUID,
        body: TicketReopenRequest,
        *,
        user_id: str | None = None,
    ) -> ServiceTicket:
        """Reopen a closed ticket within the reopen-window.

        Tickets closed within the last :data:`TICKET_REOPEN_WINDOW_DAYS` days
        may be moved back to ``in_progress``. Past that window a new ticket
        must be filed — this keeps the audit trail clean and avoids inflating
        old SLA measurements.
        """
        ticket = await self.get_ticket(ticket_id)
        if ticket.status != "closed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(f"Only closed tickets can be reopened (current status: '{ticket.status}')."),
            )
        if ticket.closed_at is not None:
            try:
                closed_dt = _parse_iso(ticket.closed_at)
                window_cutoff = datetime.now(UTC) - timedelta(days=TICKET_REOPEN_WINDOW_DAYS)
                if closed_dt < window_cutoff:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail=(
                            f"Ticket was closed more than {TICKET_REOPEN_WINDOW_DAYS} days "
                            f"ago ({ticket.closed_at}). Please open a new ticket instead."
                        ),
                    )
            except HTTPException:
                raise
            except (ValueError, TypeError):
                pass  # Unparseable closed_at — allow reopen rather than blocking

        assert_transition(ticket.status, "in_progress", machine="ticket")
        meta = dict(ticket.metadata_ or {})
        reopen_history = list(meta.get("reopen_history", []))
        reopen_history.append(
            {
                "reopened_at": _utcnow_iso(),
                "reopened_by": user_id,
                "reason": body.reason,
            }
        )
        meta["reopen_history"] = reopen_history

        await self.ticket_repo.update_fields(
            ticket_id,
            status="in_progress",
            closed_at=None,
            metadata_=meta,
        )
        await self.session.refresh(ticket)
        logger.info(
            "Service ticket reopened: %s by %s",
            ticket.ticket_number,
            user_id,
        )
        event_bus.publish_detached(
            "service.ticket.reopened",
            {
                "ticket_id": str(ticket_id),
                "ticket_number": ticket.ticket_number,
                "reopened_by": user_id,
                "reason": body.reason,
            },
            source_module="service",
        )
        return ticket

    async def await_customer(
        self,
        ticket_id: uuid.UUID,
        body: TicketAwaitCustomerRequest,
    ) -> ServiceTicket:
        """Move a ticket to ``awaiting_customer`` — SLA clock paused."""
        ticket = await self.get_ticket(ticket_id)
        assert_transition(ticket.status, "awaiting_customer", machine="ticket")
        now_iso = _utcnow_iso()
        meta = dict(ticket.metadata_ or {})
        meta["awaiting_customer_note"] = body.note
        await self.ticket_repo.update_fields(
            ticket_id,
            status="awaiting_customer",
            awaiting_customer_since=now_iso,
            metadata_=meta,
        )
        await self.session.refresh(ticket)
        event_bus.publish_detached(
            "service.ticket.awaiting_customer",
            {
                "ticket_id": str(ticket_id),
                "ticket_number": ticket.ticket_number,
                "since": now_iso,
            },
            source_module="service",
        )
        return ticket

    async def resume_ticket(self, ticket_id: uuid.UUID) -> ServiceTicket:
        """Move a ticket from ``awaiting_customer`` back to ``in_progress``."""
        ticket = await self.get_ticket(ticket_id)
        assert_transition(ticket.status, "in_progress", machine="ticket")
        await self.ticket_repo.update_fields(
            ticket_id,
            status="in_progress",
            awaiting_customer_since=None,
        )
        await self.session.refresh(ticket)
        event_bus.publish_detached(
            "service.ticket.resumed",
            {
                "ticket_id": str(ticket_id),
                "ticket_number": ticket.ticket_number,
            },
            source_module="service",
        )
        return ticket

    async def get_sla_overdue(
        self,
        *,
        contract_id: uuid.UUID | None = None,
    ) -> SLAOverdueSummaryResponse:
        """Return tickets overdue on response_due_at or resolution_due_at.

        Tickets in ``awaiting_customer`` are excluded — the clock is
        considered paused while waiting on the customer.
        """
        from sqlalchemy import select

        now_dt = datetime.now(UTC)
        now_iso = now_dt.isoformat()
        active_statuses = ("new", "assigned", "in_progress")

        stmt = select(ServiceTicket).where(ServiceTicket.status.in_(active_statuses))
        if contract_id is not None:
            stmt = stmt.where(ServiceTicket.contract_id == contract_id)

        tickets = list((await self.session.execute(stmt)).scalars().all())
        response_overdue: list[SLAOverdueReport] = []
        resolution_overdue: list[SLAOverdueReport] = []

        for ticket in tickets:
            resp_mins = 0
            res_mins = 0
            if ticket.response_due_at and ticket.response_due_at < now_iso:
                try:
                    resp_mins = int((now_dt - _parse_iso(ticket.response_due_at)).total_seconds() // 60)
                except (ValueError, TypeError):
                    pass
            if ticket.resolution_due_at and ticket.resolution_due_at < now_iso:
                try:
                    res_mins = int((now_dt - _parse_iso(ticket.resolution_due_at)).total_seconds() // 60)
                except (ValueError, TypeError):
                    pass
            if resp_mins > 0 or res_mins > 0:
                report = SLAOverdueReport(
                    ticket_id=ticket.id,
                    ticket_number=ticket.ticket_number,
                    contract_id=ticket.contract_id,
                    priority=ticket.priority,
                    response_due_at=ticket.response_due_at,
                    resolution_due_at=ticket.resolution_due_at,
                    response_overdue_minutes=resp_mins,
                    resolution_overdue_minutes=res_mins,
                    status=ticket.status,
                )
                if resp_mins > 0:
                    response_overdue.append(report)
                if res_mins > 0:
                    resolution_overdue.append(report)

        return SLAOverdueSummaryResponse(
            checked_at=now_iso,
            total_open=len(tickets),
            response_overdue=response_overdue,
            resolution_overdue=resolution_overdue,
        )

    async def delete_ticket(self, ticket_id: uuid.UUID) -> None:
        await self.get_ticket(ticket_id)
        await self.ticket_repo.delete(ticket_id)

    # ── Work Order ───────────────────────────────────────────────────────

    async def create_work_order(self, data: WorkOrderCreate) -> ServiceWorkOrder:
        ticket = await self.get_ticket(data.ticket_id)

        # The schema permits any WO label, but a WO must not be *born* in a
        # state that bypasses the finance hand-off. ``billed`` skips the
        # ``bill_work_order`` finance event + roll-up, and ``cancelled`` is a
        # terminal no-op. A direct ``completed`` is legitimate (retroactive
        # entry of work already done) — we just back-fill the billed_amount
        # roll-up below so that path never loses its total.
        allowed_initial = {"scheduled", "dispatched", "in_progress", "completed"}
        if data.status not in allowed_initial:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"A work order cannot be created in '{data.status}' state. "
                    f"Allowed initial states: {sorted(allowed_initial)}."
                ),
            )

        # Race-safe WO number allocation. ``next_work_order_number()`` uses
        # COUNT(*) globally, so two concurrent POSTs can produce identical
        # WO-NNNNNN labels. Retry on the unique-index IntegrityError.
        wo: ServiceWorkOrder | None = None
        last_exc: IntegrityError | None = None
        wo_number: str = ""
        for _attempt in range(_MAX_NUMBER_RETRIES):
            wo_number = await self.work_order_repo.next_work_order_number()
            candidate = ServiceWorkOrder(
                ticket_id=data.ticket_id,
                work_order_number=wo_number,
                scheduled_for=data.scheduled_for,
                technician_id=data.technician_id,
                status=data.status,
                currency=data.currency,
                metadata_=data.metadata,
            )
            try:
                wo = await self.work_order_repo.create(candidate)
                break
            except IntegrityError as exc:
                last_exc = exc
                await self.session.rollback()
        if wo is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Could not allocate a unique work-order number after "
                    f"{_MAX_NUMBER_RETRIES} attempts (concurrent contention)."
                ),
            ) from last_exc

        # Persist items (with computed totals if caller didn't supply them).
        for item_data in data.items:
            await self._create_work_order_item(wo.id, item_data)

        # A WO born straight into ``completed`` never passes through
        # complete_work_order(), so back-fill the billed_amount roll-up here
        # to preserve the "billed_amount == sum(items.total)" invariant.
        if data.status == "completed":
            items = await self.work_order_item_repo.list_for_work_order(wo.id)
            await self.work_order_repo.update_fields(
                wo.id,
                billed_amount=compute_work_order_total(items),
                completed_at=_utcnow_iso(),
            )

        await self.session.refresh(wo)
        logger.info(
            "Work order created: %s for ticket %s",
            wo_number,
            ticket.ticket_number,
        )
        event_bus.publish_detached(
            "service.work_order.created",
            {
                "work_order_id": str(wo.id),
                "work_order_number": wo_number,
                "ticket_id": str(data.ticket_id),
            },
            source_module="service",
        )
        return wo

    async def _create_work_order_item(
        self,
        work_order_id: uuid.UUID,
        data: WorkOrderItemCreate,
    ) -> ServiceWorkOrderItem:
        total = data.total if data.total is not None else (data.quantity * data.unit_rate).quantize(Decimal("0.01"))
        item = ServiceWorkOrderItem(
            work_order_id=work_order_id,
            item_type=data.item_type,
            description=data.description,
            quantity=data.quantity,
            unit=data.unit,
            unit_rate=data.unit_rate,
            total=total,
            metadata_=data.metadata,
        )
        return await self.work_order_item_repo.create(item)

    async def get_work_order(self, wo_id: uuid.UUID) -> ServiceWorkOrder:
        wo = await self.work_order_repo.get_by_id(wo_id)
        if wo is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Work order not found",
            )
        return wo

    async def update_work_order(
        self,
        wo_id: uuid.UUID,
        data: WorkOrderUpdate,
    ) -> ServiceWorkOrder:
        wo = await self.get_work_order(wo_id)
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
        if "status" in fields:
            assert_transition(wo.status, fields["status"], machine="work_order")
        if not fields:
            return wo
        await self.work_order_repo.update_fields(wo_id, **fields)
        await self.session.refresh(wo)
        return wo

    async def complete_work_order(
        self,
        wo_id: uuid.UUID,
        body: WorkOrderCompleteRequest,
    ) -> ServiceWorkOrder:
        """Close out a work order: persist debrief + signature, sum items.

        Sets ``billed_amount = sum(items.total)`` so the accountant has a
        ready-to-invoice figure even before the explicit /bill call.
        """
        wo = await self.get_work_order(wo_id)
        assert_transition(wo.status, "completed", machine="work_order")

        items = await self.work_order_item_repo.list_for_work_order(wo_id)
        billed_amount = compute_work_order_total(items)

        update_fields: dict[str, Any] = {
            "status": "completed",
            "completed_at": _utcnow_iso(),
            "billed_amount": billed_amount,
            "debrief_summary": (body.debrief.solution[:1000] if body.debrief.solution else wo.debrief_summary),
        }
        if body.customer_signature is not None:
            update_fields["customer_signature"] = body.customer_signature

        await self.work_order_repo.update_fields(wo_id, **update_fields)

        # Persist the structured P-C-S debrief alongside the summary.
        debrief = DebriefReport(
            work_order_id=wo_id,
            problem=body.debrief.problem,
            cause=body.debrief.cause,
            solution=body.debrief.solution,
            root_cause_category=body.debrief.root_cause_category,
            follow_up_required=body.debrief.follow_up_required,
            metadata_=body.debrief.metadata,
        )
        await self.debrief_repo.create(debrief)

        await self.session.refresh(wo)
        logger.info(
            "Work order completed: %s (billed_amount=%s)",
            wo.work_order_number,
            billed_amount,
        )
        event_bus.publish_detached(
            "service.work_order.completed",
            {
                "work_order_id": str(wo_id),
                "work_order_number": wo.work_order_number,
                "billed_amount": str(billed_amount),
                "currency": wo.currency,
                "follow_up_required": body.debrief.follow_up_required,
            },
            source_module="service",
        )
        return wo

    async def bill_work_order(self, wo_id: uuid.UUID) -> ServiceWorkOrder:
        """Move a completed WO to ``billed`` and emit a Finance event.

        Emits ``service.work_order.billed`` (caught by finance to create an
        invoice). This module does NOT touch the finance module directly.
        """
        wo = await self.get_work_order(wo_id)
        assert_transition(wo.status, "billed", machine="work_order")

        await self.work_order_repo.update_fields(
            wo_id,
            status="billed",
            billed_at=_utcnow_iso(),
        )
        await self.session.refresh(wo)

        # Look up the parent ticket/contract for the finance event payload.
        ticket = await self.ticket_repo.get_by_id(wo.ticket_id)
        contract_id = str(ticket.contract_id) if ticket else None

        logger.info("Work order billed: %s amount=%s", wo.work_order_number, wo.billed_amount)
        event_bus.publish_detached(
            "service.work_order.billed",
            {
                "work_order_id": str(wo_id),
                "work_order_number": wo.work_order_number,
                "ticket_id": str(wo.ticket_id),
                "contract_id": contract_id,
                "billed_amount": str(wo.billed_amount),
                "currency": wo.currency,
            },
            source_module="service",
        )
        return wo

    async def verify_work_order(self, wo_id: uuid.UUID) -> ServiceWorkOrder:
        """Supervisor sign-off: move a ``completed`` WO to ``verified``.

        R7: requires at least one item on the WO — a verification with zero
        items is rejected (400) to prevent empty sign-offs on untouched WOs.
        """
        wo = await self.get_work_order(wo_id)
        assert_transition(wo.status, "verified", machine="work_order")

        # Guard: must have at least one item to verify
        items = await self.work_order_item_repo.list_for_work_order(wo_id)
        if not items:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Cannot verify a work order with no line items. "
                    "Add at least one labour/material line item before verifying."
                ),
            )

        await self.work_order_repo.update_fields(
            wo_id,
            status="verified",
        )
        await self.session.refresh(wo)
        logger.info("Work order verified: %s", wo.work_order_number)
        event_bus.publish_detached(
            "service.work_order.verified",
            {"work_order_id": str(wo_id), "work_order_number": wo.work_order_number},
            source_module="service",
        )
        return wo

    async def close_work_order(self, wo_id: uuid.UUID) -> ServiceWorkOrder:
        """Close a ``verified`` or ``billed`` WO.

        R7 sub-task cascade: if there are sibling WOs on the same ticket that
        are not yet in a terminal-like state, the close is rejected with 409.
        This prevents marking a ticket done while some tasks are still open.
        """
        wo = await self.get_work_order(wo_id)
        assert_transition(wo.status, "closed", machine="work_order")

        # Sub-task cascade: all siblings must be in a terminal-like state
        sibling_wos = await self.work_order_repo.list_for_ticket(wo.ticket_id)
        open_siblings = [s for s in sibling_wos if s.id != wo_id and s.status not in _WO_TERMINAL_LIKE]
        if open_siblings:
            nums = ", ".join(s.work_order_number for s in open_siblings[:5])
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot close WO {wo.work_order_number}: "
                    f"{len(open_siblings)} sibling work order(s) are still open "
                    f"({nums}). Close or cancel them first."
                ),
            )

        await self.work_order_repo.update_fields(
            wo_id,
            status="closed",
        )
        await self.session.refresh(wo)
        logger.info("Work order closed: %s", wo.work_order_number)
        event_bus.publish_detached(
            "service.work_order.closed",
            {"work_order_id": str(wo_id), "work_order_number": wo.work_order_number},
            source_module="service",
        )
        return wo

    async def delete_work_order(self, wo_id: uuid.UUID) -> None:
        await self.get_work_order(wo_id)
        await self.work_order_repo.delete(wo_id)

    # ── SLA definitions ──────────────────────────────────────────────────

    async def create_sla(self, data: SLADefinitionCreate) -> SLADefinition:
        sla = SLADefinition(
            name=data.name,
            description=data.description,
            response_time_minutes=data.response_time_minutes,
            resolution_time_minutes=data.resolution_time_minutes,
            severity_levels=data.severity_levels,
            is_active=data.is_active,
            metadata_=data.metadata,
        )
        return await self.sla_repo.create(sla)

    async def get_sla(self, sla_id: uuid.UUID) -> SLADefinition:
        sla = await self.sla_repo.get_by_id(sla_id)
        if sla is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="SLA definition not found",
            )
        return sla

    async def update_sla(self, sla_id: uuid.UUID, data: SLADefinitionUpdate) -> SLADefinition:
        sla = await self.get_sla(sla_id)
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
        if not fields:
            return sla
        await self.sla_repo.update_fields(sla_id, **fields)
        await self.session.refresh(sla)
        return sla

    async def delete_sla(self, sla_id: uuid.UUID) -> None:
        await self.get_sla(sla_id)
        await self.sla_repo.delete(sla_id)

    # ── Schedules (PPM) ──────────────────────────────────────────────────

    async def create_schedule(self, data: ServiceScheduleCreate) -> ServiceSchedule:
        await self.get_asset(data.asset_id)
        sched = ServiceSchedule(
            asset_id=data.asset_id,
            frequency=data.frequency,
            next_due_date=data.next_due_date,
            checklist_template_id=data.checklist_template_id,
            is_active=data.is_active,
            metadata_=data.metadata,
        )
        return await self.schedule_repo.create(sched)

    async def get_schedule(self, schedule_id: uuid.UUID) -> ServiceSchedule:
        sched = await self.schedule_repo.get_by_id(schedule_id)
        if sched is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Service schedule not found",
            )
        return sched

    async def update_schedule(
        self,
        schedule_id: uuid.UUID,
        data: ServiceScheduleUpdate,
    ) -> ServiceSchedule:
        sched = await self.get_schedule(schedule_id)
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
        if not fields:
            return sched
        await self.schedule_repo.update_fields(schedule_id, **fields)
        await self.session.refresh(sched)
        return sched

    async def delete_schedule(self, schedule_id: uuid.UUID) -> None:
        await self.get_schedule(schedule_id)
        await self.schedule_repo.delete(schedule_id)

    # ── Checklists ───────────────────────────────────────────────────────

    async def create_checklist(self, data: AssetChecklistCreate) -> AssetInspectionChecklist:
        cl = AssetInspectionChecklist(
            name=data.name,
            description=data.description,
            asset_type=data.asset_type,
            items=data.items,
            is_active=data.is_active,
            metadata_=data.metadata,
        )
        return await self.checklist_repo.create(cl)

    async def get_checklist(self, checklist_id: uuid.UUID) -> AssetInspectionChecklist:
        cl = await self.checklist_repo.get_by_id(checklist_id)
        if cl is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Checklist not found",
            )
        return cl

    async def update_checklist(
        self,
        checklist_id: uuid.UUID,
        data: AssetChecklistUpdate,
    ) -> AssetInspectionChecklist:
        cl = await self.get_checklist(checklist_id)
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
        if not fields:
            return cl
        await self.checklist_repo.update_fields(checklist_id, **fields)
        await self.session.refresh(cl)
        return cl

    async def delete_checklist(self, checklist_id: uuid.UUID) -> None:
        await self.get_checklist(checklist_id)
        await self.checklist_repo.delete(checklist_id)

    # ── Dashboard ────────────────────────────────────────────────────────

    async def get_contract_dashboard(
        self,
        contract_id: uuid.UUID,
    ) -> ContractDashboardResponse:
        """Aggregate KPIs for one contract's dashboard widget."""
        from sqlalchemy import func, select  # local import to keep top tidy

        contract = await self.get_contract(contract_id)

        open_tickets = await self.ticket_repo.count_open_for_contract(contract_id)
        in_progress_tickets = await self.ticket_repo.count_in_progress_for_contract(contract_id)

        # SLA breaches: tickets past sla_due_at, not yet resolved/closed/cancelled.
        # Count at the DB level — materialising rows here would also trigger the
        # ServiceTicket.work_orders selectin load for every breached ticket.
        now_iso = _utcnow_iso()
        sla_breach_stmt = (
            select(func.count())
            .select_from(ServiceTicket)
            .where(
                ServiceTicket.contract_id == contract_id,
                ServiceTicket.sla_due_at.isnot(None),
                ServiceTicket.sla_due_at < now_iso,
                ServiceTicket.status.in_(("new", "assigned", "in_progress")),
            )
        )
        sla_breaches = int((await self.session.execute(sla_breach_stmt)).scalar_one())

        # WO counts: scheduled vs completed-in-last-30d.
        scheduled_wo_stmt = (
            select(func.count())
            .select_from(ServiceWorkOrder)
            .join(ServiceTicket, ServiceTicket.id == ServiceWorkOrder.ticket_id)
            .where(
                ServiceTicket.contract_id == contract_id,
                ServiceWorkOrder.status.in_(("scheduled", "dispatched", "in_progress")),
            )
        )
        scheduled_work_orders = int((await self.session.execute(scheduled_wo_stmt)).scalar_one())

        # completed_at is stored full-ISO ("…T…+00:00"); compare against a
        # matching full-ISO bound (not a bare date) so the string ordering is
        # well-defined.
        #
        # N+1 fix: a previous version materialised every completed-WO row
        # (triggering the ServiceWorkOrder.items selectin) only to call
        # ``len()`` + a Python-side sum. Use one aggregate query for both
        # the count and the sum.
        thirty_days_ago = (datetime.now(UTC) - timedelta(days=30)).isoformat()
        completed_wo_stmt = (
            select(
                func.count(ServiceWorkOrder.id),
                func.coalesce(func.sum(ServiceWorkOrder.billed_amount), 0),
            )
            .select_from(ServiceWorkOrder)
            .join(ServiceTicket, ServiceTicket.id == ServiceWorkOrder.ticket_id)
            .where(
                ServiceTicket.contract_id == contract_id,
                ServiceWorkOrder.status.in_(("completed", "billed")),
                ServiceWorkOrder.completed_at.isnot(None),
                ServiceWorkOrder.completed_at >= thirty_days_ago,
            )
        )
        completed_wo_count_raw, billed_amount_raw = (await self.session.execute(completed_wo_stmt)).one()
        completed_wo_count = int(completed_wo_count_raw)
        billed_amount_total = Decimal(billed_amount_raw or 0)

        # Monthly revenue: contract.value / (period months). Falls back to
        # billed_amount_total when the contract has no value or zero duration.
        monthly_revenue = Decimal("0")
        if contract.value and contract.value > 0:
            try:
                start = datetime.fromisoformat(contract.period_start)
                end = datetime.fromisoformat(contract.period_end)
                months = max(1, (end.year - start.year) * 12 + (end.month - start.month))
                monthly_revenue = (Decimal(contract.value) / Decimal(months)).quantize(Decimal("0.01"))
            except (ValueError, TypeError):
                pass

        # PPM due in next 30 days
        in_30_days = (datetime.now(UTC) + timedelta(days=30)).date().isoformat()
        upcoming = await self.schedule_repo.list_due_within(contract_id, in_30_days)

        return ContractDashboardResponse(
            contract_id=contract.id,
            contract_number=contract.contract_number,
            customer_id=contract.customer_id,
            status=contract.status,
            open_tickets=open_tickets,
            in_progress_tickets=in_progress_tickets,
            sla_breaches=sla_breaches,
            scheduled_work_orders=scheduled_work_orders,
            completed_work_orders_30d=completed_wo_count,
            billed_amount_total=billed_amount_total.quantize(Decimal("0.01")),
            monthly_revenue=monthly_revenue,
            currency=contract.currency,
            upcoming_ppm_30d=len(upcoming),
        )

    # ── SLA breach scan ───────────────────────────────────────────────────

    async def scan_sla_breaches(
        self,
        *,
        contract_id: uuid.UUID | None = None,
        notify: bool = True,
    ) -> SLABreachScanResponse:
        """Find tickets past their ``sla_due_at`` and emit breach events.

        For each ticket whose ``sla_due_at < now`` and status is one of
        (new / assigned / in_progress) AND ``sla_breach_notified_at IS NULL``,
        emit a ``service.sla.breached`` event and stamp the ticket as notified
        so the same breach isn't re-announced on every cron tick.

        Args:
            contract_id: restrict the scan to one contract. Default scans all.
            notify: if False, list breaches but don't emit events / stamp the
                ticket — used for read-only dashboard polling.

        Returns:
            ``SLABreachScanResponse`` containing every currently-overdue ticket
            (regardless of prior notification) plus a count of how many were
            newly notified by this call.
        """
        from sqlalchemy import func, select

        now_dt = datetime.now(UTC)
        now_iso = now_dt.isoformat()

        stmt = select(ServiceTicket).where(
            ServiceTicket.sla_due_at.isnot(None),
            ServiceTicket.sla_due_at < now_iso,
            ServiceTicket.status.in_(("new", "assigned", "in_progress")),
        )
        if contract_id is not None:
            stmt = stmt.where(ServiceTicket.contract_id == contract_id)

        tickets = list((await self.session.execute(stmt)).scalars().all())

        # Also count *all* open tickets in scope for context on the response.
        # Count at the DB level to avoid materialising rows (and their
        # work_orders selectin load) only to call len().
        open_stmt = (
            select(func.count())
            .select_from(ServiceTicket)
            .where(ServiceTicket.status.in_(("new", "assigned", "in_progress")))
        )
        if contract_id is not None:
            open_stmt = open_stmt.where(ServiceTicket.contract_id == contract_id)
        total_open = int((await self.session.execute(open_stmt)).scalar_one())

        breaches: list[SLABreachEntry] = []
        newly_notified = 0
        for ticket in tickets:
            try:
                due_dt = _parse_iso(ticket.sla_due_at) if ticket.sla_due_at else None
            except (ValueError, TypeError):
                continue
            minutes_overdue = int((now_dt - due_dt).total_seconds() // 60) if due_dt else 0
            breaches.append(
                SLABreachEntry(
                    ticket_id=ticket.id,
                    ticket_number=ticket.ticket_number,
                    contract_id=ticket.contract_id,
                    priority=ticket.priority,
                    sla_due_at=ticket.sla_due_at or "",
                    minutes_overdue=minutes_overdue,
                    assigned_to=ticket.assigned_to,
                )
            )

            if notify and ticket.sla_breach_notified_at is None:
                await self.ticket_repo.update_fields(
                    ticket.id,
                    sla_breach_notified_at=now_iso,
                )
                newly_notified += 1
                event_bus.publish_detached(
                    "service.sla.breached",
                    {
                        "ticket_id": str(ticket.id),
                        "ticket_number": ticket.ticket_number,
                        "contract_id": str(ticket.contract_id),
                        "priority": ticket.priority,
                        "sla_due_at": ticket.sla_due_at,
                        "minutes_overdue": minutes_overdue,
                        "assigned_to": ticket.assigned_to,
                    },
                    source_module="service",
                )

        return SLABreachScanResponse(
            scanned_at=now_iso,
            total_open=total_open,
            breaches=breaches,
            newly_notified=newly_notified,
        )

    # ── NCR from work order ───────────────────────────────────────────────

    async def file_ncr_from_work_order(
        self,
        wo_id: uuid.UUID,
        data: NCRFromWorkOrderRequest,
        user_id: str | None = None,
    ) -> NCRFromWorkOrderResponse:
        """File an NCR linked to a work order, on the parent project.

        Walks WO → ticket → contract → project_id. Requires the contract to
        carry a ``project_id`` — NCR is a project-scoped construct. Raises
        409 otherwise.
        """
        wo = await self.get_work_order(wo_id)
        ticket = await self.get_ticket(wo.ticket_id)
        contract = await self.get_contract(ticket.contract_id)

        if contract.project_id is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(f"NCR requires a project-scoped contract. Contract {contract.contract_number} has no project."),
            )

        # Late import to avoid pulling NCR into service-module import graph.
        from app.modules.ncr.models import NCR
        from app.modules.ncr.repository import NCRRepository

        ncr_repo = NCRRepository(self.session)
        ncr_number = await ncr_repo.next_ncr_number(contract.project_id)
        ncr = NCR(
            project_id=contract.project_id,
            ncr_number=ncr_number,
            title=data.title,
            description=data.description,
            ncr_type=data.ncr_type,
            severity=data.severity,
            status="identified",
            location_description=data.location_description,
            created_by=user_id,
            metadata_={
                "source": "service_work_order",
                "work_order_id": str(wo_id),
                "work_order_number": wo.work_order_number,
                "ticket_id": str(ticket.id),
                "ticket_number": ticket.ticket_number,
            },
        )
        ncr = await ncr_repo.create(ncr)

        # Echo the link back onto the WO metadata for round-trip discoverability.
        wo_meta = dict(wo.metadata_ or {})
        ncr_list = list(wo_meta.get("ncr_ids", []))
        ncr_list.append(str(ncr.id))
        wo_meta["ncr_ids"] = ncr_list
        await self.work_order_repo.update_fields(wo_id, metadata_=wo_meta)

        event_bus.publish_detached(
            "service.work_order.ncr_filed",
            {
                "work_order_id": str(wo_id),
                "work_order_number": wo.work_order_number,
                "ncr_id": str(ncr.id),
                "ncr_number": ncr_number,
                "project_id": str(contract.project_id),
                "severity": data.severity,
            },
            source_module="service",
        )
        logger.info(
            "NCR filed from work order: %s → %s (project=%s)",
            wo.work_order_number,
            ncr_number,
            contract.project_id,
        )
        return NCRFromWorkOrderResponse(
            ncr_id=ncr.id,
            ncr_number=ncr_number,
            project_id=contract.project_id,
            work_order_id=wo_id,
        )

    # ── Procurement: PR from WO material item ────────────────────────────

    async def request_purchase_for_item(
        self,
        wo_id: uuid.UUID,
        item_id: uuid.UUID,
        user_id: str | None = None,
    ) -> uuid.UUID:
        """Emit a procurement request event for a WO material item.

        Returns the item id for the caller. The actual PO row is created by
        the procurement-side subscriber (decoupled). Only material items
        flagged ``metadata.procurement_required=true`` are eligible.
        """
        wo = await self.get_work_order(wo_id)
        items = await self.work_order_item_repo.list_for_work_order(wo_id)
        item = next((i for i in items if i.id == item_id), None)
        if item is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Work order item not found",
            )
        if item.item_type != "material":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Procurement requests are only valid for material items",
            )

        ticket = await self.get_ticket(wo.ticket_id)
        contract = await self.get_contract(ticket.contract_id)

        event_bus.publish_detached(
            "service.work_order.material_requested",
            {
                "work_order_id": str(wo_id),
                "work_order_number": wo.work_order_number,
                "item_id": str(item_id),
                "description": item.description,
                "quantity": str(item.quantity),
                "unit": item.unit,
                "unit_rate": str(item.unit_rate),
                "currency": wo.currency,
                "project_id": str(contract.project_id) if contract.project_id else None,
                "contract_id": str(contract.id),
                "requested_by": user_id,
            },
            source_module="service",
        )
        # Also persist an audit hint on the item so the UI can show "PR pending".
        item_meta = dict(item.metadata_ or {})
        item_meta["procurement_requested_at"] = _utcnow_iso()
        item_meta["procurement_requested_by"] = user_id
        await self.work_order_item_repo.update_fields(item_id, metadata_=item_meta)
        return item_id

    # ── T10: SLA breach detector (priority-driven, dateutil-free) ────────

    async def check_breaches(
        self,
        *,
        contract_id: uuid.UUID | None = None,
    ) -> SLABreachCheckResponse:
        """Find tickets whose ``sla_due_at`` is past and stamp ``sla_breached_at``.

        Operates only on tickets where ``sla_breached_at IS NULL`` so re-runs
        don't re-stamp. Emits ``service.sla.breached`` for each newly stamped
        ticket. Returns the count of newly breached tickets plus the total
        currently-breached open tickets.

        Distinct from :meth:`scan_sla_breaches` (which only handles the
        *notification* idempotency stamp ``sla_breach_notified_at``) — this
        method is the T10 ground-truth marker used by the dashboard countdown.
        """
        from sqlalchemy import select

        now_dt = datetime.now(UTC)
        now_iso = now_dt.isoformat()

        stmt = select(ServiceTicket).where(
            ServiceTicket.sla_due_at.isnot(None),
            ServiceTicket.sla_due_at < now_iso,
            ServiceTicket.sla_breached_at.is_(None),
            ServiceTicket.status.in_(("new", "assigned", "in_progress")),
        )
        if contract_id is not None:
            stmt = stmt.where(ServiceTicket.contract_id == contract_id)

        tickets = list((await self.session.execute(stmt)).scalars().all())

        newly_breached: list[uuid.UUID] = []
        # Capture each ticket's identifying fields BEFORE update_fields so the
        # SQLAlchemy ``expire_all()`` it issues doesn't force a re-load of
        # ``ticket.id`` outside the async greenlet (the event payload also
        # reads several columns; we snapshot them up front to keep the
        # session traffic minimal).
        snapshots = [
            (
                t.id,
                t.ticket_number,
                t.contract_id,
                t.priority,
                t.sla_due_at,
                t.assigned_to,
            )
            for t in tickets
        ]
        for tid, tnum, cid, prio, due, assignee in snapshots:
            await self.ticket_repo.update_fields(tid, sla_breached_at=now_iso)
            newly_breached.append(tid)
            event_bus.publish_detached(
                "service.sla.breached",
                {
                    "ticket_id": str(tid),
                    "ticket_number": tnum,
                    "contract_id": str(cid),
                    "priority": prio,
                    "sla_due_at": due,
                    "sla_breached_at": now_iso,
                    "assigned_to": assignee,
                },
                source_module="service",
            )

        # Total currently-breached tickets (whether newly stamped or not).
        total_stmt = select(ServiceTicket).where(
            ServiceTicket.sla_breached_at.isnot(None),
            ServiceTicket.status.in_(("new", "assigned", "in_progress")),
        )
        if contract_id is not None:
            total_stmt = total_stmt.where(ServiceTicket.contract_id == contract_id)
        total_breached = len(list((await self.session.execute(total_stmt)).scalars().all()))

        return SLABreachCheckResponse(
            checked_at=now_iso,
            newly_breached=len(newly_breached),
            total_breached=total_breached,
            breached_ticket_ids=newly_breached,
        )

    # ── T10: RRULE-driven recurring schedules ────────────────────────────

    @staticmethod
    def _rrule_next_after(rrule_str: str, after: datetime) -> datetime | None:
        """Return the first RRULE occurrence strictly after ``after``.

        Wraps ``dateutil.rrule.rrulestr`` so the rest of the service module
        doesn't import dateutil directly. Returns None when the rule is
        exhausted (e.g. ``COUNT=`` reached).
        """
        # Local import: dateutil is a transitive dep already, but keep the
        # module-level import surface tight.
        from dateutil.rrule import rrulestr

        # An RRULE without DTSTART is anchored at ``after`` so we always get a
        # forward-looking occurrence. Strip any user-supplied prefix so we
        # never end up with "RRULE:RRULE:..." which dateutil rejects.
        rule_body = rrule_str.strip()
        if rule_body.upper().startswith("RRULE:"):
            rule_body = rule_body[6:]
        try:
            rule = rrulestr(rule_body, dtstart=after)
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid RRULE: {exc}",
            ) from exc
        candidate = rule.after(after, inc=False)
        if candidate is None:
            return None
        # Normalise to UTC-aware so downstream ISO formatting is well-defined.
        if candidate.tzinfo is None:
            candidate = candidate.replace(tzinfo=UTC)
        return candidate

    async def create_recurring(
        self,
        data: RecurringScheduleCreate,
    ) -> ServiceRecurringSchedule:
        """Persist a recurring schedule and compute its first ``next_run_at``."""
        # If contract scope is set, validate the contract exists so the user
        # gets a clean 404 (and a derived project_id when not supplied).
        project_id = data.project_id
        if data.contract_id is not None:
            contract = await self.get_contract(data.contract_id)
            if project_id is None:
                project_id = contract.project_id

        # Compute first run if caller didn't pre-supply one.
        if data.next_run_at is not None:
            next_run_iso: str | None = data.next_run_at
        else:
            anchor = datetime.now(UTC)
            next_dt = self._rrule_next_after(data.rrule, anchor)
            next_run_iso = next_dt.isoformat() if next_dt else None

        sched = ServiceRecurringSchedule(
            project_id=project_id,
            contract_id=data.contract_id,
            name=data.name,
            rrule=data.rrule,
            template_ticket_data=dict(data.template_ticket_data),
            next_run_at=next_run_iso,
            enabled=data.enabled,
            metadata_=data.metadata,
        )
        sched = await self.recurring_repo.create(sched)

        event_bus.publish_detached(
            "service.recurring.created",
            {
                "schedule_id": str(sched.id),
                "name": sched.name,
                "rrule": sched.rrule,
                "next_run_at": sched.next_run_at,
            },
            source_module="service",
        )
        return sched

    async def get_recurring(
        self,
        schedule_id: uuid.UUID,
    ) -> ServiceRecurringSchedule:
        sched = await self.recurring_repo.get_by_id(schedule_id)
        if sched is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Recurring schedule not found",
            )
        return sched

    async def update_recurring(
        self,
        schedule_id: uuid.UUID,
        data: RecurringScheduleUpdate,
    ) -> ServiceRecurringSchedule:
        sched = await self.get_recurring(schedule_id)
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
        if not fields:
            return sched
        # If the RRULE changed and no explicit next_run_at was supplied, leave
        # next_run_at alone — the materialiser will recompute it on its next
        # tick. This avoids surprising the user mid-cycle.
        await self.recurring_repo.update_fields(schedule_id, **fields)
        await self.session.refresh(sched)
        return sched

    async def delete_recurring(self, schedule_id: uuid.UUID) -> None:
        await self.get_recurring(schedule_id)
        await self.recurring_repo.delete(schedule_id)

    async def materialize_recurring(
        self,
        schedule_id: uuid.UUID,
        *,
        force: bool = False,
        user_id: str | None = None,
    ) -> RecurringScheduleMaterializeResponse:
        """Create a ticket from the schedule's template and advance ``next_run_at``.

        ``force`` lets the dispatcher trigger a "Run now" outside the normal
        cron cadence (handy for testing or backfilling). When False, refuses
        to materialise if the schedule is disabled or not yet due.
        """
        sched = await self.get_recurring(schedule_id)

        if not sched.enabled and not force:
            return RecurringScheduleMaterializeResponse(
                schedule_id=sched.id,
                next_run_at=sched.next_run_at,
                materialized=False,
                reason="Schedule disabled",
            )

        now_dt = datetime.now(UTC)
        now_iso = now_dt.isoformat()

        if not force:
            if not sched.next_run_at:
                return RecurringScheduleMaterializeResponse(
                    schedule_id=sched.id,
                    materialized=False,
                    reason="next_run_at not set",
                )
            if sched.next_run_at > now_iso:
                return RecurringScheduleMaterializeResponse(
                    schedule_id=sched.id,
                    next_run_at=sched.next_run_at,
                    materialized=False,
                    reason="Not due yet",
                )

        # Build a ServiceTicketCreate from the template. ``contract_id`` is
        # required, taken from the template payload or — when the schedule
        # itself carries one — from the schedule row.
        template = dict(sched.template_ticket_data or {})
        contract_id_raw = template.get("contract_id") or (str(sched.contract_id) if sched.contract_id else None)
        if not contract_id_raw:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Schedule has no contract_id to materialise a ticket against",
            )

        try:
            ticket_create = ServiceTicketCreate(
                contract_id=uuid.UUID(str(contract_id_raw)),
                asset_id=(uuid.UUID(str(template["asset_id"])) if template.get("asset_id") else None),
                title=str(template.get("title") or sched.name),
                description=str(template.get("description") or ""),
                priority=str(template.get("priority") or "med"),
                reported_at=now_iso,
                source="auto_ppm",
                metadata=dict(template.get("metadata") or {}),
            )
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid template_ticket_data: {exc}",
            ) from exc

        # Snapshot schedule fields BEFORE any update_fields() call — the
        # repository's ``expire_all()`` would otherwise force a re-load of
        # ``sched.rrule`` / ``sched.next_run_at`` outside the async greenlet.
        sched_id = sched.id
        sched_rrule = sched.rrule
        prev_next_run = sched.next_run_at

        ticket = await self.create_ticket(ticket_create, user_id=user_id)
        ticket_id = ticket.id
        ticket_number = ticket.ticket_number
        # Backfill the schedule link on the ticket so the dashboard can list
        # "tickets from this schedule" without an extra metadata round-trip.
        await self.ticket_repo.update_fields(
            ticket_id,
            recurring_schedule_id=sched_id,
        )

        # Advance next_run_at via the RRULE, anchored at the *previous*
        # next_run_at so we honour the configured cadence even if the cron
        # tick ran late.
        anchor_str = prev_next_run or now_iso
        try:
            anchor_dt = _parse_iso(anchor_str)
        except (ValueError, TypeError):
            anchor_dt = now_dt
        next_dt = self._rrule_next_after(sched_rrule, anchor_dt)
        next_run_iso = next_dt.isoformat() if next_dt else None

        await self.recurring_repo.update_fields(
            sched_id,
            next_run_at=next_run_iso,
            last_run_at=now_iso,
        )

        event_bus.publish_detached(
            "service.recurring.materialized",
            {
                "schedule_id": str(sched_id),
                "ticket_id": str(ticket_id),
                "ticket_number": ticket_number,
                "next_run_at": next_run_iso,
            },
            source_module="service",
        )

        return RecurringScheduleMaterializeResponse(
            schedule_id=sched_id,
            ticket_id=ticket_id,
            ticket_number=ticket_number,
            next_run_at=next_run_iso,
            materialized=True,
        )
