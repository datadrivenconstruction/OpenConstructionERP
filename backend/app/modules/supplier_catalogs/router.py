# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Supplier Catalogs API routes.

Mounted at ``/api/v1/supplier-catalogs/`` by the module loader.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from app.core.i18n import get_locale
from app.core.validation.engine import ValidationContext
from app.core.validation.messages import translate
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.supplier_catalogs import validators as sc_rules
from app.modules.supplier_catalogs.price_import import PRESETS
from app.modules.supplier_catalogs.schemas import (
    CatalogItemCreate,
    CatalogItemListResponse,
    CatalogItemResponse,
    CatalogItemUpdate,
    CommodityCodeResponse,
    DiscountAgreementCreate,
    DiscountAgreementResponse,
    DiscountAgreementUpdate,
    GoodsReceiptCreate,
    GRResponse,
    ImportPresetResponse,
    ItemAttachmentCreate,
    ItemAttachmentResponse,
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
    PriceListEntriesResponse,
    PriceListImportCommitResult,
    PriceListImportPreview,
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
    VendorListResponse,
    VendorRatingPayload,
    VendorResponse,
    VendorUpdate,
    WarehouseCreate,
    WarehouseResponse,
    WarehouseUpdate,
)
from app.modules.supplier_catalogs.service import SupplierCatalogsService

router = APIRouter(tags=["supplier_catalogs"])


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
    response_model=VendorListResponse,
    dependencies=[Depends(RequirePermission("supplier_catalogs.vendor.read"))],
)
async def list_vendors(
    user_id: CurrentUserId,
    status: str | None = Query(default=None),
    country_code: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    service: SupplierCatalogsService = Depends(_svc),
) -> VendorListResponse:
    """List one page of vendors, optionally by status or country."""
    items, total = await service.vendors.list(
        status=status,
        country_code=country_code,
        offset=offset,
        limit=limit,
    )
    return VendorListResponse(
        items=[VendorResponse.model_validate(v) for v in items],
        total=total,
        offset=offset,
        limit=limit,
    )


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


@router.delete(
    "/vendors/{vendor_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("supplier_catalogs.vendor.admin"))],
)
async def delete_vendor(
    vendor_id: uuid.UUID,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> None:
    """Delete a vendor nothing references.

    Refuses with 409 and a structured reason when price lists, purchase
    orders, invoices or KYC documents point at it; the reason names the
    suspend and blacklist lifecycle, which is what a traded-with vendor
    actually wants.
    """
    await service.delete_vendor(vendor_id, user_id=user_id)


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
    vendor = await service.rate_vendor(
        vendor_id,
        payload.rating,
        user_id=user_id,
        comment=payload.comment,
    )
    return VendorResponse.model_validate(vendor)


# ── Catalog ──────────────────────────────────────────────────────────────────


@router.get(
    "/categories",
    response_model=list[ItemCategoryResponse],
    dependencies=[Depends(RequirePermission("supplier_catalogs.catalog.read"))],
)
async def list_categories(
    user_id: CurrentUserId,
    session: SessionDep,
) -> list[ItemCategoryResponse]:
    """Every item category, by code (discount agreements are scoped to one)."""
    from sqlalchemy import select  # noqa: PLC0415

    from app.modules.supplier_catalogs.models import ItemCategory  # noqa: PLC0415

    rows = (await session.execute(select(ItemCategory).order_by(ItemCategory.code).limit(2000))).scalars().all()
    return [ItemCategoryResponse.model_validate(c) for c in rows]


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
    response_model=CatalogItemListResponse,
    dependencies=[Depends(RequirePermission("supplier_catalogs.catalog.read"))],
)
async def list_catalog_items(
    user_id: CurrentUserId,
    category_id: uuid.UUID | None = Query(default=None),
    search: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    service: SupplierCatalogsService = Depends(_svc),
) -> CatalogItemListResponse:
    """List one page of catalog items, optionally within a category or search."""
    items, total = await service.items.list(
        category_id=category_id,
        search=search,
        offset=offset,
        limit=limit,
    )
    counts = await service.attachment_counts([it.id for it in items])
    rows = []
    for it in items:
        row = CatalogItemResponse.model_validate(it)
        row.attachment_count = counts.get(it.id, 0)
        rows.append(row)
    return CatalogItemListResponse(
        items=rows,
        total=total,
        offset=offset,
        limit=limit,
    )


