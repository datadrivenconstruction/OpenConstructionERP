"""‌⁠‍Supplier Catalogs data access layer.

Thin SQLAlchemy wrappers — no business logic.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.supplier_catalogs.models import (
    CatalogEntry,
    CatalogItem,
    CommodityCode,
    GoodsReceipt,
    ItemCategory,
    KYCDocument,
    POLine,
    PriceList,
    PurchaseOrder,
    PurchaseRequisition,
    StockBalance,
    StockMovement,
    ThreeWayMatchRecord,
    TolerianceProfile,
    Vendor,
    VendorInvoice,
    VendorInvoiceLine,
    VendorScorecard,
    Warehouse,
)


class VendorRepository:
    """‌⁠‍CRUD for Vendor."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, vendor_id: uuid.UUID) -> Vendor | None:
        return await self.session.get(Vendor, vendor_id)

    async def get_by_code(self, code: str) -> Vendor | None:
        stmt = select(Vendor).where(Vendor.code == code)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list(
        self,
        *,
        status: str | None = None,
        country_code: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Vendor], int]:
        base = select(Vendor)
        if status:
            base = base.where(Vendor.status == status)
        if country_code:
            base = base.where(Vendor.country_code == country_code)
        total = (
            await self.session.execute(
                select(func.count()).select_from(base.subquery()),
            )
        ).scalar_one()
        rows = (
            (
                await self.session.execute(
                    base.order_by(Vendor.code).offset(offset).limit(limit),
                )
            )
            .scalars()
            .all()
        )
        return list(rows), total

    async def create(self, vendor: Vendor) -> Vendor:
        self.session.add(vendor)
        await self.session.flush()
        await self.session.refresh(vendor)
        return vendor

    async def update(self, vendor_id: uuid.UUID, **fields: Any) -> None:
        await self.session.execute(
            update(Vendor).where(Vendor.id == vendor_id).values(**fields),
        )
        await self.session.flush()


class ItemCategoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, cat: ItemCategory) -> ItemCategory:
        self.session.add(cat)
        await self.session.flush()
        await self.session.refresh(cat)
        return cat

    async def get(self, category_id: uuid.UUID) -> ItemCategory | None:
        return await self.session.get(ItemCategory, category_id)


class CatalogItemRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, item_id: uuid.UUID) -> CatalogItem | None:
        return await self.session.get(CatalogItem, item_id)

    async def get_by_sku(self, sku: str) -> CatalogItem | None:
        stmt = select(CatalogItem).where(CatalogItem.sku == sku)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list(
        self,
        *,
        category_id: uuid.UUID | None = None,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[CatalogItem], int]:
        base = select(CatalogItem)
        if category_id:
            base = base.where(CatalogItem.category_id == category_id)
        if search:
            like = f"%{search.lower()}%"
            base = base.where(func.lower(CatalogItem.name).like(like))
        total = (
            await self.session.execute(
                select(func.count()).select_from(base.subquery()),
            )
        ).scalar_one()
        rows = (
            (
                await self.session.execute(
                    base.order_by(CatalogItem.sku).offset(offset).limit(limit),
                )
            )
            .scalars()
            .all()
        )
        return list(rows), total

    async def create(self, item: CatalogItem) -> CatalogItem:
        self.session.add(item)
        await self.session.flush()
        await self.session.refresh(item)
        return item


class PriceListRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, pl_id: uuid.UUID) -> PriceList | None:
        stmt = (
            select(PriceList)
            .options(selectinload(PriceList.entries))
            .where(PriceList.id == pl_id)
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create(self, pl: PriceList) -> PriceList:
        self.session.add(pl)
        await self.session.flush()
        await self.session.refresh(pl)
        return pl

    async def list_entries_for_item(
        self,
        catalog_item_id: uuid.UUID,
    ) -> list[tuple[CatalogEntry, PriceList, Vendor]]:
        """‌⁠‍Return (entry, price_list, vendor) tuples for active price lists."""
        stmt = (
            select(CatalogEntry, PriceList, Vendor)
            .join(PriceList, PriceList.id == CatalogEntry.price_list_id)
            .join(Vendor, Vendor.id == PriceList.vendor_id)
            .where(
                and_(
                    CatalogEntry.catalog_item_id == catalog_item_id,
                    PriceList.status == "active",
                    Vendor.status == "active",
                ),
            )
        )
        rows = (await self.session.execute(stmt)).all()
        return [(r[0], r[1], r[2]) for r in rows]


class PRRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, pr_id: uuid.UUID) -> PurchaseRequisition | None:
        stmt = (
            select(PurchaseRequisition)
            .options(selectinload(PurchaseRequisition.lines))
            .where(PurchaseRequisition.id == pr_id)
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create(self, pr: PurchaseRequisition) -> PurchaseRequisition:
        self.session.add(pr)
        await self.session.flush()
        await self.session.refresh(pr)
        return pr

    async def update(self, pr_id: uuid.UUID, **fields: Any) -> None:
        await self.session.execute(
            update(PurchaseRequisition).where(PurchaseRequisition.id == pr_id).values(**fields),
        )
        await self.session.flush()

    async def next_number(self) -> str:
        stmt = select(func.count()).select_from(PurchaseRequisition)
        count = (await self.session.execute(stmt)).scalar_one() or 0
        return f"PR-{count + 1:06d}"


class POExtRepository:
    """Repository for the extended supplier_catalogs PO model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, po_id: uuid.UUID) -> PurchaseOrder | None:
        # ``populate_existing`` forces the identity-map entry (if any) to be
        # refreshed from the row, and the selectinload sub-queries always
        # re-run — needed so callers see freshly-inserted GR rows that were
        # added in the same session after a previous ``get`` cached an empty
        # ``receipts`` collection.
        stmt = (
            select(PurchaseOrder)
            .options(
                selectinload(PurchaseOrder.lines),
                selectinload(PurchaseOrder.receipts).selectinload(GoodsReceipt.lines),
            )
            .where(PurchaseOrder.id == po_id)
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_line(self, po_line_id: uuid.UUID) -> POLine | None:
        return await self.session.get(POLine, po_line_id)

    async def create(self, po: PurchaseOrder) -> PurchaseOrder:
        self.session.add(po)
        await self.session.flush()
        await self.session.refresh(po)
        return po

    async def update(self, po_id: uuid.UUID, **fields: Any) -> None:
        await self.session.execute(
            update(PurchaseOrder).where(PurchaseOrder.id == po_id).values(**fields),
        )
        await self.session.flush()

    async def update_line(self, po_line_id: uuid.UUID, **fields: Any) -> None:
        await self.session.execute(
            update(POLine).where(POLine.id == po_line_id).values(**fields),
        )
        await self.session.flush()

    async def next_number(self) -> str:
        stmt = select(func.count()).select_from(PurchaseOrder)
        count = (await self.session.execute(stmt)).scalar_one() or 0
        return f"PO-{count + 1:06d}"


class GRRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, gr_id: uuid.UUID) -> GoodsReceipt | None:
        stmt = (
            select(GoodsReceipt)
            .options(selectinload(GoodsReceipt.lines))
            .where(GoodsReceipt.id == gr_id)
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create(self, gr: GoodsReceipt) -> GoodsReceipt:
        self.session.add(gr)
        await self.session.flush()
        await self.session.refresh(gr)
        return gr

    async def update(self, gr_id: uuid.UUID, **fields: Any) -> None:
        await self.session.execute(
            update(GoodsReceipt).where(GoodsReceipt.id == gr_id).values(**fields),
        )
        await self.session.flush()

    async def next_number(self) -> str:
        stmt = select(func.count()).select_from(GoodsReceipt)
        count = (await self.session.execute(stmt)).scalar_one() or 0
        return f"GR-{count + 1:06d}"


class InvoiceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, inv_id: uuid.UUID) -> VendorInvoice | None:
        return await self.session.get(VendorInvoice, inv_id)

    async def create(self, inv: VendorInvoice) -> VendorInvoice:
        self.session.add(inv)
        await self.session.flush()
        await self.session.refresh(inv)
        return inv

    async def update(self, inv_id: uuid.UUID, **fields: Any) -> None:
        await self.session.execute(
            update(VendorInvoice).where(VendorInvoice.id == inv_id).values(**fields),
        )
        await self.session.flush()

    async def record_match(self, record: ThreeWayMatchRecord) -> ThreeWayMatchRecord:
        self.session.add(record)
        await self.session.flush()
        await self.session.refresh(record)
        return record


class WarehouseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, wh_id: uuid.UUID) -> Warehouse | None:
        return await self.session.get(Warehouse, wh_id)

    async def create(self, wh: Warehouse) -> Warehouse:
        self.session.add(wh)
        await self.session.flush()
        await self.session.refresh(wh)
        return wh

    async def list(self) -> list[Warehouse]:
        stmt = select(Warehouse).order_by(Warehouse.code)
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_balances(self, warehouse_id: uuid.UUID) -> list[StockBalance]:
        stmt = (
            select(StockBalance).where(StockBalance.warehouse_id == warehouse_id).order_by(StockBalance.catalog_item_id)
        )
        return list((await self.session.execute(stmt)).scalars().all())


class StockRepository:
    """Operations on stock balances + movements (no business rules here)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_balance(
        self,
        warehouse_id: uuid.UUID,
        catalog_item_id: uuid.UUID,
        batch_lot: str = "",
    ) -> StockBalance | None:
        stmt = select(StockBalance).where(
            and_(
                StockBalance.warehouse_id == warehouse_id,
                StockBalance.catalog_item_id == catalog_item_id,
                StockBalance.batch_lot == batch_lot,
            ),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_or_create_balance(
        self,
        warehouse_id: uuid.UUID,
        catalog_item_id: uuid.UUID,
        batch_lot: str = "",
    ) -> StockBalance:
        balance = await self.get_balance(warehouse_id, catalog_item_id, batch_lot)
        if balance is None:
            balance = StockBalance(
                warehouse_id=warehouse_id,
                catalog_item_id=catalog_item_id,
                batch_lot=batch_lot,
                quantity_on_hand=Decimal("0"),
                quantity_reserved=Decimal("0"),
                unit_cost_avg=Decimal("0"),
            )
            self.session.add(balance)
            await self.session.flush()
            await self.session.refresh(balance)
        return balance

    async def update_balance(self, balance_id: uuid.UUID, **fields: Any) -> None:
        await self.session.execute(
            update(StockBalance).where(StockBalance.id == balance_id).values(**fields),
        )
        await self.session.flush()

    async def record_movement(self, movement: StockMovement) -> StockMovement:
        self.session.add(movement)
        await self.session.flush()
        await self.session.refresh(movement)
        return movement


# ── Commodity codes ──────────────────────────────────────────────────────────


class CommodityCodeRepository:
    """Lookup + seed for UNSPSC / eClass / CPV codes."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(
        self,
        *,
        scheme: str | None = None,
        search: str | None = None,
        parent_code: str | None = None,
        level: int | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[CommodityCode]:
        stmt = select(CommodityCode).where(CommodityCode.active.is_(True))
        if scheme:
            stmt = stmt.where(CommodityCode.scheme == scheme)
        if parent_code is not None:
            stmt = stmt.where(CommodityCode.parent_code == parent_code)
        if level is not None:
            stmt = stmt.where(CommodityCode.level == level)
        if search:
            like = f"%{search.lower()}%"
            stmt = stmt.where(
                func.lower(CommodityCode.name).like(like) | (CommodityCode.code == search),
            )
        stmt = (
            stmt.order_by(
                CommodityCode.scheme,
                CommodityCode.code,
            )
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_by_code(
        self,
        scheme: str,
        code: str,
    ) -> CommodityCode | None:
        stmt = select(CommodityCode).where(
            CommodityCode.scheme == scheme,
            CommodityCode.code == code,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def upsert(self, cc: CommodityCode) -> CommodityCode:
        existing = await self.get_by_code(cc.scheme, cc.code)
        if existing is not None:
            existing.name = cc.name
            existing.description = cc.description
            existing.parent_code = cc.parent_code
            existing.level = cc.level
            existing.active = cc.active
            await self.session.flush()
            return existing
        self.session.add(cc)
        await self.session.flush()
        return cc


# ── Tolerance profiles ───────────────────────────────────────────────────────


class TolerianceProfileRepository:
    """CRUD for per-tenant 3-way match tolerance profiles."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self) -> list[TolerianceProfile]:
        stmt = select(TolerianceProfile).order_by(TolerianceProfile.name)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get(self, profile_id: uuid.UUID) -> TolerianceProfile | None:
        return await self.session.get(TolerianceProfile, profile_id)

    async def get_by_name(self, name: str) -> TolerianceProfile | None:
        stmt = select(TolerianceProfile).where(TolerianceProfile.name == name)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_default(self) -> TolerianceProfile | None:
        stmt = select(TolerianceProfile).where(
            TolerianceProfile.is_default.is_(True),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create(self, profile: TolerianceProfile) -> TolerianceProfile:
        self.session.add(profile)
        await self.session.flush()
        await self.session.refresh(profile)
        return profile

    async def update(
        self,
        profile_id: uuid.UUID,
        **fields: Any,
    ) -> None:
        await self.session.execute(
            update(TolerianceProfile).where(TolerianceProfile.id == profile_id).values(**fields),
        )
        await self.session.flush()


# ── KYC documents ────────────────────────────────────────────────────────────


class KYCDocumentRepository:
    """CRUD + expiry queries for vendor KYC documents."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, doc_id: uuid.UUID) -> KYCDocument | None:
        return await self.session.get(KYCDocument, doc_id)

    async def list_for_vendor(
        self,
        vendor_id: uuid.UUID,
    ) -> list[KYCDocument]:
        stmt = (
            select(KYCDocument)
            .where(KYCDocument.vendor_id == vendor_id)
            .order_by(KYCDocument.doc_type, KYCDocument.expires_on.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_expiring(
        self,
        *,
        on_or_before: Any,
    ) -> list[KYCDocument]:
        """Return active KYC docs with ``expires_on <= on_or_before``."""
        stmt = select(KYCDocument).where(
            KYCDocument.status == "active",
            KYCDocument.expires_on.is_not(None),
            KYCDocument.expires_on <= on_or_before,
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def create(self, doc: KYCDocument) -> KYCDocument:
        self.session.add(doc)
        await self.session.flush()
        await self.session.refresh(doc)
        return doc

    async def update(self, doc_id: uuid.UUID, **fields: Any) -> None:
        await self.session.execute(
            update(KYCDocument).where(KYCDocument.id == doc_id).values(**fields),
        )
        await self.session.flush()

    async def delete(self, doc_id: uuid.UUID) -> bool:
        doc = await self.get(doc_id)
        if doc is None:
            return False
        await self.session.delete(doc)
        await self.session.flush()
        return True


# ── Vendor scorecards ────────────────────────────────────────────────────────


class ScorecardRepository:
    """Per-period vendor scorecards."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, sc_id: uuid.UUID) -> VendorScorecard | None:
        return await self.session.get(VendorScorecard, sc_id)

    async def get_for_period(
        self,
        vendor_id: uuid.UUID,
        period_start: Any,
        period_end: Any,
    ) -> VendorScorecard | None:
        stmt = select(VendorScorecard).where(
            VendorScorecard.vendor_id == vendor_id,
            VendorScorecard.period_start == period_start,
            VendorScorecard.period_end == period_end,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_vendor(
        self,
        vendor_id: uuid.UUID,
        *,
        limit: int = 24,
    ) -> list[VendorScorecard]:
        stmt = (
            select(VendorScorecard)
            .where(VendorScorecard.vendor_id == vendor_id)
            .order_by(VendorScorecard.period_end.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def upsert(
        self,
        *,
        vendor_id: uuid.UUID,
        period_start: Any,
        period_end: Any,
        delivery_score: Decimal,
        quality_score: Decimal,
        price_score: Decimal,
        esg_score: Decimal,
        composite_score: Decimal,
        inputs_json: dict,
        weights_json: dict,
        computed_at: Any,
    ) -> VendorScorecard:
        existing = await self.get_for_period(
            vendor_id,
            period_start,
            period_end,
        )
        if existing is not None:
            existing.delivery_score = delivery_score
            existing.quality_score = quality_score
            existing.price_score = price_score
            existing.esg_score = esg_score
            existing.composite_score = composite_score
            existing.inputs_json = inputs_json
            existing.weights_json = weights_json
            existing.computed_at = computed_at
            await self.session.flush()
            return existing
        sc = VendorScorecard(
            vendor_id=vendor_id,
            period_start=period_start,
            period_end=period_end,
            delivery_score=delivery_score,
            quality_score=quality_score,
            price_score=price_score,
            esg_score=esg_score,
            composite_score=composite_score,
            inputs_json=inputs_json,
            weights_json=weights_json,
            computed_at=computed_at,
        )
        self.session.add(sc)
        await self.session.flush()
        await self.session.refresh(sc)
        return sc


# ── Invoice lines ────────────────────────────────────────────────────────────


class VendorInvoiceLineRepository:
    """Direct access to line-level invoice rows for PEPPOL ingest."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_batch(
        self,
        invoice_id: uuid.UUID,
        lines: list[VendorInvoiceLine],
    ) -> int:
        for line in lines:
            line.invoice_id = invoice_id
            self.session.add(line)
        await self.session.flush()
        return len(lines)

    async def list_for_invoice(
        self,
        invoice_id: uuid.UUID,
    ) -> list[VendorInvoiceLine]:
        stmt = (
            select(VendorInvoiceLine).where(VendorInvoiceLine.invoice_id == invoice_id).order_by(VendorInvoiceLine.id)
        )
        return list((await self.session.execute(stmt)).scalars().all())
