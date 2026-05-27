"""‌⁠‍Equipment & Fleet API routes.

Endpoints (mounted at /api/v1/equipment/):

    GET    /types                           - List equipment types
    POST   /types                           - Create equipment type

    GET    /equipment                       - List equipment
    POST   /equipment                       - Create equipment
    GET    /equipment/{id}                  - Get single equipment
    PATCH  /equipment/{id}                  - Update equipment
    DELETE /equipment/{id}                  - Delete equipment
    GET    /equipment/{id}/dashboard        - Per-unit dashboard

    POST   /equipment/{id}/telemetry        - Append a telemetry reading
    GET    /equipment/{id}/telemetry        - List telemetry (since=)

    GET    /maintenance-schedules           - List schedules (equipment_id=)
    POST   /maintenance-schedules           - Create schedule
    PATCH  /maintenance-schedules/{id}      - Update schedule
    DELETE /maintenance-schedules/{id}      - Delete schedule
    GET    /maintenance-schedules/due-within  - Generate WO stubs for due schedules

    GET    /maintenance-work-orders         - List WOs
    POST   /maintenance-work-orders         - Create WO
    POST   /maintenance-work-orders/{id}/complete  - Complete WO
    PATCH  /maintenance-work-orders/{id}    - Update WO
    DELETE /maintenance-work-orders/{id}    - Delete WO

    GET    /inspections                     - List inspections (equipment_id=)
    POST   /inspections                     - Create inspection
    PATCH  /inspections/{id}                - Update inspection
    DELETE /inspections/{id}                - Delete inspection
    GET    /inspections/expiring            - Inspections expiring within N days

    GET    /rentals                         - List rentals
    POST   /rentals                         - Create rental
    POST   /rentals/{id}/return             - Return a rental
    PATCH  /rentals/{id}                    - Update rental
    DELETE /rentals/{id}                    - Delete rental

    GET    /fuel-logs                       - List fuel logs (equipment_id=)
    POST   /fuel-logs                       - Create fuel log
    PATCH  /fuel-logs/{id}                  - Update fuel log
    DELETE /fuel-logs/{id}                  - Delete fuel log
    GET    /fuel-logs/efficiency            - L/cost per period for an equipment

    GET    /parts-logs                      - List parts logs (equipment_id=)
    POST   /parts-logs                      - Create parts log

    GET    /damage-reports                  - List damage reports
    POST   /damage-reports                  - Create damage report
    PATCH  /damage-reports/{id}             - Update damage report

    GET    /dashboard/fleet                 - Fleet-wide dashboard
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.equipment.schemas import (
    DamageReportCreate,
    DamageReportResponse,
    DamageReportUpdate,
    EquipmentCreate,
    EquipmentDashboardResponse,
    EquipmentRentalCreate,
    EquipmentRentalResponse,
    EquipmentRentalUpdate,
    EquipmentResponse,
    EquipmentTypeCreate,
    EquipmentTypeResponse,
    EquipmentTypeUpdate,
    EquipmentUpdate,
    FleetDashboardResponse,
    FuelLogCreate,
    FuelLogResponse,
    FuelLogUpdate,
    InspectionCreate,
    InspectionResponse,
    InspectionUpdate,
    MaintenanceScheduleCreate,
    MaintenanceScheduleResponse,
    MaintenanceScheduleUpdate,
    MaintenanceWorkOrderCreate,
    MaintenanceWorkOrderResponse,
    MaintenanceWorkOrderUpdate,
    PartsLogCreate,
    PartsLogResponse,
    TelemetryReadingCreate,
    TelemetryReadingResponse,
)
from app.modules.equipment.service import EquipmentService

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> EquipmentService:
    return EquipmentService(session)


# ── Equipment Types ──────────────────────────────────────────────────────


@router.get("/types/", response_model=list[EquipmentTypeResponse])
async def list_types(
    _perm: None = Depends(RequirePermission("equipment.read")),
    service: EquipmentService = Depends(_get_service),
) -> list[EquipmentTypeResponse]:
    types = await service.list_types()
    return [EquipmentTypeResponse.model_validate(t) for t in types]


@router.post("/types/", response_model=EquipmentTypeResponse, status_code=201)
async def create_type(
    data: EquipmentTypeCreate,
    _perm: None = Depends(RequirePermission("equipment.create")),
    service: EquipmentService = Depends(_get_service),
) -> EquipmentTypeResponse:
    t = await service.create_type(data)
    return EquipmentTypeResponse.model_validate(t)


@router.patch("/types/{type_id}", response_model=EquipmentTypeResponse)
async def update_type(
    type_id: uuid.UUID,
    data: EquipmentTypeUpdate,
    _perm: None = Depends(RequirePermission("equipment.update")),
    service: EquipmentService = Depends(_get_service),
) -> EquipmentTypeResponse:
    t = await service.type_repo.get_by_id(type_id)
    if t is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Equipment type not found",
        )
    fields = data.model_dump(exclude_unset=True)
    if fields:
        await service.type_repo.update_fields(type_id, **fields)
        await service.session.refresh(t)
    return EquipmentTypeResponse.model_validate(t)


@router.delete("/types/{type_id}", status_code=204)
async def delete_type(
    type_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("equipment.delete")),
    service: EquipmentService = Depends(_get_service),
) -> None:
    await service.delete_type(type_id)


# ── Equipment CRUD ───────────────────────────────────────────────────────


@router.get("/equipment/", response_model=list[EquipmentResponse])
async def list_equipment(
    _perm: None = Depends(RequirePermission("equipment.read")),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    status_filter: str | None = Query(default=None, alias="status"),
    type_filter: str | None = Query(default=None, alias="type"),
    ownership: str | None = Query(default=None),
    service: EquipmentService = Depends(_get_service),
) -> list[EquipmentResponse]:
    items, _ = await service.equipment_repo.list_(
        offset=offset,
        limit=limit,
        status=status_filter,
        type_code=type_filter,
        ownership=ownership,
    )
    return [EquipmentResponse.model_validate(i) for i in items]


@router.post("/equipment/", response_model=EquipmentResponse, status_code=201)
async def create_equipment(
    data: EquipmentCreate,
    _perm: None = Depends(RequirePermission("equipment.create")),
    service: EquipmentService = Depends(_get_service),
) -> EquipmentResponse:
    e = await service.create_equipment(data)
    return EquipmentResponse.model_validate(e)


@router.get("/equipment/{equipment_id}", response_model=EquipmentResponse)
async def get_equipment(
    equipment_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("equipment.read")),
    service: EquipmentService = Depends(_get_service),
) -> EquipmentResponse:
    e = await service.get_equipment(equipment_id)
    await verify_project_access(e.project_id, str(user_id), session)
    return EquipmentResponse.model_validate(e)


@router.patch("/equipment/{equipment_id}", response_model=EquipmentResponse)
async def update_equipment(
    equipment_id: uuid.UUID,
    data: EquipmentUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("equipment.update")),
    service: EquipmentService = Depends(_get_service),
) -> EquipmentResponse:
    existing = await service.get_equipment(equipment_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    e = await service.update_equipment(equipment_id, data)
    return EquipmentResponse.model_validate(e)


@router.delete("/equipment/{equipment_id}", status_code=204)
async def delete_equipment(
    equipment_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("equipment.delete")),
    service: EquipmentService = Depends(_get_service),
) -> None:
    existing = await service.get_equipment(equipment_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    await service.delete_equipment(equipment_id)


@router.get(
    "/equipment/{equipment_id}/dashboard",
    response_model=EquipmentDashboardResponse,
)
async def equipment_dashboard(
    equipment_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("equipment.read")),
    service: EquipmentService = Depends(_get_service),
) -> EquipmentDashboardResponse:
    return await service.equipment_dashboard(equipment_id)


# ── Telemetry ────────────────────────────────────────────────────────────


@router.post(
    "/equipment/{equipment_id}/telemetry",
    response_model=TelemetryReadingResponse,
    status_code=201,
)
async def record_telemetry(
    equipment_id: uuid.UUID,
    data: TelemetryReadingCreate,
    _perm: None = Depends(RequirePermission("equipment.record_telemetry")),
    service: EquipmentService = Depends(_get_service),
) -> TelemetryReadingResponse:
    reading = await service.record_telemetry(equipment_id, data)
    return TelemetryReadingResponse.model_validate(reading)


@router.get(
    "/equipment/{equipment_id}/telemetry",
    response_model=list[TelemetryReadingResponse],
)
async def list_telemetry(
    equipment_id: uuid.UUID,
    since: datetime | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=5000),
    _perm: None = Depends(RequirePermission("equipment.read")),
    service: EquipmentService = Depends(_get_service),
) -> list[TelemetryReadingResponse]:
    readings = await service.list_telemetry(equipment_id, since=since, limit=limit)
    return [TelemetryReadingResponse.model_validate(r) for r in readings]


# ── Maintenance Schedules ────────────────────────────────────────────────


@router.get(
    "/maintenance-schedules/",
    response_model=list[MaintenanceScheduleResponse],
)
async def list_schedules(
    equipment_id: uuid.UUID | None = Query(default=None),
    _perm: None = Depends(RequirePermission("equipment.read")),
    service: EquipmentService = Depends(_get_service),
) -> list[MaintenanceScheduleResponse]:
    if equipment_id is not None:
        items = await service.schedule_repo.list_for_equipment(equipment_id)
    else:
        items = await service.schedule_repo.list_active()
    return [MaintenanceScheduleResponse.model_validate(i) for i in items]


@router.post(
    "/maintenance-schedules/",
    response_model=MaintenanceScheduleResponse,
    status_code=201,
)
async def create_schedule(
    data: MaintenanceScheduleCreate,
    _perm: None = Depends(RequirePermission("equipment.create")),
    service: EquipmentService = Depends(_get_service),
) -> MaintenanceScheduleResponse:
    s = await service.create_schedule(data)
    return MaintenanceScheduleResponse.model_validate(s)


@router.patch(
    "/maintenance-schedules/{schedule_id}",
    response_model=MaintenanceScheduleResponse,
)
async def update_schedule(
    schedule_id: uuid.UUID,
    data: MaintenanceScheduleUpdate,
    _perm: None = Depends(RequirePermission("equipment.update")),
    service: EquipmentService = Depends(_get_service),
) -> MaintenanceScheduleResponse:
    schedule = await service.schedule_repo.get_by_id(schedule_id)
    if schedule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Maintenance schedule not found",
        )
    fields = data.model_dump(exclude_unset=True)
    if fields:
        await service.schedule_repo.update_fields(schedule_id, **fields)
        await service.session.refresh(schedule)
    return MaintenanceScheduleResponse.model_validate(schedule)


@router.delete("/maintenance-schedules/{schedule_id}", status_code=204)
async def delete_schedule(
    schedule_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("equipment.delete")),
    service: EquipmentService = Depends(_get_service),
) -> None:
    await service.schedule_repo.delete(schedule_id)


@router.get(
    "/maintenance-schedules/due-within",
    response_model=list[MaintenanceWorkOrderResponse],
)
async def generate_due_work_orders(
    hours: float = Query(default=50.0, ge=0),
    equipment_id: uuid.UUID | None = Query(default=None),
    _perm: None = Depends(RequirePermission("equipment.update")),
    service: EquipmentService = Depends(_get_service),
) -> list[MaintenanceWorkOrderResponse]:
    """‌⁠‍Generate work-order stubs for schedules within `hours` of due."""
    wos = await service.generate_due_work_orders(
        equipment_id=equipment_id,
        lookahead_hours=hours,
    )
    return [MaintenanceWorkOrderResponse.model_validate(w) for w in wos]


# ── Maintenance Work Orders ──────────────────────────────────────────────


@router.get(
    "/maintenance-work-orders/",
    response_model=list[MaintenanceWorkOrderResponse],
)
async def list_work_orders(
    equipment_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    _perm: None = Depends(RequirePermission("equipment.read")),
    service: EquipmentService = Depends(_get_service),
) -> list[MaintenanceWorkOrderResponse]:
    items, _ = await service.workorder_repo.list_(
        equipment_id=equipment_id,
        status=status_filter,
        offset=offset,
        limit=limit,
    )
    return [MaintenanceWorkOrderResponse.model_validate(i) for i in items]


@router.post(
    "/maintenance-work-orders/",
    response_model=MaintenanceWorkOrderResponse,
    status_code=201,
)
async def create_work_order(
    data: MaintenanceWorkOrderCreate,
    _perm: None = Depends(RequirePermission("equipment.create")),
    service: EquipmentService = Depends(_get_service),
) -> MaintenanceWorkOrderResponse:
    wo = await service.create_work_order(data)
    return MaintenanceWorkOrderResponse.model_validate(wo)


@router.post(
    "/maintenance-work-orders/{work_order_id}/complete",
    response_model=MaintenanceWorkOrderResponse,
)
async def complete_work_order(
    work_order_id: uuid.UUID,
    completed_at: str | None = Query(default=None),
    _perm: None = Depends(RequirePermission("equipment.complete_maintenance")),
    service: EquipmentService = Depends(_get_service),
) -> MaintenanceWorkOrderResponse:
    wo = await service.complete_work_order(work_order_id, completed_at=completed_at)
    return MaintenanceWorkOrderResponse.model_validate(wo)


@router.patch(
    "/maintenance-work-orders/{work_order_id}",
    response_model=MaintenanceWorkOrderResponse,
)
async def update_work_order(
    work_order_id: uuid.UUID,
    data: MaintenanceWorkOrderUpdate,
    _perm: None = Depends(RequirePermission("equipment.update")),
    service: EquipmentService = Depends(_get_service),
) -> MaintenanceWorkOrderResponse:
    wo = await service.workorder_repo.get_by_id(work_order_id)
    if wo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Work order not found",
        )
    fields = data.model_dump(exclude_unset=True)
    if fields:
        await service.workorder_repo.update_fields(work_order_id, **fields)
        await service.session.refresh(wo)
    return MaintenanceWorkOrderResponse.model_validate(wo)


@router.delete("/maintenance-work-orders/{work_order_id}", status_code=204)
async def delete_work_order(
    work_order_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("equipment.delete")),
    service: EquipmentService = Depends(_get_service),
) -> None:
    await service.workorder_repo.delete(work_order_id)


# ── Inspections ──────────────────────────────────────────────────────────


@router.get("/inspections/", response_model=list[InspectionResponse])
async def list_inspections(
    equipment_id: uuid.UUID | None = Query(default=None),
    _perm: None = Depends(RequirePermission("equipment.read")),
    service: EquipmentService = Depends(_get_service),
) -> list[InspectionResponse]:
    if equipment_id is not None:
        items = await service.inspection_repo.list_for_equipment(equipment_id)
    else:
        from datetime import date as _d

        items = await service.inspection_repo.expiring_within(_d.today().isoformat(), 365)
    return [InspectionResponse.model_validate(i) for i in items]


@router.post("/inspections/", response_model=InspectionResponse, status_code=201)
async def create_inspection(
    data: InspectionCreate,
    _perm: None = Depends(RequirePermission("equipment.create")),
    service: EquipmentService = Depends(_get_service),
) -> InspectionResponse:
    insp = await service.create_inspection(data)
    return InspectionResponse.model_validate(insp)


@router.get("/inspections/expiring", response_model=list[InspectionResponse])
async def expiring_inspections(
    days: int = Query(default=30, ge=1, le=365),
    _perm: None = Depends(RequirePermission("equipment.read")),
    service: EquipmentService = Depends(_get_service),
) -> list[InspectionResponse]:
    items = await service.expiring_inspections(days=days)
    return [InspectionResponse.model_validate(i) for i in items]


@router.patch("/inspections/{inspection_id}", response_model=InspectionResponse)
async def update_inspection(
    inspection_id: uuid.UUID,
    data: InspectionUpdate,
    _perm: None = Depends(RequirePermission("equipment.approve_inspection")),
    service: EquipmentService = Depends(_get_service),
) -> InspectionResponse:
    insp = await service.inspection_repo.get_by_id(inspection_id)
    if insp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Inspection not found",
        )
    fields = data.model_dump(exclude_unset=True)
    if fields:
        await service.inspection_repo.update_fields(inspection_id, **fields)
        await service.session.refresh(insp)
    return InspectionResponse.model_validate(insp)


@router.delete("/inspections/{inspection_id}", status_code=204)
async def delete_inspection(
    inspection_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("equipment.delete")),
    service: EquipmentService = Depends(_get_service),
) -> None:
    await service.inspection_repo.delete(inspection_id)


# ── Rentals ──────────────────────────────────────────────────────────────


@router.get("/rentals/", response_model=list[EquipmentRentalResponse])
async def list_rentals(
    equipment_id: uuid.UUID | None = Query(default=None),
    project_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    _perm: None = Depends(RequirePermission("equipment.read")),
    service: EquipmentService = Depends(_get_service),
) -> list[EquipmentRentalResponse]:
    items, _ = await service.rental_repo.list_(
        equipment_id=equipment_id,
        project_id=project_id,
        status=status_filter,
        offset=offset,
        limit=limit,
    )
    return [EquipmentRentalResponse.model_validate(i) for i in items]


@router.post("/rentals/", response_model=EquipmentRentalResponse, status_code=201)
async def create_rental(
    data: EquipmentRentalCreate,
    _perm: None = Depends(RequirePermission("equipment.assign")),
    service: EquipmentService = Depends(_get_service),
) -> EquipmentRentalResponse:
    try:
        rental = await service.create_rental(data)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return EquipmentRentalResponse.model_validate(rental)


@router.post("/rentals/{rental_id}/return", response_model=EquipmentRentalResponse)
async def return_rental(
    rental_id: uuid.UUID,
    end_date: str | None = Query(default=None),
    _perm: None = Depends(RequirePermission("equipment.assign")),
    service: EquipmentService = Depends(_get_service),
) -> EquipmentRentalResponse:
    rental = await service.return_rental(rental_id, end_date=end_date)
    return EquipmentRentalResponse.model_validate(rental)


@router.patch("/rentals/{rental_id}", response_model=EquipmentRentalResponse)
async def update_rental(
    rental_id: uuid.UUID,
    data: EquipmentRentalUpdate,
    _perm: None = Depends(RequirePermission("equipment.assign")),
    service: EquipmentService = Depends(_get_service),
) -> EquipmentRentalResponse:
    rental = await service.rental_repo.get_by_id(rental_id)
    if rental is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rental not found",
        )
    fields = data.model_dump(exclude_unset=True)
    if fields:
        await service.rental_repo.update_fields(rental_id, **fields)
        await service.session.refresh(rental)
    return EquipmentRentalResponse.model_validate(rental)


@router.delete("/rentals/{rental_id}", status_code=204)
async def delete_rental(
    rental_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("equipment.delete")),
    service: EquipmentService = Depends(_get_service),
) -> None:
    await service.rental_repo.delete(rental_id)


# ── Fuel Logs ────────────────────────────────────────────────────────────


@router.get("/fuel-logs/", response_model=list[FuelLogResponse])
async def list_fuel_logs(
    equipment_id: uuid.UUID = Query(...),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    _perm: None = Depends(RequirePermission("equipment.read")),
    service: EquipmentService = Depends(_get_service),
) -> list[FuelLogResponse]:
    items, _ = await service.fuel_repo.list_for_equipment(equipment_id, offset=offset, limit=limit)
    return [FuelLogResponse.model_validate(i) for i in items]


@router.post("/fuel-logs/", response_model=FuelLogResponse, status_code=201)
async def create_fuel_log(
    data: FuelLogCreate,
    _perm: None = Depends(RequirePermission("equipment.update")),
    service: EquipmentService = Depends(_get_service),
) -> FuelLogResponse:
    log = await service.create_fuel_log(data)
    return FuelLogResponse.model_validate(log)


@router.patch("/fuel-logs/{log_id}", response_model=FuelLogResponse)
async def update_fuel_log(
    log_id: uuid.UUID,
    data: FuelLogUpdate,
    _perm: None = Depends(RequirePermission("equipment.update")),
    service: EquipmentService = Depends(_get_service),
) -> FuelLogResponse:
    log = await service.fuel_repo.get_by_id(log_id)
    if log is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Fuel log not found")
    fields = data.model_dump(exclude_unset=True)
    if fields:
        await service.fuel_repo.update_fields(log_id, **fields)
        await service.session.refresh(log)
    return FuelLogResponse.model_validate(log)


@router.delete("/fuel-logs/{log_id}", status_code=204)
async def delete_fuel_log(
    log_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("equipment.delete")),
    service: EquipmentService = Depends(_get_service),
) -> None:
    await service.fuel_repo.delete(log_id)


@router.get("/fuel-logs/efficiency", response_model=dict[str, Decimal])
async def fuel_efficiency(
    equipment_id: uuid.UUID = Query(...),
    period_start: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    period_end: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    _perm: None = Depends(RequirePermission("equipment.read")),
    service: EquipmentService = Depends(_get_service),
) -> dict[str, Decimal]:
    return await service.fuel_repo.fuel_consumption(equipment_id, period_start, period_end)


# ── Parts Logs ───────────────────────────────────────────────────────────


@router.get("/parts-logs/", response_model=list[PartsLogResponse])
async def list_parts_logs(
    equipment_id: uuid.UUID = Query(...),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    _perm: None = Depends(RequirePermission("equipment.read")),
    service: EquipmentService = Depends(_get_service),
) -> list[PartsLogResponse]:
    items, _ = await service.parts_repo.list_for_equipment(equipment_id, offset=offset, limit=limit)
    return [PartsLogResponse.model_validate(i) for i in items]


@router.post("/parts-logs/", response_model=PartsLogResponse, status_code=201)
async def create_parts_log(
    data: PartsLogCreate,
    _perm: None = Depends(RequirePermission("equipment.update")),
    service: EquipmentService = Depends(_get_service),
) -> PartsLogResponse:
    p = await service.create_parts_log(data)
    return PartsLogResponse.model_validate(p)


# ── Damage Reports ───────────────────────────────────────────────────────


@router.get("/damage-reports/", response_model=list[DamageReportResponse])
async def list_damage_reports(
    equipment_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    _perm: None = Depends(RequirePermission("equipment.read")),
    service: EquipmentService = Depends(_get_service),
) -> list[DamageReportResponse]:
    items, _ = await service.damage_repo.list_(
        equipment_id=equipment_id,
        status=status_filter,
        offset=offset,
        limit=limit,
    )
    return [DamageReportResponse.model_validate(i) for i in items]


@router.post(
    "/damage-reports/",
    response_model=DamageReportResponse,
    status_code=201,
)
async def create_damage_report(
    data: DamageReportCreate,
    _perm: None = Depends(RequirePermission("equipment.record_damage")),
    service: EquipmentService = Depends(_get_service),
) -> DamageReportResponse:
    d = await service.record_damage(data)
    return DamageReportResponse.model_validate(d)


@router.patch(
    "/damage-reports/{report_id}",
    response_model=DamageReportResponse,
)
async def update_damage_report(
    report_id: uuid.UUID,
    data: DamageReportUpdate,
    _perm: None = Depends(RequirePermission("equipment.update")),
    service: EquipmentService = Depends(_get_service),
) -> DamageReportResponse:
    d = await service.damage_repo.get_by_id(report_id)
    if d is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Damage report not found",
        )
    fields = data.model_dump(exclude_unset=True)
    if fields:
        await service.damage_repo.update_fields(report_id, **fields)
        await service.session.refresh(d)
    return DamageReportResponse.model_validate(d)


@router.delete("/damage-reports/{report_id}", status_code=204)
async def delete_damage_report(
    report_id: uuid.UUID,
    _perm: None = Depends(RequirePermission("equipment.update")),
    service: EquipmentService = Depends(_get_service),
) -> None:
    d = await service.damage_repo.get_by_id(report_id)
    if d is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Damage report not found",
        )
    await service.damage_repo.delete(report_id)


# ── Fleet Dashboard ──────────────────────────────────────────────────────


@router.get("/dashboard/fleet", response_model=FleetDashboardResponse)
async def fleet_dashboard(
    _perm: None = Depends(RequirePermission("equipment.read")),
    service: EquipmentService = Depends(_get_service),
) -> FleetDashboardResponse:
    return await service.fleet_dashboard()
