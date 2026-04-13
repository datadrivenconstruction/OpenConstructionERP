"""NCR API routes.

Endpoints:
    GET    /                           - List NCRs for a project
    POST   /                           - Create NCR
    GET    /{ncr_id}                   - Get single NCR
    PATCH  /{ncr_id}                   - Update NCR
    DELETE /{ncr_id}                   - Delete NCR
    POST   /{ncr_id}/create-variation  - Create change order from NCR
    POST   /{ncr_id}/close             - Close NCR
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.ncr.schemas import (
    NCRCreate,
    NCRResponse,
    NCRUpdate,
)
from app.modules.ncr.service import NCRService

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_service(session: SessionDep) -> NCRService:
    return NCRService(session)


def _to_response(item: object) -> NCRResponse:
    return NCRResponse(
        id=item.id,  # type: ignore[attr-defined]
        project_id=item.project_id,  # type: ignore[attr-defined]
        ncr_number=item.ncr_number,  # type: ignore[attr-defined]
        title=item.title,  # type: ignore[attr-defined]
        description=item.description,  # type: ignore[attr-defined]
        ncr_type=item.ncr_type,  # type: ignore[attr-defined]
        severity=item.severity,  # type: ignore[attr-defined]
        root_cause=item.root_cause,  # type: ignore[attr-defined]
        root_cause_category=item.root_cause_category,  # type: ignore[attr-defined]
        corrective_action=item.corrective_action,  # type: ignore[attr-defined]
        preventive_action=item.preventive_action,  # type: ignore[attr-defined]
        status=item.status,  # type: ignore[attr-defined]
        cost_impact=item.cost_impact,  # type: ignore[attr-defined]
        schedule_impact_days=item.schedule_impact_days,  # type: ignore[attr-defined]
        location_description=item.location_description,  # type: ignore[attr-defined]
        linked_inspection_id=item.linked_inspection_id,  # type: ignore[attr-defined]
        change_order_id=item.change_order_id,  # type: ignore[attr-defined]
        created_by=item.created_by,  # type: ignore[attr-defined]
        metadata=getattr(item, "metadata_", {}),
        created_at=item.created_at,  # type: ignore[attr-defined]
        updated_at=item.updated_at,  # type: ignore[attr-defined]
    )


@router.get("/", response_model=list[NCRResponse])
async def list_ncrs(
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    type_filter: str | None = Query(default=None, alias="type"),
    status_filter: str | None = Query(default=None, alias="status"),
    severity: str | None = Query(default=None),
    service: NCRService = Depends(_get_service),
) -> list[NCRResponse]:
    await verify_project_access(project_id, user_id, session)
    ncrs, _ = await service.list_ncrs(
        project_id,
        offset=offset,
        limit=limit,
        ncr_type=type_filter,
        status_filter=status_filter,
        severity=severity,
    )
    return [_to_response(n) for n in ncrs]


@router.post("/", response_model=NCRResponse, status_code=201)
async def create_ncr(
    data: NCRCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("ncr.create")),
    service: NCRService = Depends(_get_service),
) -> NCRResponse:
    await verify_project_access(data.project_id, user_id, session)
    ncr = await service.create_ncr(data, user_id=user_id)
    return _to_response(ncr)


@router.get("/{ncr_id}", response_model=NCRResponse)
async def get_ncr(
    ncr_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: NCRService = Depends(_get_service),
) -> NCRResponse:
    ncr = await service.get_ncr(ncr_id)
    return _to_response(ncr)


@router.patch("/{ncr_id}", response_model=NCRResponse)
async def update_ncr(
    ncr_id: uuid.UUID,
    data: NCRUpdate,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("ncr.update")),
    service: NCRService = Depends(_get_service),
) -> NCRResponse:
    ncr = await service.update_ncr(ncr_id, data)
    return _to_response(ncr)


@router.delete("/{ncr_id}", status_code=204)
async def delete_ncr(
    ncr_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("ncr.delete")),
    service: NCRService = Depends(_get_service),
) -> None:
    await service.delete_ncr(ncr_id)


@router.post("/{ncr_id}/create-variation/", status_code=201)
async def create_variation_from_ncr(
    ncr_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("ncr.update")),
    service: NCRService = Depends(_get_service),
) -> dict:
    """Create a change order/variation pre-filled from an NCR with cost impact.

    The NCR must have a non-empty cost_impact value.
    Pre-fills the change order with the NCR title, description, and cost impact.
    """
    ncr = await service.get_ncr(ncr_id)

    if not ncr.cost_impact:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="NCR has no cost impact — cannot create a variation.",
        )

    # Lazy import changeorders module
    try:
        from app.modules.changeorders.models import ChangeOrder
        from app.modules.changeorders.repository import ChangeOrderRepository

        repo = ChangeOrderRepository(session)
        count = await repo.count_for_project(ncr.project_id)
        code = f"CO-{count + 1:03d}"

        description_parts = [
            f"Variation from NCR {ncr.ncr_number}: {ncr.title}",
            "",
            "Description:",
            ncr.description,
        ]
        if ncr.corrective_action:
            description_parts.extend(["", "Corrective Action:", ncr.corrective_action])
        if ncr.root_cause:
            description_parts.extend(["", "Root Cause:", ncr.root_cause])

        order = ChangeOrder(
            project_id=ncr.project_id,
            code=code,
            title=f"Variation: {ncr.title}",
            description="\n".join(description_parts),
            reason_category="non_conformance",
            cost_impact=ncr.cost_impact or "0",
            schedule_impact_days=ncr.schedule_impact_days or 0,
            metadata_={
                "source": "ncr",
                "ncr_id": str(ncr_id),
                "ncr_number": ncr.ncr_number,
            },
        )
        session.add(order)
        await session.flush()

        # Link the change order back to the NCR
        ncr.change_order_id = str(order.id)
        await session.flush()

        logger.info(
            "Created change order %s from NCR %s",
            code,
            ncr_id,
        )
        return {
            "change_order_id": str(order.id),
            "code": code,
            "ncr_id": str(ncr_id),
            "title": order.title,
        }
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Change orders module is not available.",
        )
    except Exception as exc:
        logger.exception("Failed to create variation from NCR %s: %s", ncr_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create change order from NCR.",
        )


@router.post("/{ncr_id}/close/", response_model=NCRResponse)
async def close_ncr(
    ncr_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("ncr.update")),
    service: NCRService = Depends(_get_service),
) -> NCRResponse:
    """Close an NCR after verification."""
    ncr = await service.close_ncr(ncr_id)
    return _to_response(ncr)