@router.patch(
    "/catalog-items/{item_id}",
    response_model=CatalogItemResponse,
    dependencies=[Depends(RequirePermission("supplier_catalogs.catalog.write"))],
)
async def update_catalog_item(
    item_id: uuid.UUID,
    data: CatalogItemUpdate,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> CatalogItemResponse:
    """Correct a catalog item's own fields. ``sku`` is not one of them."""
    item = await service.update_catalog_item(item_id, data)
    return CatalogItemResponse.model_validate(item)


@router.delete(
    "/catalog-items/{item_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("supplier_catalogs.catalog.write"))],
)
async def delete_catalog_item(
    item_id: uuid.UUID,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> None:
    """Delete a catalog item nothing quotes.

    Refuses with 409 and a structured reason when requisition lines, order
    lines, vendor prices or stock on hand point at it.
    """
    await service.delete_catalog_item(item_id, user_id=user_id)


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


# Upload ceiling for a vendor price list file (Excel/CSV); keeps the import inside the 3 GB server budget.
_MAX_IMPORT_BYTES = 25 * 1024 * 1024


def _mapping_from_form(raw: str | None) -> dict[str, str] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="mapping must be a JSON object") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="mapping must be a JSON object")
    return {str(k): str(v) for k, v in data.items() if v}


async def _read_upload(file: UploadFile) -> bytes:
    raw = await file.read(_MAX_IMPORT_BYTES + 1)
    if len(raw) > _MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail="File is larger than 25 MB")
    return raw


@router.get(
    "/price-list-import-presets",
    response_model=list[ImportPresetResponse],
    dependencies=[Depends(RequirePermission("supplier_catalogs.catalog.read"))],
)
async def list_import_presets(user_id: CurrentUserId) -> list[ImportPresetResponse]:
    """Column-mapping presets for the price list import (generic, SAP condition export)."""
    return [ImportPresetResponse(name=n, fields={k: list(v) for k, v in f.items()}) for n, f in PRESETS.items()]


@router.post(
    "/price-lists/{vendor_id}/import/preview",
    response_model=PriceListImportPreview,
    dependencies=[Depends(RequirePermission("supplier_catalogs.catalog.write"))],
)
async def preview_price_list_import(
    vendor_id: uuid.UUID,
    user_id: CurrentUserId,
    file: UploadFile = File(...),
    mapping: str | None = Form(default=None),
    preset: str | None = Form(default=None),
    price_list_id: uuid.UUID | None = Form(default=None),
    currency: str | None = Form(default=None),
    service: SupplierCatalogsService = Depends(_svc),
) -> PriceListImportPreview:
    """Dry run of a price list import: mapping, matches and changes. Writes nothing."""
    raw = await _read_upload(file)
    return await service.preview_price_list_import(
        vendor_id,
        file.filename or "upload.csv",
        raw,
        mapping=_mapping_from_form(mapping),
        preset=preset,
        price_list_id=price_list_id,
        currency=currency,
    )


@router.post(
    "/price-lists/{vendor_id}/import/commit",
    response_model=PriceListImportCommitResult,
    status_code=201,
    dependencies=[Depends(RequirePermission("supplier_catalogs.catalog.write"))],
)
async def commit_price_list_import(
    vendor_id: uuid.UUID,
    user_id: CurrentUserId,
    file: UploadFile = File(...),
    mapping: str | None = Form(default=None),
    preset: str | None = Form(default=None),
    price_list_id: uuid.UUID | None = Form(default=None),
    name: str | None = Form(default=None),
    currency: str | None = Form(default=None),
    valid_from: str | None = Form(default=None),
    valid_to: str | None = Form(default=None),
    service: SupplierCatalogsService = Depends(_svc),
) -> PriceListImportCommitResult:
    """Import the file into a new price list, or update ``price_list_id``."""
    raw = await _read_upload(file)
    return await service.commit_price_list_import(
        vendor_id,
        file.filename or "upload.csv",
        raw,
        mapping=_mapping_from_form(mapping),
        preset=preset,
        price_list_id=price_list_id,
        name=name,
        currency=currency,
        valid_from=valid_from or None,
        valid_to=valid_to or None,
        user_id=user_id,
    )


