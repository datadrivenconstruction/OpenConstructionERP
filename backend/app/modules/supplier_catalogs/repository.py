# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Supplier Catalogs data access layer.

Thin SQLAlchemy wrappers - no business logic.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.supplier_catalogs.models import (
    COST_STATE_UNKNOWN,
    CatalogEntry,
    CatalogItem,
    CommodityCode,
    GoodsReceipt,
    ItemCategory,
    KYCDocument,
    POLine,
    PriceList,
    PRLine,
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


async def _count_by_kind(
    session: AsyncSession,
    probes: list[tuple[str, Any, Any]],
) -> dict[str, int]:
    """Count rows per ``(kind, entity, condition)`` probe, dropping the zeros.

    Used by the delete guards. Each probe is counted with its own explicit
    ``select_from`` rather than letting the FROM be inferred, because an
    inferred FROM is decided by the condition and would change silently if a
    condition ever grew a join. Kinds that count zero are left out, so an
    empty result reads as "nothing holds this row".
    """
    counts: dict[str, int] = {}
    for kind, entity, condition in probes:
        total = (
            await session.execute(
                select(func.count()).select_from(entity).where(condition),
            )
        ).scalar_one()
        if total:
            counts[kind] = int(total)
    return counts


class VendorRepository:
    """CRUD for Vendor."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, vendor_id: uuid.UUID) -> Vendor | None:
        return await self.session.get(Vendor, vendor_id)

    async def get_loaded(self, vendor_id: uuid.UUID) -> Vendor | None:
        """Re-select a vendor with ``price_lists`` eagerly loaded inside async.

        After a bulk ``update().values()`` the identity-mapped Vendor is
        expired; serializing it would refresh it and trigger the
        ``lazy="selectin"`` ``price_lists`` load synchronously outside the
        async greenlet (-> MissingGreenlet on asyncpg). ``populate_existing``
        forces the expired instance and its relationship to be re-populated
        here, within the greenlet.
        """
        stmt = (
            select(Vendor)
            .options(selectinload(Vendor.price_lists))
            .where(Vendor.id == vendor_id)
            .execution_options(populate_existing=True)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

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

    async def count_references(self, vendor_id: uuid.UUID) -> dict[str, int]:
        """Count the rows in this module that point at one vendor.

        Kinds with a zero count are dropped, so an empty mapping means
        nothing holds the vendor. Purchase requisitions are absent because
        they carry no ``vendor_id`` at all; they reach a vendor only through
        the purchase order they convert into.

        ``VendorScorecard`` also carries a ``vendor_id`` and is deliberately
        NOT counted. It is ``ondelete="CASCADE"``, so deleting a vendor does
        destroy its scorecards - but a scorecard is derived, not recorded. It
        is recomputed from the orders, receipts and invoices by
        ``recompute_scorecard``, so what goes with the vendor is a cached
        figure rather than a record of anything that happened. A vendor with
        scorecards but no orders, invoices, price lists or KYC documents was
        never actually traded with, and blocking on a cache would make that
        vendor permanently undeletable for no reason a buyer could act on.
        """
        return await _count_by_kind(
            self.session,
            [
                ("price_list", PriceList, PriceList.vendor_id == vendor_id),
                ("purchase_order", PurchaseOrder, PurchaseOrder.vendor_id == vendor_id),
                ("vendor_invoice", VendorInvoice, VendorInvoice.vendor_id == vendor_id),
                ("kyc_document", KYCDocument, KYCDocument.vendor_id == vendor_id),
            ],
        )

    async def delete(self, vendor_id: uuid.UUID) -> bool:
        vendor = await self.get(vendor_id)
        if vendor is None:
            return False
        await self.session.delete(vendor)
        await self.session.flush()
        return True


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

    async def update(self, item_id: uuid.UUID, **fields: Any) -> None:
        await self.session.execute(
            update(CatalogItem).where(CatalogItem.id == item_id).values(**fields),
        )
        await self.session.flush()

    async def count_references(self, item_id: uuid.UUID) -> dict[str, int]:
        """Count the rows that point at one catalog item, zeros dropped.

        ``stock_balance`` counts only balances that still carry quantity. A
        balance that has been emptied is a row about a thing that is no
        longer there and must not keep an item alive; a balance that still
        holds stock is inventory, and its item may not vanish underneath it.

        ``StockMovement`` is deliberately NOT counted, and the cost of that is
        real: it is ``ondelete="CASCADE"``, so deleting an item destroys the
        immutable movement rows that record every stock change it was ever
        part of. Counting it would be the safer instinct, but it would also
        make the decision above unreachable - an emptied balance only exists
        because movements took the stock out, so any item that was ever
        stocked would become permanently undeletable and the "emptied balance
        does not block" rule would never fire. The rule chosen here is that an
        item nothing currently holds may go; if that trade is wrong, the fix
        is to retire the item with ``is_active`` rather than to delete it.
        """
        return await _count_by_kind(
            self.session,
            [
                ("requisition_line", PRLine, PRLine.catalog_item_id == item_id),
                ("order_line", POLine, POLine.catalog_item_id == item_id),
                ("catalog_entry", CatalogEntry, CatalogEntry.catalog_item_id == item_id),
                (
                    "stock_balance",
                    StockBalance,
                    and_(
                        StockBalance.catalog_item_id == item_id,
                        StockBalance.quantity_on_hand != 0,
                    ),
                ),
            ],
        )

    async def delete(self, item_id: uuid.UUID) -> bool:
        item = await self.get(item_id)
        if item is None:
            return False
        await self.session.delete(item)
        await self.session.flush()
        return True


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
        """Return (entry, price_list, vendor) tuples for active price lists."""
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
        # re-run - needed so callers see freshly-inserted GR rows that were
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

    async def update(self, wh_id: uuid.UUID, **fields: Any) -> None:
        await self.session.execute(
            update(Warehouse).where(Warehouse.id == wh_id).values(**fields),
        )
        await self.session.flush()

    async def count_references(self, wh_id: uuid.UUID) -> dict[str, int]:
        """Count what holds one warehouse, zeros dropped.

        ``stock_balance`` counts balances that still carry quantity: an empty
        balance row is a record of stock that has gone, and it must not keep
        an unused location on the books.

        ``goods_receipt`` is here because the database says so. That foreign
        key is ``ondelete="RESTRICT"``, so a receipt would make the delete
        fail as an IntegrityError at flush time, which reaches the caller as
        a 500 with nothing in it a buyer could act on. Counting it first
        turns the same refusal into a sentence.

        ``StockMovement`` is deliberately NOT counted here, for the same
        reason as in :meth:`CatalogItemRepository.count_references`: it is
        ``ondelete="CASCADE"``, so the movement history for this location is
        destroyed with it, and counting it would make an emptied warehouse
        permanently undeletable. A location with history that should be kept
        is retired with ``is_active`` rather than deleted.
        """
        return await _count_by_kind(
            self.session,
            [
                (
                    "stock_balance",
                    StockBalance,
                    and_(
                        StockBalance.warehouse_id == wh_id,
                        StockBalance.quantity_on_hand != 0,
                    ),
                ),
                ("goods_receipt", GoodsReceipt, GoodsReceipt.warehouse_id == wh_id),
            ],
        )

    async def delete(self, wh_id: uuid.UUID) -> bool:
        warehouse = await self.get(wh_id)
        if warehouse is None:
            return False
        await self.session.delete(warehouse)
        await self.session.flush()
        return True


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
                # A balance that has never received anything has no average
                # cost, as distinct from an average cost of zero. Zero is a
                # price, and stock genuinely received for nothing would record
                # exactly that, so the two must not share a representation.
                unit_cost_avg=None,
                currency=None,
                cost_state=COST_STATE_UNKNOWN,
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

    async def count_references(self, name: str) -> dict[str, int]:
        """Count the vendors matched against a profile, by profile NAME.

        ``Vendor.tolerance_profile_name`` is a name, not a foreign key, so
        the database has nothing to enforce here and a delete would succeed
        in silence. What the vendors would lose is not cosmetic: the profile
        is what the three-way match compares an invoice against, so vendors
        left pointing at a name that no longer resolves fall back to a
        different set of tolerances, and invoices that used to raise a price
        exception start passing.
        """
        return await _count_by_kind(
            self.session,
            [("vendor", Vendor, Vendor.tolerance_profile_name == name)],
        )

    async def delete(self, profile_id: uuid.UUID) -> bool:
        profile = await self.get(profile_id)
        if profile is None:
            return False
        await self.session.delete(profile)
        await self.session.flush()
        return True


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
