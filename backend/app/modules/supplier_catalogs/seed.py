"""‌⁠‍Demo seed data for supplier_catalogs.

Loaded on demand via ``await seed_supplier_catalogs(session)``.
Safe to call repeatedly: existing vendors/items/warehouses are skipped.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.supplier_catalogs.models import (
    CatalogEntry,
    CatalogItem,
    GoodsReceipt,
    GRLine,
    ItemCategory,
    POLine,
    PriceList,
    PRLine,
    PurchaseOrder,
    PurchaseRequisition,
    StockBalance,
    StockMovement,
    Vendor,
    VendorInvoice,
    Warehouse,
)

logger = logging.getLogger(__name__)


async def seed_supplier_catalogs(
    session: AsyncSession,
    project_id: uuid.UUID | None = None,
) -> dict[str, int]:
    """‌⁠‍Seed demo vendors, catalog, price lists, PRs, POs, GRs, invoices.

    Returns a summary dict with row counts inserted per entity. Existing
    vendors / catalog items (matched by code/sku) are skipped silently.
    """
    project_id = project_id or uuid.uuid4()
    counts: dict[str, int] = {}

    # Idempotency guard. This seed inserts vendors with fixed codes
    # (V001..V005) plus other fixed-key rows, and vendor.code is unique. On a
    # second boot the blind insert hit that constraint, raised an
    # IntegrityError that aborted the seed transaction, and slowed startup. If
    # the marker vendor V001 is already present the demo set has been seeded,
    # so skip silently (mirrors the marker-check pattern used by other seeds).
    existing = await session.scalar(select(Vendor.id).where(Vendor.code == "V001"))
    if existing is not None:
        logger.info("supplier_catalogs seed skipped: marker vendor V001 already present")
        return {"skipped": 1}

    # --- 5 vendors ---
    vendor_specs = [
        ("V001", "Beton AG", "concrete", ["concrete", "rebar"], 4),
        ("V002", "Stahl GmbH", "steel", ["rebar", "structural_steel"], 5),
        ("V003", "MEP Supply Co", "mep", ["pipe", "fittings", "cable"], 3),
        ("V004", "Finishing Trade", "finishing", ["paint", "drywall"], 4),
        ("V005", "Generic Supplies", "general", [], 2),
    ]
    vendors: list[Vendor] = []
    for code, name, region, cats, rating in vendor_specs:
        v = Vendor(
            code=code,
            name=name,
            status="active",
            currency="EUR",
            payment_terms_days=30,
            rating=rating,
            categories_json=list(cats),
            country_code="DE",
            region=region,
        )
        session.add(v)
        vendors.append(v)
    await session.flush()
    counts["vendors"] = len(vendors)

    # --- 3-level category tree ---
    cat_l1 = ItemCategory(code="MATERIALS", name="Materials", level=0)
    session.add(cat_l1)
    await session.flush()
    cat_l2 = ItemCategory(
        code="CONCRETE",
        name="Concrete",
        parent_id=cat_l1.id,
        level=1,
    )
    session.add(cat_l2)
    await session.flush()
    cat_l3 = ItemCategory(
        code="C30_37",
        name="C30/37 concrete",
        parent_id=cat_l2.id,
        level=2,
        classification_ref="03 30 00",
    )
    session.add(cat_l3)
    await session.flush()
    counts["categories"] = 3

    # --- 100 catalog items ---
    items: list[CatalogItem] = []
    units = ["m3", "kg", "pcs", "m", "m2", "ton", "l"]
    for i in range(100):
        item = CatalogItem(
            sku=f"SKU-{i + 1:05d}",
            name=f"Item {i + 1}",
            description=f"Demo construction material item {i + 1}",
            category_id=cat_l3.id if i < 30 else cat_l2.id,
            unit_of_measure=units[i % len(units)],
            reorder_point=Decimal("10") if i % 5 == 0 else Decimal("0"),
            active=True,
        )
        session.add(item)
        items.append(item)
    await session.flush()
    counts["catalog_items"] = len(items)

    # --- 3 price lists (vendors 0, 1, 2) with 30+ entries each ---
    price_lists: list[PriceList] = []
    for vi, vendor in enumerate(vendors[:3]):
        pl = PriceList(
            vendor_id=vendor.id,
            name=f"{vendor.code} 2026-Q1",
            currency="EUR",
            status="active",
        )
        session.add(pl)
        await session.flush()
        price_lists.append(pl)
        for j in range(30 + vi * 5):
            session.add(
                CatalogEntry(
                    price_list_id=pl.id,
                    catalog_item_id=items[j].id,
                    unit_price=Decimal("10") + Decimal(j) + Decimal(vi),
                    min_order_qty=Decimal("1"),
                    lead_time_days=7 + vi,
                )
            )
    await session.flush()
    counts["price_lists"] = len(price_lists)

    # --- 1 warehouse ---
    warehouse = Warehouse(
        code="WH-MAIN",
        name="Main warehouse",
        project_id=project_id,
        status="active",
    )
    session.add(warehouse)
    await session.flush()
    counts["warehouses"] = 1

    # --- 5 PRs across statuses ---
    pr_statuses = ["draft", "approval_pending", "approved", "rejected", "converted"]
    prs: list[PurchaseRequisition] = []
    for idx, st in enumerate(pr_statuses):
        pr = PurchaseRequisition(
            number=f"PR-S{idx + 1:04d}",
            project_id=project_id,
            requested_at="2026-05-01T00:00:00+00:00",
            needed_by="2026-06-01",
            status=st,
            total_estimate=Decimal("1000") * (idx + 1),
            currency="EUR",
            approval_chain_json=["user-a"] if st == "approval_pending" else [],
        )
        session.add(pr)
        await session.flush()
        session.add(
            PRLine(
                pr_id=pr.id,
                catalog_item_id=items[idx].id,
                description=items[idx].name,
                quantity=Decimal("10"),
                unit_of_measure=items[idx].unit_of_measure,
                estimated_unit_price=Decimal("100") + Decimal(idx),
                estimated_total=Decimal("1000") + Decimal(idx) * Decimal("10"),
            )
        )
        prs.append(pr)
    counts["prs"] = len(prs)

    # --- 4 POs across statuses ---
    po_specs = [
        ("draft", 0),
        ("sent", 1),
        ("partial", 2),
        ("closed", 3),
    ]
    pos: list[PurchaseOrder] = []
    # Track each PO's first line locally; the GR loop below needs it, and
    # reading ``po.lines`` (a lazy relationship) under async SQLAlchemy raises
    # MissingGreenlet because the load is not awaited.
    po_first_line: dict[uuid.UUID, POLine] = {}
    for idx, (st, vi) in enumerate(po_specs):
        po = PurchaseOrder(
            number=f"PO-S{idx + 1:04d}",
            vendor_id=vendors[vi].id,
            project_id=project_id,
            status=st,
            currency="EUR",
            subtotal=Decimal("5000"),
            tax=Decimal("950"),
            total=Decimal("5950"),
        )
        session.add(po)
        await session.flush()
        line = POLine(
            po_id=po.id,
            catalog_item_id=items[idx].id,
            description=items[idx].name,
            ordered_qty=Decimal("50"),
            unit_of_measure=items[idx].unit_of_measure,
            unit_price=Decimal("100"),
            line_total=Decimal("5000"),
            received_qty=Decimal("25") if st == "partial" else (Decimal("50") if st == "closed" else Decimal("0")),
        )
        session.add(line)
        await session.flush()
        po_first_line[po.id] = line
        pos.append(po)
    counts["pos"] = len(pos)

    # --- 2 GRs for the "partial" + "closed" POs ---
    grs: list[GoodsReceipt] = []
    for idx, target_po in enumerate(pos[2:4]):
        gr = GoodsReceipt(
            number=f"GR-S{idx + 1:04d}",
            po_id=target_po.id,
            warehouse_id=warehouse.id,
            received_at="2026-05-05T10:00:00+00:00",
            status="posted",
            scan_method="manual",
            photos_json=[],
        )
        session.add(gr)
        await session.flush()
        # Pick the first line of this PO (tracked locally above; ``po.lines``
        # would lazy-load and raise MissingGreenlet under async).
        line = po_first_line.get(target_po.id)
        if line is None:
            continue
        session.add(
            GRLine(
                gr_id=gr.id,
                po_line_id=line.id,
                received_qty=Decimal("25") if idx == 0 else Decimal("50"),
                accepted_qty=Decimal("25") if idx == 0 else Decimal("50"),
                rejected_qty=Decimal("0"),
            )
        )
        grs.append(gr)
    counts["grs"] = len(grs)

    # --- 2 invoices: one matched, one exception ---
    inv_matched = VendorInvoice(
        number="INV-OK-001",
        vendor_id=pos[3].vendor_id,
        po_id=pos[3].id,
        currency="EUR",
        subtotal=Decimal("5000"),
        tax=Decimal("950"),
        total=Decimal("5950"),
        status="approved",
        three_way_match_status="matched",
    )
    session.add(inv_matched)
    inv_exc = VendorInvoice(
        number="INV-EXC-001",
        vendor_id=pos[1].vendor_id,
        po_id=pos[1].id,
        currency="EUR",
        subtotal=Decimal("9000"),
        tax=Decimal("1710"),
        total=Decimal("10710"),
        status="disputed",
        three_way_match_status="exception",
        exception_reason="price variance exceeds tolerance",
    )
    session.add(inv_exc)
    counts["invoices"] = 2

    # --- Stock balances for 20 items ---
    for it in items[:20]:
        sb = StockBalance(
            warehouse_id=warehouse.id,
            catalog_item_id=it.id,
            batch_lot="",
            quantity_on_hand=Decimal("100"),
            quantity_reserved=Decimal("0"),
            unit_cost_avg=Decimal("50"),
        )
        session.add(sb)
        session.add(
            StockMovement(
                warehouse_id=warehouse.id,
                catalog_item_id=it.id,
                movement_type="in",
                quantity=Decimal("100"),
                unit_cost=Decimal("50"),
                reference_type="seed",
            )
        )
    counts["stock_balances"] = 20

    await session.flush()
    logger.info("Supplier catalogs seed inserted: %s", counts)
    return counts
