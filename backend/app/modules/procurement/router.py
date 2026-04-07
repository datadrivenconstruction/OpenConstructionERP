"""Procurement API routes.

Endpoints:
    GET    /                           — List purchase orders
    POST   /                           — Create PO (auth required)
    GET    /{id}                       — Get single PO
    PATCH  /{id}                       — Update PO (auth required)
    POST   /{id}/issue                 — Issue PO (auth required)
    GET    /goods-receipts             — List goods receipts
    POST   /goods-receipts             — Create GR (auth required)
    POST   /goods-receipts/{id}/confirm — Confirm GR (auth required)
"""

import uuid

from fastapi import APIRouter, Depends, Query

from app.dependencies import CurrentUserId, SessionDep
from app.modules.procurement.schemas import (
    GRCreate,
    GRListResponse,
    GRResponse,
    POCreate,
    POListResponse,
    POResponse,
    POUpdate,
)
from app.modules.procurement.service import ProcurementService

router = APIRouter()


def _get_service(session: SessionDep) -> ProcurementService:
    return ProcurementService(session)


# ── Purchase Orders ──────────────────────────────────────────────────────────


@router.get("/", response_model=POListResponse)
async def list_purchase_orders(
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    project_id: uuid.UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    vendor_contact_id: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: ProcurementService = Depends(_get_service),
) -> POListResponse:
    """List purchase orders with optional filters."""
    items, total = await service.list_pos(
        project_id=project_id,
        po_status=status,
        vendor_contact_id=vendor_contact_id,
        offset=offset,
        limit=limit,
    )
    return POListResponse(
        items=[POResponse.model_validate(po) for po in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("/", response_model=POResponse, status_code=201)
async def create_purchase_order(
    data: POCreate,
    user_id: CurrentUserId,
    service: ProcurementService = Depends(_get_service),
) -> POResponse:
    """Create a new purchase order."""
    po = await service.create_po(data, user_id=user_id)
    return POResponse.model_validate(po)


@router.get("/{po_id}", response_model=POResponse)
async def get_purchase_order(
    po_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: ProcurementService = Depends(_get_service),
) -> POResponse:
    """Get a single purchase order by ID."""
    po = await service.get_po(po_id)
    return POResponse.model_validate(po)


@router.patch("/{po_id}", response_model=POResponse)
async def update_purchase_order(
    po_id: uuid.UUID,
    data: POUpdate,
    user_id: CurrentUserId,
    service: ProcurementService = Depends(_get_service),
) -> POResponse:
    """Update a purchase order."""
    po = await service.update_po(po_id, data)
    return POResponse.model_validate(po)


@router.post("/{po_id}/issue", response_model=POResponse)
async def issue_purchase_order(
    po_id: uuid.UUID,
    user_id: CurrentUserId,
    service: ProcurementService = Depends(_get_service),
) -> POResponse:
    """Issue a purchase order."""
    po = await service.issue_po(po_id)
    return POResponse.model_validate(po)


# ── Goods Receipts ───────────────────────────────────────────────────────────


@router.get("/goods-receipts", response_model=GRListResponse)
async def list_goods_receipts(
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    po_id: uuid.UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    service: ProcurementService = Depends(_get_service),
) -> GRListResponse:
    """List goods receipts with optional filters."""
    items, total = await service.list_goods_receipts(
        po_id=po_id, gr_status=status, limit=limit, offset=offset
    )
    return GRListResponse(
        items=[GRResponse.model_validate(gr) for gr in items],
        total=total,
    )


@router.post("/goods-receipts", response_model=GRResponse, status_code=201)
async def create_goods_receipt(
    data: GRCreate,
    user_id: CurrentUserId,
    service: ProcurementService = Depends(_get_service),
) -> GRResponse:
    """Create a goods receipt against a PO."""
    gr = await service.create_goods_receipt(data, user_id=user_id)
    return GRResponse.model_validate(gr)


@router.post("/goods-receipts/{gr_id}/confirm", response_model=GRResponse)
async def confirm_goods_receipt(
    gr_id: uuid.UUID,
    user_id: CurrentUserId,
    service: ProcurementService = Depends(_get_service),
) -> GRResponse:
    """Confirm a goods receipt."""
    gr = await service.confirm_goods_receipt(gr_id)
    return GRResponse.model_validate(gr)
