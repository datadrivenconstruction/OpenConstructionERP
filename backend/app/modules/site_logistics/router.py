# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Site Logistics & Delivery API routes.

Route prefix: /api/v1/site-logistics

    GET    /gates/                         - list gates
    POST   /gates/                         - create gate
    GET    /gates/{gate_id}                - get gate
    PATCH  /gates/{gate_id}                - update gate
    DELETE /gates/{gate_id}                - delete gate

    GET    /laydown-zones/                 - list laydown zones
    POST   /laydown-zones/                 - create laydown zone
    GET    /laydown-zones/{zone_id}        - get laydown zone
    PATCH  /laydown-zones/{zone_id}        - update laydown zone
    DELETE /laydown-zones/{zone_id}        - delete laydown zone

    GET    /deliveries/                    - list deliveries (filter by day/gate/status)
    POST   /deliveries/                    - book delivery
    GET    /deliveries/{delivery_id}       - get delivery
    PATCH  /deliveries/{delivery_id}       - update delivery
    DELETE /deliveries/{delivery_id}       - delete delivery
    POST   /deliveries/{delivery_id}/approve/ - approve delivery
    POST   /deliveries/{delivery_id}/reject/  - reject delivery

    GET    /bill-coverage/                - the project's bill read as a
                                            delivery ledger (booked, delivered,
                                            outstanding per position)

    GET    /stats/                         - aggregate delivery stats