@router.get(
    "/vendors/{vendor_id}/price-lists",
    response_model=list[PriceListResponse],
    dependencies=[Depends(RequirePermission("supplier_catalogs.catalog.read"))],
)
async def list_vendor_price_lists(
    vendor_id: uuid.UUID,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> list[PriceListResponse]:
    return await service.list_price_lists(vendor_id)


@router.get(
    "/price-lists/{price_list_id}/entries",
    response_model=PriceListEntriesResponse,
    dependencies=[Depends(RequirePermission("supplier_catalogs.catalog.read"))],
)
async def list_price_list_entries(
    price_list_id: uuid.UUID,
    user_id: CurrentUserId,
    search: str | None = Query(default=None, max_length=200),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    service: SupplierCatalogsService = Depends(_svc),
) -> PriceListEntriesResponse:
    """One page of a price list: list price, discount, net price and item links."""
    return await service.list_price_list_entries(price_list_id, search=search, offset=offset, limit=limit)


@router.get(
    "/price-lists/{price_list_id}/validation",
    dependencies=[Depends(RequirePermission("supplier_catalogs.catalog.read"))],
)
async def validate_price_list(
    price_list_id: uuid.UUID,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> dict:
    """Run the supplier_catalogs rule set over one price list and its items."""
    page = await service.list_price_list_entries(price_list_id, offset=0, limit=200)
    total, offset, rows = page.total, 200, list(page.items)
    while offset < total:
        nxt = await service.list_price_list_entries(price_list_id, offset=offset, limit=200)
        rows.extend(nxt.items)
        offset += 200
    agreements = await service.list_discounts(page.price_list.vendor_id)
    data = {
        "prices": [{"ref": r.sku, "gross": r.gross_price, "net": r.net_price} for r in rows],
        "discounts": [{"ref": a.name, "discount_pct": a.discount_pct} for a in agreements],
        "price_list_rows": [{"ref": r.sku, "vendor_sku": r.vendor_sku} for r in rows],
        "urls": [{"ref": r.sku, "url": r.product_url} for r in rows if r.product_url],
        "po_price_lists": [],
    }
    ctx = ValidationContext(data=data)
    results = []
    for rule_cls in sc_rules.RULES:
        for res in await rule_cls().validate(ctx):
            results.append(
                {
                    "rule_id": res.rule_id,
                    "severity": str(res.severity),
                    "passed": res.passed,
                    "message": res.message,
                    "element_ref": res.element_ref,
                }
            )
    return {
        "price_list_id": str(price_list_id),
        "expired": page.price_list.expired,
        "passed": all(r["passed"] for r in results),
        "results": results,
    }


# ── Contractor discounts ─────────────────────────────────────────────────────


@router.get(
    "/vendors/{vendor_id}/discounts",
    response_model=list[DiscountAgreementResponse],
    dependencies=[Depends(RequirePermission("supplier_catalogs.discount.read"))],
)
async def list_vendor_discounts(
    vendor_id: uuid.UUID,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> list[DiscountAgreementResponse]:
    return [DiscountAgreementResponse.model_validate(a) for a in await service.list_discounts(vendor_id)]


@router.post(
    "/vendors/{vendor_id}/discounts",
    response_model=DiscountAgreementResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("supplier_catalogs.discount.manage"))],
)
async def create_vendor_discount(
    vendor_id: uuid.UUID,
    data: DiscountAgreementCreate,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> DiscountAgreementResponse:
    """Agree a discount: overall, per price list, per item category or per item."""
    return DiscountAgreementResponse.model_validate(await service.create_discount(vendor_id, data))


@router.patch(
    "/discounts/{agreement_id}",
    response_model=DiscountAgreementResponse,
    dependencies=[Depends(RequirePermission("supplier_catalogs.discount.manage"))],
)
async def update_vendor_discount(
    agreement_id: uuid.UUID,
    data: DiscountAgreementUpdate,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> DiscountAgreementResponse:
    return DiscountAgreementResponse.model_validate(await service.update_discount(agreement_id, data))


@router.delete(
    "/discounts/{agreement_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("supplier_catalogs.discount.manage"))],
)
async def delete_vendor_discount(
    agreement_id: uuid.UUID,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> None:
    await service.delete_discount(agreement_id)


# ── Item documents (datasheets, drawings) ────────────────────────────────────
#
# The files stay in the Documents module, which is project scoped. Linking,
# listing and unlinking check the caller may reach the document's project, and
# downloading goes through /api/v1/documents/{id}/download with its own check.


@router.get(
    "/catalog-items/{item_id}/attachments",
    response_model=list[ItemAttachmentResponse],
    dependencies=[Depends(RequirePermission("supplier_catalogs.catalog.read"))],
)
async def list_item_attachments(
    item_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: SupplierCatalogsService = Depends(_svc),
) -> list[ItemAttachmentResponse]:
    """Datasheets and drawings of an item, only those in projects the caller can open."""
    allowed: dict[uuid.UUID, bool] = {}
    out = []
    for att in await service.list_item_attachments(item_id):
        if att.project_id not in allowed:
            try:
                await verify_project_access(att.project_id, str(user_id), session)
                allowed[att.project_id] = True
            except HTTPException:
                allowed[att.project_id] = False
        if allowed[att.project_id]:
            out.append(ItemAttachmentResponse.model_validate(att))
    return out


@router.post(
    "/catalog-items/{item_id}/attachments",
    response_model=ItemAttachmentResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("supplier_catalogs.catalog.write"))],
)
async def add_item_attachment(
    item_id: uuid.UUID,
    data: ItemAttachmentCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: SupplierCatalogsService = Depends(_svc),
) -> ItemAttachmentResponse:
    """Link a document (upload it in Documents first) to the item as datasheet or drawing."""
    project_id, doc_name = await service.document_project(data.document_id)
    await verify_project_access(project_id, str(user_id), session)
    att = await service.add_item_attachment(
        item_id,
        document_id=data.document_id,
        project_id=project_id,
        kind=data.kind,
        title=data.title or doc_name,
        user_id=str(user_id),
    )
    return ItemAttachmentResponse.model_validate(att)


@router.delete(
    "/catalog-items/{item_id}/attachments/{attachment_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("supplier_catalogs.catalog.write"))],
)
async def delete_item_attachment(
    item_id: uuid.UUID,
    attachment_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: SupplierCatalogsService = Depends(_svc),
) -> None:
    """Unlink a document from the item. The document itself stays in Documents."""
    att = await service.get_item_attachment(item_id, attachment_id)
    await verify_project_access(att.project_id, str(user_id), session)
    await service.delete_item_attachment(att)


# ── Purchase Requisition ──────────────────────────────────────────────────────
#
# Legacy. The canonical requisition is ``procurement.MaterialRequisition`` behind
# ``/api/v1/procurement/requisitions/`` (issue #516), which keeps BOQ sources,
# designated approvers, line-level ordering and the change feed. These routes
# stay for existing callers and records and are marked deprecated in OpenAPI.


@router.post(
    "/prs",
    response_model=PRResponse,
    status_code=201,
    deprecated=True,
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
    deprecated=True,
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
    deprecated=True,
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
    deprecated=True,
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
    deprecated=True,
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
    po = await service.acknowledge_po(po_id, user_id=user_id)
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
    po = await service.close_po(po_id, user_id=user_id)
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
    """Accept a UBL 2.1 PEPPOL invoice XML file → VendorInvoice + 3-way match.

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
    wh = await service.create_warehouse(data, user_id=user_id)
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


@router.patch(
    "/warehouses/{warehouse_id}",
    response_model=WarehouseResponse,
    dependencies=[Depends(RequirePermission("supplier_catalogs.warehouse.write"))],
)
async def update_warehouse(
    warehouse_id: uuid.UUID,
    data: WarehouseUpdate,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> WarehouseResponse:
    """Correct a warehouse's own fields. ``code`` and ``project_id`` are not among them."""
    wh = await service.update_warehouse(warehouse_id, data, user_id=user_id)
    return WarehouseResponse.model_validate(wh)


@router.delete(
    "/warehouses/{warehouse_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("supplier_catalogs.warehouse.manage"))],
)
async def delete_warehouse(
    warehouse_id: uuid.UUID,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> None:
    """Delete an empty warehouse.

    Refuses with 409 and a structured reason when stock is still on hand or
    goods were received into it.
    """
    await service.delete_warehouse(warehouse_id, user_id=user_id)


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
    rows = await service.list_warehouse_balances(warehouse_id, user_id=user_id)
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
    """Idempotently bulk-load UNSPSC + CPV codes from the bundled CSV."""
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


@router.delete(
    "/tolerance-profiles/{profile_id}",
    status_code=204,
    dependencies=[
        Depends(RequirePermission("supplier_catalogs.vendor.admin")),
    ],
)
async def delete_tolerance_profile(
    profile_id: uuid.UUID,
    user_id: CurrentUserId,
    service: SupplierCatalogsService = Depends(_svc),
) -> None:
    """Delete a tolerance profile no vendor is matched against.

    Refuses with 409 when vendors name it, or when it is the tenant default.
    """
    await service.delete_tolerance_profile(profile_id)


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
