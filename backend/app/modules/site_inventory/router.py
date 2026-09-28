# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site-inventory API routes (mounted at ``/api/v1/site-inventory``).

On-site material metering and stock: storage locations, stock items, the
movement ledger (inbound / consumption / waste / transfer), and the derived
stock-on-hand, material-variance and waste reports.

Every endpoint is scoped to a project in its path and gated twice, exactly like
the sibling modules: a ``RequirePermission`` dependency enforces the read/write
permission, and ``verify_project_access`` (which raises 404 on both "missing" and
"denied") is awaited as the first line of every handler so a stranger can never
read or mutate another project's inventory. By-id references are additionally
re-checked in the service layer against the same project.
"""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.site_inventory.schemas import (
    LocationCreate,
    LocationResponse,
    MovementCreate,
    MovementResponse,
    StockItemCreate,
    StockItemResponse,
    StockItemUpdate,
)
from app.modules.site_inventory.service import SiteInventoryService

router = APIRouter(tags=["site-inventory"])

_READ = Depends(RequirePermission("site_inventory.read"))
_WRITE = Depends(RequirePermission("site_inventory.write"))


def _get_service(session: SessionDep) -> SiteInventoryService:
    return SiteInventoryService(session)


def _parse_optional_decimal(value: str | None, field: str) -> Decimal | None:
    """Parse an optional numeric query param to ``Decimal`` (422 on garbage)."""
    if value is None:
        return None
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Invalid decimal for {field}: {value!r}",
        ) from exc


# -- Locations --------------------------------------------------------------


@router.post(
    "/projects/{project_id}/locations",
    response_model=LocationResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_WRITE],
)
async def create_location(
    project_id: uuid.UUID,
    payload: LocationCreate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> LocationResponse:
    """Create a geo-tagged storage location on a project."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.create_location(project_id, payload)  # type: ignore[return-value]


@router.get(
    "/projects/{project_id}/locations",
    response_model=list[LocationResponse],
    dependencies=[_READ],
)
async def list_locations(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> list[LocationResponse]:
    """List the storage locations on a project."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.list_locations(project_id)  # type: ignore[return-value]


@router.delete(
    "/projects/{project_id}/locations/{location_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_WRITE],
)
async def delete_location(
    project_id: uuid.UUID,
    location_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> None:
    """Delete an empty storage location.

    Refuses with 409, naming what holds it, when any movement was booked at the
    location or any item defaults to it.
    """
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    await service.delete_location(project_id, location_id)


# -- Items ------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/items",
    response_model=StockItemResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_WRITE],
)
async def create_item(
    project_id: uuid.UUID,
    payload: StockItemCreate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> StockItemResponse:
    """Create a stock item / material record on a project."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.create_item(project_id, payload)  # type: ignore[return-value]


@router.get(
    "/projects/{project_id}/items",
    response_model=list[StockItemResponse],
    dependencies=[_READ],
)
async def list_items(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> list[StockItemResponse]:
    """List the stock items on a project."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.list_items(project_id)  # type: ignore[return-value]


@router.patch(
    "/projects/{project_id}/items/{item_id}",
    response_model=StockItemResponse,
    dependencies=[_WRITE],
)
async def update_item(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: StockItemUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> StockItemResponse:
    """Patch a stock item - the endpoint that links it to its BoQ position."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.update_item(project_id, item_id, payload)  # type: ignore[return-value]


@router.delete(
    "/projects/{project_id}/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_WRITE],
)
async def delete_item(
    project_id: uuid.UUID,
    item_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> None:
    """Delete a stock item that has never moved.

    Refuses with 409, naming the movement count, once anything has been booked
    against the item - deleting it would cascade the ledger away with it.
    """
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    await service.delete_item(project_id, item_id)


# -- Movements --------------------------------------------------------------


@router.post(
    "/projects/{project_id}/movements",
    response_model=MovementResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_WRITE],
)
async def record_movement(
    project_id: uuid.UUID,
    payload: MovementCreate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> MovementResponse:
    """Record a stock movement (inbound / consumption / waste / transfer)."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.record_movement(project_id, payload, actor_id=user_id)  # type: ignore[return-value]


@router.get(
    "/projects/{project_id}/movements",
    response_model=list[MovementResponse],
    dependencies=[_READ],
)
async def list_movements(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    item_id: uuid.UUID | None = Query(default=None),
    location_id: uuid.UUID | None = Query(default=None),
    movement_type: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=5000),
) -> list[MovementResponse]:
    """List a project's stock movements with optional filters."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.list_movements(  # type: ignore[return-value]
        project_id,
        item_id=item_id,
        location_id=location_id,
        movement_type=movement_type,
        limit=limit,
    )


# -- Derived reports --------------------------------------------------------


@router.get(
    "/projects/{project_id}/stock-on-hand",
    response_model=None,
    dependencies=[_READ],
)
async def get_stock_on_hand(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    location_id: uuid.UUID | None = Query(default=None),
) -> dict:
    """Per-item stock on hand for a project, optionally within one location."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.stock_on_hand(project_id, location_id=location_id)


@router.get(
    "/projects/{project_id}/reports/material-variance",
    response_model=None,
    dependencies=[_READ],
)
async def get_material_variance(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> dict:
    """Per-position material-cost variance (actual consumed vs BoQ budget)."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.material_variance_report(project_id)


@router.get(
    "/projects/{project_id}/reports/position-coverage",
    response_model=None,
    dependencies=[_READ],
)
async def get_position_coverage(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> dict:
    """Per BoQ position: ordered against delivered against the bill quantity."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.position_coverage_report(project_id)


@router.get(
    "/projects/{project_id}/reports/unfixed-value",
    response_model=None,
    dependencies=[_READ],
)
async def get_unfixed_value(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> dict:
    """Value of the material standing on site and not yet installed."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.unfixed_value_report(project_id)


@router.get(
    "/projects/{project_id}/reports/waste",
    response_model=None,
    dependencies=[_READ],
)
async def get_waste_report(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    opening_stock: str | None = Query(default=None, description="Opening stock quantity for turnover"),
    period_days: str | None = Query(default=None, description="Period length in days for turnover"),
) -> dict:
    """Waste ratio plus inventory turnover / days-on-hand for a project."""
    await verify_project_access(project_id, user_id, session)
    service = _get_service(session)
    return await service.waste_report(
        project_id,
        opening_stock=_parse_optional_decimal(opening_stock, "opening_stock"),
        period_days=_parse_optional_decimal(period_days, "period_days"),
    )