Logistics plan (framework module 6), project-scoped under
``/projects/{project_id}/``: stages, areas (+ allocations), balance, media
(+ demands), plant-positions/power-demand, concept, transports, permits,
customs (+ lines, documents), neighbourhood, neighbour-issues, coordination,
readiness, sweep, catalogue, frame-summary, export/{register}. The contract is
written down in the module's API notes; see the section further down.
"""

import logging
import uuid
from collections.abc import Awaitable
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.core.i18n import get_locale
from app.dependencies import (
    CurrentUserId,
    CurrentUserPayload,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.site_logistics.errors import LogisticsError
from app.modules.site_logistics.messages import translate as plan_translate
from app.modules.site_logistics.plan_schemas import (
    AllocationsPut,
    AreaIn,
    CataloguePinIn,
    ComplaintIn,
    ConceptIn,
    CoordinationIn,
    CustomsIn,
    DemandIn,
    DocumentAddIn,
    DocumentIn,
    LineIn,
    MediaIn,
    NeighbourhoodIn,
    PermitIn,
    PlantDemandIn,
    StageIn,
    SweepIn,
    TransitionIn,
    TransportIn,
)
from app.modules.site_logistics.plan_service import (
    LogisticsPlanService,
    PlanPerms,
    allocation_out,
    area_out,
    complaint_out,
    concept_out,
    coordination_out,
    customs_out,
    demand_out,
    document_out,
    line_out,
    media_out,
    neighbourhood_out,
    permit_out,
    stage_out,
)
from app.modules.site_logistics.schemas import (
    BILL_COVERAGE_LIMIT,
    BillCoverageResponse,
    DeliveryCreate,
    DeliveryDecisionRequest,
    DeliveryLineResponse,
    DeliveryResponse,
    DeliveryUpdate,
    GateCreate,
    GateResponse,
    GateUpdate,
    LaydownZoneCreate,
    LaydownZoneResponse,
    LaydownZoneUpdate,
    SiteLogisticsStatsResponse,
)
from app.modules.site_logistics.service import SiteLogisticsService

router = APIRouter(tags=["site-logistics"])
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> SiteLogisticsService:
    return SiteLogisticsService(session)


# ── Response builders (hand-built to read the JSON ``metadata_`` column, never
# SQLAlchemy's class-level ``metadata`` registry) ─────────────────────────────


def _has(payload: dict[str, Any], permission: str) -> bool:
    """Whether the caller holds a permission, read from the sources RequirePermission reads."""
    from app.core.permissions import permission_registry

    # The permissions of the token, then the live role mapping (which lets the admin role through).
    if permission in (payload.get("permissions") or []):
        return True
    return bool(permission_registry.role_has_permission(str(payload.get("role") or ""), permission))


def _sees_values(payload: dict[str, Any]) -> bool:
    """Decision 12: customs values only with ``site_logistics.customs``."""
    return _has(payload, "site_logistics.customs")


async def _plan_perms(payload: CurrentUserPayload) -> PlanPerms:
    return PlanPerms(
        write=_has(payload, "site_logistics.write"),
        approve=_has(payload, "site_logistics.approve"),
        customs=_has(payload, "site_logistics.customs"),
    )


PlanPermsDep = Annotated[PlanPerms, Depends(_plan_perms)]


def _gate_out(perms: PlanPerms, gate: object) -> GateResponse:
    out = _gate_to_response(gate)
    out.can = SiteLogisticsService.can_plain(perms)
    return out


def _zone_out(perms: PlanPerms, zone: object) -> LaydownZoneResponse:
    out = _zone_to_response(zone)
    out.can = SiteLogisticsService.can_plain(perms)
    return out


async def _delivery_out(service: SiteLogisticsService, perms: PlanPerms, delivery: Any) -> DeliveryResponse:
    out = _delivery_to_response(delivery)
    out.can = await service.can_delivery(delivery, perms)
    out.warnings = await service.delivery_warnings(delivery)
    return out


def _gate_to_response(gate: object) -> GateResponse:
    return GateResponse(
        id=gate.id,  # type: ignore[attr-defined]
        project_id=gate.project_id,  # type: ignore[attr-defined]
        name=gate.name,  # type: ignore[attr-defined]
        open_time=gate.open_time,  # type: ignore[attr-defined]
        close_time=gate.close_time,  # type: ignore[attr-defined]
        capacity_per_slot=gate.capacity_per_slot,  # type: ignore[attr-defined]
        notes=gate.notes,  # type: ignore[attr-defined]
        access_kind=getattr(gate, "access_kind", None),
        max_axle_load_t=getattr(gate, "max_axle_load_t", None),
        max_gross_t=getattr(gate, "max_gross_t", None),
        max_height_m=getattr(gate, "max_height_m", None),
        max_width_m=getattr(gate, "max_width_m", None),
        max_length_m=getattr(gate, "max_length_m", None),
        turning_radius_m=getattr(gate, "turning_radius_m", None),
        created_by=gate.created_by,  # type: ignore[attr-defined]
        metadata=getattr(gate, "metadata_", {}),
        created_at=gate.created_at,  # type: ignore[attr-defined]
        updated_at=gate.updated_at,  # type: ignore[attr-defined]
    )


def _zone_to_response(zone: object) -> LaydownZoneResponse:
    return LaydownZoneResponse(
        id=zone.id,  # type: ignore[attr-defined]
        project_id=zone.project_id,  # type: ignore[attr-defined]
        name=zone.name,  # type: ignore[attr-defined]
        capacity_desc=zone.capacity_desc,  # type: ignore[attr-defined]
        usage_note=zone.usage_note,  # type: ignore[attr-defined]
        site_area_id=getattr(zone, "site_area_id", None),
        created_by=zone.created_by,  # type: ignore[attr-defined]
        metadata=getattr(zone, "metadata_", {}),
        created_at=zone.created_at,  # type: ignore[attr-defined]
        updated_at=zone.updated_at,  # type: ignore[attr-defined]
    )


def _line_to_response(line: object) -> DeliveryLineResponse:
    return DeliveryLineResponse(
        id=line.id,  # type: ignore[attr-defined]
        delivery_id=line.delivery_id,  # type: ignore[attr-defined]
        boq_position_id=line.boq_position_id,  # type: ignore[attr-defined]
        position_ordinal=line.position_ordinal,  # type: ignore[attr-defined]
        description=line.description,  # type: ignore[attr-defined]
        quantity=str(line.quantity),  # type: ignore[attr-defined]
        unit=line.unit,  # type: ignore[attr-defined]
        note=line.note,  # type: ignore[attr-defined]
        sort_order=line.sort_order,  # type: ignore[attr-defined]
    )


def _delivery_to_response(delivery: object) -> DeliveryResponse:
    return DeliveryResponse(
        id=delivery.id,  # type: ignore[attr-defined]
        project_id=delivery.project_id,  # type: ignore[attr-defined]
        gate_id=delivery.gate_id,  # type: ignore[attr-defined]
        supplier_name=delivery.supplier_name,  # type: ignore[attr-defined]
        contact_name=delivery.contact_name,  # type: ignore[attr-defined]
        contact_phone=delivery.contact_phone,  # type: ignore[attr-defined]
        vehicle_type=delivery.vehicle_type,  # type: ignore[attr-defined]
        materials_desc=delivery.materials_desc,  # type: ignore[attr-defined]
        window_start=delivery.window_start,  # type: ignore[attr-defined]
        window_end=delivery.window_end,  # type: ignore[attr-defined]
        status=delivery.status,  # type: ignore[attr-defined]
        po_ref=delivery.po_ref,  # type: ignore[attr-defined]
        notes=delivery.notes,  # type: ignore[attr-defined]
        transport_id=getattr(delivery, "transport_id", None),
        direction=getattr(delivery, "direction", None) or "inbound",
        gross_weight_t=getattr(delivery, "gross_weight_t", None),
        plant_item_id=getattr(delivery, "plant_item_id", None),
        takt_location_id=getattr(delivery, "takt_location_id", None),
        created_by=delivery.created_by,  # type: ignore[attr-defined]
        lines=[_line_to_response(line) for line in getattr(delivery, "lines", [])],
        metadata=getattr(delivery, "metadata_", {}),
        created_at=delivery.created_at,  # type: ignore[attr-defined]
        updated_at=delivery.updated_at,  # type: ignore[attr-defined]
    )


# ── Gates ─────────────────────────────────────────────────────────────────────


@router.get(
    "/gates",
    response_model=list[GateResponse],
    dependencies=[Depends(RequirePermission("site_logistics.read"))],
    include_in_schema=False,
)
@router.get(
    "/gates/",
    response_model=list[GateResponse],
    dependencies=[Depends(RequirePermission("site_logistics.read"))],
)
async def list_gates(
    user_id: CurrentUserId,
    session: SessionDep,
    perms: PlanPermsDep,
    project_id: uuid.UUID = Query(...),
    service: SiteLogisticsService = Depends(_get_service),
) -> list[GateResponse]:
    """List site access gates for a project."""
    await verify_project_access(project_id, user_id, session)
    gates = await service.list_gates(project_id)
    return [_gate_out(perms, g) for g in gates]


@router.post(
    "/gates/",
    response_model=GateResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("site_logistics.write"))],
)
async def create_gate(
    data: GateCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    perms: PlanPermsDep,
    service: SiteLogisticsService = Depends(_get_service),
) -> GateResponse:
    """Create a site access gate."""
    await verify_project_access(data.project_id, user_id, session)
    gate = await service.create_gate(data, user_id=user_id)
    return _gate_out(perms, gate)


@router.get(
    "/gates/{gate_id}",
    response_model=GateResponse,
    dependencies=[Depends(RequirePermission("site_logistics.read"))],
)
async def get_gate(
    gate_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    perms: PlanPermsDep,
    service: SiteLogisticsService = Depends(_get_service),
) -> GateResponse:
    """Get a single gate."""
    gate = await service.get_gate(gate_id)
    await verify_project_access(gate.project_id, user_id, session)
    return _gate_out(perms, gate)


@router.patch(
    "/gates/{gate_id}",
    response_model=GateResponse,
    dependencies=[Depends(RequirePermission("site_logistics.write"))],
)
async def update_gate(
    gate_id: uuid.UUID,
    data: GateUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    perms: PlanPermsDep,
    service: SiteLogisticsService = Depends(_get_service),
) -> GateResponse:
    """Update a gate."""
    existing = await service.get_gate(gate_id)
    await verify_project_access(existing.project_id, user_id, session)
    gate = await service.update_gate(gate_id, data)
    return _gate_out(perms, gate)


@router.delete(
    "/gates/{gate_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("site_logistics.write"))],
)
async def delete_gate(
    gate_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: SiteLogisticsService = Depends(_get_service),
) -> None:
    """Delete a gate."""
    existing = await service.get_gate(gate_id)
    await verify_project_access(existing.project_id, user_id, session)
    await service.delete_gate(gate_id)


# ── Laydown zones ──────────────────────────────────────────────────────────────


@router.get(
    "/laydown-zones",
    response_model=list[LaydownZoneResponse],
    dependencies=[Depends(RequirePermission("site_logistics.read"))],
    include_in_schema=False,
)
@router.get(
    "/laydown-zones/",
    response_model=list[LaydownZoneResponse],
    dependencies=[Depends(RequirePermission("site_logistics.read"))],
)
async def list_zones(
    user_id: CurrentUserId,
    session: SessionDep,
    perms: PlanPermsDep,
    project_id: uuid.UUID = Query(...),
    service: SiteLogisticsService = Depends(_get_service),
) -> list[LaydownZoneResponse]:
    """List material laydown zones for a project."""
    await verify_project_access(project_id, user_id, session)
    zones = await service.list_zones(project_id)
    return [_zone_out(perms, z) for z in zones]


@router.post(
    "/laydown-zones/",
    response_model=LaydownZoneResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("site_logistics.write"))],
)
async def create_zone(
    data: LaydownZoneCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    perms: PlanPermsDep,
    service: SiteLogisticsService = Depends(_get_service),
) -> LaydownZoneResponse:
    """Create a laydown zone."""
    await verify_project_access(data.project_id, user_id, session)
    zone = await service.create_zone(data, user_id=user_id)
    return _zone_out(perms, zone)


@router.get(
    "/laydown-zones/{zone_id}",
    response_model=LaydownZoneResponse,
    dependencies=[Depends(RequirePermission("site_logistics.read"))],
)
async def get_zone(
    zone_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    perms: PlanPermsDep,
    service: SiteLogisticsService = Depends(_get_service),
) -> LaydownZoneResponse:
    """Get a single laydown zone."""
    zone = await service.get_zone(zone_id)
    await verify_project_access(zone.project_id, user_id, session)
    return _zone_out(perms, zone)


@router.patch(
    "/laydown-zones/{zone_id}",
    response_model=LaydownZoneResponse,
    dependencies=[Depends(RequirePermission("site_logistics.write"))],
)
async def update_zone(
    zone_id: uuid.UUID,
    data: LaydownZoneUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    perms: PlanPermsDep,
    service: SiteLogisticsService = Depends(_get_service),
) -> LaydownZoneResponse:
    """Update a laydown zone."""
    existing = await service.get_zone(zone_id)
    await verify_project_access(existing.project_id, user_id, session)
    zone = await service.update_zone(zone_id, data)
    return _zone_out(perms, zone)


@router.delete(
    "/laydown-zones/{zone_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("site_logistics.write"))],
)
async def delete_zone(
    zone_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: SiteLogisticsService = Depends(_get_service),
) -> None:
    """Delete a laydown zone."""
    existing = await service.get_zone(zone_id)
    await verify_project_access(existing.project_id, user_id, session)
    await service.delete_zone(zone_id)


# ── Deliveries ─────────────────────────────────────────────────────────────────


@router.get(
    "/deliveries",
    response_model=list[DeliveryResponse],
    dependencies=[Depends(RequirePermission("site_logistics.read"))],
    include_in_schema=False,
)
@router.get(
    "/deliveries/",
    response_model=list[DeliveryResponse],
    dependencies=[Depends(RequirePermission("site_logistics.read"))],
)
async def list_deliveries(
    user_id: CurrentUserId,
    session: SessionDep,
    perms: PlanPermsDep,
    project_id: uuid.UUID = Query(...),
    day: datetime | None = Query(default=None, description="Filter to deliveries whose window touches this day"),
    gate_id: uuid.UUID | None = Query(default=None),
    delivery_status: str | None = Query(default=None, alias="status"),
    service: SiteLogisticsService = Depends(_get_service),
) -> list[DeliveryResponse]:
    """List deliveries for a project, optionally filtered by day, gate and status."""
    await verify_project_access(project_id, user_id, session)
    deliveries = await service.list_deliveries(
        project_id,
        day=day,
        gate_id=gate_id,
        status_filter=delivery_status,
    )
    return [await _delivery_out(service, perms, d) for d in deliveries]


@router.post(
    "/deliveries/",
    response_model=DeliveryResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("site_logistics.write"))],
)
async def create_delivery(
    data: DeliveryCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    perms: PlanPermsDep,
    service: SiteLogisticsService = Depends(_get_service),
) -> DeliveryResponse:
    """Book an inbound delivery."""
    await verify_project_access(data.project_id, user_id, session)
    delivery = await service.create_delivery(data, user_id=user_id)
    return await _delivery_out(service, perms, delivery)


@router.get(
    "/deliveries/{delivery_id}",
    response_model=DeliveryResponse,
    dependencies=[Depends(RequirePermission("site_logistics.read"))],
)
async def get_delivery(
    delivery_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    perms: PlanPermsDep,
    service: SiteLogisticsService = Depends(_get_service),
) -> DeliveryResponse:
    """Get a single delivery."""
    delivery = await service.get_delivery(delivery_id)
    await verify_project_access(delivery.project_id, user_id, session)
    return await _delivery_out(service, perms, delivery)


@router.patch(
    "/deliveries/{delivery_id}",
    response_model=DeliveryResponse,
    dependencies=[Depends(RequirePermission("site_logistics.write"))],
)
async def update_delivery(
    delivery_id: uuid.UUID,
    data: DeliveryUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    perms: PlanPermsDep,
    service: SiteLogisticsService = Depends(_get_service),
) -> DeliveryResponse:
    """Update a delivery booking."""
    existing = await service.get_delivery(delivery_id)
    await verify_project_access(existing.project_id, user_id, session)
    delivery = await service.update_delivery(delivery_id, data)
    return await _delivery_out(service, perms, delivery)


@router.delete(
    "/deliveries/{delivery_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("site_logistics.write"))],
)
async def delete_delivery(
    delivery_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: SiteLogisticsService = Depends(_get_service),
) -> None:
    """Delete a delivery booking."""
    existing = await service.get_delivery(delivery_id)
    await verify_project_access(existing.project_id, user_id, session)
    await service.delete_delivery(delivery_id)


@router.post(
    "/deliveries/{delivery_id}/approve/",
    response_model=DeliveryResponse,
    dependencies=[Depends(RequirePermission("site_logistics.approve"))],
)
async def approve_delivery(
    delivery_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    perms: PlanPermsDep,
    data: DeliveryDecisionRequest | None = None,
    service: SiteLogisticsService = Depends(_get_service),
) -> DeliveryResponse:
    """Approve a delivery, holding its gate slot (clash-checked)."""
    existing = await service.get_delivery(delivery_id)
    await verify_project_access(existing.project_id, user_id, session)
    delivery = await service.approve_delivery(
        delivery_id,
        reason=data.reason if data else None,
        user_id=user_id,
    )
    return await _delivery_out(service, perms, delivery)


@router.post(
    "/deliveries/{delivery_id}/reject/",
    response_model=DeliveryResponse,
    dependencies=[Depends(RequirePermission("site_logistics.approve"))],
)
async def reject_delivery(
    delivery_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    perms: PlanPermsDep,
    data: DeliveryDecisionRequest | None = None,
    service: SiteLogisticsService = Depends(_get_service),
) -> DeliveryResponse:
    """Reject a delivery, releasing its gate slot."""
    existing = await service.get_delivery(delivery_id)
    await verify_project_access(existing.project_id, user_id, session)
    delivery = await service.reject_delivery(
        delivery_id,
        reason=data.reason if data else None,
        user_id=user_id,
    )
    return await _delivery_out(service, perms, delivery)


# ── Bill coverage ──────────────────────────────────────────────────────────────


@router.get("/can/", dependencies=[Depends(RequirePermission("site_logistics.read"))])
async def board_can(
    user_id: CurrentUserId,
    session: SessionDep,
    perms: PlanPermsDep,
    project_id: uuid.UUID = Query(...),
) -> dict[str, Any]:
    """Whether the caller may add a gate, a laydown zone or a delivery to the project.

    These three lists are plain arrays, so their ``can.create`` is served here:
    ``{"gate": {"create": flag}, "zone": {...}, "delivery": {...}}``.
    """
    await verify_project_access(project_id, user_id, session)
    return SiteLogisticsService.can_board(perms)


@router.get(
    "/bill-coverage",
    response_model=BillCoverageResponse,
    dependencies=[Depends(RequirePermission("site_logistics.read"))],
    include_in_schema=False,
)
@router.get(
    "/bill-coverage/",
    response_model=BillCoverageResponse,
    dependencies=[Depends(RequirePermission("site_logistics.read"))],
)
async def bill_coverage(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    boq_id: uuid.UUID | None = Query(default=None, description="Narrow to a single bill"),
    search: str | None = Query(default=None, max_length=120, description="Filter by ordinal or description"),
    limit: int = Query(default=BILL_COVERAGE_LIMIT, ge=1, le=BILL_COVERAGE_LIMIT),
    service: SiteLogisticsService = Depends(_get_service),
) -> BillCoverageResponse:
    """Read the project's bill with what has been booked and delivered against it.

    Backs both the coverage table on the logistics page and the position picker
    in the booking dialog, so the picker can show what is still outstanding on a
    line at the moment somebody books a lorry against it.
    """
    await verify_project_access(project_id, user_id, session)
    return await service.get_bill_coverage(project_id, boq_id=boq_id, search=search, limit=limit)


# ── Stats ──────────────────────────────────────────────────────────────────────


@router.get(
    "/stats",
    response_model=SiteLogisticsStatsResponse,
    dependencies=[Depends(RequirePermission("site_logistics.read"))],
    include_in_schema=False,
)
@router.get(
    "/stats/",
    response_model=SiteLogisticsStatsResponse,
    dependencies=[Depends(RequirePermission("site_logistics.read"))],
)
async def site_logistics_stats(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    service: SiteLogisticsService = Depends(_get_service),
) -> SiteLogisticsStatsResponse:
    """Aggregate delivery statistics for a project."""
    await verify_project_access(project_id, user_id, session)
    return await service.get_stats(project_id)


# ══ Logistics plan (framework module 6), project-scoped ══════════════════════
#
# Mounted under the module prefix, so the full path is
# ``/api/v1/site-logistics/projects/{project_id}/...``. Every handler calls
# ``verify_project_access`` before it reads anything; child rows are looked up by
# ``(project_id, id)`` in the service, so an id of another project is 404 (rule 20).
# Errors carry ``{"code", "message_key", "message", "violations"?}`` in ``detail``.

PLAN_READ = Depends(RequirePermission("site_logistics.read"))
PLAN_WRITE = Depends(RequirePermission("site_logistics.write"))
PLAN_APPROVE = Depends(RequirePermission("site_logistics.approve"))


async def _plan_run(awaitable: Awaitable[Any]) -> Any:
    """Turn a :class:`LogisticsError` into the documented HTTP error."""
    try:
        return await awaitable
    except LogisticsError as exc:
        message = plan_translate(f"site_logistics.errors.{exc.code}", locale=get_locale() or "en")
        raise HTTPException(status_code=exc.status_code, detail=exc.as_detail(message)) from exc


def _plan_page(
    items: list[Any], offset: int = 0, limit: int | None = None, *, can: dict[str, Any] | None = None
) -> dict[str, Any]:
    window = items[offset : offset + limit] if limit else items[offset:]
    page = {"items": window, "total": len(items), "offset": offset, "limit": limit or len(window)}
    if can is not None:
        page["can"] = can
    return page


async def _with_can(
    svc: LogisticsPlanService,
    project_id: uuid.UUID,
    kind: str,
    row: Any,
    body: dict[str, Any],
    perms: PlanPerms,
    **loaded: Any,
) -> dict[str, Any]:
    """Add ``can`` to a record: what this caller may do with it now, from the guards the writes call."""
    body["can"] = await _plan_run(svc.can(project_id, kind, row, perms, **loaded))
    return body


async def _transport_body(
    svc: LogisticsPlanService, project_id: uuid.UUID, row: Any, perms: PlanPerms
) -> dict[str, Any]:
    cat = await _plan_run(svc.catalogue(project_id))
    view = await _plan_run(svc.transport_view(row, cat, await svc.site_tz(project_id)))
    return await _with_can(svc, project_id, "transport", row, view, perms, view=view, cat=cat)


# ── catalogue ─────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/catalogue", dependencies=[PLAN_READ])
async def plan_catalogue(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """The pinned ``site_logistics`` catalogue of the project, parent chain resolved."""
    await verify_project_access(project_id, user_id, session)
    svc = LogisticsPlanService(session)
    cat = await _plan_run(svc.catalogue(project_id))
    concept = await _plan_run(svc.concept_view(project_id))
    body = cat.model_dump(mode="json")
    body["pin"] = {
        "source": concept["catalogue_source"],
        "id": concept["catalogue_id"],
        "version": concept["catalogue_version"],
    }
    body["resolved_thresholds"] = cat.resolved_thresholds().model_dump(mode="json")
    return body


@router.put("/projects/{project_id}/catalogue", dependencies=[PLAN_APPROVE])
async def plan_pin_catalogue(
    project_id: uuid.UUID,
    body: CataloguePinIn,
    session: SessionDep,
    perms: PlanPermsDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    """Re-pin the project's catalogue (a scheduling decision, manager level)."""
    from app.core.tenant_scope import resolve_tenant_id

    await verify_project_access(project_id, user_id, session)
    svc = LogisticsPlanService(session)
    row = await _plan_run(
        svc.pin_catalogue(
            project_id,
            tenant_id=resolve_tenant_id(payload),
            source=body.source,
            catalogue_id=body.catalogue_id,
            version=body.version,
            actor_id=user_id,
        )
    )
    return await _with_can(svc, project_id, "concept", row, plan_concept_out(row), perms)


