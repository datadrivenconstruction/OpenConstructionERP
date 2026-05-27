"""‌⁠‍Supplier Catalogs service — vendor management, catalog, PR/PO/GR/Invoice,
warehouse stock control, 3-way match.

Stateless. All cross-module references (project_id, contract_id, user_id,
contact_id) are plain UUID/strings — no ORM FK joins out of the module.
"""

from __future__ import annotations

import csv
import io
import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from importlib import resources
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.i18n import get_locale
from app.core.validation.messages import translate
from app.modules.supplier_catalogs import events as ev
from app.modules.supplier_catalogs.models import (
    CatalogEntry,
    CatalogItem,
    CommodityCode,
    GoodsReceipt,
    GRLine,
    ItemCategory,
    KYCDocument,
    POLine,
    PriceList,
    PRLine,
    PurchaseOrder,
    PurchaseRequisition,
    StockMovement,
    ThreeWayMatchRecord,
    TolerianceProfile,
    Vendor,
    VendorInvoice,
    VendorInvoiceLine,
    VendorScorecard,
    Warehouse,
)
from app.modules.supplier_catalogs.peppol import (
    PeppolParseError,
    parse_peppol_invoice,
)
from app.modules.supplier_catalogs.repository import (
    CatalogItemRepository,
    CommodityCodeRepository,
    GRRepository,
    InvoiceRepository,
    ItemCategoryRepository,
    KYCDocumentRepository,
    POExtRepository,
    PriceListRepository,
    PRRepository,
    ScorecardRepository,
    StockRepository,
    TolerianceProfileRepository,
    VendorInvoiceLineRepository,
    VendorRepository,
    WarehouseRepository,
)
from app.modules.supplier_catalogs.schemas import (
    CatalogItemCreate,
    GoodsReceiptCreate,
    ItemCategoryCreate,
    KYCDocumentCreate,
    MatchResult,
    PeppolIngestResult,
    POCreateExt,
    PRCreate,
    PriceListCreate,
    PriceListImportResult,
    ScorecardRecomputeRequest,
    ScorecardWeights,
    StockIssuePayload,
    StockReservePayload,
    StocktakePayload,
    TolerianceProfileCreate,
    TolerianceProfileUpdate,
    VendorCreate,
    VendorInvoiceCreate,
    VendorUpdate,
    WarehouseCreate,
)

logger = logging.getLogger(__name__)
_logger_ev = logging.getLogger(__name__ + ".events")

VALID_VENDOR_STATUSES = {"active", "suspended", "blacklisted"}
# Allowed vendor status transitions. ``blacklisted`` is a terminal
# compliance state — a vendor can only leave it via an explicit
# reactivation (which is itself a deliberate compliance decision), never
# be re-suspended or silently flipped. ``active`` ⇄ ``suspended`` is the
# normal operational toggle.
VENDOR_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "active": {"suspended", "blacklisted"},
    "suspended": {"active", "blacklisted"},
    "blacklisted": {"active"},
}
VALID_PR_STATUSES = {
    "draft",
    "approval_pending",
    "approved",
    "rejected",
    "converted",
}
VALID_PO_STATUSES = {
    "draft",
    "sent",
    "acknowledged",
    "partial",
    "received",
    "closed",
    "cancelled",
}


async def _safe_publish(name: str, data: dict[str, Any]) -> None:
    """‌⁠‍Fire-and-forget event publish; never propagate publish failures."""
    try:
        event_bus.publish_detached(name, data, source_module="oe_supplier_catalogs")
    except Exception:  # noqa: BLE001
        _logger_ev.debug("Event publish skipped: %s", name)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


