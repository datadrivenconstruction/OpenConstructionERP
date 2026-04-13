"""Procurement API routes.

Endpoints:
    GET    /                           — List purchase orders
    POST   /                           — Create PO (auth required)
    GET    /goods-receipts             — List goods receipts
    POST   /goods-receipts             — Create GR (auth required)
    POST   /goods-receipts/{id}/confirm — Confirm GR (auth required)
    GET    /{id}                       — Get single PO
    PATCH  /{id}                       — Update PO (auth required)
    POST   /{id}/issue                 — Issue PO (auth required)

NOTE: Fixed-path routes (/goods-receipts) are registered BEFORE the parametric
/{po_id} route so that FastAPI does not try to parse "goods-receipts" as a UUID.
"""

import uuid

from fastapi import APIRouter, Depends, Query

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.procurement.schemas import (
    GRCreate,
    GRListResponse,
    GRResponse,
    POCreate,
    POListResponse,
    POResponse,
    POUpdate,
    ProcurementStatsResponse,
)
from app.modules.procurement.service import ProcurementService

router = APIRouter()


def _get_service(session: SessionDep) -> ProcurementService:
    return ProcurementService(session)


# ── Purchase Orders (list / create) ─────────────────────────────────────────


@router.get(
    "/",
    response_model=POListResponse,
    dependencies=[Depends(RequirePermission("procurement.read"))],
)
async def list_purchase_orders(
    user_id: CurrentUserId,
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


@router.post(
    "/",
    response_model=POResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("procurement.create"))],
)
async def create_purchase_order(
    data: POCreate,
    user_id: CurrentUserId,
    service: ProcurementService = Depends(_get_service),
) -> POResponse:
    """Create a new purchase order."""
    po = await service.create_po(data, user_id=user_id)
    return POResponse.model_validate(po)


# ── Stats ────────────────────────────────────────────────────────────────────


@router.get(
    "/stats/",
    response_model=ProcurementStatsResponse,
    dependencies=[Depends(RequirePermission("procurement.read"))],
)
async def procurement_stats(
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    service: ProcurementService = Depends(_get_service),
) -> ProcurementStatsResponse:
    """Aggregate procurement statistics for a project.

    Returns total POs, breakdown by status, total committed amount,
    confirmed goods receipt count, and count of POs pending delivery.
    """
    return await service.get_stats(project_id)


# ── Goods Receipts (MUST be before /{po_id}) ────────────────────────────────


@router.get(
    "/goods-receipts/",
    response_model=GRListResponse,
    dependencies=[Depends(RequirePermission("procurement.read"))],
)
async def list_goods_receipts(
    user_id: CurrentUserId,
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


@router.post(
    "/goods-receipts/",
    response_model=GRResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("procurement.create"))],
)
async def create_goods_receipt(
    data: GRCreate,
    user_id: CurrentUserId,
    service: ProcurementService = Depends(_get_service),
) -> GRResponse:
    """Create a goods receipt against a PO."""
    gr = await service.create_goods_receipt(data, user_id=user_id)
    return GRResponse.model_validate(gr)


@router.post(
    "/goods-receipts/{gr_id}/confirm/",
    response_model=GRResponse,
    dependencies=[Depends(RequirePermission("procurement.confirm_receipt"))],
)
async def confirm_goods_receipt(
    gr_id: uuid.UUID,
    user_id: CurrentUserId,
    service: ProcurementService = Depends(_get_service),
) -> GRResponse:
    """Confirm a goods receipt."""
    gr = await service.confirm_goods_receipt(gr_id)
    return GRResponse.model_validate(gr)


# ── PO by ID (parametric routes LAST) ───────────────────────────────────────


@router.get(
    "/{po_id}",
    response_model=POResponse,
    dependencies=[Depends(RequirePermission("procurement.read"))],
)
async def get_purchase_order(
    po_id: uuid.UUID,
    user_id: CurrentUserId,
    service: ProcurementService = Depends(_get_service),
) -> POResponse:
    """Get a single purchase order by ID."""
    po = await service.get_po(po_id)
    return POResponse.model_validate(po)


@router.patch(
    "/{po_id}",
    response_model=POResponse,
    dependencies=[Depends(RequirePermission("procurement.update"))],
)
async def update_purchase_order(
    po_id: uuid.UUID,
    data: POUpdate,
    user_id: CurrentUserId,
    service: ProcurementService = Depends(_get_service),
) -> POResponse:
    """Update a purchase order."""
    po = await service.update_po(po_id, data)
    return POResponse.model_validate(po)


@router.post(
    "/{po_id}/create-invoice/",
    status_code=201,
    dependencies=[Depends(RequirePermission("procurement.create"))],
)
async def create_invoice_from_po(
    po_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ProcurementService = Depends(_get_service),
) -> dict:
    """Create a payable invoice pre-filled from PO line items.

    Copies the PO's vendor, amounts, and line items into a new draft invoice
    in the finance module.
    """
    import logging as _logging

    _log = _logging.getLogger(__name__)

    po = await service.get_po(po_id)

    # Lazy import finance module
    try:
        from app.modules.finance.models import Invoice, InvoiceLineItem

        # Generate invoice number from PO number
        invoice_number = f"INV-{po.po_number}"

        invoice = Invoice(
            project_id=po.project_id,
            contact_id=po.vendor_contact_id,
            invoice_direction="payable",
            invoice_number=invoice_number,
            invoice_date=po.issue_date or "",
            due_date=None,
            currency_code=po.currency_code,
            amount_subtotal=po.amount_subtotal,
            tax_amount=po.tax_amount,
            amount_total=po.amount_total,
            status="draft",
            notes=f"Auto-created from PO {po.po_number}",
            created_by=user_id,
            metadata_={
                "source": "procurement",
                "po_id": str(po_id),
                "po_number": po.po_number,
            },
        )
        session.add(invoice)
        await session.flush()

        # Copy PO line items to invoice line items
        po_items = po.items or []
        for idx, item in enumerate(po_items):
            line = InvoiceLineItem(
                invoice_id=invoice.id,
                description=item.description,
                quantity=item.quantity,
                unit=item.unit,
                unit_rate=item.unit_rate,
                amount=item.amount,
                wbs_id=item.wbs_id,
                cost_category=item.cost_category,
                sort_order=idx,
            )
            session.add(line)

        await session.flush()

        _log.info(
            "Created invoice %s from PO %s (project %s)",
            invoice_number,
            po.po_number,
            po.project_id,
        )
        return {
            "invoice_id": str(invoice.id),
            "invoice_number": invoice_number,
            "po_id": str(po_id),
            "po_number": po.po_number,
            "amount_total": po.amount_total,
        }
    except ImportError:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=501,
            detail="Finance module is not available.",
        )
    except Exception as exc:
        _log.exception("Failed to create invoice from PO %s: %s", po_id, exc)
        from fastapi import HTTPException

        raise HTTPException(
            status_code=500,
            detail="Failed to create invoice from purchase order.",
        )


@router.post(
    "/{po_id}/issue/",
    response_model=POResponse,
    dependencies=[Depends(RequirePermission("procurement.issue"))],
)
async def issue_purchase_order(
    po_id: uuid.UUID,
    user_id: CurrentUserId,
    service: ProcurementService = Depends(_get_service),
) -> POResponse:
    """Issue a purchase order."""
    po = await service.issue_po(po_id)
    return POResponse.model_validate(po)