# ── stages ────────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/stages", dependencies=[PLAN_READ])
async def plan_list_stages(
    project_id: uuid.UUID, session: SessionDep, perms: PlanPermsDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = LogisticsPlanService(session)
    rows = await svc.stages(project_id)
    out = []
    for s in rows:
        start, end = await svc.stage_dates(s)
        out.append(await _with_can(svc, project_id, "stage", s, stage_out(s, start, end), perms, count=len(rows)))
    return _plan_page(out, can=svc.can_create("stage", perms))


@router.post("/projects/{project_id}/stages", status_code=201, dependencies=[PLAN_WRITE])
async def plan_create_stage(
    project_id: uuid.UUID, body: StageIn, session: SessionDep, perms: PlanPermsDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    row = await _plan_run(
        LogisticsPlanService(session).create_stage(project_id, body.model_dump(exclude_unset=True), user_id)
    )
    return await _with_can(LogisticsPlanService(session), project_id, "stage", row, stage_out(row), perms)


@router.patch("/projects/{project_id}/stages/{stage_id}", dependencies=[PLAN_WRITE])
async def plan_update_stage(
    project_id: uuid.UUID,
    stage_id: uuid.UUID,
    body: StageIn,
    session: SessionDep,
    perms: PlanPermsDep,
    user_id: CurrentUserId,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = LogisticsPlanService(session)
    row = await _plan_run(svc.update_stage(project_id, stage_id, body.model_dump(exclude_unset=True), user_id))
    return await _with_can(svc, project_id, "stage", row, stage_out(row, *(await svc.stage_dates(row))), perms)


@router.post("/projects/{project_id}/stages/{stage_id}/transition", dependencies=[PLAN_WRITE])
async def plan_transition_stage(
    project_id: uuid.UUID,
    stage_id: uuid.UUID,
    body: TransitionIn,
    session: SessionDep,
    perms: PlanPermsDep,
    user_id: CurrentUserId,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    row = await _plan_run(LogisticsPlanService(session).transition_stage(project_id, stage_id, body.target, user_id))
    return await _with_can(LogisticsPlanService(session), project_id, "stage", row, stage_out(row), perms)


@router.delete("/projects/{project_id}/stages/{stage_id}", status_code=204, dependencies=[PLAN_WRITE])
async def plan_delete_stage(
    project_id: uuid.UUID, stage_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> Response:
    await verify_project_access(project_id, user_id, session)
    await _plan_run(LogisticsPlanService(session).delete_stage(project_id, stage_id, user_id))
    return Response(status_code=204)


# ── areas and allocations ─────────────────────────────────────────────────


@router.get("/projects/{project_id}/areas", dependencies=[PLAN_READ])
async def plan_list_areas(
    project_id: uuid.UUID, session: SessionDep, perms: PlanPermsDep, user_id: CurrentUserId
) -> dict[str, Any]:
    from app.modules.site_logistics.models import AreaAllocation, SiteArea

    await verify_project_access(project_id, user_id, session)
    svc = LogisticsPlanService(session)
    allocs = await svc._list(AreaAllocation, project_id)
    out = []
    for a in await svc._list(SiteArea, project_id, SiteArea.code):
        item = area_out(a)
        item["allocations"] = [allocation_out(x) for x in allocs if x.site_area_id == a.id]
        out.append(await _with_can(svc, project_id, "area", a, item, perms))
    return _plan_page(out, can=svc.can_create("area", perms))


@router.post("/projects/{project_id}/areas", status_code=201, dependencies=[PLAN_WRITE])
async def plan_create_area(
    project_id: uuid.UUID, body: AreaIn, session: SessionDep, perms: PlanPermsDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    row = await _plan_run(
        LogisticsPlanService(session).create_area(project_id, body.model_dump(exclude_unset=True), user_id)
    )
    return await _with_can(LogisticsPlanService(session), project_id, "area", row, area_out(row), perms)


@router.patch("/projects/{project_id}/areas/{area_id}", dependencies=[PLAN_WRITE])
async def plan_update_area(
    project_id: uuid.UUID,
    area_id: uuid.UUID,
    body: AreaIn,
    session: SessionDep,
    perms: PlanPermsDep,
    user_id: CurrentUserId,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    row = await _plan_run(
        LogisticsPlanService(session).update_area(project_id, area_id, body.model_dump(exclude_unset=True), user_id)
    )
    return await _with_can(LogisticsPlanService(session), project_id, "area", row, area_out(row), perms)


@router.delete("/projects/{project_id}/areas/{area_id}", status_code=204, dependencies=[PLAN_WRITE])
async def plan_delete_area(
    project_id: uuid.UUID, area_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> Response:
    await verify_project_access(project_id, user_id, session)
    await _plan_run(LogisticsPlanService(session).delete_area(project_id, area_id, user_id))
    return Response(status_code=204)


@router.put("/projects/{project_id}/areas/{area_id}/allocations", dependencies=[PLAN_WRITE])
async def plan_put_allocations(
    project_id: uuid.UUID, area_id: uuid.UUID, body: AllocationsPut, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    """Replace the area's allocations, one per stage."""
    await verify_project_access(project_id, user_id, session)
    items = [i.model_dump(exclude_none=True) for i in body.items]
    rows = await _plan_run(LogisticsPlanService(session).put_allocations(project_id, area_id, items, user_id))
    return _plan_page([allocation_out(r) for r in rows])


@router.get("/projects/{project_id}/balance", dependencies=[PLAN_READ])
async def plan_balance(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    stage: uuid.UUID | None = Query(default=None),
) -> dict[str, Any]:
    """Area and media balance per stage (rules 1 to 3, 8, 10)."""
    await verify_project_access(project_id, user_id, session)
    return await _plan_run(LogisticsPlanService(session).balance(project_id, stage))


# ── media ─────────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/media", dependencies=[PLAN_READ])
async def plan_list_media(
    project_id: uuid.UUID, session: SessionDep, perms: PlanPermsDep, user_id: CurrentUserId
) -> dict[str, Any]:
    from app.modules.site_logistics.models import MediaConnection

    await verify_project_access(project_id, user_id, session)
    svc = LogisticsPlanService(session)
    rows = await svc._list(MediaConnection, project_id, MediaConnection.media_kind)
    items = [await _with_can(svc, project_id, "media", m, media_out(m), perms) for m in rows]
    return _plan_page(items, can=svc.can_create("media", perms))


@router.post("/projects/{project_id}/media", status_code=201, dependencies=[PLAN_WRITE])
async def plan_create_media(
    project_id: uuid.UUID, body: MediaIn, session: SessionDep, perms: PlanPermsDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    row = await _plan_run(
        LogisticsPlanService(session).create_media(project_id, body.model_dump(exclude_unset=True), user_id)
    )
    return await _with_can(LogisticsPlanService(session), project_id, "media", row, media_out(row), perms)


@router.patch("/projects/{project_id}/media/{media_id}", dependencies=[PLAN_WRITE])
async def plan_update_media(
    project_id: uuid.UUID,
    media_id: uuid.UUID,
    body: MediaIn,
    session: SessionDep,
    perms: PlanPermsDep,
    user_id: CurrentUserId,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    row = await _plan_run(
        LogisticsPlanService(session).update_media(project_id, media_id, body.model_dump(exclude_unset=True), user_id)
    )
    return await _with_can(LogisticsPlanService(session), project_id, "media", row, media_out(row), perms)


@router.post("/projects/{project_id}/media/{media_id}/transition", dependencies=[PLAN_WRITE])
async def plan_transition_media(
    project_id: uuid.UUID,
    media_id: uuid.UUID,
    body: TransitionIn,
    session: SessionDep,
    perms: PlanPermsDep,
    user_id: CurrentUserId,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    row = await _plan_run(LogisticsPlanService(session).transition_media(project_id, media_id, body.target, user_id))
    return await _with_can(LogisticsPlanService(session), project_id, "media", row, media_out(row), perms)


@router.delete("/projects/{project_id}/media/{media_id}", status_code=204, dependencies=[PLAN_WRITE])
async def plan_delete_media(
    project_id: uuid.UUID, media_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> Response:
    await verify_project_access(project_id, user_id, session)
    await _plan_run(LogisticsPlanService(session).delete_media(project_id, media_id, user_id))
    return Response(status_code=204)


@router.get("/projects/{project_id}/media/{media_id}/demands", dependencies=[PLAN_READ])
async def plan_list_demands(
    project_id: uuid.UUID, media_id: uuid.UUID, session: SessionDep, perms: PlanPermsDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = LogisticsPlanService(session)
    rows = await _plan_run(svc.demands(project_id, media_id))
    items = [await _with_can(svc, project_id, "demand", d, demand_out(d), perms) for d in rows]
    return _plan_page(items, can=svc.can_create("demand", perms))


@router.post("/projects/{project_id}/media/{media_id}/demands", status_code=201, dependencies=[PLAN_WRITE])
async def plan_create_demand(
    project_id: uuid.UUID,
    media_id: uuid.UUID,
    body: DemandIn,
    session: SessionDep,
    perms: PlanPermsDep,
    user_id: CurrentUserId,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    row = await _plan_run(
        LogisticsPlanService(session).create_demand(project_id, media_id, body.model_dump(exclude_unset=True), user_id)
    )
    return await _with_can(LogisticsPlanService(session), project_id, "demand", row, demand_out(row), perms)


@router.patch("/projects/{project_id}/demands/{demand_id}", dependencies=[PLAN_WRITE])
async def plan_update_demand(
    project_id: uuid.UUID,
    demand_id: uuid.UUID,
    body: DemandIn,
    session: SessionDep,
    perms: PlanPermsDep,
    user_id: CurrentUserId,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    row = await _plan_run(
        LogisticsPlanService(session).update_demand(project_id, demand_id, body.model_dump(exclude_unset=True), user_id)
    )
    return await _with_can(LogisticsPlanService(session), project_id, "demand", row, demand_out(row), perms)


@router.delete("/projects/{project_id}/demands/{demand_id}", status_code=204, dependencies=[PLAN_WRITE])
async def plan_delete_demand(
    project_id: uuid.UUID, demand_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> Response:
    await verify_project_access(project_id, user_id, session)
    await _plan_run(LogisticsPlanService(session).delete_demand(project_id, demand_id, user_id))
    return Response(status_code=204)


@router.put("/projects/{project_id}/plant-positions/power-demand", dependencies=[PLAN_WRITE])
async def plan_sync_plant_demand(
    project_id: uuid.UUID, body: PlantDemandIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    """Rule 9: the power demand of a site plant position, written as its one media demand row."""
    await verify_project_access(project_id, user_id, session)
    row = await _plan_run(
        LogisticsPlanService(session).sync_plant_power_demand(
            project_id,
            site_plant_position_id=body.site_plant_position_id,
            power_demand_kva=body.power_demand_kva,
            stage_id=body.stage_id,
            consumer=body.consumer,
            actor_id=user_id,
        )
    )
    return {"demand": demand_out(row) if row is not None else None}


# ── concept ───────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/concept", dependencies=[PLAN_READ])
async def plan_get_concept(
    project_id: uuid.UUID, session: SessionDep, perms: PlanPermsDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = LogisticsPlanService(session)
    return await _with_can(svc, project_id, "concept", None, await _plan_run(svc.concept_view(project_id)), perms)


@router.put("/projects/{project_id}/concept", dependencies=[PLAN_WRITE])
async def plan_put_concept(
    project_id: uuid.UUID, body: ConceptIn, session: SessionDep, perms: PlanPermsDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    data = body.model_dump(exclude_unset=True)
    if body.strategy is not None:
        # Only what the form sent: a field it does not show keeps its stored value.
        data["strategy"] = [f.model_dump(exclude_unset=True) for f in body.strategy]
    svc = LogisticsPlanService(session)
    row = await _plan_run(svc.put_concept(project_id, data, user_id))
    return await _with_can(svc, project_id, "concept", row, plan_concept_out(row), perms)


# ── transports ────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/transports", dependencies=[PLAN_READ])
async def plan_list_transports(
    project_id: uuid.UUID,
    session: SessionDep,
    perms: PlanPermsDep,
    user_id: CurrentUserId,
    direction: str | None = Query(default=None, pattern=r"^(inbound|outbound)$"),
    state: str | None = Query(default=None, max_length=20),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict[str, Any]:
    from app.modules.site_logistics.models import Transport

    await verify_project_access(project_id, user_id, session)
    svc = LogisticsPlanService(session)
    cat = await _plan_run(svc.catalogue(project_id))
    rows = await svc._list(Transport, project_id, Transport.planned_window_start, direction=direction, state=state)
    tz = await svc.site_tz(project_id)
    quiet = await svc.neighbourhood(project_id)
    items = []
    # Only the page asked for is worked out; the rest of the register is counted.
    for t in rows[offset : offset + limit]:
        view = await svc.transport_view(t, cat, tz)
        items.append(await _with_can(svc, project_id, "transport", t, view, perms, view=view, cat=cat, quiet=quiet))
    page = {"items": items, "total": len(rows), "offset": offset, "limit": limit}
    return {**page, "can": svc.can_create("transport", perms)}


@router.post("/projects/{project_id}/transports", status_code=201, dependencies=[PLAN_WRITE])
async def plan_create_transport(
    project_id: uuid.UUID, body: TransportIn, session: SessionDep, perms: PlanPermsDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = LogisticsPlanService(session)
    row = await _plan_run(svc.create_transport(project_id, body.model_dump(exclude_unset=True), user_id))
    return await _transport_body(svc, project_id, row, perms)


@router.get("/projects/{project_id}/transports/{transport_id}", dependencies=[PLAN_READ])
async def plan_get_transport(
    project_id: uuid.UUID, transport_id: uuid.UUID, session: SessionDep, perms: PlanPermsDep, user_id: CurrentUserId
) -> dict[str, Any]:
    from app.modules.site_logistics.models import Transport

    await verify_project_access(project_id, user_id, session)
    svc = LogisticsPlanService(session)
    row = await _plan_run(svc._get(Transport, project_id, transport_id, "transport_not_found"))
    return await _transport_body(svc, project_id, row, perms)


@router.patch("/projects/{project_id}/transports/{transport_id}", dependencies=[PLAN_WRITE])
async def plan_update_transport(
    project_id: uuid.UUID,
    transport_id: uuid.UUID,
    body: TransportIn,
    session: SessionDep,
    perms: PlanPermsDep,
    user_id: CurrentUserId,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = LogisticsPlanService(session)
    row = await _plan_run(svc.update_transport(project_id, transport_id, body.model_dump(exclude_unset=True), user_id))
    return await _transport_body(svc, project_id, row, perms)


@router.post("/projects/{project_id}/transports/{transport_id}/transition", dependencies=[PLAN_APPROVE])
async def plan_transition_transport(
    project_id: uuid.UUID,
    transport_id: uuid.UUID,
    body: TransitionIn,
    session: SessionDep,
    perms: PlanPermsDep,
    user_id: CurrentUserId,
) -> dict[str, Any]:
    """Move a transport; ``scheduled`` holds a gate slot, so it is a manager decision (rules 5, 6, 13, 19)."""
    await verify_project_access(project_id, user_id, session)
    svc = LogisticsPlanService(session)
    row = await _plan_run(svc.transition_transport(project_id, transport_id, body.target, user_id))
    return await _transport_body(svc, project_id, row, perms)


@router.delete("/projects/{project_id}/transports/{transport_id}", status_code=204, dependencies=[PLAN_WRITE])
async def plan_delete_transport(
    project_id: uuid.UUID, transport_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> Response:
    await verify_project_access(project_id, user_id, session)
    await _plan_run(LogisticsPlanService(session).delete_transport(project_id, transport_id, user_id))
    return Response(status_code=204)


# ── transport permits ─────────────────────────────────────────────────────


@router.get("/projects/{project_id}/permits", dependencies=[PLAN_READ])
async def plan_list_permits(
    project_id: uuid.UUID, session: SessionDep, perms: PlanPermsDep, user_id: CurrentUserId
) -> dict[str, Any]:
    from app.modules.site_logistics.models import TransportPermit

    await verify_project_access(project_id, user_id, session)
    svc = LogisticsPlanService(session)
    rows = await svc._list(TransportPermit, project_id, TransportPermit.valid_to)
    items = [
        await _with_can(svc, project_id, "permit", p, permit_out(p, await svc.permit_links(project_id, p.id)), perms)
        for p in rows
    ]
    return _plan_page(items, can=svc.can_create("permit", perms))


@router.post("/projects/{project_id}/permits", status_code=201, dependencies=[PLAN_WRITE])
async def plan_create_permit(
    project_id: uuid.UUID, body: PermitIn, session: SessionDep, perms: PlanPermsDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = LogisticsPlanService(session)
    row = await _plan_run(svc.create_permit(project_id, body.payload(), user_id))
    body = permit_out(row, await svc.permit_links(project_id, row.id))
    return await _with_can(svc, project_id, "permit", row, body, perms)


@router.patch("/projects/{project_id}/permits/{permit_id}", dependencies=[PLAN_WRITE])
async def plan_update_permit(
    project_id: uuid.UUID,
    permit_id: uuid.UUID,
    body: PermitIn,
    session: SessionDep,
    perms: PlanPermsDep,
    user_id: CurrentUserId,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = LogisticsPlanService(session)
    row = await _plan_run(svc.update_permit(project_id, permit_id, body.payload(), user_id))
    body = permit_out(row, await svc.permit_links(project_id, row.id))
    return await _with_can(svc, project_id, "permit", row, body, perms)


@router.post("/projects/{project_id}/permits/{permit_id}/transition", dependencies=[PLAN_WRITE])
async def plan_transition_permit(
    project_id: uuid.UUID,
    permit_id: uuid.UUID,
    body: TransitionIn,
    session: SessionDep,
    perms: PlanPermsDep,
    user_id: CurrentUserId,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = LogisticsPlanService(session)
    row = await _plan_run(svc.transition_permit(project_id, permit_id, body.target, user_id))
    body = permit_out(row, await svc.permit_links(project_id, row.id))
    return await _with_can(svc, project_id, "permit", row, body, perms)


@router.delete("/projects/{project_id}/permits/{permit_id}", status_code=204, dependencies=[PLAN_WRITE])
async def plan_delete_permit(
    project_id: uuid.UUID, permit_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> Response:
    await verify_project_access(project_id, user_id, session)
    await _plan_run(LogisticsPlanService(session).delete_permit(project_id, permit_id, user_id))
    return Response(status_code=204)


# ── customs ───────────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/customs", dependencies=[PLAN_READ])
async def plan_list_customs(
    project_id: uuid.UUID, session: SessionDep, perms: PlanPermsDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    from app.modules.site_logistics.models import CustomsCase, CustomsDocument, CustomsLine

    await verify_project_access(project_id, user_id, session)
    svc = LogisticsPlanService(session)
    rows = await svc._list(CustomsCase, project_id, CustomsCase.created_at)
    cat = await _plan_run(svc.catalogue(project_id))
    # The documents and lines of every case in two reads, not two per case.
    docs = [(d.customs_case_id, document_out(d)) for d in await svc._list(CustomsDocument, project_id)]
    lines = [x.customs_case_id for x in await svc._list(CustomsLine, project_id)]
    sees = _sees_values(payload)
    items = [
        await _with_can(
            svc,
            project_id,
            "customs",
            c,
            customs_out(c, sees),
            perms,
            cat=cat,
            docs=[d for cid, d in docs if cid == c.id],
            line_count=lines.count(c.id),
        )
        for c in rows
    ]
    return _plan_page(items, can=svc.can_create("customs", perms))


@router.post("/projects/{project_id}/customs", status_code=201, dependencies=[PLAN_WRITE])
async def plan_create_customs(
    project_id: uuid.UUID,
    body: CustomsIn,
    session: SessionDep,
    perms: PlanPermsDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    sees = _sees_values(payload)
    row = await _plan_run(
        LogisticsPlanService(session).create_customs(
            project_id, body.model_dump(exclude_unset=True), user_id, can_see_values=sees
        )
    )
    return await _with_can(LogisticsPlanService(session), project_id, "customs", row, customs_out(row, sees), perms)


@router.get("/projects/{project_id}/customs/{case_id}", dependencies=[PLAN_READ])
async def plan_get_customs(
    project_id: uuid.UUID,
    case_id: uuid.UUID,
    session: SessionDep,
    perms: PlanPermsDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    """One case with its incoterm card, lines and document checklist."""
    from app.modules.site_logistics.models import CustomsCase

    await verify_project_access(project_id, user_id, session)
    svc = LogisticsPlanService(session)
    sees = _sees_values(payload)
    row = await _plan_run(svc._get(CustomsCase, project_id, case_id, "customs_not_found"))
    cat = await svc.catalogue(project_id)
    incoterm = svc.incoterm_of(cat, row)
    out = customs_out(row, sees)
    out["incoterm_card"] = incoterm.model_dump(mode="json") if incoterm is not None else None
    lines = await svc.lines(project_id, row.id)
    documents = await svc.documents(project_id, row.id)
    out["lines"] = [await _with_can(svc, project_id, "line", x, line_out(x, sees), perms, case=row) for x in lines]
    out["documents"] = [
        await _with_can(svc, project_id, "document", d, document_out(d), perms, case=row) for d in documents
    ]
    return await _with_can(
        svc,
        project_id,
        "customs",
        row,
        out,
        perms,
        cat=cat,
        docs=[document_out(d) for d in documents],
        line_count=len(lines),
    )


@router.patch("/projects/{project_id}/customs/{case_id}", dependencies=[PLAN_WRITE])
async def plan_update_customs(
    project_id: uuid.UUID,
    case_id: uuid.UUID,
    body: CustomsIn,
    session: SessionDep,
    perms: PlanPermsDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    sees = _sees_values(payload)
    row = await _plan_run(
        LogisticsPlanService(session).update_customs(
            project_id, case_id, body.model_dump(exclude_unset=True), user_id, can_see_values=sees
        )
    )
    return await _with_can(LogisticsPlanService(session), project_id, "customs", row, customs_out(row, sees), perms)


@router.post("/projects/{project_id}/customs/{case_id}/transition", dependencies=[PLAN_WRITE])
async def plan_transition_customs(
    project_id: uuid.UUID,
    case_id: uuid.UUID,
    body: TransitionIn,
    session: SessionDep,
    perms: PlanPermsDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    row = await _plan_run(LogisticsPlanService(session).transition_customs(project_id, case_id, body.target, user_id))
    return await _with_can(
        LogisticsPlanService(session), project_id, "customs", row, customs_out(row, _sees_values(payload)), perms
    )


@router.delete("/projects/{project_id}/customs/{case_id}", status_code=204, dependencies=[PLAN_WRITE])
async def plan_delete_customs(
    project_id: uuid.UUID, case_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> Response:
    await verify_project_access(project_id, user_id, session)
    await _plan_run(LogisticsPlanService(session).delete_customs(project_id, case_id, user_id))
    return Response(status_code=204)


@router.get("/projects/{project_id}/customs/{case_id}/lines", dependencies=[PLAN_READ])
async def plan_list_lines(
    project_id: uuid.UUID,
    case_id: uuid.UUID,
    session: SessionDep,
    perms: PlanPermsDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = LogisticsPlanService(session)
    rows = await _plan_run(svc.lines(project_id, case_id))
    sees = _sees_values(payload)
    items = [await _with_can(svc, project_id, "line", x, line_out(x, sees), perms) for x in rows]
    return _plan_page(items, can={"create": (await svc.can_in_case(project_id, case_id, perms))["line"]})


@router.post("/projects/{project_id}/customs/{case_id}/lines", status_code=201, dependencies=[PLAN_WRITE])
async def plan_create_line(
    project_id: uuid.UUID,
    case_id: uuid.UUID,
    body: LineIn,
    session: SessionDep,
    perms: PlanPermsDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    sees = _sees_values(payload)
    row = await _plan_run(
        LogisticsPlanService(session).create_line(
            project_id, case_id, body.model_dump(exclude_unset=True), user_id, can_see_values=sees
        )
    )
    return await _with_can(LogisticsPlanService(session), project_id, "line", row, line_out(row, sees), perms)


@router.patch("/projects/{project_id}/customs-lines/{line_id}", dependencies=[PLAN_WRITE])
async def plan_update_line(
    project_id: uuid.UUID,
    line_id: uuid.UUID,
    body: LineIn,
    session: SessionDep,
    perms: PlanPermsDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    sees = _sees_values(payload)
    row = await _plan_run(
        LogisticsPlanService(session).update_line(
            project_id, line_id, body.model_dump(exclude_unset=True), user_id, can_see_values=sees
        )
    )
    return await _with_can(LogisticsPlanService(session), project_id, "line", row, line_out(row, sees), perms)


@router.delete("/projects/{project_id}/customs-lines/{line_id}", status_code=204, dependencies=[PLAN_WRITE])
async def plan_delete_line(
    project_id: uuid.UUID, line_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> Response:
    await verify_project_access(project_id, user_id, session)
    await _plan_run(LogisticsPlanService(session).delete_line(project_id, line_id, user_id))
    return Response(status_code=204)


@router.get("/projects/{project_id}/customs/{case_id}/documents", dependencies=[PLAN_READ])
async def plan_list_documents(
    project_id: uuid.UUID, case_id: uuid.UUID, session: SessionDep, perms: PlanPermsDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = LogisticsPlanService(session)
    rows = await _plan_run(svc.documents(project_id, case_id))
    items = [await _with_can(svc, project_id, "document", d, document_out(d), perms) for d in rows]
    return _plan_page(items, can={"create": (await svc.can_in_case(project_id, case_id, perms))["document"]})


@router.post("/projects/{project_id}/customs/{case_id}/documents", status_code=201, dependencies=[PLAN_WRITE])
async def plan_add_document(
    project_id: uuid.UUID,
    case_id: uuid.UUID,
    body: DocumentAddIn,
    session: SessionDep,
    perms: PlanPermsDep,
    user_id: CurrentUserId,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    row = await _plan_run(LogisticsPlanService(session).add_document(project_id, case_id, body.kind, user_id))
    return await _with_can(LogisticsPlanService(session), project_id, "document", row, document_out(row), perms)


@router.patch("/projects/{project_id}/customs-documents/{document_id}", dependencies=[PLAN_WRITE])
async def plan_update_document(
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    body: DocumentIn,
    session: SessionDep,
    perms: PlanPermsDep,
    user_id: CurrentUserId,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    row = await _plan_run(
        LogisticsPlanService(session).update_document(
            project_id, document_id, body.model_dump(exclude_unset=True), user_id
        )
    )
    return await _with_can(LogisticsPlanService(session), project_id, "document", row, document_out(row), perms)


# ── neighbourhood ─────────────────────────────────────────────────────────


@router.get("/projects/{project_id}/neighbourhood", dependencies=[PLAN_READ])
async def plan_get_neighbourhood(
    project_id: uuid.UUID, session: SessionDep, perms: PlanPermsDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    svc = LogisticsPlanService(session)
    plan = await _plan_run(svc.neighbourhood_view(project_id))
    return {"plan": await _with_can(svc, project_id, "neighbourhood", None, plan, perms)}


@router.put("/projects/{project_id}/neighbourhood", dependencies=[PLAN_WRITE])
async def plan_put_neighbourhood(
    project_id: uuid.UUID, body: NeighbourhoodIn, session: SessionDep, perms: PlanPermsDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    row = await _plan_run(
        LogisticsPlanService(session).put_neighbourhood(project_id, body.model_dump(exclude_unset=True), user_id)
    )
    return {
        "plan": await _with_can(
            LogisticsPlanService(session), project_id, "neighbourhood", row, neighbourhood_out(row), perms
        )
    }


@router.get("/projects/{project_id}/neighbour-issues", dependencies=[PLAN_READ])
async def plan_list_complaints(
    project_id: uuid.UUID,
    session: SessionDep,
    perms: PlanPermsDep,
    user_id: CurrentUserId,
    state: str | None = Query(default=None, max_length=20),
) -> dict[str, Any]:
    from app.modules.site_logistics.models import NeighbourIssue

    await verify_project_access(project_id, user_id, session)
    svc = LogisticsPlanService(session)
    rows = await svc._list(NeighbourIssue, project_id, NeighbourIssue.reported_on.desc(), state=state)
    items = [await _with_can(svc, project_id, "complaint", c, complaint_out(c), perms) for c in rows]
    return _plan_page(items, can=svc.can_create("complaint", perms))


@router.post("/projects/{project_id}/neighbour-issues", status_code=201, dependencies=[PLAN_WRITE])
async def plan_create_complaint(
    project_id: uuid.UUID, body: ComplaintIn, session: SessionDep, perms: PlanPermsDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    row = await _plan_run(
        LogisticsPlanService(session).create_complaint(project_id, body.model_dump(exclude_unset=True), user_id)
    )
    return await _with_can(LogisticsPlanService(session), project_id, "complaint", row, complaint_out(row), perms)


@router.patch("/projects/{project_id}/neighbour-issues/{issue_id}", dependencies=[PLAN_WRITE])
async def plan_update_complaint(
    project_id: uuid.UUID,
    issue_id: uuid.UUID,
    body: ComplaintIn,
    session: SessionDep,
    perms: PlanPermsDep,
    user_id: CurrentUserId,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    row = await _plan_run(
        LogisticsPlanService(session).update_complaint(
            project_id, issue_id, body.model_dump(exclude_unset=True), user_id
        )
    )
    return await _with_can(LogisticsPlanService(session), project_id, "complaint", row, complaint_out(row), perms)


@router.post("/projects/{project_id}/neighbour-issues/{issue_id}/transition", dependencies=[PLAN_WRITE])
async def plan_transition_complaint(
    project_id: uuid.UUID,
    issue_id: uuid.UUID,
    body: TransitionIn,
    session: SessionDep,
    perms: PlanPermsDep,
    user_id: CurrentUserId,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    row = await _plan_run(
        LogisticsPlanService(session).transition_complaint(project_id, issue_id, body.target, user_id)
    )
    return await _with_can(LogisticsPlanService(session), project_id, "complaint", row, complaint_out(row), perms)


@router.delete("/projects/{project_id}/neighbour-issues/{issue_id}", status_code=204, dependencies=[PLAN_WRITE])
async def plan_delete_complaint(
    project_id: uuid.UUID, issue_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> Response:
    await verify_project_access(project_id, user_id, session)
    await _plan_run(LogisticsPlanService(session).delete_complaint(project_id, issue_id, user_id))
    return Response(status_code=204)


@router.get("/projects/{project_id}/coordination", dependencies=[PLAN_READ])
async def plan_list_coordination(
    project_id: uuid.UUID, session: SessionDep, perms: PlanPermsDep, user_id: CurrentUserId
) -> dict[str, Any]:
    from app.modules.site_logistics.models import CoordinationEntry

    await verify_project_access(project_id, user_id, session)
    svc = LogisticsPlanService(session)
    rows = await svc._list(CoordinationEntry, project_id, CoordinationEntry.entry_date.desc())
    items = [await _with_can(svc, project_id, "coordination", x, coordination_out(x), perms) for x in rows]
    return _plan_page(items, can=svc.can_create("coordination", perms))


@router.post("/projects/{project_id}/coordination", status_code=201, dependencies=[PLAN_WRITE])
async def plan_create_coordination(
    project_id: uuid.UUID, body: CoordinationIn, session: SessionDep, perms: PlanPermsDep, user_id: CurrentUserId
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    row = await _plan_run(
        LogisticsPlanService(session).create_coordination(project_id, body.model_dump(exclude_unset=True), user_id)
    )
    return await _with_can(LogisticsPlanService(session), project_id, "coordination", row, coordination_out(row), perms)


@router.patch("/projects/{project_id}/coordination/{entry_id}", dependencies=[PLAN_WRITE])
async def plan_update_coordination(
    project_id: uuid.UUID,
    entry_id: uuid.UUID,
    body: CoordinationIn,
    session: SessionDep,
    perms: PlanPermsDep,
    user_id: CurrentUserId,
) -> dict[str, Any]:
    await verify_project_access(project_id, user_id, session)
    row = await _plan_run(
        LogisticsPlanService(session).update_coordination(
            project_id, entry_id, body.model_dump(exclude_unset=True), user_id
        )
    )
    return await _with_can(LogisticsPlanService(session), project_id, "coordination", row, coordination_out(row), perms)


@router.delete("/projects/{project_id}/coordination/{entry_id}", status_code=204, dependencies=[PLAN_WRITE])
async def plan_delete_coordination(
    project_id: uuid.UUID, entry_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> Response:
    await verify_project_access(project_id, user_id, session)
    await _plan_run(LogisticsPlanService(session).delete_coordination(project_id, entry_id, user_id))
    return Response(status_code=204)


# ── what a link field can point at ────────────────────────────────────────


@router.get("/projects/{project_id}/link-options/{kind}", dependencies=[PLAN_READ])
async def plan_link_options(
    project_id: uuid.UUID,
    kind: str,
    session: SessionDep,
    user_id: CurrentUserId,
    search: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict[str, Any]:
    """The rows of THIS project a plan record can link to: activities, takt, purchase orders, documents.

    A write checks the id against the project again, so this list is a
    convenience for the form and never the guard.
    """
    await verify_project_access(project_id, user_id, session)
    items = await _plan_run(LogisticsPlanService(session).link_options(project_id, kind, search=search, limit=limit))
    return {"items": items, "total": len(items)}


# ── readiness, sweeps, frame summary, exports ─────────────────────────────


@router.get("/projects/{project_id}/readiness", dependencies=[PLAN_READ])
async def plan_readiness(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """Readiness of the plan for the gate into construction, with every finding. Reads only."""
    await verify_project_access(project_id, user_id, session)
    return await _plan_run(LogisticsPlanService(session).readiness(project_id))


@router.post("/projects/{project_id}/validate", dependencies=[PLAN_READ])
async def plan_validate(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> dict[str, Any]:
    """Run the ``site_logistics`` rule set over the plan: every plan rule and the delivery rules."""
    await verify_project_access(project_id, user_id, session)
    return await _plan_run(
        LogisticsPlanService(session).validate(project_id, locale=get_locale() or "en", actor_id=user_id)
    )


@router.post("/projects/{project_id}/sweep", dependencies=[PLAN_WRITE])
async def plan_sweep(
    project_id: uuid.UUID, body: SweepIn, session: SessionDep, user_id: CurrentUserId
) -> dict[str, Any]:
    """Run the dated rules now: permit expiry (7), overdue complaints (18), arrivals from goods receipts (19).

    The date is the server's date on the site clock; the request carries none.
    """
    await verify_project_access(project_id, user_id, session)
    svc = LogisticsPlanService(session)
    permits = await _plan_run(svc.sweep_permits(project_id, user_id))
    overdue = await _plan_run(svc.sweep_complaints(project_id, user_id))
    arrived = await _plan_run(svc.sync_arrivals(project_id, user_id))
    return {"permits": permits, "complaints_overdue": overdue, "transports_arrived": arrived}


@router.get("/projects/{project_id}/frame-summary", dependencies=[PLAN_READ])
async def plan_frame_summary(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, payload: CurrentUserPayload
) -> dict[str, Any]:
    """The content of the governance frame document for logistics."""
    await verify_project_access(project_id, user_id, session)
    return await _plan_run(
        LogisticsPlanService(session).frame_summary(project_id, can_see_values=_sees_values(payload))
    )


@router.get("/projects/{project_id}/export/{register}", dependencies=[PLAN_READ])
async def plan_export(
    project_id: uuid.UUID,
    register: str,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    fmt: str = Query(default="pdf", alias="format", pattern=r"^(pdf|xlsx)$"),
) -> Response:
    """One register as PDF or XLSX (rule 21)."""
    from app.modules.projects.models import Project
    from app.modules.site_logistics import export as plan_export_mod
    from app.modules.site_logistics.models import CoordinationEntry, CustomsDocument, CustomsLine, NeighbourIssue

    await verify_project_access(project_id, user_id, session)
    if register not in plan_export_mod.REGISTERS:
        raise HTTPException(status_code=404, detail={"code": "unknown_register"})
    svc = LogisticsPlanService(session)
    summary = await _plan_run(svc.frame_summary(project_id, can_see_values=_sees_values(payload)))
    cat = await svc.catalogue(project_id)
    data: dict[str, Any] = {**summary, "groups": {k.code: k.balance_group for k in cat.area_kinds}}
    if register == "customs":
        cases = []
        for c in summary["customs"]:
            cid = uuid.UUID(c["id"])
            lines = await svc._list(CustomsLine, project_id, customs_case_id=cid)
            docs = await svc._list(CustomsDocument, project_id, customs_case_id=cid)
            cases.append(
                {
                    **c,
                    "hs_codes": ", ".join(x.hs_code for x in lines),
                    "documents": ", ".join(f"{d.kind}: {d.state}" for d in docs if d.required),
                }
            )
        data["customs"] = cases
    if register == "neighbourhood":
        data["complaints"] = [complaint_out(c) for c in await svc._list(NeighbourIssue, project_id)]
        data["coordination"] = [coordination_out(e) for e in await svc._list(CoordinationEntry, project_id)]
    project = await session.get(Project, project_id)
    locale = plan_export_mod.written_locale(get_locale())
    body = plan_export_mod.render(
        register,
        plan_export_mod.register_rows(register, data),
        project_name=getattr(project, "name", "") or "",
        locale=locale,
        as_of=summary["as_of"],
        fmt=fmt,
    )
    media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if fmt == "xlsx" else "application/pdf"
    return Response(
        content=body,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="logistics_{register}.{fmt}"',
            # The language the register was written in, which is not always the one asked for.
            "Content-Language": locale,
        },
    )


def plan_concept_out(row: Any) -> dict[str, Any]:
    return concept_out(row)