class SupplierCatalogsService:
    """‌⁠‍High-level facade exposing all supplier-catalogs business operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.vendors = VendorRepository(session)
        self.categories = ItemCategoryRepository(session)
        self.items = CatalogItemRepository(session)
        self.price_lists = PriceListRepository(session)
        self.prs = PRRepository(session)
        self.pos = POExtRepository(session)
        self.grs = GRRepository(session)
        self.invoices = InvoiceRepository(session)
        self.warehouses = WarehouseRepository(session)
        self.stock = StockRepository(session)
        self.commodity_codes = CommodityCodeRepository(session)
        self.tolerance_profiles = TolerianceProfileRepository(session)
        self.kyc_docs = KYCDocumentRepository(session)
        self.scorecards = ScorecardRepository(session)
        self.invoice_lines = VendorInvoiceLineRepository(session)

    # ── Vendor ────────────────────────────────────────────────────────────────

    async def create_vendor(self, data: VendorCreate, user_id: str | None = None) -> Vendor:
        if await self.vendors.get_by_code(data.code) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Vendor with code '{data.code}' already exists.",
            )
        vendor = Vendor(
            code=data.code,
            name=data.name,
            legal_name=data.legal_name,
            tax_id=data.tax_id,
            contact_id=data.contact_id,
            status="active",
            currency=data.currency,
            payment_terms_days=data.payment_terms_days,
            country_code=data.country_code,
            region=data.region,
            categories_json=list(data.categories),
            preferred_for_json=list(data.preferred_for),
            contacts_json=[c.model_dump() for c in data.contacts],
            notes=data.notes,
            tolerance_profile_name=data.tolerance_profile_name,
        )
        vendor = await self.vendors.create(vendor)
        await _safe_publish(
            ev.VENDOR_CREATED,
            {
                "vendor_id": str(vendor.id),
                "code": vendor.code,
                "name": vendor.name,
                "actor_id": user_id,
            },
        )
        logger.info("Vendor created: %s", vendor.code)
        return vendor

    async def update_vendor(
        self,
        vendor_id: uuid.UUID,
        data: VendorUpdate,
    ) -> Vendor:
        vendor = await self.vendors.get(vendor_id)
        if vendor is None:
            raise HTTPException(status_code=404, detail=translate("errors.vendor_not_found", locale=get_locale()))
        payload = data.model_dump(exclude_unset=True)
        if "categories" in payload:
            payload["categories_json"] = list(payload.pop("categories") or [])
        if "preferred_for" in payload:
            payload["preferred_for_json"] = list(payload.pop("preferred_for") or [])
        if "contacts" in payload:
            payload["contacts_json"] = [
                c if isinstance(c, dict) else c.model_dump() for c in (payload.pop("contacts") or [])
            ]
        if payload:
            await self.vendors.update(vendor_id, **payload)
        refreshed = await self.vendors.get(vendor_id)
        assert refreshed is not None
        return refreshed

    async def _set_vendor_status(
        self,
        vendor_id: uuid.UUID,
        new_status: str,
        event_name: str,
        user_id: str | None,
        reason: str | None = None,
    ) -> Vendor:
        vendor = await self.vendors.get(vendor_id)
        if vendor is None:
            raise HTTPException(status_code=404, detail=translate("errors.vendor_not_found", locale=get_locale()))
        if new_status not in VALID_VENDOR_STATUSES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid vendor status: {new_status}",
            )
        if new_status == vendor.status:
            raise HTTPException(
                status_code=400,
                detail=f"Vendor is already '{new_status}'",
            )
        allowed = VENDOR_STATUS_TRANSITIONS.get(vendor.status, set())
        if new_status not in allowed:
            raise HTTPException(
                status_code=400,
                detail=(f"Illegal vendor status transition '{vendor.status}' → '{new_status}'"),
            )
        await self.vendors.update(vendor_id, status=new_status)
        await _safe_publish(
            event_name,
            {
                "vendor_id": str(vendor_id),
                "code": vendor.code,
                "previous_status": vendor.status,
                "new_status": new_status,
                "actor_id": user_id,
                "reason": reason,
            },
        )
        refreshed = await self.vendors.get(vendor_id)
        assert refreshed is not None
        return refreshed

    async def suspend_vendor(
        self,
        vendor_id: uuid.UUID,
        user_id: str | None = None,
        reason: str | None = None,
    ) -> Vendor:
        return await self._set_vendor_status(
            vendor_id,
            "suspended",
            ev.VENDOR_SUSPENDED,
            user_id,
            reason,
        )

    async def blacklist_vendor(
        self,
        vendor_id: uuid.UUID,
        user_id: str | None = None,
        reason: str | None = None,
    ) -> Vendor:
        return await self._set_vendor_status(
            vendor_id,
            "blacklisted",
            ev.VENDOR_BLACKLISTED,
            user_id,
            reason,
        )

    async def reactivate_vendor(
        self,
        vendor_id: uuid.UUID,
        user_id: str | None = None,
    ) -> Vendor:
        return await self._set_vendor_status(
            vendor_id,
            "active",
            ev.VENDOR_CREATED,
            user_id,  # reuse "created" topic
        )

    async def rate_vendor(
        self,
        vendor_id: uuid.UUID,
        rating: int,
        user_id: str | None = None,
    ) -> Vendor:
        if rating < 1 or rating > 5:
            raise HTTPException(status_code=400, detail="Rating must be 1..5")
        vendor = await self.vendors.get(vendor_id)
        if vendor is None:
            raise HTTPException(status_code=404, detail=translate("errors.vendor_not_found", locale=get_locale()))
        await self.vendors.update(vendor_id, rating=rating)
        await _safe_publish(
            ev.VENDOR_RATED,
            {"vendor_id": str(vendor_id), "rating": rating, "actor_id": user_id},
        )
        refreshed = await self.vendors.get(vendor_id)
        assert refreshed is not None
        return refreshed

    # ── Catalog ───────────────────────────────────────────────────────────────

    async def create_category(self, data: ItemCategoryCreate) -> ItemCategory:
        cat = ItemCategory(
            code=data.code,
            name=data.name,
            parent_id=data.parent_id,
            level=data.level,
            classification_ref=data.classification_ref,
        )
        return await self.categories.create(cat)

    async def create_catalog_item(self, data: CatalogItemCreate) -> CatalogItem:
        if await self.items.get_by_sku(data.sku) is not None:
            raise HTTPException(
                status_code=409,
                detail=f"Catalog item with SKU '{data.sku}' already exists.",
            )
        item = CatalogItem(
            sku=data.sku,
            name=data.name,
            description=data.description,
            category_id=data.category_id,
            unit_of_measure=data.unit_of_measure,
            manufacturer=data.manufacturer,
            mpn=data.mpn,
            spec_json=dict(data.spec),
            hazard_class=data.hazard_class,
            shelf_life_days=data.shelf_life_days,
            reorder_point=data.reorder_point,
            active=True,
        )
        created = await self.items.create(item)
        # Wave-M4 deep-pass: emit MATERIAL_ADDED so match_elements re-indexes
        # the new SKU into the vector store and BI projections tick.
        await _safe_publish(
            ev.MATERIAL_ADDED,
            {
                "catalog_item_id": str(created.id),
                "sku": created.sku,
                "name": created.name,
                "manufacturer": created.manufacturer or "",
                "mpn": created.mpn or "",
                "unit_of_measure": created.unit_of_measure,
                "category_id": (str(created.category_id) if created.category_id else None),
                "description": (created.description or "")[:500],
            },
        )
        return created

    # ── Price lists & comparison ──────────────────────────────────────────────

    async def create_price_list(
        self,
        vendor_id: uuid.UUID,
        data: PriceListCreate,
        user_id: str | None = None,
        activate: bool = True,
    ) -> PriceList:
        vendor = await self.vendors.get(vendor_id)
        if vendor is None:
            raise HTTPException(status_code=404, detail=translate("errors.vendor_not_found", locale=get_locale()))
        pl = PriceList(
            vendor_id=vendor_id,
            name=data.name,
            valid_from=data.valid_from,
            valid_to=data.valid_to,
            currency=data.currency,
            status="active" if activate else "draft",
            uploaded_by=user_id,
        )
        pl = await self.price_lists.create(pl)
        for entry in data.entries:
            self.session.add(
                CatalogEntry(
                    price_list_id=pl.id,
                    catalog_item_id=entry.catalog_item_id,
                    vendor_sku=entry.vendor_sku,
                    unit_price=entry.unit_price,
                    min_order_qty=entry.min_order_qty,
                    lead_time_days=entry.lead_time_days,
                    notes=entry.notes,
                )
            )
        await self.session.flush()
        return pl

    async def import_price_list(
        self,
        vendor_id: uuid.UUID,
        rows_csv: str | bytes,
        name: str = "Imported price list",
        currency: str = "EUR",
        user_id: str | None = None,
    ) -> PriceListImportResult:
        """Import a price list from CSV text.

        Expected columns: ``sku, unit_price`` (required); optional:
        ``vendor_sku, min_order_qty, lead_time_days, notes``.
        Duplicate ``sku`` rows within the upload are de-duplicated
        (last write wins). Rows referencing unknown SKUs are reported
        in ``errors`` and skipped.
        """
        vendor = await self.vendors.get(vendor_id)
        if vendor is None:
            raise HTTPException(status_code=404, detail=translate("errors.vendor_not_found", locale=get_locale()))
        if isinstance(rows_csv, bytes):
            text = rows_csv.decode("utf-8", errors="replace")
        else:
            text = rows_csv

        reader = csv.DictReader(io.StringIO(text))
        seen: dict[str, dict[str, Any]] = {}
        errors: list[str] = []
        for idx, row in enumerate(reader, start=2):  # row 1 = header
            sku = (row.get("sku") or "").strip()
            if not sku:
                errors.append(f"row {idx}: missing sku")
                continue
            try:
                unit_price = Decimal(str(row.get("unit_price", "0") or "0"))
            except (InvalidOperation, ValueError, TypeError):
                errors.append(f"row {idx}: invalid unit_price")
                continue
            seen[sku] = {
                "vendor_sku": (row.get("vendor_sku") or "").strip() or None,
                "unit_price": unit_price,
                "min_order_qty": _to_decimal(row.get("min_order_qty"), "1"),
                "lead_time_days": int(_to_decimal(row.get("lead_time_days"), "7")),
                "notes": (row.get("notes") or "").strip() or None,
            }

        # Create the price list
        pl = PriceList(
            vendor_id=vendor_id,
            name=name,
            currency=currency,
            status="active",
            uploaded_by=user_id,
        )
        pl = await self.price_lists.create(pl)

        imported = 0
        skipped = 0
        for sku, payload in seen.items():
            item = await self.items.get_by_sku(sku)
            if item is None:
                errors.append(f"unknown sku '{sku}'")
                skipped += 1
                continue
            self.session.add(
                CatalogEntry(
                    price_list_id=pl.id,
                    catalog_item_id=item.id,
                    vendor_sku=payload["vendor_sku"],
                    unit_price=payload["unit_price"],
                    min_order_qty=payload["min_order_qty"],
                    lead_time_days=payload["lead_time_days"],
                    notes=payload["notes"],
                )
            )
            imported += 1
        await self.session.flush()

        await _safe_publish(
            ev.PRICE_LIST_IMPORTED,
            {
                "price_list_id": str(pl.id),
                "vendor_id": str(vendor_id),
                "imported_count": imported,
                "skipped_count": skipped,
            },
        )
        return PriceListImportResult(
            price_list_id=pl.id,
            imported_count=imported,
            skipped_count=skipped,
            errors=errors,
        )

    async def compare_prices(
        self,
        catalog_item_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        """Return active-price comparison rows for an item, sorted by unit price."""
        rows = await self.price_lists.list_entries_for_item(catalog_item_id)
        results = [
            {
                "vendor_id": vendor.id,
                "vendor_code": vendor.code,
                "vendor_name": vendor.name,
                "unit_price": entry.unit_price,
                "currency": pl.currency,
                "min_order_qty": entry.min_order_qty,
                "lead_time_days": entry.lead_time_days,
                "price_list_id": pl.id,
                "rating": vendor.rating,
            }
            for entry, pl, vendor in rows
        ]
        return sorted(results, key=lambda r: (r["unit_price"], r["lead_time_days"]))

    # ── Purchase Requisition ──────────────────────────────────────────────────

    async def create_pr(
        self,
        data: PRCreate,
        user_id: str | None = None,
    ) -> PurchaseRequisition:
        number = await self.prs.next_number()
        total_estimate = sum(
            (line.quantity * line.estimated_unit_price for line in data.lines),
            Decimal("0"),
        )
        pr = PurchaseRequisition(
            number=number,
            project_id=data.project_id,
            requested_by=user_id,
            requested_at=_now_iso(),
            needed_by=data.needed_by,
            status="draft",
            total_estimate=total_estimate,
            currency=data.currency,
            notes=data.notes,
            approval_chain_json=list(data.approval_chain),
        )
        pr = await self.prs.create(pr)
        pr_id = pr.id
        for line in data.lines:
            self.session.add(
                PRLine(
                    pr_id=pr_id,
                    catalog_item_id=line.catalog_item_id,
                    description=line.description,
                    quantity=line.quantity,
                    unit_of_measure=line.unit_of_measure,
                    estimated_unit_price=line.estimated_unit_price,
                    estimated_total=line.quantity * line.estimated_unit_price,
                )
            )
        await self.session.flush()
        # Evict the cached PR from the identity-map so the next ``get`` issues
        # a fresh selectinload and the newly-inserted lines come back populated.
        self.session.expunge(pr)
        refreshed = await self.prs.get(pr_id)
        assert refreshed is not None
        return refreshed

    async def submit_pr(
        self,
        pr_id: uuid.UUID,
        user_id: str | None = None,
    ) -> PurchaseRequisition:
        pr = await self.prs.get(pr_id)
        if pr is None:
            raise HTTPException(
                status_code=404, detail=translate("errors.purchase_requisition_not_found", locale=get_locale())
            )
        if pr.status != "draft":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot submit PR in status '{pr.status}'",
            )
        new_status = "approval_pending" if pr.approval_chain_json else "approved"
        await self.prs.update(pr_id, status=new_status)
        await _safe_publish(
            ev.PR_SUBMITTED,
            {
                "pr_id": str(pr_id),
                "number": pr.number,
                "project_id": str(pr.project_id),
                "actor_id": user_id,
                "approval_chain": list(pr.approval_chain_json or []),
            },
        )
        refreshed = await self.prs.get(pr_id)
        assert refreshed is not None
        return refreshed

    async def approve_pr(
        self,
        pr_id: uuid.UUID,
        approver_id: str,
    ) -> PurchaseRequisition:
        pr = await self.prs.get(pr_id)
        if pr is None:
            raise HTTPException(
                status_code=404, detail=translate("errors.purchase_requisition_not_found", locale=get_locale())
            )
        if pr.status != "approval_pending":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot approve PR in status '{pr.status}'",
            )
        chain = list(pr.approval_chain_json or [])
        if not chain:
            await self.prs.update(pr_id, status="approved")
        else:
            # Pop the next approver. If the caller is in the chain, allow them
            # to advance regardless of position (single-stage approval per call).
            if approver_id in chain:
                chain.remove(approver_id)
            else:
                # Anyone with permission can advance, but log it
                chain.pop(0)
            new_status = "approved" if not chain else "approval_pending"
            await self.prs.update(
                pr_id,
                status=new_status,
                approval_chain_json=chain,
            )
        await _safe_publish(
            ev.PR_APPROVED,
            {
                "pr_id": str(pr_id),
                "number": pr.number,
                "project_id": str(pr.project_id),
                "approver_id": approver_id,
            },
        )
        refreshed = await self.prs.get(pr_id)
        assert refreshed is not None
        return refreshed

    async def reject_pr(
        self,
        pr_id: uuid.UUID,
        approver_id: str,
        reason: str | None = None,
    ) -> PurchaseRequisition:
        pr = await self.prs.get(pr_id)
        if pr is None:
            raise HTTPException(
                status_code=404, detail=translate("errors.purchase_requisition_not_found", locale=get_locale())
            )
        if pr.status not in ("approval_pending", "draft"):
            raise HTTPException(
                status_code=400,
                detail=f"Cannot reject PR in status '{pr.status}'",
            )
        await self.prs.update(pr_id, status="rejected")
        await _safe_publish(
            ev.PR_REJECTED,
            {
                "pr_id": str(pr_id),
                "approver_id": approver_id,
                "reason": reason,
            },
        )
        refreshed = await self.prs.get(pr_id)
        assert refreshed is not None
        return refreshed

    async def convert_pr_to_po(
        self,
        pr_id: uuid.UUID,
        vendor_id: uuid.UUID,
        user_id: str | None = None,
        currency: str | None = None,
        tax: Decimal | None = None,
    ) -> PurchaseOrder:
        pr = await self.prs.get(pr_id)
        if pr is None:
            raise HTTPException(
                status_code=404, detail=translate("errors.purchase_requisition_not_found", locale=get_locale())
            )
        if pr.status != "approved":
            raise HTTPException(
                status_code=400,
                detail=f"PR must be 'approved' to convert (currently '{pr.status}')",
            )
        vendor = await self.vendors.get(vendor_id)
        if vendor is None:
            raise HTTPException(status_code=404, detail=translate("errors.vendor_not_found", locale=get_locale()))
        if vendor.status != "active":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot use vendor in status '{vendor.status}'",
            )

        po_currency = currency or pr.currency
        po_tax = Decimal(tax) if tax is not None else Decimal("0")
        subtotal = sum(
            (line.quantity * line.estimated_unit_price for line in pr.lines),
            Decimal("0"),
        )
        number = await self.pos.next_number()
        po = PurchaseOrder(
            number=number,
            vendor_id=vendor_id,
            project_id=pr.project_id,
            pr_id=pr.id,
            status="draft",
            order_date=_now_iso()[:10],
            currency=po_currency,
            subtotal=subtotal,
            tax=po_tax,
            total=subtotal + po_tax,
        )
        po = await self.pos.create(po)
        for line in pr.lines:
            self.session.add(
                POLine(
                    po_id=po.id,
                    catalog_item_id=line.catalog_item_id,
                    description=line.description,
                    ordered_qty=line.quantity,
                    unit_of_measure=line.unit_of_measure,
                    unit_price=line.estimated_unit_price,
                    line_total=line.quantity * line.estimated_unit_price,
                )
            )
        await self.session.flush()
        await self.prs.update(pr_id, status="converted")
        await _safe_publish(
            ev.PR_CONVERTED,
            {
                "pr_id": str(pr_id),
                "po_id": str(po.id),
                "vendor_id": str(vendor_id),
                "actor_id": user_id,
            },
        )
        po_id = po.id
        await _safe_publish(
            ev.PO_CREATED,
            {
                "po_id": str(po_id),
                "vendor_id": str(vendor_id),
                "project_id": str(po.project_id),
                "total": str(po.total),
                "currency": po.currency,
            },
        )
        self.session.expunge(po)
        refreshed = await self.pos.get(po_id)
        assert refreshed is not None
        return refreshed

    # ── Purchase Order (extended) ─────────────────────────────────────────────

    async def create_po(
        self,
        data: POCreateExt,
        user_id: str | None = None,
    ) -> PurchaseOrder:
        vendor = await self.vendors.get(data.vendor_id)
        if vendor is None:
            raise HTTPException(status_code=404, detail=translate("errors.vendor_not_found", locale=get_locale()))
        if vendor.status != "active":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot order from vendor in status '{vendor.status}'",
            )
        subtotal = sum(
            (line.ordered_qty * line.unit_price for line in data.lines),
            Decimal("0"),
        )
        tax = Decimal(data.tax)
        number = await self.pos.next_number()
        po = PurchaseOrder(
            number=number,
            vendor_id=data.vendor_id,
            project_id=data.project_id,
            contract_id=data.contract_id,
            pr_id=data.pr_id,
            status="draft",
            order_date=data.order_date or _now_iso()[:10],
            expected_delivery=data.expected_delivery,
            currency=data.currency,
            subtotal=subtotal,
            tax=tax,
            total=subtotal + tax,
            terms=data.terms,
        )
        po = await self.pos.create(po)
        for line in data.lines:
            self.session.add(
                POLine(
                    po_id=po.id,
                    catalog_item_id=line.catalog_item_id,
                    description=line.description,
                    ordered_qty=line.ordered_qty,
                    unit_of_measure=line.unit_of_measure,
                    unit_price=line.unit_price,
                    line_total=line.ordered_qty * line.unit_price,
                )
            )
        await self.session.flush()
        po_id = po.id
        await _safe_publish(
            ev.PO_CREATED,
            {
                "po_id": str(po_id),
                "vendor_id": str(data.vendor_id),
                "project_id": str(po.project_id),
                "total": str(po.total),
                "currency": po.currency,
            },
        )
        self.session.expunge(po)
        refreshed = await self.pos.get(po_id)
        assert refreshed is not None
        return refreshed

    async def send_po(
        self,
        po_id: uuid.UUID,
        user_id: str | None = None,
    ) -> PurchaseOrder:
        po = await self.pos.get(po_id)
        if po is None:
            raise HTTPException(
                status_code=404, detail=translate("errors.purchase_order_not_found", locale=get_locale())
            )
        if po.status != "draft":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot send PO in status '{po.status}'",
            )
        await self.pos.update(po_id, status="sent")
        await _safe_publish(
            ev.PO_SENT,
            {
                "po_id": str(po_id),
                "vendor_id": str(po.vendor_id),
                "project_id": str(po.project_id),
                "total": str(po.total),
                "currency": po.currency,
                "actor_id": user_id,
            },
        )
        refreshed = await self.pos.get(po_id)
        assert refreshed is not None
        return refreshed

    async def acknowledge_po(self, po_id: uuid.UUID) -> PurchaseOrder:
        po = await self.pos.get(po_id)
        if po is None:
            raise HTTPException(
                status_code=404, detail=translate("errors.purchase_order_not_found", locale=get_locale())
            )
        if po.status != "sent":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot acknowledge PO in status '{po.status}'",
            )
        await self.pos.update(po_id, status="acknowledged")
        await _safe_publish(
            ev.PO_ACKNOWLEDGED,
            {"po_id": str(po_id), "vendor_id": str(po.vendor_id)},
        )
        refreshed = await self.pos.get(po_id)
        assert refreshed is not None
        return refreshed

    async def close_po(self, po_id: uuid.UUID) -> PurchaseOrder:
        po = await self.pos.get(po_id)
        if po is None:
            raise HTTPException(
                status_code=404, detail=translate("errors.purchase_order_not_found", locale=get_locale())
            )
        if po.status in ("closed", "cancelled"):
            raise HTTPException(
                status_code=400,
                detail=f"PO already in terminal status '{po.status}'",
            )
        await self.pos.update(po_id, status="closed")
        await _safe_publish(
            ev.PO_CLOSED,
            {"po_id": str(po_id), "project_id": str(po.project_id)},
        )
        refreshed = await self.pos.get(po_id)
        assert refreshed is not None
        return refreshed

    # ── Goods Receipt ─────────────────────────────────────────────────────────

    async def post_goods_receipt(
        self,
        data: GoodsReceiptCreate,
        user_id: str | None = None,
    ) -> GoodsReceipt:
        """Post a goods receipt — update PO line received_qty + stock balance.

        Validates:
            - PO is in (sent / acknowledged / partial) status
            - Each GR line maps to a PO line and is within (ordered - received)
        Side effects:
            - POLine.received_qty advanced by accepted_qty
            - PO status advances to ``partial`` or ``received``
            - StockBalance.quantity_on_hand updated (FIFO unit_cost_avg)
            - StockMovement IN row recorded per (item, batch)
        """
        po = await self.pos.get(data.po_id)
        if po is None:
            raise HTTPException(
                status_code=404, detail=translate("errors.purchase_order_not_found", locale=get_locale())
            )
        if po.status not in ("sent", "acknowledged", "partial"):
            raise HTTPException(
                status_code=400,
                detail=f"Cannot receive goods for PO in status '{po.status}'",
            )
        warehouse = await self.warehouses.get(data.warehouse_id)
        if warehouse is None:
            raise HTTPException(status_code=404, detail="Warehouse not found")

        po_lines_by_id = {line.id: line for line in po.lines}

        # Validate every GR line up front
        for gr_line in data.lines:
            po_line = po_lines_by_id.get(gr_line.po_line_id)
            if po_line is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"PO line {gr_line.po_line_id} not found in PO {po.id}",
                )
            outstanding = po_line.ordered_qty - po_line.received_qty
            if gr_line.received_qty > outstanding:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Received qty {gr_line.received_qty} exceeds outstanding "
                        f"{outstanding} for line '{po_line.description}'"
                    ),
                )

        number = await self.grs.next_number()
        gr = GoodsReceipt(
            number=number,
            po_id=data.po_id,
            warehouse_id=data.warehouse_id,
            received_at=data.received_at or _now_iso(),
            received_by=user_id,
            status="posted",
            scan_method=data.scan_method,
            photos_json=list(data.photos),
            discrepancy_notes=data.discrepancy_notes,
        )
        gr = await self.grs.create(gr)

        # Apply each line
        low_stock_alerts: list[dict[str, Any]] = []
        for gr_line in data.lines:
            po_line = po_lines_by_id[gr_line.po_line_id]
            accepted = (
                gr_line.accepted_qty
                if gr_line.accepted_qty is not None
                else gr_line.received_qty - gr_line.rejected_qty
            )
            if accepted < 0:
                accepted = Decimal("0")
            # Persist GR line
            self.session.add(
                GRLine(
                    gr_id=gr.id,
                    po_line_id=po_line.id,
                    received_qty=gr_line.received_qty,
                    accepted_qty=accepted,
                    rejected_qty=gr_line.rejected_qty,
                    batch_lot=gr_line.batch_lot,
                    serial_numbers_json=(list(gr_line.serial_numbers) if gr_line.serial_numbers else None),
                    notes=gr_line.notes,
                )
            )
            # Advance PO line counter
            await self.pos.update_line(
                po_line.id,
                received_qty=po_line.received_qty + accepted,
            )
            # Update stock balance for accepted_qty only
            if accepted > 0 and po_line.catalog_item_id is not None:
                batch = gr_line.batch_lot or ""
                balance = await self.stock.get_or_create_balance(
                    warehouse_id=data.warehouse_id,
                    catalog_item_id=po_line.catalog_item_id,
                    batch_lot=batch,
                )
                # Weighted-average cost
                prev_qty = balance.quantity_on_hand
                prev_cost = balance.unit_cost_avg
                new_qty = prev_qty + accepted
                if new_qty > 0:
                    new_cost = ((prev_qty * prev_cost) + (accepted * po_line.unit_price)) / new_qty
                else:
                    new_cost = po_line.unit_price
                await self.stock.update_balance(
                    balance.id,
                    quantity_on_hand=new_qty,
                    unit_cost_avg=new_cost,
                    last_movement_at=_now_iso(),
                )
                # Movement audit
                await self.stock.record_movement(
                    StockMovement(
                        warehouse_id=data.warehouse_id,
                        catalog_item_id=po_line.catalog_item_id,
                        movement_type="in",
                        quantity=accepted,
                        unit_cost=po_line.unit_price,
                        reference_type="gr",
                        reference_id=str(gr.id),
                        batch_lot=batch or None,
                        project_id=po.project_id,
                        performed_by=user_id,
                        performed_at=_now_iso(),
                    )
                )
                # Check low-stock threshold
                catalog_item = await self.items.get(po_line.catalog_item_id)
                if catalog_item is not None and catalog_item.reorder_point > 0:
                    available = new_qty - balance.quantity_reserved
                    if available < catalog_item.reorder_point:
                        low_stock_alerts.append(
                            {
                                "catalog_item_id": str(catalog_item.id),
                                "sku": catalog_item.sku,
                                "warehouse_id": str(data.warehouse_id),
                                "available_qty": str(available),
                                "reorder_point": str(catalog_item.reorder_point),
                            }
                        )

        # Advance PO status
        refreshed_po = await self.pos.get(po.id)
        assert refreshed_po is not None
        fully_received = all(line.received_qty >= line.ordered_qty for line in refreshed_po.lines)
        new_status = "received" if fully_received else "partial"
        if refreshed_po.status != new_status:
            await self.pos.update(po.id, status=new_status)

        await _safe_publish(
            ev.GR_POSTED,
            {
                "gr_id": str(gr.id),
                "po_id": str(po.id),
                "warehouse_id": str(data.warehouse_id),
                "project_id": str(po.project_id),
            },
        )
        if new_status == "received":
            await _safe_publish(
                ev.PO_RECEIVED,
                {"po_id": str(po.id), "project_id": str(po.project_id)},
            )
        for alert in low_stock_alerts:
            # Back-compat: old subscribers still listen on STOCK_LOW_THRESHOLD
            await _safe_publish(ev.STOCK_LOW_THRESHOLD, alert)
            # Canonical name (matches v3 ``supplier_catalogs.stock.low``)
            await _safe_publish(ev.STOCK_LOW, alert)

        gr_id = gr.id
        self.session.expunge(gr)
        refreshed = await self.grs.get(gr_id)
        assert refreshed is not None
        return refreshed

    # ── Invoice & 3-way match ─────────────────────────────────────────────────

    async def create_invoice(
        self,
        data: VendorInvoiceCreate,
        user_id: str | None = None,
    ) -> VendorInvoice:
        vendor = await self.vendors.get(data.vendor_id)
        if vendor is None:
            raise HTTPException(status_code=404, detail=translate("errors.vendor_not_found", locale=get_locale()))
        invoice = VendorInvoice(
            number=data.number,
            vendor_id=data.vendor_id,
            po_id=data.po_id,
            invoice_date=data.invoice_date,
            due_date=data.due_date,
            currency=data.currency,
            subtotal=data.subtotal,
            tax=data.tax,
            total=data.subtotal + data.tax,
            status="received",
            three_way_match_status="pending",
        )
        return await self.invoices.create(invoice)

    async def _resolve_tolerance(
        self,
        *,
        profile_name: str | None,
        override_pct: Decimal | None,
    ) -> TolerianceProfile:
        """Resolve the tolerance profile to use for this match.

        Precedence:
            1. explicit ``profile_name`` parameter (named lookup)
            2. caller-supplied legacy ``override_pct`` (back-compat)
            3. tenant ``default`` profile
            4. a synthetic in-memory fallback profile (2% / 0 abs / 0% qty)
        """
        if profile_name:
            existing = await self.tolerance_profiles.get_by_name(profile_name)
            if existing is not None:
                return existing
        if override_pct is not None:
            # Synthesise an in-memory profile from the legacy single param
            return TolerianceProfile(
                name="__inline__",
                price_tolerance_pct=override_pct,
                price_tolerance_abs=Decimal("0"),
                qty_tolerance_pct=Decimal("0"),
                period_tolerance_days=7,
                require_gr=True,
                is_default=False,
            )
        default = await self.tolerance_profiles.get_default()
        if default is not None:
            return default
        return TolerianceProfile(
            name="default",
            price_tolerance_pct=Decimal("2.0"),
            price_tolerance_abs=Decimal("0"),
            qty_tolerance_pct=Decimal("0"),
            period_tolerance_days=7,
            require_gr=True,
            is_default=True,
        )

    async def match_invoice(
        self,
        invoice_id: uuid.UUID,
        tolerance_pct: Decimal | None = None,
        tolerance_profile_name: str | None = None,
        user_id: str | None = None,
    ) -> MatchResult:
        """Run 3-way match: invoice ↔ PO ↔ GR with configurable tolerances.

        Resolution order for the tolerance band:
            1. ``tolerance_profile_name`` parameter
            2. Vendor's ``tolerance_profile_name`` (set at vendor creation)
            3. Tenant's default profile
            4. Legacy ``tolerance_pct`` parameter (back-compat)

        Returns a :class:`MatchResult` with per-line variance breakdown.
        """
        invoice = await self.invoices.get(invoice_id)
        if invoice is None:
            raise HTTPException(status_code=404, detail="Invoice not found")
        if invoice.po_id is None:
            await self.invoices.update(
                invoice_id,
                three_way_match_status="exception",
                exception_reason="No PO linked to invoice",
            )
            return MatchResult(
                invoice_id=invoice_id,
                status="exception",
                price_variance=Decimal("0"),
                qty_variance=Decimal("0"),
                tolerance_used_pct=tolerance_pct or Decimal("2.0"),
                exception_reason="No PO linked to invoice",
                tolerance_profile_name=tolerance_profile_name or "default",
                line_results=[],
            )

        po = await self.pos.get(invoice.po_id)
        if po is None:
            raise HTTPException(status_code=400, detail="Linked PO not found")

        # Resolve tolerance profile. Vendor-bound profile takes precedence
        # over the tenant default but loses to an explicit override.
        vendor = await self.vendors.get(invoice.vendor_id)
        resolved_profile_name = tolerance_profile_name or (
            vendor.tolerance_profile_name if vendor is not None else None
        )
        profile = await self._resolve_tolerance(
            profile_name=resolved_profile_name,
            override_pct=tolerance_pct,
        )

        # ── Header-level price variance ────────────────────────────
        price_var = invoice.total - po.total
        price_tol_pct = po.total * profile.price_tolerance_pct / Decimal("100")
        price_tol = max(price_tol_pct, profile.price_tolerance_abs)
        price_exception = abs(price_var) > price_tol

        # ── Quantity variance ──────────────────────────────────────
        total_ordered = sum(
            (line.ordered_qty for line in po.lines),
            Decimal("0"),
        )
        total_received = sum(
            (line.received_qty for line in po.lines),
            Decimal("0"),
        )
        qty_var = total_ordered - total_received
        has_confirmed_gr = any(gr.status == "posted" for gr in po.receipts)
        if profile.require_gr:
            qty_exception = not has_confirmed_gr or total_received <= 0
        else:
            qty_exception = False
        # Apply qty tolerance percentage to *received* vs ordered shortfall
        if not qty_exception and total_ordered > 0 and profile.qty_tolerance_pct > 0:
            allowed_short = total_ordered * profile.qty_tolerance_pct / Decimal("100")
            shortfall = total_ordered - total_received
            if shortfall > allowed_short:
                qty_exception = True

        # ── Period variance (delivery vs PO.expected_delivery) ────
        period_exception = False
        period_delta_days: int | None = None
        if po.expected_delivery and has_confirmed_gr and profile.period_tolerance_days >= 0:
            try:
                expected = datetime.fromisoformat(po.expected_delivery).date()
                latest_gr = max(
                    (
                        datetime.fromisoformat(
                            (gr.received_at or "")[:10],
                        ).date()
                        for gr in po.receipts
                        if gr.status == "posted" and gr.received_at
                    ),
                    default=None,
                )
                if latest_gr is not None:
                    period_delta_days = (latest_gr - expected).days
                    if abs(period_delta_days) > profile.period_tolerance_days:
                        period_exception = True
            except (ValueError, TypeError):
                pass

        # ── Line-level breakdown ───────────────────────────────────
        line_results: list[dict[str, Any]] = []
        inv_lines = await self.invoice_lines.list_for_invoice(invoice_id)
        if inv_lines:
            po_lines_by_id = {pl.id: pl for pl in po.lines}
            for il in inv_lines:
                po_line = po_lines_by_id.get(il.po_line_id) if il.po_line_id else None
                line_price_var: Decimal | None = None
                line_qty_var: Decimal | None = None
                status_str = "no_po_line"
                if po_line is not None:
                    line_price_var = il.unit_price - po_line.unit_price
                    line_qty_var = il.quantity - po_line.received_qty
                    pl_tol_pct = po_line.unit_price * profile.price_tolerance_pct / Decimal("100")
                    pl_tol = max(pl_tol_pct, profile.price_tolerance_abs)
                    status_str = "ok" if abs(line_price_var) <= pl_tol else "price_variance"
                line_results.append(
                    {
                        "invoice_line_id": str(il.id),
                        "po_line_id": str(il.po_line_id) if il.po_line_id else None,
                        "description": il.description,
                        "invoice_qty": str(il.quantity),
                        "invoice_unit_price": str(il.unit_price),
                        "po_unit_price": (str(po_line.unit_price) if po_line else None),
                        "received_qty": (str(po_line.received_qty) if po_line else None),
                        "price_variance": (str(line_price_var) if line_price_var is not None else None),
                        "qty_variance": (str(line_qty_var) if line_qty_var is not None else None),
                        "status": status_str,
                    },
                )

        if price_exception or qty_exception or period_exception:
            reasons = []
            if price_exception:
                reasons.append(
                    f"price variance {price_var} exceeds tolerance {price_tol} ({profile.price_tolerance_pct}%)",
                )
            if qty_exception:
                reasons.append(
                    "no goods received yet"
                    if not has_confirmed_gr
                    else f"received qty {total_received} below tolerance vs ordered {total_ordered}",
                )
            if period_exception:
                reasons.append(
                    f"delivery {period_delta_days}d outside ±{profile.period_tolerance_days}d tolerance",
                )
            reason = "; ".join(reasons)
            await self.invoices.update(
                invoice_id,
                three_way_match_status="exception",
                status="disputed",
                exception_reason=reason,
                line_level_match_json={"lines": line_results},
            )
            await self.invoices.record_match(
                ThreeWayMatchRecord(
                    invoice_id=invoice_id,
                    po_id=invoice.po_id,
                    gr_id=None,
                    matched_at=_now_iso(),
                    matched_by=user_id,
                    price_variance=price_var,
                    qty_variance=qty_var,
                    status="exception",
                    tolerance_used_pct=profile.price_tolerance_pct,
                    notes=reason,
                ),
            )
            await _safe_publish(
                ev.INVOICE_EXCEPTION,
                {
                    "invoice_id": str(invoice_id),
                    "po_id": str(invoice.po_id),
                    "reason": reason,
                    "price_variance": str(price_var),
                    "qty_variance": str(qty_var),
                    "tolerance_profile": profile.name,
                },
            )
            return MatchResult(
                invoice_id=invoice_id,
                status="exception",
                price_variance=price_var,
                qty_variance=qty_var,
                tolerance_used_pct=profile.price_tolerance_pct,
                exception_reason=reason,
                tolerance_profile_name=profile.name,
                line_results=line_results,
            )

        # Auto-match
        first_gr = next(
            (gr for gr in po.receipts if gr.status == "posted"),
            None,
        )
        await self.invoices.update(
            invoice_id,
            three_way_match_status="matched",
            status="approved",
            exception_reason=None,
            line_level_match_json={"lines": line_results},
        )
        await self.invoices.record_match(
            ThreeWayMatchRecord(
                invoice_id=invoice_id,
                po_id=invoice.po_id,
                gr_id=first_gr.id if first_gr else None,
                matched_at=_now_iso(),
                matched_by=user_id,
                price_variance=price_var,
                qty_variance=qty_var,
                status="auto_matched",
                tolerance_used_pct=profile.price_tolerance_pct,
            ),
        )
        await _safe_publish(
            ev.INVOICE_MATCHED,
            {
                "invoice_id": str(invoice_id),
                "po_id": str(invoice.po_id),
                "price_variance": str(price_var),
                "tolerance_profile": profile.name,
            },
        )
        return MatchResult(
            invoice_id=invoice_id,
            status="auto_matched",
            price_variance=price_var,
            qty_variance=qty_var,
            tolerance_used_pct=profile.price_tolerance_pct,
            tolerance_profile_name=profile.name,
            line_results=line_results,
        )

    # ── Warehouse & stock ─────────────────────────────────────────────────────

    async def create_warehouse(self, data: WarehouseCreate) -> Warehouse:
        wh = Warehouse(
            code=data.code,
            name=data.name,
            project_id=data.project_id,
            address=data.address,
            manager_user_id=data.manager_user_id,
            status="active",
        )
        return await self.warehouses.create(wh)

    async def reserve_stock(
        self,
        data: StockReservePayload,
        user_id: str | None = None,
    ) -> StockMovement:
        balance = await self.stock.get_or_create_balance(
            warehouse_id=data.warehouse_id,
            catalog_item_id=data.catalog_item_id,
            batch_lot=data.batch_lot or "",
        )
        available = balance.quantity_on_hand - balance.quantity_reserved
        if data.quantity > available:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Cannot reserve {data.quantity}: only {available} available "
                    f"(on_hand={balance.quantity_on_hand}, "
                    f"reserved={balance.quantity_reserved})"
                ),
            )
        await self.stock.update_balance(
            balance.id,
            quantity_reserved=balance.quantity_reserved + data.quantity,
            last_movement_at=_now_iso(),
        )
        movement = await self.stock.record_movement(
            StockMovement(
                warehouse_id=data.warehouse_id,
                catalog_item_id=data.catalog_item_id,
                movement_type="reservation",
                quantity=data.quantity,
                unit_cost=balance.unit_cost_avg,
                reference_type="reservation",
                reference_id=str(data.project_id) if data.project_id else None,
                batch_lot=data.batch_lot,
                project_id=data.project_id,
                performed_by=user_id,
                performed_at=_now_iso(),
            )
        )
        await _safe_publish(
            ev.STOCK_RESERVED,
            {
                "catalog_item_id": str(data.catalog_item_id),
                "warehouse_id": str(data.warehouse_id),
                "quantity": str(data.quantity),
                "project_id": str(data.project_id) if data.project_id else None,
            },
        )
        return movement

    async def issue_stock(
        self,
        data: StockIssuePayload,
        user_id: str | None = None,
    ) -> StockMovement:
        balance = await self.stock.get_balance(
            warehouse_id=data.warehouse_id,
            catalog_item_id=data.catalog_item_id,
            batch_lot=data.batch_lot or "",
        )
        if balance is None:
            raise HTTPException(
                status_code=400,
                detail="No stock balance for this item/warehouse",
            )
        if data.quantity > balance.quantity_on_hand:
            raise HTTPException(
                status_code=400,
                detail=(f"Cannot issue {data.quantity}: only {balance.quantity_on_hand} on hand"),
            )
        # Reduce reserved if it was reserved
        new_reserved = balance.quantity_reserved
        if new_reserved >= data.quantity:
            new_reserved = new_reserved - data.quantity
        await self.stock.update_balance(
            balance.id,
            quantity_on_hand=balance.quantity_on_hand - data.quantity,
            quantity_reserved=new_reserved,
            last_movement_at=_now_iso(),
        )
        movement = await self.stock.record_movement(
            StockMovement(
                warehouse_id=data.warehouse_id,
                catalog_item_id=data.catalog_item_id,
                movement_type="out",
                quantity=data.quantity,
                unit_cost=balance.unit_cost_avg,
                reference_type="issue",
                reference_id=(str(data.to_project_id) if data.to_project_id else None),
                batch_lot=data.batch_lot,
                project_id=data.to_project_id,
                performed_by=user_id,
                performed_at=_now_iso(),
                notes=data.notes,
            )
        )
        await _safe_publish(
            ev.STOCK_ISSUED,
            {
                "catalog_item_id": str(data.catalog_item_id),
                "warehouse_id": str(data.warehouse_id),
                "quantity": str(data.quantity),
                "to_project_id": (str(data.to_project_id) if data.to_project_id else None),
            },
        )
        return movement

    async def stocktake(
        self,
        warehouse_id: uuid.UUID,
        data: StocktakePayload,
        user_id: str | None = None,
    ) -> list[StockMovement]:
        """Reconcile counted quantities vs on-hand — record ADJUST movements."""
        wh = await self.warehouses.get(warehouse_id)
        if wh is None:
            raise HTTPException(status_code=404, detail="Warehouse not found")
        movements: list[StockMovement] = []
        for count in data.counts:
            balance = await self.stock.get_or_create_balance(
                warehouse_id=warehouse_id,
                catalog_item_id=count.catalog_item_id,
                batch_lot=count.batch_lot or "",
            )
            delta = count.counted_qty - balance.quantity_on_hand
            if delta == 0:
                continue
            await self.stock.update_balance(
                balance.id,
                quantity_on_hand=count.counted_qty,
                last_movement_at=_now_iso(),
            )
            mv = await self.stock.record_movement(
                StockMovement(
                    warehouse_id=warehouse_id,
                    catalog_item_id=count.catalog_item_id,
                    movement_type="adjust",
                    quantity=delta,
                    unit_cost=balance.unit_cost_avg,
                    reference_type="stocktake",
                    reference_id=None,
                    batch_lot=count.batch_lot,
                    performed_by=user_id,
                    performed_at=_now_iso(),
                    notes=f"Stocktake delta={delta}",
                )
            )
            movements.append(mv)
            await _safe_publish(
                ev.STOCK_ADJUSTED,
                {
                    "catalog_item_id": str(count.catalog_item_id),
                    "warehouse_id": str(warehouse_id),
                    "delta": str(delta),
                },
            )
        return movements

    # ── Budget check (soft dependency) ────────────────────────────────────────

    async def check_budget(self, po: PurchaseOrder) -> dict[str, Any]:
        """Best-effort budget check against a project budget if available.

        Returns ``{"available": True}`` if the budget module isn't installed,
        else a dict with committed/budget/remaining figures.
        """
        try:
            from app.modules.finance.models import (  # type: ignore[import-untyped]
                ProjectBudget,
            )
        except Exception:  # noqa: BLE001
            return {"available": False, "reason": "finance_module_not_present"}
        from sqlalchemy import func as _func
        from sqlalchemy import select as _select

        try:
            stmt = _select(_func.coalesce(_func.sum(ProjectBudget.amount), 0)).where(
                ProjectBudget.project_id == po.project_id,
            )
            budget = (await self.session.execute(stmt)).scalar_one()
        except Exception:  # noqa: BLE001
            return {"available": False, "reason": "budget_query_failed"}
        return {
            "available": True,
            "budget": str(budget),
            "po_total": str(po.total),
        }

    # ── Commodity codes ───────────────────────────────────────────────────────

    async def seed_commodity_codes(self) -> dict[str, int]:
        """Bulk-load UNSPSC + CPV codes from the bundled CSV.

        Idempotent — re-runs upsert existing entries. Returns counts per scheme.
        """
        counts: dict[str, int] = {}
        try:
            csv_text = (
                resources.files("app.modules.supplier_catalogs.data")
                .joinpath("unspsc_construction.csv")
                .read_text(encoding="utf-8")
            )
        except Exception:
            logger.warning("commodity_codes: bundled CSV missing")
            return counts

        reader = csv.DictReader(io.StringIO(csv_text))
        for row in reader:
            scheme = (row.get("scheme") or "unspsc").strip().lower()
            code = (row.get("code") or "").strip()
            if not code:
                continue
            cc = CommodityCode(
                scheme=scheme,
                code=code,
                name=(row.get("name") or "").strip() or code,
                description=(row.get("description") or "").strip() or None,
                parent_code=(row.get("parent_code") or "").strip() or None,
                level=int((row.get("level") or "1") or "1"),
                active=True,
            )
            await self.commodity_codes.upsert(cc)
            counts[scheme] = counts.get(scheme, 0) + 1
        return counts

    async def list_commodity_codes(
        self,
        *,
        scheme: str | None = None,
        search: str | None = None,
        parent_code: str | None = None,
        level: int | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[CommodityCode]:
        return await self.commodity_codes.list(
            scheme=scheme,
            search=search,
            parent_code=parent_code,
            level=level,
            limit=limit,
            offset=offset,
        )

    async def validate_commodity_code(
        self,
        scheme: str,
        code: str,
    ) -> bool:
        """Return True if (scheme, code) exists and is active."""
        cc = await self.commodity_codes.get_by_code(scheme, code)
        return cc is not None and cc.active

    # ── Tolerance profiles ────────────────────────────────────────────────────

    async def create_tolerance_profile(
        self,
        data: TolerianceProfileCreate,
    ) -> TolerianceProfile:
        existing = await self.tolerance_profiles.get_by_name(data.name)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Tolerance profile '{data.name}' already exists",
            )
        # Demote any existing default if this one claims to be default
        if data.is_default:
            current_default = await self.tolerance_profiles.get_default()
            if current_default is not None:
                await self.tolerance_profiles.update(
                    current_default.id,
                    is_default=False,
                )
        profile = TolerianceProfile(
            name=data.name,
            description=data.description,
            price_tolerance_pct=data.price_tolerance_pct,
            price_tolerance_abs=data.price_tolerance_abs,
            qty_tolerance_pct=data.qty_tolerance_pct,
            period_tolerance_days=data.period_tolerance_days,
            require_gr=data.require_gr,
            is_default=data.is_default,
        )
        return await self.tolerance_profiles.create(profile)

    async def update_tolerance_profile(
        self,
        profile_id: uuid.UUID,
        data: TolerianceProfileUpdate,
    ) -> TolerianceProfile:
        existing = await self.tolerance_profiles.get(profile_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Profile not found")
        updates = data.model_dump(exclude_unset=True)
        if updates.get("is_default") is True:
            current = await self.tolerance_profiles.get_default()
            if current is not None and current.id != profile_id:
                await self.tolerance_profiles.update(
                    current.id,
                    is_default=False,
                )
        if updates:
            await self.tolerance_profiles.update(profile_id, **updates)
        refreshed = await self.tolerance_profiles.get(profile_id)
        assert refreshed is not None
        return refreshed

    async def ensure_default_tolerance_profile(self) -> TolerianceProfile:
        """Idempotently ensure the ``default`` profile exists. Called on boot."""
        existing = await self.tolerance_profiles.get_by_name("default")
        if existing is not None:
            return existing
        profile = TolerianceProfile(
            name="default",
            description="Tenant default 3-way match tolerance",
            price_tolerance_pct=Decimal("2.0"),
            price_tolerance_abs=Decimal("0"),
            qty_tolerance_pct=Decimal("0"),
            period_tolerance_days=7,
            require_gr=True,
            is_default=True,
        )
        return await self.tolerance_profiles.create(profile)

    # ── KYC documents ─────────────────────────────────────────────────────────

    async def add_kyc_document(
        self,
        vendor_id: uuid.UUID,
        data: KYCDocumentCreate,
        user_id: str | None = None,
    ) -> KYCDocument:
        vendor = await self.vendors.get(vendor_id)
        if vendor is None:
            raise HTTPException(status_code=404, detail=translate("errors.vendor_not_found", locale=get_locale()))
        valid_types = {
            "w9",
            "vat_cert",
            "gst",
            "trn",
            "coi",
            "iso",
            "other",
        }
        if data.doc_type not in valid_types:
            raise HTTPException(
                status_code=400,
                detail=(f"Invalid doc_type '{data.doc_type}'. Allowed: {sorted(valid_types)}"),
            )
        doc = KYCDocument(
            vendor_id=vendor_id,
            doc_type=data.doc_type,
            document_number=data.document_number,
            issued_on=data.issued_on,
            expires_on=data.expires_on,
            issuing_country=data.issuing_country,
            issuing_authority=data.issuing_authority,
            file_url=data.file_url,
            status="active",
            notes=data.notes,
        )
        doc = await self.kyc_docs.create(doc)
        await _safe_publish(
            ev.KYC_DOC_UPLOADED,
            {
                "vendor_id": str(vendor_id),
                "doc_type": data.doc_type,
                "expires_on": (data.expires_on.isoformat() if data.expires_on else None),
                "actor_id": user_id,
            },
        )
        return doc

    async def list_kyc_for_vendor(
        self,
        vendor_id: uuid.UUID,
    ) -> list[KYCDocument]:
        return await self.kyc_docs.list_for_vendor(vendor_id)

    async def check_kyc_expiry(
        self,
        *,
        days_ahead: int = 30,
    ) -> dict[str, int]:
        """Scan all KYC docs; emit ``KYC_DOC_EXPIRING`` or ``KYC_DOC_EXPIRED``.

        Runs as a background job. Idempotent because the status flip from
        ``active`` → ``expired`` prevents duplicate events.
        """
        today = datetime.now(UTC).date()
        threshold = today + timedelta(days=days_ahead)
        expiring_count = 0
        expired_count = 0
        docs = await self.kyc_docs.list_expiring(on_or_before=threshold)
        for doc in docs:
            if doc.expires_on is None:
                continue
            if doc.expires_on < today:
                await self.kyc_docs.update(doc.id, status="expired")
                await _safe_publish(
                    ev.KYC_DOC_EXPIRED,
                    {
                        "vendor_id": str(doc.vendor_id),
                        "doc_id": str(doc.id),
                        "doc_type": doc.doc_type,
                        "expired_on": doc.expires_on.isoformat(),
                    },
                )
                expired_count += 1
            else:
                await _safe_publish(
                    ev.KYC_DOC_EXPIRING,
                    {
                        "vendor_id": str(doc.vendor_id),
                        "doc_id": str(doc.id),
                        "doc_type": doc.doc_type,
                        "expires_on": doc.expires_on.isoformat(),
                        "days_until_expiry": (doc.expires_on - today).days,
                    },
                )
                expiring_count += 1
        return {"expiring": expiring_count, "expired": expired_count}

    # ── Vendor scorecard ──────────────────────────────────────────────────────

    async def recompute_scorecard(
        self,
        vendor_id: uuid.UUID,
        data: ScorecardRecomputeRequest,
    ) -> VendorScorecard:
        """Compute a weighted multi-criteria scorecard for a vendor.

        Score components (each 0..100):
            * **delivery_score** — on-time delivery from GR.received_at vs
              PO.expected_delivery (100 = always on or early).
            * **quality_score**  — accepted_qty / received_qty over the
              period (100 = no rejections).
            * **price_score**    — vendor's avg unit_price vs cheapest
              vendor for matching items (100 = cheapest).
            * **esg_score**      — derived from active KYC docs
              (ISO certs + non-expired tax docs count positively).
        """
        vendor = await self.vendors.get(vendor_id)
        if vendor is None:
            raise HTTPException(status_code=404, detail=translate("errors.vendor_not_found", locale=get_locale()))
        if data.period_start > data.period_end:
            raise HTTPException(
                status_code=400,
                detail="period_start > period_end",
            )

        weights = data.weights or ScorecardWeights()
        weight_sum = weights.delivery + weights.quality + weights.price + weights.esg
        if weight_sum <= 0:
            raise HTTPException(
                status_code=400,
                detail="Sum of weights must be > 0",
            )

        # 1. Delivery score — fraction of GRs that arrived on or before expected
        from sqlalchemy import select as _select

        po_stmt = _select(PurchaseOrder).where(
            PurchaseOrder.vendor_id == vendor_id,
        )
        po_rows = (await self.session.execute(po_stmt)).scalars().all()
        total_grs = 0
        on_time = 0
        accepted_sum = Decimal("0")
        received_sum = Decimal("0")
        for po in po_rows:
            for gr in po.receipts:
                if gr.status != "posted":
                    continue
                total_grs += 1
                # Quality
                for line in gr.lines:
                    accepted_sum += line.accepted_qty
                    received_sum += line.received_qty
                # Delivery
                if gr.received_at and po.expected_delivery:
                    try:
                        rcv = datetime.fromisoformat(
                            gr.received_at[:10],
                        ).date()
                        exp = datetime.fromisoformat(
                            po.expected_delivery,
                        ).date()
                        if rcv <= exp:
                            on_time += 1
                    except (ValueError, TypeError):
                        pass

        delivery_score = (Decimal(on_time) * Decimal("100") / Decimal(total_grs)) if total_grs > 0 else Decimal("0")
        quality_score = (accepted_sum * Decimal("100") / received_sum) if received_sum > 0 else Decimal("0")

        # 2. Price score — vendor avg unit_price vs cheapest competing vendor
        # For each catalog item the vendor prices, compute the ratio
        # cheapest/this; average over the basket. Two grouped aggregate
        # queries (NOT a per-item N+1): one for this vendor's lowest price
        # per item, one for the market-wide cheapest per item.
        from sqlalchemy import func as _func

        from app.modules.supplier_catalogs.models import (
            CatalogEntry as _CE,
        )

        vendor_min_stmt = (
            _select(
                _CE.catalog_item_id,
                _func.min(_CE.unit_price).label("vendor_min"),
            )
            .join(PriceList, PriceList.id == _CE.price_list_id)
            .where(PriceList.vendor_id == vendor_id)
            .where(PriceList.status == "active")
            .where(_CE.unit_price > 0)
            .group_by(_CE.catalog_item_id)
        )
        vendor_min: dict[uuid.UUID, Decimal] = {
            row[0]: row[1] for row in (await self.session.execute(vendor_min_stmt)).all()
        }

        market_min: dict[uuid.UUID, Decimal] = {}
        if vendor_min:
            market_min_stmt = (
                _select(
                    _CE.catalog_item_id,
                    _func.min(_CE.unit_price).label("market_min"),
                )
                .join(PriceList, PriceList.id == _CE.price_list_id)
                .where(PriceList.status == "active")
                .where(_CE.unit_price > 0)
                .where(_CE.catalog_item_id.in_(list(vendor_min.keys())))
                .group_by(_CE.catalog_item_id)
            )
            market_min = {row[0]: row[1] for row in (await self.session.execute(market_min_stmt)).all()}

        sample_count = 0
        ratio_sum = Decimal("0")
        for item_id, this_price in vendor_min.items():
            cheapest = market_min.get(item_id)
            if cheapest is None or this_price <= 0:
                continue
            ratio = Decimal(cheapest) / Decimal(this_price)  # 1.0 if cheapest
            ratio_sum += ratio
            sample_count += 1
        price_score = (ratio_sum * Decimal("100") / Decimal(sample_count)) if sample_count > 0 else Decimal("0")

        # 3. ESG score — based on KYC documents in good standing
        kyc_docs = await self.kyc_docs.list_for_vendor(vendor_id)
        active_docs = [d for d in kyc_docs if d.status == "active"]
        iso_present = any(d.doc_type == "iso" for d in active_docs)
        tax_doc_present = any(d.doc_type in ("w9", "vat_cert", "gst", "trn") for d in active_docs)
        coi_present = any(d.doc_type == "coi" for d in active_docs)
        esg_components = sum(
            [
                Decimal("40") if iso_present else Decimal("0"),
                Decimal("35") if tax_doc_present else Decimal("0"),
                Decimal("25") if coi_present else Decimal("0"),
            ],
            Decimal("0"),
        )
        esg_score = min(esg_components, Decimal("100"))

        # Composite
        composite = (
            (delivery_score * weights.delivery)
            + (quality_score * weights.quality)
            + (price_score * weights.price)
            + (esg_score * weights.esg)
        ) / weight_sum

        now = datetime.now(UTC)
        sc = await self.scorecards.upsert(
            vendor_id=vendor_id,
            period_start=data.period_start,
            period_end=data.period_end,
            delivery_score=delivery_score.quantize(Decimal("0.01")),
            quality_score=quality_score.quantize(Decimal("0.01")),
            price_score=price_score.quantize(Decimal("0.01")),
            esg_score=esg_score.quantize(Decimal("0.01")),
            composite_score=composite.quantize(Decimal("0.01")),
            inputs_json={
                "total_grs": total_grs,
                "on_time": on_time,
                "accepted_qty": str(accepted_sum),
                "received_qty": str(received_sum),
                "price_sample_count": sample_count,
                "iso_present": iso_present,
                "tax_doc_present": tax_doc_present,
                "coi_present": coi_present,
            },
            weights_json={
                "delivery": str(weights.delivery),
                "quality": str(weights.quality),
                "price": str(weights.price),
                "esg": str(weights.esg),
            },
            computed_at=now,
        )
        await _safe_publish(
            ev.SCORECARD_COMPUTED,
            {
                "vendor_id": str(vendor_id),
                "period_start": data.period_start.isoformat(),
                "period_end": data.period_end.isoformat(),
                "composite_score": str(sc.composite_score),
            },
        )
        return sc

    async def list_scorecards(
        self,
        vendor_id: uuid.UUID,
        *,
        limit: int = 24,
    ) -> list[VendorScorecard]:
        return await self.scorecards.list_for_vendor(vendor_id, limit=limit)

    # ── PEPPOL invoice ingest ─────────────────────────────────────────────────

    async def ingest_peppol_invoice(
        self,
        xml_payload: bytes | str,
        *,
        user_id: str | None = None,
        auto_match: bool = True,
    ) -> PeppolIngestResult:
        """Parse a UBL 2.1 PEPPOL invoice and ingest into the system.

        Vendor resolution order:
            1. Match by ``supplier_vat`` (Vendor.tax_id)
            2. Match by ``supplier_name`` (case-insensitive)
            3. 404 if unmatched (PEPPOL invoices from new suppliers require
               manual vendor onboarding first)

        PO resolution: matches by ``cac:OrderReference/cbc:ID`` ==
        ``PurchaseOrder.number``. If found, ``auto_match`` runs 3-way match.
        """
        try:
            parsed = parse_peppol_invoice(xml_payload)
        except PeppolParseError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        # Find vendor
        vendor: Vendor | None = None
        if parsed.supplier_vat:
            from sqlalchemy import select as _select

            stmt = _select(Vendor).where(Vendor.tax_id == parsed.supplier_vat)
            vendor = (await self.session.execute(stmt)).scalar_one_or_none()
        if vendor is None and parsed.supplier_name:
            from sqlalchemy import func as _func
            from sqlalchemy import select as _select

            stmt = _select(Vendor).where(
                _func.lower(Vendor.name) == parsed.supplier_name.lower(),
            )
            vendor = (await self.session.execute(stmt)).scalar_one_or_none()
        if vendor is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Vendor not found. Onboard supplier '{parsed.supplier_name}' (VAT={parsed.supplier_vat}) first."
                ),
            )

        # Resolve PO by number
        po: PurchaseOrder | None = None
        if parsed.order_reference:
            from sqlalchemy import select as _select

            stmt = _select(PurchaseOrder).where(
                PurchaseOrder.number == parsed.order_reference,
            )
            po = (await self.session.execute(stmt)).scalar_one_or_none()

        # Create invoice (idempotency: skip if same number+vendor exists)
        from sqlalchemy import select as _select

        existing_stmt = _select(VendorInvoice).where(
            VendorInvoice.number == parsed.invoice_id,
            VendorInvoice.vendor_id == vendor.id,
        )
        existing = (await self.session.execute(existing_stmt)).scalar_one_or_none()
        if existing is not None:
            return PeppolIngestResult(
                invoice_id=existing.id,
                invoice_number=existing.number,
                vendor_id=vendor.id,
                matched_status=existing.three_way_match_status,
                line_count=len(parsed.lines),
                total=existing.total,
                currency=existing.currency,
                exception_reason=existing.exception_reason,
                peppol_message_id=existing.peppol_message_id,
            )

        invoice = VendorInvoice(
            number=parsed.invoice_id,
            vendor_id=vendor.id,
            po_id=po.id if po is not None else None,
            invoice_date=parsed.issue_date,
            due_date=parsed.due_date,
            currency=parsed.currency,
            subtotal=parsed.line_extension_amount,
            tax=parsed.tax_total,
            total=parsed.payable_amount,
            status="received",
            three_way_match_status="pending",
            source="peppol",
            peppol_message_id=parsed.peppol_message_id,
        )
        invoice = await self.invoices.create(invoice)

        # Persist lines + best-effort PO line match by vendor_sku/buyer_sku
        po_lines_by_sku: dict[str, uuid.UUID] = {}
        if po is not None:
            for pl in po.lines:
                if pl.catalog_item_id is None:
                    continue
                item = await self.items.get(pl.catalog_item_id)
                if item is None:
                    continue
                # Match by sku, vendor_sku via catalog_entries, or description
                if item.sku:
                    po_lines_by_sku[item.sku.lower()] = pl.id

        invoice_lines: list[VendorInvoiceLine] = []
        for pline in parsed.lines:
            po_line_id: uuid.UUID | None = None
            for sku in (pline.buyer_sku, pline.vendor_sku):
                if sku and sku.lower() in po_lines_by_sku:
                    po_line_id = po_lines_by_sku[sku.lower()]
                    break
            invoice_lines.append(
                VendorInvoiceLine(
                    invoice_id=invoice.id,
                    po_line_id=po_line_id,
                    description=pline.description,
                    quantity=pline.quantity,
                    unit_of_measure=pline.unit_of_measure,
                    unit_price=pline.unit_price,
                    line_total=pline.line_total,
                    vendor_sku=pline.vendor_sku,
                ),
            )
        if invoice_lines:
            await self.invoice_lines.create_batch(invoice.id, invoice_lines)

        await _safe_publish(
            ev.PEPPOL_INVOICE_INGESTED,
            {
                "invoice_id": str(invoice.id),
                "vendor_id": str(vendor.id),
                "po_id": str(po.id) if po else None,
                "line_count": len(invoice_lines),
                "total": str(invoice.total),
                "currency": invoice.currency,
            },
        )

        matched_status = "unmatched"
        exception_reason: str | None = None
        if auto_match and po is not None:
            match = await self.match_invoice(invoice.id, user_id=user_id)
            matched_status = match.status
            exception_reason = match.exception_reason

        return PeppolIngestResult(
            invoice_id=invoice.id,
            invoice_number=invoice.number,
            vendor_id=vendor.id,
            matched_status=matched_status,
            line_count=len(invoice_lines),
            total=invoice.total,
            currency=invoice.currency,
            exception_reason=exception_reason,
            peppol_message_id=invoice.peppol_message_id,
        )
