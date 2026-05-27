"""‌⁠‍FastAPI routes for the Service & Maintenance module.

Mounted at ``/api/v1/service/`` by the module loader.

Endpoint groups:
    /contracts             — CRUD + dashboard
    /assets                — CRUD
    /tickets               — CRUD + dispatch/resolve/close
    /work-orders           — CRUD + complete/bill
    /sla-definitions       — CRUD
    /schedules             — CRUD (PPM)
    /checklists            — CRUD (inspection templates)

All endpoints require auth via ``RequirePermission`` (or read-permission
where the action is observational).
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import (
    CurrentUserId,
    CurrentUserPayload,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.service.schemas import (
    AssetChecklistCreate,
    AssetChecklistResponse,
    AssetChecklistUpdate,
    ContractDashboardResponse,
    NCRFromWorkOrderRequest,
    NCRFromWorkOrderResponse,
    RecurringScheduleCreate,
    RecurringScheduleMaterializeResponse,
    RecurringScheduleResponse,
    RecurringScheduleUpdate,
    ServiceAssetCreate,
    ServiceAssetResponse,
    ServiceAssetUpdate,
    ServiceContractCreate,
    ServiceContractResponse,
    ServiceContractUpdate,
    ServiceScheduleCreate,
    ServiceScheduleResponse,
    ServiceScheduleUpdate,
    ServiceTicketCreate,
    ServiceTicketResponse,
    ServiceTicketUpdate,
    SLABreachCheckResponse,
    SLABreachScanResponse,
    SLADefinitionCreate,
    SLADefinitionResponse,
    SLADefinitionUpdate,
    TicketDispatchRequest,
    WorkOrderCompleteRequest,
    WorkOrderCreate,
    WorkOrderResponse,
    WorkOrderUpdate,
)
from app.modules.service.service import ServiceService

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> ServiceService:
    return ServiceService(session)


def _payload_has_permission(payload: dict, permission: str) -> bool:
    """‌⁠‍Mirror :class:`RequirePermission` semantics for an ad-hoc check.

    Used where a single endpoint needs *different* permission levels depending
    on a request flag (read-only vs. side-effecting). Honours the admin bypass
    and the live-registry fallback for stale JWTs, exactly like the dependency.
    """
    role: str = payload.get("role", "")
    if role == "admin":
        return True
    if permission in payload.get("permissions", []):
        return True
    from app.core.permissions import permission_registry as _reg

    return _reg.role_has_permission(role, permission)


async def _verify_contract_project(
    contract_id: uuid.UUID | None,
    user_id: str,
    session: SessionDep,
    svc: ServiceService,
) -> None:
    """‌⁠‍If the contract is project-scoped, enforce project access.

    Tickets / work orders / assets do not carry a ``project_id`` themselves;
    they inherit it from their parent ``ServiceContract``. When the contract
    has no project (customer-only contract) we fall back to tenant scope and
    do not gate further.
    """
    if contract_id is None:
        return
    contract = await svc.contract_repo.get_by_id(contract_id)
    if contract is None or contract.project_id is None:
        return
    await verify_project_access(contract.project_id, user_id, session)


async def _verify_ticket_project(
    ticket_id: uuid.UUID,
    user_id: str,
    session: SessionDep,
    svc: ServiceService,
) -> None:
    """Look up the parent ticket → contract chain and gate by project."""
    ticket = await svc.ticket_repo.get_by_id(ticket_id)
    if ticket is None:
        return
    await _verify_contract_project(ticket.contract_id, user_id, session, svc)


async def _verify_work_order_project(
    wo_id: uuid.UUID,
    user_id: str,
    session: SessionDep,
    svc: ServiceService,
) -> None:
    """Look up wo → ticket → contract and gate by project."""
    wo = await svc.work_order_repo.get_by_id(wo_id)
    if wo is None:
        return
    await _verify_ticket_project(wo.ticket_id, user_id, session, svc)


# ── Contracts ─────────────────────────────────────────────────────────────


@router.get("/contracts/", response_model=list[ServiceContractResponse])
async def list_contracts(
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.read")),
    customer_id: uuid.UUID | None = Query(default=None),
    project_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    service: ServiceService = Depends(_get_service),
) -> list[ServiceContractResponse]:
    """List service contracts (optionally filtered by customer/project/status)."""
    if project_id is not None:
        await verify_project_access(project_id, user_id, session)
    if customer_id is not None:
        items, _ = await service.contract_repo.list_for_customer(
            customer_id,
            offset=offset,
            limit=limit,
            status=status_filter,
        )
    elif project_id is not None:
        items, _ = await service.contract_repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
        )
    else:
        items, _ = await service.contract_repo.list_all(
            offset=offset,
            limit=limit,
            status=status_filter,
        )
    return [ServiceContractResponse.model_validate(it) for it in items]


@router.post("/contracts/", response_model=ServiceContractResponse, status_code=201)
async def create_contract(
    data: ServiceContractCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("service.create")),
    service: ServiceService = Depends(_get_service),
) -> ServiceContractResponse:
    """Create a new service contract."""
    if data.project_id is not None:
        await verify_project_access(data.project_id, user_id, session)
    contract = await service.create_contract(data, user_id=user_id)
    return ServiceContractResponse.model_validate(contract)


@router.get("/contracts/{contract_id}", response_model=ServiceContractResponse)
async def get_contract(
    contract_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.read")),
    service: ServiceService = Depends(_get_service),
) -> ServiceContractResponse:
    """Get a single service contract."""
    await _verify_contract_project(contract_id, user_id, session, service)
    contract = await service.get_contract(contract_id)
    return ServiceContractResponse.model_validate(contract)


@router.patch("/contracts/{contract_id}", response_model=ServiceContractResponse)
async def update_contract(
    contract_id: uuid.UUID,
    data: ServiceContractUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.update")),
    service: ServiceService = Depends(_get_service),
) -> ServiceContractResponse:
    """Update a service contract."""
    await _verify_contract_project(contract_id, user_id, session, service)
    # Also guard the *target* project_id when the caller is moving the
    # contract under a new project — prevents privilege escalation by
    # reassigning a contract you can no longer reach.
    if data.project_id is not None:
        await verify_project_access(data.project_id, user_id, session)
    contract = await service.update_contract(contract_id, data)
    return ServiceContractResponse.model_validate(contract)


@router.delete("/contracts/{contract_id}", status_code=204)
async def delete_contract(
    contract_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.delete")),
    service: ServiceService = Depends(_get_service),
) -> None:
    """Delete a service contract."""
    await _verify_contract_project(contract_id, user_id, session, service)
    await service.delete_contract(contract_id)


@router.post("/contracts/{contract_id}/close", response_model=ServiceContractResponse)
async def close_contract(
    contract_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.close_contract")),
    service: ServiceService = Depends(_get_service),
) -> ServiceContractResponse:
    """Manager-only: terminate a service contract."""
    await _verify_contract_project(contract_id, user_id, session, service)
    contract = await service.close_contract(contract_id)
    return ServiceContractResponse.model_validate(contract)


@router.get("/contracts/{contract_id}/dashboard", response_model=ContractDashboardResponse)
async def contract_dashboard(
    contract_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.read")),
    service: ServiceService = Depends(_get_service),
) -> ContractDashboardResponse:
    """Aggregated KPIs for a service contract."""
    await _verify_contract_project(contract_id, user_id, session, service)
    return await service.get_contract_dashboard(contract_id)


# ── Assets ────────────────────────────────────────────────────────────────


@router.get("/assets/", response_model=list[ServiceAssetResponse])
async def list_assets(
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.read")),
    contract_id: uuid.UUID = Query(...),
    status_filter: str | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    service: ServiceService = Depends(_get_service),
) -> list[ServiceAssetResponse]:
    """List service assets under a contract."""
    await _verify_contract_project(contract_id, user_id, session, service)
    items, _ = await service.asset_repo.list_for_contract(
        contract_id,
        offset=offset,
        limit=limit,
        status=status_filter,
    )
    return [ServiceAssetResponse.model_validate(it) for it in items]


@router.post("/assets/", response_model=ServiceAssetResponse, status_code=201)
async def create_asset(
    data: ServiceAssetCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.create")),
    service: ServiceService = Depends(_get_service),
) -> ServiceAssetResponse:
    """Create a new service asset."""
    await _verify_contract_project(data.contract_id, user_id, session, service)
    asset = await service.create_asset(data)
    return ServiceAssetResponse.model_validate(asset)


@router.get("/assets/{asset_id}", response_model=ServiceAssetResponse)
async def get_asset(
    asset_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.read")),
    service: ServiceService = Depends(_get_service),
) -> ServiceAssetResponse:
    """Get a single service asset."""
    asset = await service.asset_repo.get_by_id(asset_id)
    if asset is not None:
        await _verify_contract_project(asset.contract_id, user_id, session, service)
    asset = await service.get_asset(asset_id)
    return ServiceAssetResponse.model_validate(asset)


@router.patch("/assets/{asset_id}", response_model=ServiceAssetResponse)
async def update_asset(
    asset_id: uuid.UUID,
    data: ServiceAssetUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.update")),
    service: ServiceService = Depends(_get_service),
) -> ServiceAssetResponse:
    """Update a service asset."""
    existing = await service.asset_repo.get_by_id(asset_id)
    if existing is not None:
        await _verify_contract_project(existing.contract_id, user_id, session, service)
    asset = await service.update_asset(asset_id, data)
    return ServiceAssetResponse.model_validate(asset)


@router.delete("/assets/{asset_id}", status_code=204)
async def delete_asset(
    asset_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.delete")),
    service: ServiceService = Depends(_get_service),
) -> None:
    """Delete a service asset."""
    existing = await service.asset_repo.get_by_id(asset_id)
    if existing is not None:
        await _verify_contract_project(existing.contract_id, user_id, session, service)
    await service.delete_asset(asset_id)


# ── Tickets ───────────────────────────────────────────────────────────────


@router.get("/tickets/", response_model=list[ServiceTicketResponse])
async def list_tickets(
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.read")),
    contract_id: uuid.UUID | None = Query(default=None),
    project_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    priority: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    service: ServiceService = Depends(_get_service),
) -> list[ServiceTicketResponse]:
    """List service tickets."""
    if project_id is not None:
        await verify_project_access(project_id, user_id, session)
    if contract_id is not None:
        await _verify_contract_project(contract_id, user_id, session, service)
    if contract_id is not None:
        items, _ = await service.ticket_repo.list_for_contract(
            contract_id,
            offset=offset,
            limit=limit,
            status=status_filter,
            priority=priority,
        )
    elif project_id is not None:
        items, _ = await service.ticket_repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
        )
    else:
        # No contract/project scope ⇒ tenant-wide dispatcher view. Previously
        # this returned [] which left the default /service Tickets tab
        # permanently empty (and the WO-create ticket picker blank).
        items, _ = await service.ticket_repo.list_all(
            offset=offset,
            limit=limit,
            status=status_filter,
            priority=priority,
        )
    return [ServiceTicketResponse.model_validate(it) for it in items]


@router.post("/tickets/", response_model=ServiceTicketResponse, status_code=201)
async def create_ticket(
    data: ServiceTicketCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("service.create")),
    service: ServiceService = Depends(_get_service),
) -> ServiceTicketResponse:
    """Create a new service ticket."""
    await _verify_contract_project(data.contract_id, user_id, session, service)
    ticket = await service.create_ticket(data, user_id=user_id)
    return ServiceTicketResponse.model_validate(ticket)


@router.get("/tickets/{ticket_id}", response_model=ServiceTicketResponse)
async def get_ticket(
    ticket_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.read")),
    service: ServiceService = Depends(_get_service),
) -> ServiceTicketResponse:
    """Get a single service ticket."""
    existing = await service.ticket_repo.get_by_id(ticket_id)
    if existing is not None:
        await _verify_contract_project(existing.contract_id, user_id, session, service)
    ticket = await service.get_ticket(ticket_id)
    return ServiceTicketResponse.model_validate(ticket)


@router.patch("/tickets/{ticket_id}", response_model=ServiceTicketResponse)
async def update_ticket(
    ticket_id: uuid.UUID,
    data: ServiceTicketUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("service.update")),
    service: ServiceService = Depends(_get_service),
) -> ServiceTicketResponse:
    """Update a service ticket.

    Dispatch-protected fields (``assigned_to``, ``sla_due_at``,
    ``sla_breach_notified_at``, ``sla_breached_at``) additionally require
    ``service.dispatch`` — see :data:`TICKET_DISPATCH_PROTECTED_FIELDS`.
    Without this gate an EDITOR with ``service.update`` could self-assign
    internal tickets or silence SLA-breach alerts.
    """
    existing = await service.ticket_repo.get_by_id(ticket_id)
    if existing is not None:
        await _verify_contract_project(existing.contract_id, user_id, session, service)
    has_dispatch = _payload_has_permission(payload, "service.dispatch")
    ticket = await service.update_ticket(
        ticket_id,
        data,
        has_dispatch_permission=has_dispatch,
    )
    return ServiceTicketResponse.model_validate(ticket)


@router.delete("/tickets/{ticket_id}", status_code=204)
async def delete_ticket(
    ticket_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.delete")),
    service: ServiceService = Depends(_get_service),
) -> None:
    """Delete a service ticket."""
    existing = await service.ticket_repo.get_by_id(ticket_id)
    if existing is not None:
        await _verify_contract_project(existing.contract_id, user_id, session, service)
    await service.delete_ticket(ticket_id)


@router.post("/tickets/{ticket_id}/dispatch", response_model=ServiceTicketResponse)
async def dispatch_ticket(
    ticket_id: uuid.UUID,
    body: TicketDispatchRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.dispatch")),
    service: ServiceService = Depends(_get_service),
) -> ServiceTicketResponse:
    """Assign a ticket to a technician (manager-only)."""
    existing = await service.ticket_repo.get_by_id(ticket_id)
    if existing is not None:
        await _verify_contract_project(existing.contract_id, user_id, session, service)
    ticket = await service.dispatch_ticket(ticket_id, body)
    return ServiceTicketResponse.model_validate(ticket)


@router.post("/tickets/{ticket_id}/resolve", response_model=ServiceTicketResponse)
async def resolve_ticket(
    ticket_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.update")),
    service: ServiceService = Depends(_get_service),
) -> ServiceTicketResponse:
    """Mark a ticket as resolved."""
    existing = await service.ticket_repo.get_by_id(ticket_id)
    if existing is not None:
        await _verify_contract_project(existing.contract_id, user_id, session, service)
    ticket = await service.resolve_ticket(ticket_id)
    return ServiceTicketResponse.model_validate(ticket)


@router.post("/tickets/{ticket_id}/close", response_model=ServiceTicketResponse)
async def close_ticket(
    ticket_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.update")),
    service: ServiceService = Depends(_get_service),
) -> ServiceTicketResponse:
    """Close a resolved ticket."""
    existing = await service.ticket_repo.get_by_id(ticket_id)
    if existing is not None:
        await _verify_contract_project(existing.contract_id, user_id, session, service)
    ticket = await service.close_ticket(ticket_id)
    return ServiceTicketResponse.model_validate(ticket)


# ── Work orders ───────────────────────────────────────────────────────────


@router.get("/work-orders/", response_model=list[WorkOrderResponse])
async def list_work_orders(
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.read")),
    status_filter: str | None = Query(default=None, alias="status"),
    technician_id: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    service: ServiceService = Depends(_get_service),
) -> list[WorkOrderResponse]:
    """List work orders."""
    items, _ = await service.work_order_repo.list_all(
        offset=offset,
        limit=limit,
        status=status_filter,
        technician_id=technician_id,
    )
    return [WorkOrderResponse.model_validate(it) for it in items]


@router.post("/work-orders/", response_model=WorkOrderResponse, status_code=201)
async def create_work_order(
    data: WorkOrderCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.create")),
    service: ServiceService = Depends(_get_service),
) -> WorkOrderResponse:
    """Create a new work order under a ticket."""
    await _verify_ticket_project(data.ticket_id, user_id, session, service)
    wo = await service.create_work_order(data)
    return WorkOrderResponse.model_validate(wo)


@router.get("/work-orders/{wo_id}", response_model=WorkOrderResponse)
async def get_work_order(
    wo_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.read")),
    service: ServiceService = Depends(_get_service),
) -> WorkOrderResponse:
    """Get a single work order."""
    await _verify_work_order_project(wo_id, user_id, session, service)
    wo = await service.get_work_order(wo_id)
    return WorkOrderResponse.model_validate(wo)


@router.patch("/work-orders/{wo_id}", response_model=WorkOrderResponse)
async def update_work_order(
    wo_id: uuid.UUID,
    data: WorkOrderUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.update")),
    service: ServiceService = Depends(_get_service),
) -> WorkOrderResponse:
    """Update a work order."""
    await _verify_work_order_project(wo_id, user_id, session, service)
    wo = await service.update_work_order(wo_id, data)
    return WorkOrderResponse.model_validate(wo)


@router.delete("/work-orders/{wo_id}", status_code=204)
async def delete_work_order(
    wo_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.delete")),
    service: ServiceService = Depends(_get_service),
) -> None:
    """Delete a work order."""
    await _verify_work_order_project(wo_id, user_id, session, service)
    await service.delete_work_order(wo_id)


@router.post("/work-orders/{wo_id}/complete", response_model=WorkOrderResponse)
async def complete_work_order(
    wo_id: uuid.UUID,
    body: WorkOrderCompleteRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.update")),
    service: ServiceService = Depends(_get_service),
) -> WorkOrderResponse:
    """Mark a work order completed, persist debrief, sum billed_amount."""
    await _verify_work_order_project(wo_id, user_id, session, service)
    wo = await service.complete_work_order(wo_id, body)
    return WorkOrderResponse.model_validate(wo)


@router.post("/work-orders/{wo_id}/bill", response_model=WorkOrderResponse)
async def bill_work_order(
    wo_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.bill")),
    service: ServiceService = Depends(_get_service),
) -> WorkOrderResponse:
    """Manager-only: mark work order billed, emit Finance event."""
    await _verify_work_order_project(wo_id, user_id, session, service)
    wo = await service.bill_work_order(wo_id)
    return WorkOrderResponse.model_validate(wo)


@router.post(
    "/work-orders/{wo_id}/file-ncr",
    response_model=NCRFromWorkOrderResponse,
    status_code=201,
)
async def file_ncr_from_wo(
    wo_id: uuid.UUID,
    body: NCRFromWorkOrderRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.update")),
    service: ServiceService = Depends(_get_service),
) -> NCRFromWorkOrderResponse:
    """File an NCR on this work order's parent project.

    Triggered from the field engineer's debrief flow when a non-conformance
    is uncovered separately from the original ticket. Creates a real NCR row
    via :class:`NCRService` and round-trips the link in WO metadata.
    """
    await _verify_work_order_project(wo_id, user_id, session, service)
    return await service.file_ncr_from_work_order(wo_id, body, user_id=user_id)


@router.post(
    "/work-orders/{wo_id}/items/{item_id}/request-purchase",
    status_code=202,
)
async def request_purchase(
    wo_id: uuid.UUID,
    item_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.update")),
    service: ServiceService = Depends(_get_service),
) -> dict[str, str]:
    """Request a purchase order for a material line on a WO.

    Emits ``service.work_order.material_requested``. The procurement-side
    subscriber creates a draft PO. Returns 202 to signal that the PO is
    eventually-consistent (the subscriber runs in its own session).
    """
    await _verify_work_order_project(wo_id, user_id, session, service)
    returned = await service.request_purchase_for_item(wo_id, item_id, user_id=user_id)
    return {"status": "queued", "item_id": str(returned)}


# ── SLA scan ──────────────────────────────────────────────────────────────


@router.post(
    "/sla/scan",
    response_model=SLABreachScanResponse,
)
async def scan_sla_breaches(
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    _perm: None = Depends(RequirePermission("service.read")),
    contract_id: uuid.UUID | None = Query(default=None),
    notify: bool = Query(
        default=True,
        description="Emit `service.sla.breached` for not-yet-notified tickets",
    ),
    service: ServiceService = Depends(_get_service),
) -> SLABreachScanResponse:
    """Scan open tickets for SLA breaches.

    Intended to be called by a periodic worker (or, in dev, from the
    dispatcher's dashboard refresh). Each newly-overdue ticket gets a
    ``service.sla.breached`` event exactly once.

    Read-only polling (``notify=false``) only needs ``service.read``. Actually
    notifying — which stamps the ticket and emits ``service.sla.breached`` —
    is a side-effecting dispatcher action and requires ``service.dispatch``;
    a viewer cannot trigger event fan-out or mutate ticket state.
    """
    if notify and not _payload_has_permission(payload, "service.dispatch"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing permission: service.dispatch (required to notify on SLA breach)",
        )
    if contract_id is not None:
        await _verify_contract_project(contract_id, user_id, session, service)
    return await service.scan_sla_breaches(contract_id=contract_id, notify=notify)


# ── T10: SLA breach check + recurring schedules ─────────────────────────


@router.post(
    "/tickets/check-breaches",
    response_model=SLABreachCheckResponse,
)
async def check_ticket_breaches(
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.dispatch")),
    contract_id: uuid.UUID | None = Query(default=None),
    service: ServiceService = Depends(_get_service),
) -> SLABreachCheckResponse:
    """Admin trigger: stamp ``sla_breached_at`` on every now-overdue ticket.

    Idempotent — only tickets where ``sla_breached_at IS NULL`` are touched.
    Emits ``service.sla.breached`` once per newly stamped ticket.
    """
    if contract_id is not None:
        await _verify_contract_project(contract_id, user_id, session, service)
    return await service.check_breaches(contract_id=contract_id)


@router.get(
    "/recurring-schedules/",
    response_model=list[RecurringScheduleResponse],
)
async def list_recurring_schedules(
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.read")),
    project_id: uuid.UUID | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    service: ServiceService = Depends(_get_service),
) -> list[RecurringScheduleResponse]:
    """List recurring schedules (optionally filtered by project / enabled)."""
    if project_id is not None:
        await verify_project_access(project_id, user_id, session)
    items, _ = await service.recurring_repo.list_for_project(
        project_id,
        offset=offset,
        limit=limit,
        enabled=enabled,
    )
    return [RecurringScheduleResponse.model_validate(it) for it in items]


@router.post(
    "/recurring-schedules/",
    response_model=RecurringScheduleResponse,
    status_code=201,
)
async def create_recurring_schedule(
    data: RecurringScheduleCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.create")),
    service: ServiceService = Depends(_get_service),
) -> RecurringScheduleResponse:
    """Create a new RRULE-driven recurring schedule."""
    if data.project_id is not None:
        await verify_project_access(data.project_id, user_id, session)
    if data.contract_id is not None:
        await _verify_contract_project(data.contract_id, user_id, session, service)
    sched = await service.create_recurring(data)
    return RecurringScheduleResponse.model_validate(sched)


@router.get(
    "/recurring-schedules/{schedule_id}",
    response_model=RecurringScheduleResponse,
)
async def get_recurring_schedule(
    schedule_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.read")),
    service: ServiceService = Depends(_get_service),
) -> RecurringScheduleResponse:
    """Get a single recurring schedule."""
    existing = await service.recurring_repo.get_by_id(schedule_id)
    if existing is not None and existing.project_id is not None:
        await verify_project_access(existing.project_id, user_id, session)
    sched = await service.get_recurring(schedule_id)
    return RecurringScheduleResponse.model_validate(sched)


@router.patch(
    "/recurring-schedules/{schedule_id}",
    response_model=RecurringScheduleResponse,
)
async def update_recurring_schedule(
    schedule_id: uuid.UUID,
    data: RecurringScheduleUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.update")),
    service: ServiceService = Depends(_get_service),
) -> RecurringScheduleResponse:
    """Update a recurring schedule (e.g. toggle enabled, edit RRULE)."""
    existing = await service.recurring_repo.get_by_id(schedule_id)
    if existing is not None and existing.project_id is not None:
        await verify_project_access(existing.project_id, user_id, session)
    if data.project_id is not None:
        await verify_project_access(data.project_id, user_id, session)
    sched = await service.update_recurring(schedule_id, data)
    return RecurringScheduleResponse.model_validate(sched)


@router.delete("/recurring-schedules/{schedule_id}", status_code=204)
async def delete_recurring_schedule(
    schedule_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.delete")),
    service: ServiceService = Depends(_get_service),
) -> None:
    """Delete a recurring schedule."""
    existing = await service.recurring_repo.get_by_id(schedule_id)
    if existing is not None and existing.project_id is not None:
        await verify_project_access(existing.project_id, user_id, session)
    await service.delete_recurring(schedule_id)


@router.post(
    "/recurring-schedules/{schedule_id}/materialize",
    response_model=RecurringScheduleMaterializeResponse,
)
async def materialize_recurring_schedule(
    schedule_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.dispatch")),
    force: bool = Query(
        default=False,
        description="Force materialise even if not due / disabled",
    ),
    service: ServiceService = Depends(_get_service),
) -> RecurringScheduleMaterializeResponse:
    """Run a recurring schedule now: stamp one ticket + advance next_run_at."""
    existing = await service.recurring_repo.get_by_id(schedule_id)
    if existing is not None and existing.project_id is not None:
        await verify_project_access(existing.project_id, user_id, session)
    return await service.materialize_recurring(
        schedule_id,
        force=force,
        user_id=user_id,
    )


# ── SLA definitions ───────────────────────────────────────────────────────


@router.get("/sla-definitions/", response_model=list[SLADefinitionResponse])
async def list_slas(
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.read")),
    active_only: bool = Query(default=False),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    service: ServiceService = Depends(_get_service),
) -> list[SLADefinitionResponse]:
    """List SLA definitions."""
    items, _ = await service.sla_repo.list_all(
        offset=offset,
        limit=limit,
        active_only=active_only,
    )
    return [SLADefinitionResponse.model_validate(it) for it in items]


@router.post("/sla-definitions/", response_model=SLADefinitionResponse, status_code=201)
async def create_sla(
    data: SLADefinitionCreate,
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.create")),
    service: ServiceService = Depends(_get_service),
) -> SLADefinitionResponse:
    """Create a new SLA definition."""
    sla = await service.create_sla(data)
    return SLADefinitionResponse.model_validate(sla)


@router.get("/sla-definitions/{sla_id}", response_model=SLADefinitionResponse)
async def get_sla(
    sla_id: uuid.UUID,
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.read")),
    service: ServiceService = Depends(_get_service),
) -> SLADefinitionResponse:
    """Get an SLA definition."""
    sla = await service.get_sla(sla_id)
    return SLADefinitionResponse.model_validate(sla)


@router.patch("/sla-definitions/{sla_id}", response_model=SLADefinitionResponse)
async def update_sla(
    sla_id: uuid.UUID,
    data: SLADefinitionUpdate,
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.update")),
    service: ServiceService = Depends(_get_service),
) -> SLADefinitionResponse:
    """Update an SLA definition."""
    sla = await service.update_sla(sla_id, data)
    return SLADefinitionResponse.model_validate(sla)


@router.delete("/sla-definitions/{sla_id}", status_code=204)
async def delete_sla(
    sla_id: uuid.UUID,
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.delete")),
    service: ServiceService = Depends(_get_service),
) -> None:
    """Delete an SLA definition."""
    await service.delete_sla(sla_id)


# ── Schedules (PPM) ───────────────────────────────────────────────────────


@router.get("/schedules/", response_model=list[ServiceScheduleResponse])
async def list_schedules(
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.read")),
    asset_id: uuid.UUID = Query(...),
    service: ServiceService = Depends(_get_service),
) -> list[ServiceScheduleResponse]:
    """List PPM schedules for an asset."""
    items = await service.schedule_repo.list_for_asset(asset_id)
    return [ServiceScheduleResponse.model_validate(it) for it in items]


@router.post("/schedules/", response_model=ServiceScheduleResponse, status_code=201)
async def create_schedule(
    data: ServiceScheduleCreate,
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.create")),
    service: ServiceService = Depends(_get_service),
) -> ServiceScheduleResponse:
    """Create a new PPM schedule."""
    sched = await service.create_schedule(data)
    return ServiceScheduleResponse.model_validate(sched)


@router.get("/schedules/{schedule_id}", response_model=ServiceScheduleResponse)
async def get_schedule(
    schedule_id: uuid.UUID,
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.read")),
    service: ServiceService = Depends(_get_service),
) -> ServiceScheduleResponse:
    """Get a single PPM schedule."""
    sched = await service.get_schedule(schedule_id)
    return ServiceScheduleResponse.model_validate(sched)


@router.patch("/schedules/{schedule_id}", response_model=ServiceScheduleResponse)
async def update_schedule(
    schedule_id: uuid.UUID,
    data: ServiceScheduleUpdate,
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.update")),
    service: ServiceService = Depends(_get_service),
) -> ServiceScheduleResponse:
    """Update a PPM schedule."""
    sched = await service.update_schedule(schedule_id, data)
    return ServiceScheduleResponse.model_validate(sched)


@router.delete("/schedules/{schedule_id}", status_code=204)
async def delete_schedule(
    schedule_id: uuid.UUID,
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.delete")),
    service: ServiceService = Depends(_get_service),
) -> None:
    """Delete a PPM schedule."""
    await service.delete_schedule(schedule_id)


# ── Checklists ────────────────────────────────────────────────────────────


@router.get("/checklists/", response_model=list[AssetChecklistResponse])
async def list_checklists(
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.read")),
    asset_type: str | None = Query(default=None),
    active_only: bool = Query(default=False),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    service: ServiceService = Depends(_get_service),
) -> list[AssetChecklistResponse]:
    """List inspection-checklist templates."""
    items, _ = await service.checklist_repo.list_all(
        offset=offset,
        limit=limit,
        asset_type=asset_type,
        active_only=active_only,
    )
    return [AssetChecklistResponse.model_validate(it) for it in items]


@router.post("/checklists/", response_model=AssetChecklistResponse, status_code=201)
async def create_checklist(
    data: AssetChecklistCreate,
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.create")),
    service: ServiceService = Depends(_get_service),
) -> AssetChecklistResponse:
    """Create a new inspection-checklist template."""
    cl = await service.create_checklist(data)
    return AssetChecklistResponse.model_validate(cl)


@router.get("/checklists/{checklist_id}", response_model=AssetChecklistResponse)
async def get_checklist(
    checklist_id: uuid.UUID,
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.read")),
    service: ServiceService = Depends(_get_service),
) -> AssetChecklistResponse:
    """Get an inspection-checklist template."""
    cl = await service.get_checklist(checklist_id)
    return AssetChecklistResponse.model_validate(cl)


@router.patch("/checklists/{checklist_id}", response_model=AssetChecklistResponse)
async def update_checklist(
    checklist_id: uuid.UUID,
    data: AssetChecklistUpdate,
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.update")),
    service: ServiceService = Depends(_get_service),
) -> AssetChecklistResponse:
    """Update an inspection-checklist template."""
    cl = await service.update_checklist(checklist_id, data)
    return AssetChecklistResponse.model_validate(cl)


@router.delete("/checklists/{checklist_id}", status_code=204)
async def delete_checklist(
    checklist_id: uuid.UUID,
    _user: CurrentUserId,
    _perm: None = Depends(RequirePermission("service.delete")),
    service: ServiceService = Depends(_get_service),
) -> None:
    """Delete an inspection-checklist template."""
    await service.delete_checklist(checklist_id)
