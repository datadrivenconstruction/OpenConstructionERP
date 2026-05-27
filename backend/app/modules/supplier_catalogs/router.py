"""‌⁠‍Supplier Catalogs API routes.

Mounted at ``/api/v1/supplier-catalogs/`` by the module loader.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Query, UploadFile

from app.core.i18n import get_locale
from app.core.validation.messages import translate
from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.supplier_catalogs.schemas import (
    CatalogItemCreate,
    CatalogItemResponse,
    CommodityCodeResponse,
    GoodsReceiptCreate,
    GRResponse,
    ItemCategoryCreate,
    ItemCategoryResponse,
    KYCDocumentCreate,
    KYCDocumentResponse,
    MatchResult,
    PeppolIngestResult,
    POCreateExt,
    POResponseExt,
    PRCreate,
    PriceComparisonRow,
    PriceListCreate,
    PriceListImportResult,
    PriceListResponse,
    PRResponse,
    ScorecardRecomputeRequest,
    ScorecardResponse,
    StockBalanceResponse,
    StockIssuePayload,
    StockMovementResponse,
    StockReservePayload,
    StocktakePayload,
    TolerianceProfileCreate,
    TolerianceProfileResponse,
    TolerianceProfileUpdate,
    VendorCreate,
    VendorInvoiceCreate,
    VendorInvoiceResponse,
    VendorRatingPayload,
    VendorResponse,
    VendorUpdate,
    WarehouseCreate,
    WarehouseResponse,
)
from app.modules.supplier_catalogs.service import SupplierCatalogsService

router = APIRouter()


def _svc(session: SessionDep) -> SupplierCatalogsService:
    return SupplierCatalogsService(session)


# ── Vendors ──────────────────────────────────────────────────────────────────


@router.post(
    "/vendors",
    response_model=VendorResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("supplier_catalogs.vendor.write"))],
)
async def create_vendor(
    data: VendorCreate,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> VendorResponse:
    vendor = await service.create_vendor(data, user_id=user_id)
    return VendorResponse.model_validate(vendor)


@router.get(
    "/vendors",
    response_model=list[VendorResponse],
    dependencies=[Depends(RequirePermission("supplier_catalogs.vendor.read"))],
)
async def list_vendors(
    user_id: CurrentUserId,
    status: str | None = Query(default=None),
    country_code: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    service: SupplierCatalogsService = Depends(_svc),
) -> list[VendorResponse]:
    items, _total = await service.vendors.list(
        status=status,
        country_code=country_code,
        offset=offset,
        limit=limit,
    )
    return [VendorResponse.model_validate(v) for v in items]


@router.get(
    "/vendors/{vendor_id}",
    response_model=VendorResponse,
    dependencies=[Depends(RequirePermission("supplier_catalogs.vendor.read"))],
)
async def get_vendor(
    vendor_id: uuid.UUID,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> VendorResponse:
    from fastapi import HTTPException

    vendor = await service.vendors.get(vendor_id)
    if vendor is None:
        raise HTTPException(
            status_code=404,
            detail=translate("errors.vendor_not_found", locale=get_locale()),
        )
    return VendorResponse.model_validate(vendor)


@router.patch(
    "/vendors/{vendor_id}",
    response_model=VendorResponse,
    dependencies=[Depends(RequirePermission("supplier_catalogs.vendor.write"))],
)
async def update_vendor(
    vendor_id: uuid.UUID,
    data: VendorUpdate,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> VendorResponse:
    vendor = await service.update_vendor(vendor_id, data)
    return VendorResponse.model_validate(vendor)


@router.patch(
    "/vendors/{vendor_id}/suspend",
    response_model=VendorResponse,
    dependencies=[Depends(RequirePermission("supplier_catalogs.vendor.admin"))],
)
async def suspend_vendor(
    vendor_id: uuid.UUID,
    user_id: CurrentUserId,
    reason: str | None = Query(default=None),
    service: SupplierCatalogsService = Depends(_svc),
) -> VendorResponse:
    vendor = await service.suspend_vendor(vendor_id, user_id=user_id, reason=reason)
    return VendorResponse.model_validate(vendor)


@router.patch(
    "/vendors/{vendor_id}/blacklist",
    response_model=VendorResponse,
    dependencies=[Depends(RequirePermission("supplier_catalogs.vendor.admin"))],
)
async def blacklist_vendor(
    vendor_id: uuid.UUID,
    user_id: CurrentUserId,
    reason: str | None = Query(default=None),
    service: SupplierCatalogsService = Depends(_svc),
) -> VendorResponse:
    vendor = await service.blacklist_vendor(vendor_id, user_id=user_id, reason=reason)
    return VendorResponse.model_validate(vendor)


@router.post(
    "/vendors/{vendor_id}/rating",
    response_model=VendorResponse,
    dependencies=[Depends(RequirePermission("supplier_catalogs.vendor.write"))],
)
async def rate_vendor(
    vendor_id: uuid.UUID,
    payload: VendorRatingPayload,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> VendorResponse:
    vendor = await service.rate_vendor(vendor_id, payload.rating, user_id=user_id)
    return VendorResponse.model_validate(vendor)


# ── Catalog ──────────────────────────────────────────────────────────────────


@router.post(
    "/categories",
    response_model=ItemCategoryResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("supplier_catalogs.catalog.write"))],
)
async def create_category(
    data: ItemCategoryCreate,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> ItemCategoryResponse:
    cat = await service.create_category(data)
    return ItemCategoryResponse.model_validate(cat)


@router.post(
    "/catalog-items",
    response_model=CatalogItemResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("supplier_catalogs.catalog.write"))],
)
async def create_catalog_item(
    data: CatalogItemCreate,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> CatalogItemResponse:
    item = await service.create_catalog_item(data)
    return CatalogItemResponse.model_validate(item)


@router.get(
    "/catalog-items",
    response_model=list[CatalogItemResponse],
    dependencies=[Depends(RequirePermission("supplier_catalogs.catalog.read"))],
)
async def list_catalog_items(
    user_id: CurrentUserId,
    category_id: uuid.UUID | None = Query(default=None),
    search: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    service: SupplierCatalogsService = Depends(_svc),
) -> list[CatalogItemResponse]:
    items, _total = await service.items.list(
        category_id=category_id,
        search=search,
        offset=offset,
        limit=limit,
    )
    return [CatalogItemResponse.model_validate(it) for it in items]


@router.get(
    "/catalog-items/{item_id}/price-comparison",
    response_model=list[PriceComparisonRow],
    dependencies=[Depends(RequirePermission("supplier_catalogs.catalog.read"))],
)
async def price_comparison(
    item_id: uuid.UUID,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> list[PriceComparisonRow]:
    rows = await service.compare_prices(item_id)
    return [PriceComparisonRow(**r) for r in rows]


# ── Price lists ──────────────────────────────────────────────────────────────


@router.post(
    "/price-lists/{vendor_id}",
    response_model=PriceListResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("supplier_catalogs.catalog.write"))],
)
async def create_price_list(
    vendor_id: uuid.UUID,
    data: PriceListCreate,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> PriceListResponse:
    pl = await service.create_price_list(vendor_id, data, user_id=user_id)
    return PriceListResponse.model_validate(pl)


@router.post(
    "/price-lists/{vendor_id}/import",
    response_model=PriceListImportResult,
    status_code=201,
    dependencies=[Depends(RequirePermission("supplier_catalogs.catalog.write"))],
)
async def import_price_list(
    vendor_id: uuid.UUID,
    user_id: CurrentUserId,
    file: UploadFile = File(...),
    name: str = Query(default="Imported price list"),
    currency: str = Query(default="EUR"),
    service: SupplierCatalogsService = Depends(_svc),
) -> PriceListImportResult:
    raw = await file.read()
    return await service.import_price_list(
        vendor_id,
        raw,
        name=name,
        currency=currency,
        user_id=user_id,
    )


# ── Purchase Requisition ─────────────────────────────────────────────────────


@router.post(
    "/prs",
    response_model=PRResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("supplier_catalogs.pr.create"))],
)
async def create_pr(
    data: PRCreate,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> PRResponse:
    pr = await service.create_pr(data, user_id=user_id)
    return PRResponse.model_validate(pr)


@router.post(
    "/prs/{pr_id}/submit",
    response_model=PRResponse,
    dependencies=[Depends(RequirePermission("supplier_catalogs.pr.create"))],
)
async def submit_pr(
    pr_id: uuid.UUID,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> PRResponse:
    pr = await service.submit_pr(pr_id, user_id=user_id)
    return PRResponse.model_validate(pr)


@router.post(
    "/prs/{pr_id}/approve",
    response_model=PRResponse,
    dependencies=[Depends(RequirePermission("supplier_catalogs.pr.approve"))],
)
async def approve_pr(
    pr_id: uuid.UUID,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> PRResponse:
    pr = await service.approve_pr(pr_id, approver_id=str(user_id))
    return PRResponse.model_validate(pr)


@router.post(
    "/prs/{pr_id}/reject",
    response_model=PRResponse,
    dependencies=[Depends(RequirePermission("supplier_catalogs.pr.approve"))],
)
async def reject_pr(
    pr_id: uuid.UUID,
    user_id: CurrentUserId,
    reason: str | None = Query(default=None),
    service: SupplierCatalogsService = Depends(_svc),
) -> PRResponse:
    pr = await service.reject_pr(pr_id, approver_id=str(user_id), reason=reason)
    return PRResponse.model_validate(pr)


@router.post(
    "/prs/{pr_id}/convert-to-po",
    response_model=POResponseExt,
    dependencies=[Depends(RequirePermission("supplier_catalogs.po.create"))],
)
async def convert_pr_to_po(
    pr_id: uuid.UUID,
    user_id: CurrentUserId,
    vendor_id: uuid.UUID = Query(...),
    service: SupplierCatalogsService = Depends(_svc),
) -> POResponseExt:
    po = await service.convert_pr_to_po(pr_id, vendor_id, user_id=user_id)
    return POResponseExt.model_validate(po)


# ── Purchase Order (extended) ────────────────────────────────────────────────


@router.post(
    "/pos",
    response_model=POResponseExt,
    status_code=201,
    dependencies=[Depends(RequirePermission("supplier_catalogs.po.create"))],
)
async def create_po(
    data: POCreateExt,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> POResponseExt:
    po = await service.create_po(data, user_id=user_id)
    return POResponseExt.model_validate(po)


@router.post(
    "/pos/{po_id}/send",
    response_model=POResponseExt,
    dependencies=[Depends(RequirePermission("supplier_catalogs.po.send"))],
)
async def send_po(
    po_id: uuid.UUID,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> POResponseExt:
    po = await service.send_po(po_id, user_id=user_id)
    return POResponseExt.model_validate(po)


@router.post(
    "/pos/{po_id}/acknowledge",
    response_model=POResponseExt,
    dependencies=[Depends(RequirePermission("supplier_catalogs.po.send"))],
)
async def acknowledge_po(
    po_id: uuid.UUID,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> POResponseExt:
    po = await service.acknowledge_po(po_id)
    return POResponseExt.model_validate(po)


@router.post(
    "/pos/{po_id}/close",
    response_model=POResponseExt,
    dependencies=[Depends(RequirePermission("supplier_catalogs.po.close"))],
)
async def close_po(
    po_id: uuid.UUID,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> POResponseExt:
    po = await service.close_po(po_id)
    return POResponseExt.model_validate(po)


# ── Goods Receipts ───────────────────────────────────────────────────────────


@router.post(
    "/goods-receipts",
    response_model=GRResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("supplier_catalogs.gr.post"))],
)
async def post_goods_receipt(
    data: GoodsReceiptCreate,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> GRResponse:
    gr = await service.post_goods_receipt(data, user_id=user_id)
    return GRResponse.model_validate(gr)


# ── Invoices ─────────────────────────────────────────────────────────────────


@router.post(
    "/invoices",
    response_model=VendorInvoiceResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("supplier_catalogs.invoice.match"))],
)
async def create_invoice(
    data: VendorInvoiceCreate,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> VendorInvoiceResponse:
    inv = await service.create_invoice(data, user_id=user_id)
    return VendorInvoiceResponse.model_validate(inv)


@router.post(
    "/invoices/{invoice_id}/match",
    response_model=MatchResult,
    dependencies=[Depends(RequirePermission("supplier_catalogs.invoice.match"))],
)
async def match_invoice(
    invoice_id: uuid.UUID,
    user_id: CurrentUserId,
    tolerance_pct: float | None = Query(default=None, ge=0.0, le=100.0),
    tolerance_profile: str | None = Query(
        default=None,
        description=(
            "Name of a TolerianceProfile to use; overrides vendor / "
            "tenant defaults. Falls back to the vendor's "
            "``tolerance_profile_name`` if omitted."
        ),
    ),
    service: SupplierCatalogsService = Depends(_svc),
) -> MatchResult:
    return await service.match_invoice(
        invoice_id,
        tolerance_pct=Decimal(str(tolerance_pct)) if tolerance_pct is not None else None,
        tolerance_profile_name=tolerance_profile,
        user_id=user_id,
    )


@router.post(
    "/invoices/peppol",
    response_model=PeppolIngestResult,
    status_code=201,
    dependencies=[Depends(RequirePermission("supplier_catalogs.invoice.match"))],
)
async def ingest_peppol_invoice(
    user_id: CurrentUserId,
    file: UploadFile = File(...),
    auto_match: bool = Query(default=True),
    service: SupplierCatalogsService = Depends(_svc),
) -> PeppolIngestResult:
    """‌⁠‍Accept a UBL 2.1 PEPPOL invoice XML file → VendorInvoice + 3-way match.

    The supplier is matched by VAT-id then by name; the buyer PO is
    resolved by ``cac:OrderReference/cbc:ID`` against
    ``PurchaseOrder.number``. Line-level match is run when ``auto_match``
    is true (default) and a PO link exists.
    """
    raw = await file.read()
    return await service.ingest_peppol_invoice(
        raw,
        user_id=user_id,
        auto_match=auto_match,
    )


# ── Warehouses & stock ───────────────────────────────────────────────────────


@router.post(
    "/warehouses",
    response_model=WarehouseResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("supplier_catalogs.warehouse.write"))],
)
async def create_warehouse(
    data: WarehouseCreate,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> WarehouseResponse:
    wh = await service.create_warehouse(data)
    return WarehouseResponse.model_validate(wh)


@router.get(
    "/warehouses",
    response_model=list[WarehouseResponse],
    dependencies=[Depends(RequirePermission("supplier_catalogs.warehouse.read"))],
)
async def list_warehouses(
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> list[WarehouseResponse]:
    rows = await service.warehouses.list()
    return [WarehouseResponse.model_validate(w) for w in rows]


@router.get(
    "/warehouses/{warehouse_id}/balances",
    response_model=list[StockBalanceResponse],
    dependencies=[Depends(RequirePermission("supplier_catalogs.warehouse.read"))],
)
async def list_warehouse_balances(
    warehouse_id: uuid.UUID,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> list[StockBalanceResponse]:
    rows = await service.warehouses.list_balances(warehouse_id)
    return [StockBalanceResponse.model_validate(b) for b in rows]


@router.post(
    "/stock/reserve",
    response_model=StockMovementResponse,
    dependencies=[Depends(RequirePermission("supplier_catalogs.warehouse.write"))],
)
async def reserve_stock(
    payload: StockReservePayload,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> StockMovementResponse:
    mv = await service.reserve_stock(payload, user_id=user_id)
    return StockMovementResponse.model_validate(mv)


@router.post(
    "/stock/issue",
    response_model=StockMovementResponse,
    dependencies=[Depends(RequirePermission("supplier_catalogs.warehouse.write"))],
)
async def issue_stock(
    payload: StockIssuePayload,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> StockMovementResponse:
    mv = await service.issue_stock(payload, user_id=user_id)
    return StockMovementResponse.model_validate(mv)


@router.post(
    "/stock/stocktake/{warehouse_id}",
    response_model=list[StockMovementResponse],
    dependencies=[Depends(RequirePermission("supplier_catalogs.warehouse.manage"))],
)
async def stocktake(
    warehouse_id: uuid.UUID,
    payload: StocktakePayload,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> list[StockMovementResponse]:
    movements = await service.stocktake(warehouse_id, payload, user_id=user_id)
    return [StockMovementResponse.model_validate(m) for m in movements]


# ── Commodity codes (UNSPSC / eClass / CPV) ─────────────────────────────────


@router.get(
    "/commodity-codes",
    response_model=list[CommodityCodeResponse],
    dependencies=[Depends(RequirePermission("supplier_catalogs.catalog.read"))],
)
async def list_commodity_codes(
    user_id: CurrentUserId,
    scheme: str | None = Query(default=None, description="unspsc | eclass | cpv"),
    search: str | None = Query(default=None, max_length=255),
    parent_code: str | None = Query(default=None, max_length=32),
    level: int | None = Query(default=None, ge=1, le=10),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
    service: SupplierCatalogsService = Depends(_svc),
) -> list[CommodityCodeResponse]:
    rows = await service.list_commodity_codes(
        scheme=scheme,
        search=search,
        parent_code=parent_code,
        level=level,
        offset=offset,
        limit=limit,
    )
    return [CommodityCodeResponse.model_validate(c) for c in rows]


@router.post(
    "/commodity-codes/seed",
    dependencies=[
        Depends(RequirePermission("supplier_catalogs.catalog.write")),
    ],
)
async def seed_commodity_codes(
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> dict[str, int]:
    """‌⁠‍Idempotently bulk-load UNSPSC + CPV codes from the bundled CSV."""
    return await service.seed_commodity_codes()


# ── Tolerance profiles ──────────────────────────────────────────────────────


@router.get(
    "/tolerance-profiles",
    response_model=list[TolerianceProfileResponse],
    dependencies=[
        Depends(RequirePermission("supplier_catalogs.invoice.match")),
    ],
)
async def list_tolerance_profiles(
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> list[TolerianceProfileResponse]:
    rows = await service.tolerance_profiles.list()
    return [TolerianceProfileResponse.model_validate(p) for p in rows]


@router.post(
    "/tolerance-profiles",
    response_model=TolerianceProfileResponse,
    status_code=201,
    dependencies=[
        Depends(RequirePermission("supplier_catalogs.vendor.admin")),
    ],
)
async def create_tolerance_profile(
    data: TolerianceProfileCreate,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> TolerianceProfileResponse:
    profile = await service.create_tolerance_profile(data)
    return TolerianceProfileResponse.model_validate(profile)


@router.patch(
    "/tolerance-profiles/{profile_id}",
    response_model=TolerianceProfileResponse,
    dependencies=[
        Depends(RequirePermission("supplier_catalogs.vendor.admin")),
    ],
)
async def update_tolerance_profile(
    profile_id: uuid.UUID,
    data: TolerianceProfileUpdate,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> TolerianceProfileResponse:
    profile = await service.update_tolerance_profile(profile_id, data)
    return TolerianceProfileResponse.model_validate(profile)


# ── KYC documents ───────────────────────────────────────────────────────────


@router.get(
    "/vendors/{vendor_id}/kyc",
    response_model=list[KYCDocumentResponse],
    dependencies=[Depends(RequirePermission("supplier_catalogs.vendor.read"))],
)
async def list_vendor_kyc(
    vendor_id: uuid.UUID,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> list[KYCDocumentResponse]:
    rows = await service.list_kyc_for_vendor(vendor_id)
    return [KYCDocumentResponse.model_validate(d) for d in rows]


@router.post(
    "/vendors/{vendor_id}/kyc",
    response_model=KYCDocumentResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("supplier_catalogs.vendor.write"))],
)
async def add_vendor_kyc(
    vendor_id: uuid.UUID,
    data: KYCDocumentCreate,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> KYCDocumentResponse:
    doc = await service.add_kyc_document(vendor_id, data, user_id=user_id)
    return KYCDocumentResponse.model_validate(doc)


@router.post(
    "/kyc/check-expiry",
    dependencies=[Depends(RequirePermission("supplier_catalogs.vendor.admin"))],
)
async def check_kyc_expiry(
    user_id: CurrentUserId,
    days_ahead: int = Query(default=30, ge=1, le=365),
    service: SupplierCatalogsService = Depends(_svc),
) -> dict[str, int]:
    """Scan KYC docs, emit ``KYC_DOC_EXPIRING`` / ``KYC_DOC_EXPIRED``.

    Usually triggered by a nightly cron; exposed here for manual runs.
    """
    return await service.check_kyc_expiry(days_ahead=days_ahead)


# ── Vendor scorecards ───────────────────────────────────────────────────────


@router.post(
    "/vendors/{vendor_id}/scorecard/recompute",
    response_model=ScorecardResponse,
    dependencies=[Depends(RequirePermission("supplier_catalogs.vendor.read"))],
)
async def recompute_vendor_scorecard(
    vendor_id: uuid.UUID,
    data: ScorecardRecomputeRequest,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> ScorecardResponse:
    """Recompute a weighted multi-criteria scorecard for the vendor."""
    sc = await service.recompute_scorecard(vendor_id, data)
    return ScorecardResponse.model_validate(sc)


@router.get(
    "/vendors/{vendor_id}/scorecards",
    response_model=list[ScorecardResponse],
    dependencies=[Depends(RequirePermission("supplier_catalogs.vendor.read"))],
)
async def list_vendor_scorecards(
    vendor_id: uuid.UUID,
    user_id: CurrentUserId,
    limit: int = Query(default=24, ge=1, le=120),
    service: SupplierCatalogsService = Depends(_svc),
) -> list[ScorecardResponse]:
    rows = await service.list_scorecards(vendor_id, limit=limit)
    return [ScorecardResponse.model_validate(s) for s in rows]
