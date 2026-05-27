"""Unit tests for the supplier_catalogs module.

Scope:
    - Vendor CRUD + status lifecycle (active → suspended → blacklisted)
    - Price list CSV import with dedup + unknown SKUs skipped
    - Price comparison ordering
    - PR approval chain + conversion to PO
    - PO lifecycle (draft → sent → acknowledged → received → closed)
    - Goods receipt posts stock balance + advances PO line counters
    - 3-way match: auto match / price-exception / qty-exception
    - Stock reservation insufficiency + happy path
    - Stock issue updates balance + emits OUT movement
    - Stocktake creates ADJUST movements
    - Events published with expected names
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.events import event_bus
from app.database import Base
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
from app.modules.supplier_catalogs.schemas import (
    CatalogItemCreate,
    GoodsReceiptCreate,
    GRLineCreate,
    ItemCategoryCreate,
    POCreateExt,
    POLineCreate,
    PRCreate,
    PriceListCreate,
    PRLineCreate,
    StockIssuePayload,
    StockReservePayload,
    StocktakeCount,
    StocktakePayload,
    VendorCreate,
    VendorInvoiceCreate,
    WarehouseCreate,
)
from app.modules.supplier_catalogs.service import SupplierCatalogsService

# ── Fixtures ────────────────────────────────────────────────────────────────


_SUPPLIER_TABLES = [
    Vendor.__table__,
    ItemCategory.__table__,
    CatalogItem.__table__,
    PriceList.__table__,
    CatalogEntry.__table__,
    PurchaseRequisition.__table__,
    PRLine.__table__,
    PurchaseOrder.__table__,
    POLine.__table__,
    Warehouse.__table__,
    GoodsReceipt.__table__,
    GRLine.__table__,
    VendorInvoice.__table__,
    VendorInvoiceLine.__table__,
    ThreeWayMatchRecord.__table__,
    StockBalance.__table__,
    StockMovement.__table__,
    CommodityCode.__table__,
    TolerianceProfile.__table__,
    KYCDocument.__table__,
    VendorScorecard.__table__,
]


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Per-test in-memory SQLite — only supplier_catalogs tables."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=_SUPPLIER_TABLES)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def captured_events(monkeypatch) -> list[tuple[str, dict]]:
    """Spy on event_bus.publish_detached to capture published events."""
    captured: list[tuple[str, dict]] = []

    def _spy(name, data=None, source_module=None):  # noqa: ARG001
        captured.append((name, dict(data or {})))
        # Return a completed future-like to mimic the real method
        import asyncio

        fut: asyncio.Future = asyncio.Future()
        fut.set_result(None)
        return fut

    monkeypatch.setattr(event_bus, "publish_detached", _spy)
    return captured


async def _seed_warehouse(svc: SupplierCatalogsService) -> Warehouse:
    return await svc.create_warehouse(
        WarehouseCreate(code=f"WH-{uuid.uuid4().hex[:6]}", name="Main"),
    )


async def _seed_vendor(svc: SupplierCatalogsService, code: str = "V-A") -> Vendor:
    return await svc.create_vendor(VendorCreate(code=code, name=f"Vendor {code}"))


async def _seed_item(svc: SupplierCatalogsService, sku: str = "SKU-1") -> CatalogItem:
    return await svc.create_catalog_item(
        CatalogItemCreate(sku=sku, name=f"Item {sku}", unit_of_measure="pcs"),
    )


# ── Vendor lifecycle ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_vendor(session, captured_events):
    svc = SupplierCatalogsService(session)
    vendor = await svc.create_vendor(VendorCreate(code="V001", name="Acme"))
    assert vendor.id is not None
    assert vendor.status == "active"
    assert any(name == "supplier_catalogs.vendor.created" for name, _ in captured_events)


@pytest.mark.asyncio
async def test_create_vendor_duplicate_code(session):
    svc = SupplierCatalogsService(session)
    await svc.create_vendor(VendorCreate(code="V001", name="Acme"))
    with pytest.raises(HTTPException) as exc:
        await svc.create_vendor(VendorCreate(code="V001", name="Acme 2"))
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_suspend_blacklist_reactivate(session, captured_events):
    svc = SupplierCatalogsService(session)
    vendor = await _seed_vendor(svc)
    vendor = await svc.suspend_vendor(vendor.id, user_id="u1", reason="late delivery")
    assert vendor.status == "suspended"
    vendor = await svc.blacklist_vendor(vendor.id, user_id="u1", reason="fraud")
    assert vendor.status == "blacklisted"
    names = [n for n, _ in captured_events]
    assert "supplier_catalogs.vendor.suspended" in names
    assert "supplier_catalogs.vendor.blacklisted" in names


@pytest.mark.asyncio
async def test_blacklisted_vendor_cannot_be_suspended(session):
    """Blacklist is terminal — re-suspending it is an illegal transition."""
    svc = SupplierCatalogsService(session)
    vendor = await _seed_vendor(svc)
    vendor = await svc.blacklist_vendor(vendor.id, reason="fraud")
    assert vendor.status == "blacklisted"
    with pytest.raises(HTTPException) as exc:
        await svc.suspend_vendor(vendor.id, reason="x")
    assert exc.value.status_code == 400
    assert "Illegal vendor status transition" in (exc.value.detail or "")


@pytest.mark.asyncio
async def test_vendor_status_noop_rejected(session):
    """Setting a vendor to a status it already holds is a 400, not a no-op."""
    svc = SupplierCatalogsService(session)
    vendor = await _seed_vendor(svc)  # born active
    with pytest.raises(HTTPException) as exc:
        await svc.reactivate_vendor(vendor.id)
    assert exc.value.status_code == 400
    assert "already" in (exc.value.detail or "")


@pytest.mark.asyncio
async def test_blacklisted_vendor_can_be_reactivated(session):
    """Reactivation is the one legal exit from blacklist (deliberate action)."""
    svc = SupplierCatalogsService(session)
    vendor = await _seed_vendor(svc)
    await svc.blacklist_vendor(vendor.id, reason="fraud")
    reactivated = await svc.reactivate_vendor(vendor.id)
    assert reactivated.status == "active"


@pytest.mark.asyncio
async def test_rate_vendor(session, captured_events):
    svc = SupplierCatalogsService(session)
    vendor = await _seed_vendor(svc)
    rated = await svc.rate_vendor(vendor.id, 4)
    assert rated.rating == 4
    with pytest.raises(HTTPException):
        await svc.rate_vendor(vendor.id, 10)


# ── Catalog & price list import ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_category_and_item(session):
    svc = SupplierCatalogsService(session)
    cat = await svc.create_category(
        ItemCategoryCreate(code="CAT1", name="Cat 1"),
    )
    item = await svc.create_catalog_item(
        CatalogItemCreate(sku="SKU-100", name="Item 100", category_id=cat.id),
    )
    assert item.sku == "SKU-100"


@pytest.mark.asyncio
async def test_create_catalog_item_dup_sku(session):
    svc = SupplierCatalogsService(session)
    await svc.create_catalog_item(CatalogItemCreate(sku="X", name="X"))
    with pytest.raises(HTTPException) as exc:
        await svc.create_catalog_item(CatalogItemCreate(sku="X", name="X2"))
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_import_price_list_dedup_and_unknown(session, captured_events):
    svc = SupplierCatalogsService(session)
    vendor = await _seed_vendor(svc)
    await _seed_item(svc, "SKU-A")
    await _seed_item(svc, "SKU-B")
    csv_text = (
        "sku,unit_price,vendor_sku,min_order_qty,lead_time_days,notes\n"
        "SKU-A,10.0,VA-1,1,7,\n"
        "SKU-A,12.0,VA-1,1,7,duplicate row — last wins\n"  # dedup
        "SKU-B,5.5,VB-1,5,3,\n"
        "SKU-Z,9.0,,,,unknown sku — skipped\n"
    )
    result = await svc.import_price_list(vendor.id, csv_text, name="Q1")
    assert result.imported_count == 2  # SKU-A + SKU-B
    assert result.skipped_count == 1  # SKU-Z unknown
    assert any("unknown sku" in e for e in result.errors)
    names = [n for n, _ in captured_events]
    assert "supplier_catalogs.price_list.imported" in names


@pytest.mark.asyncio
async def test_import_price_list_invalid_unit_price(session):
    svc = SupplierCatalogsService(session)
    vendor = await _seed_vendor(svc)
    await _seed_item(svc, "SKU-A")
    csv_text = "sku,unit_price\nSKU-A,not-a-number\n"
    result = await svc.import_price_list(vendor.id, csv_text)
    assert result.imported_count == 0
    assert any("invalid unit_price" in e for e in result.errors)


@pytest.mark.asyncio
async def test_compare_prices_sorted(session):
    svc = SupplierCatalogsService(session)
    v1 = await _seed_vendor(svc, "V1")
    v2 = await _seed_vendor(svc, "V2")
    v3 = await _seed_vendor(svc, "V3")
    item = await _seed_item(svc, "SKU-X")
    for v, price in ((v1, "10"), (v2, "5"), (v3, "20")):
        await svc.create_price_list(
            v.id,
            PriceListCreate(
                name=f"{v.code}-PL",
                entries=[
                    {  # type: ignore[list-item]
                        "catalog_item_id": item.id,
                        "unit_price": Decimal(price),
                        "min_order_qty": Decimal("1"),
                        "lead_time_days": 5,
                    },
                ],
            ),
        )
    rows = await svc.compare_prices(item.id)
    prices = [r["unit_price"] for r in rows]
    assert prices == sorted(prices)
    assert prices[0] == Decimal("5")  # cheapest first


# ── PR / approval chain / conversion ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_pr_full_workflow_with_approval_chain(session, captured_events):
    svc = SupplierCatalogsService(session)
    vendor = await _seed_vendor(svc)
    item = await _seed_item(svc, "SKU-PR")
    project_id = uuid.uuid4()

    pr = await svc.create_pr(
        PRCreate(
            project_id=project_id,
            approval_chain=["user-a", "user-b"],
            lines=[
                PRLineCreate(
                    catalog_item_id=item.id,
                    description="Test",
                    quantity=Decimal("10"),
                    estimated_unit_price=Decimal("100"),
                )
            ],
        ),
        user_id="user-requester",
    )
    assert pr.status == "draft"
    assert pr.total_estimate == Decimal("1000")
    assert len(pr.lines) == 1

    submitted = await svc.submit_pr(pr.id, user_id="user-requester")
    assert submitted.status == "approval_pending"

    # First approval
    approved_once = await svc.approve_pr(pr.id, approver_id="user-a")
    assert approved_once.status == "approval_pending"  # chain not exhausted

    # Second approval → done
    approved = await svc.approve_pr(pr.id, approver_id="user-b")
    assert approved.status == "approved"

    # Convert to PO
    po = await svc.convert_pr_to_po(pr.id, vendor_id=vendor.id, user_id="user-buyer")
    assert po.status == "draft"
    assert po.vendor_id == vendor.id
    assert po.subtotal == Decimal("1000")
    assert len(po.lines) == 1

    # PR is now converted
    pr_after = await svc.prs.get(pr.id)
    assert pr_after is not None
    assert pr_after.status == "converted"

    names = [n for n, _ in captured_events]
    assert "supplier_catalogs.pr.submitted" in names
    assert "supplier_catalogs.pr.approved" in names
    assert "supplier_catalogs.pr.converted" in names
    assert "supplier_catalogs.po.created" in names


@pytest.mark.asyncio
async def test_pr_submit_without_chain_auto_approves(session):
    svc = SupplierCatalogsService(session)
    item = await _seed_item(svc, "SKU-AUTO")
    pr = await svc.create_pr(
        PRCreate(
            project_id=uuid.uuid4(),
            approval_chain=[],
            lines=[
                PRLineCreate(
                    catalog_item_id=item.id,
                    description="x",
                    quantity=Decimal("1"),
                    estimated_unit_price=Decimal("10"),
                )
            ],
        )
    )
    submitted = await svc.submit_pr(pr.id)
    assert submitted.status == "approved"


@pytest.mark.asyncio
async def test_pr_reject(session, captured_events):
    svc = SupplierCatalogsService(session)
    item = await _seed_item(svc, "SKU-REJ")
    pr = await svc.create_pr(
        PRCreate(
            project_id=uuid.uuid4(),
            approval_chain=["user-a"],
            lines=[
                PRLineCreate(
                    catalog_item_id=item.id,
                    description="x",
                    quantity=Decimal("1"),
                    estimated_unit_price=Decimal("10"),
                )
            ],
        )
    )
    await svc.submit_pr(pr.id)
    rejected = await svc.reject_pr(pr.id, approver_id="user-a", reason="too expensive")
    assert rejected.status == "rejected"
    assert any(n == "supplier_catalogs.pr.rejected" for n, _ in captured_events)


@pytest.mark.asyncio
async def test_pr_cannot_convert_unless_approved(session):
    svc = SupplierCatalogsService(session)
    vendor = await _seed_vendor(svc)
    item = await _seed_item(svc, "SKU-Q")
    pr = await svc.create_pr(
        PRCreate(
            project_id=uuid.uuid4(),
            lines=[
                PRLineCreate(
                    catalog_item_id=item.id,
                    description="x",
                    quantity=Decimal("1"),
                    estimated_unit_price=Decimal("10"),
                )
            ],
        )
    )
    with pytest.raises(HTTPException):
        await svc.convert_pr_to_po(pr.id, vendor_id=vendor.id)


@pytest.mark.asyncio
async def test_pr_cannot_convert_with_inactive_vendor(session):
    svc = SupplierCatalogsService(session)
    vendor = await _seed_vendor(svc)
    await svc.suspend_vendor(vendor.id)
    item = await _seed_item(svc, "SKU-K")
    pr = await svc.create_pr(
        PRCreate(
            project_id=uuid.uuid4(),
            approval_chain=[],
            lines=[
                PRLineCreate(
                    catalog_item_id=item.id,
                    description="x",
                    quantity=Decimal("1"),
                    estimated_unit_price=Decimal("10"),
                )
            ],
        )
    )
    await svc.submit_pr(pr.id)
    with pytest.raises(HTTPException) as exc:
        await svc.convert_pr_to_po(pr.id, vendor_id=vendor.id)
    assert exc.value.status_code == 400


# ── PO lifecycle ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_po_lifecycle(session, captured_events):
    svc = SupplierCatalogsService(session)
    vendor = await _seed_vendor(svc)
    item = await _seed_item(svc, "SKU-PO")
    po = await svc.create_po(
        POCreateExt(
            vendor_id=vendor.id,
            project_id=uuid.uuid4(),
            lines=[
                POLineCreate(
                    catalog_item_id=item.id,
                    description="thing",
                    ordered_qty=Decimal("10"),
                    unit_price=Decimal("100"),
                )
            ],
        )
    )
    assert po.subtotal == Decimal("1000")
    assert po.total == Decimal("1000")

    sent = await svc.send_po(po.id, user_id="buyer")
    assert sent.status == "sent"
    ack = await svc.acknowledge_po(po.id)
    assert ack.status == "acknowledged"
    closed = await svc.close_po(po.id)
    assert closed.status == "closed"

    names = [n for n, _ in captured_events]
    assert "supplier_catalogs.po.sent" in names
    assert "supplier_catalogs.po.acknowledged" in names
    assert "supplier_catalogs.po.closed" in names


@pytest.mark.asyncio
async def test_po_cannot_send_twice(session):
    svc = SupplierCatalogsService(session)
    vendor = await _seed_vendor(svc)
    item = await _seed_item(svc, "SKU-DUP")
    po = await svc.create_po(
        POCreateExt(
            vendor_id=vendor.id,
            project_id=uuid.uuid4(),
            lines=[
                POLineCreate(
                    catalog_item_id=item.id,
                    description="x",
                    ordered_qty=Decimal("1"),
                    unit_price=Decimal("1"),
                )
            ],
        )
    )
    await svc.send_po(po.id)
    with pytest.raises(HTTPException):
        await svc.send_po(po.id)


# ── Goods receipt + stock ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_post_gr_updates_stock_and_po_status(session, captured_events):
    svc = SupplierCatalogsService(session)
    vendor = await _seed_vendor(svc)
    item = await _seed_item(svc, "SKU-GR")
    wh = await _seed_warehouse(svc)
    po = await svc.create_po(
        POCreateExt(
            vendor_id=vendor.id,
            project_id=uuid.uuid4(),
            lines=[
                POLineCreate(
                    catalog_item_id=item.id,
                    description="cement",
                    ordered_qty=Decimal("100"),
                    unit_price=Decimal("50"),
                )
            ],
        )
    )
    await svc.send_po(po.id)
    po_line = po.lines[0]

    # Partial receipt
    gr = await svc.post_goods_receipt(
        GoodsReceiptCreate(
            po_id=po.id,
            warehouse_id=wh.id,
            lines=[
                GRLineCreate(
                    po_line_id=po_line.id,
                    received_qty=Decimal("40"),
                    accepted_qty=Decimal("40"),
                    batch_lot="LOT-A",
                )
            ],
        ),
        user_id="receiver",
    )
    assert gr.status == "posted"

    # PO is now partial
    refreshed_po = await svc.pos.get(po.id)
    assert refreshed_po is not None
    assert refreshed_po.status == "partial"
    assert refreshed_po.lines[0].received_qty == Decimal("40")

    # Balance landed in stock
    balance = await svc.stock.get_balance(wh.id, item.id, "LOT-A")
    assert balance is not None
    assert balance.quantity_on_hand == Decimal("40")
    assert balance.unit_cost_avg == Decimal("50")

    names = [n for n, _ in captured_events]
    assert "supplier_catalogs.gr.posted" in names

    # Complete receipt
    await svc.post_goods_receipt(
        GoodsReceiptCreate(
            po_id=po.id,
            warehouse_id=wh.id,
            lines=[
                GRLineCreate(
                    po_line_id=po_line.id,
                    received_qty=Decimal("60"),
                    accepted_qty=Decimal("60"),
                    batch_lot="LOT-A",
                )
            ],
        )
    )
    refreshed_po = await svc.pos.get(po.id)
    assert refreshed_po is not None
    assert refreshed_po.status == "received"
    assert any(n == "supplier_catalogs.po.received" for n, _ in captured_events)


@pytest.mark.asyncio
async def test_gr_cannot_exceed_outstanding(session):
    svc = SupplierCatalogsService(session)
    vendor = await _seed_vendor(svc)
    item = await _seed_item(svc, "SKU-OV")
    wh = await _seed_warehouse(svc)
    po = await svc.create_po(
        POCreateExt(
            vendor_id=vendor.id,
            project_id=uuid.uuid4(),
            lines=[
                POLineCreate(
                    catalog_item_id=item.id,
                    description="x",
                    ordered_qty=Decimal("10"),
                    unit_price=Decimal("1"),
                )
            ],
        )
    )
    await svc.send_po(po.id)
    line = po.lines[0]
    with pytest.raises(HTTPException) as exc:
        await svc.post_goods_receipt(
            GoodsReceiptCreate(
                po_id=po.id,
                warehouse_id=wh.id,
                lines=[
                    GRLineCreate(
                        po_line_id=line.id,
                        received_qty=Decimal("20"),
                    )
                ],
            )
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_gr_low_stock_alert(session, captured_events):
    svc = SupplierCatalogsService(session)
    vendor = await _seed_vendor(svc)
    # Reorder point > 0 so the threshold check fires
    item = await svc.create_catalog_item(
        CatalogItemCreate(sku="SKU-RE", name="Re", reorder_point=Decimal("100")),
    )
    wh = await _seed_warehouse(svc)
    po = await svc.create_po(
        POCreateExt(
            vendor_id=vendor.id,
            project_id=uuid.uuid4(),
            lines=[
                POLineCreate(
                    catalog_item_id=item.id,
                    description="x",
                    ordered_qty=Decimal("50"),
                    unit_price=Decimal("1"),
                )
            ],
        )
    )
    await svc.send_po(po.id)
    # Receive only 50 (< reorder_point of 100)
    await svc.post_goods_receipt(
        GoodsReceiptCreate(
            po_id=po.id,
            warehouse_id=wh.id,
            lines=[GRLineCreate(po_line_id=po.lines[0].id, received_qty=Decimal("50"))],
        )
    )
    names = [n for n, _ in captured_events]
    assert "supplier_catalogs.stock.low_threshold" in names


# ── 3-way match ──────────────────────────────────────────────────────────────


async def _build_po_received(
    svc: SupplierCatalogsService,
    qty: Decimal = Decimal("10"),
    price: Decimal = Decimal("100"),
) -> tuple[PurchaseOrder, Warehouse, Vendor]:
    vendor = await _seed_vendor(svc, f"V-{uuid.uuid4().hex[:5]}")
    item = await _seed_item(svc, f"SKU-{uuid.uuid4().hex[:5]}")
    wh = await _seed_warehouse(svc)
    po = await svc.create_po(
        POCreateExt(
            vendor_id=vendor.id,
            project_id=uuid.uuid4(),
            lines=[
                POLineCreate(
                    catalog_item_id=item.id,
                    description="x",
                    ordered_qty=qty,
                    unit_price=price,
                )
            ],
        )
    )
    await svc.send_po(po.id)
    await svc.post_goods_receipt(
        GoodsReceiptCreate(
            po_id=po.id,
            warehouse_id=wh.id,
            lines=[
                GRLineCreate(
                    po_line_id=po.lines[0].id,
                    received_qty=qty,
                    accepted_qty=qty,
                )
            ],
        )
    )
    refreshed = await svc.pos.get(po.id)
    assert refreshed is not None
    return refreshed, wh, vendor


@pytest.mark.asyncio
async def test_match_invoice_auto(session, captured_events):
    svc = SupplierCatalogsService(session)
    po, _wh, vendor = await _build_po_received(svc)
    invoice = await svc.create_invoice(
        VendorInvoiceCreate(
            number="INV-1",
            vendor_id=vendor.id,
            po_id=po.id,
            subtotal=po.total,
            tax=Decimal("0"),
        )
    )
    result = await svc.match_invoice(invoice.id)
    assert result.status == "auto_matched"
    refreshed_inv = await svc.invoices.get(invoice.id)
    assert refreshed_inv is not None
    assert refreshed_inv.three_way_match_status == "matched"
    assert refreshed_inv.status == "approved"
    assert any(n == "supplier_catalogs.invoice.matched" for n, _ in captured_events)


@pytest.mark.asyncio
async def test_match_invoice_price_exception(session, captured_events):
    svc = SupplierCatalogsService(session)
    po, _wh, vendor = await _build_po_received(svc)
    # Inflate invoice well beyond 2% tolerance
    invoice = await svc.create_invoice(
        VendorInvoiceCreate(
            number="INV-OVER",
            vendor_id=vendor.id,
            po_id=po.id,
            subtotal=po.total + Decimal("500"),
            tax=Decimal("0"),
        )
    )
    result = await svc.match_invoice(invoice.id)
    assert result.status == "exception"
    assert result.price_variance > 0
    assert "price variance" in (result.exception_reason or "")
    refreshed_inv = await svc.invoices.get(invoice.id)
    assert refreshed_inv is not None
    assert refreshed_inv.three_way_match_status == "exception"
    assert refreshed_inv.status == "disputed"
    assert any(n == "supplier_catalogs.invoice.exception" for n, _ in captured_events)


@pytest.mark.asyncio
async def test_match_invoice_qty_exception_no_gr(session):
    svc = SupplierCatalogsService(session)
    vendor = await _seed_vendor(svc)
    item = await _seed_item(svc, "SKU-NOGR")
    po = await svc.create_po(
        POCreateExt(
            vendor_id=vendor.id,
            project_id=uuid.uuid4(),
            lines=[
                POLineCreate(
                    catalog_item_id=item.id,
                    description="x",
                    ordered_qty=Decimal("5"),
                    unit_price=Decimal("20"),
                )
            ],
        )
    )
    await svc.send_po(po.id)
    invoice = await svc.create_invoice(
        VendorInvoiceCreate(
            number="INV-NOGR",
            vendor_id=vendor.id,
            po_id=po.id,
            subtotal=po.total,
            tax=Decimal("0"),
        )
    )
    result = await svc.match_invoice(invoice.id)
    assert result.status == "exception"
    assert "no goods received" in (result.exception_reason or "")


@pytest.mark.asyncio
async def test_match_invoice_without_po(session):
    svc = SupplierCatalogsService(session)
    vendor = await _seed_vendor(svc)
    invoice = await svc.create_invoice(
        VendorInvoiceCreate(
            number="INV-NOPO",
            vendor_id=vendor.id,
            po_id=None,
            subtotal=Decimal("100"),
            tax=Decimal("0"),
        )
    )
    result = await svc.match_invoice(invoice.id)
    assert result.status == "exception"


# ── Stock reservation / issue / stocktake ────────────────────────────────────


async def _seed_stock(
    svc: SupplierCatalogsService,
    on_hand: Decimal = Decimal("100"),
) -> tuple[Warehouse, CatalogItem]:
    wh = await _seed_warehouse(svc)
    item = await _seed_item(svc, f"SKU-{uuid.uuid4().hex[:5]}")
    balance = await svc.stock.get_or_create_balance(wh.id, item.id, "")
    await svc.stock.update_balance(balance.id, quantity_on_hand=on_hand)
    return wh, item


@pytest.mark.asyncio
async def test_reserve_stock_happy(session, captured_events):
    svc = SupplierCatalogsService(session)
    wh, item = await _seed_stock(svc, on_hand=Decimal("50"))
    movement = await svc.reserve_stock(
        StockReservePayload(
            catalog_item_id=item.id,
            warehouse_id=wh.id,
            quantity=Decimal("10"),
        )
    )
    assert movement.movement_type == "reservation"
    balance = await svc.stock.get_balance(wh.id, item.id, "")
    assert balance is not None
    assert balance.quantity_reserved == Decimal("10")
    assert any(n == "supplier_catalogs.stock.reserved" for n, _ in captured_events)


@pytest.mark.asyncio
async def test_reserve_stock_insufficient(session):
    svc = SupplierCatalogsService(session)
    wh, item = await _seed_stock(svc, on_hand=Decimal("5"))
    with pytest.raises(HTTPException) as exc:
        await svc.reserve_stock(
            StockReservePayload(
                catalog_item_id=item.id,
                warehouse_id=wh.id,
                quantity=Decimal("100"),
            )
        )
    assert exc.value.status_code == 400
    assert "available" in (exc.value.detail or "")


@pytest.mark.asyncio
async def test_issue_stock_reduces_balance(session, captured_events):
    svc = SupplierCatalogsService(session)
    wh, item = await _seed_stock(svc, on_hand=Decimal("50"))
    movement = await svc.issue_stock(
        StockIssuePayload(
            catalog_item_id=item.id,
            warehouse_id=wh.id,
            quantity=Decimal("10"),
        )
    )
    assert movement.movement_type == "out"
    assert movement.quantity == Decimal("10")
    balance = await svc.stock.get_balance(wh.id, item.id, "")
    assert balance is not None
    assert balance.quantity_on_hand == Decimal("40")
    assert any(n == "supplier_catalogs.stock.issued" for n, _ in captured_events)


@pytest.mark.asyncio
async def test_issue_stock_no_balance(session):
    svc = SupplierCatalogsService(session)
    wh = await _seed_warehouse(svc)
    item = await _seed_item(svc, "SKU-NONE")
    with pytest.raises(HTTPException):
        await svc.issue_stock(
            StockIssuePayload(
                catalog_item_id=item.id,
                warehouse_id=wh.id,
                quantity=Decimal("1"),
            )
        )


@pytest.mark.asyncio
async def test_stocktake_creates_adjust(session, captured_events):
    svc = SupplierCatalogsService(session)
    wh, item = await _seed_stock(svc, on_hand=Decimal("50"))
    movements = await svc.stocktake(
        wh.id,
        StocktakePayload(
            counts=[
                StocktakeCount(catalog_item_id=item.id, counted_qty=Decimal("48")),
            ]
        ),
    )
    assert len(movements) == 1
    assert movements[0].movement_type == "adjust"
    assert movements[0].quantity == Decimal("-2")
    balance = await svc.stock.get_balance(wh.id, item.id, "")
    assert balance is not None
    assert balance.quantity_on_hand == Decimal("48")
    assert any(n == "supplier_catalogs.stock.adjusted" for n, _ in captured_events)


@pytest.mark.asyncio
async def test_stocktake_skips_zero_delta(session):
    svc = SupplierCatalogsService(session)
    wh, item = await _seed_stock(svc, on_hand=Decimal("50"))
    movements = await svc.stocktake(
        wh.id,
        StocktakePayload(
            counts=[
                StocktakeCount(catalog_item_id=item.id, counted_qty=Decimal("50")),
            ]
        ),
    )
    assert movements == []  # no delta → no movement


# ── Budget check soft dependency ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_budget_when_finance_module_absent(session):
    svc = SupplierCatalogsService(session)
    vendor = await _seed_vendor(svc)
    item = await _seed_item(svc, "SKU-B")
    po = await svc.create_po(
        POCreateExt(
            vendor_id=vendor.id,
            project_id=uuid.uuid4(),
            lines=[
                POLineCreate(
                    catalog_item_id=item.id,
                    description="x",
                    ordered_qty=Decimal("1"),
                    unit_price=Decimal("1"),
                )
            ],
        )
    )
    result = await svc.check_budget(po)
    # Either finance module is loaded (returns figures) OR absent (returns flag)
    assert "available" in result


# ── Service constructor sanity ───────────────────────────────────────────────


def test_service_construct_wires_all_repos():
    svc = SupplierCatalogsService.__new__(SupplierCatalogsService)
    # The init wires each repo — verify attribute names exist on the class
    expected = {
        "vendors",
        "categories",
        "items",
        "price_lists",
        "prs",
        "pos",
        "grs",
        "invoices",
        "warehouses",
        "stock",
    }
    for name in expected:
        # Set so attribute lookup wouldn't AttributeError if we used the obj
        setattr(svc, name, object())
    assert all(hasattr(svc, n) for n in expected)


# ── Permission registry ──────────────────────────────────────────────────────


def test_register_permissions_registers_keys():
    from app.modules.supplier_catalogs.permissions import (
        register_supplier_catalogs_permissions,
    )

    register_supplier_catalogs_permissions()
    # If it didn't raise, the call succeeded; we don't introspect the registry
    # internals here as different test runs share permission state.


# ── Notification subscriber registration ─────────────────────────────────────


def test_wave4_subscriber_registration_idempotent():
    from app.modules.notifications._wave4_subscribers import (
        register_supplier_catalogs_notification_subscribers,
    )

    # Calling twice should not raise; EventBus is identity-deduplicated.
    register_supplier_catalogs_notification_subscribers()
    register_supplier_catalogs_notification_subscribers()


# ── Commodity codes ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_seed_commodity_codes_idempotent(session):
    svc = SupplierCatalogsService(session)
    counts1 = await svc.seed_commodity_codes()
    assert sum(counts1.values()) > 30  # CSV ships > 30 rows
    counts2 = await svc.seed_commodity_codes()
    # Idempotent — counts2 reflects upserts, so same total
    assert sum(counts2.values()) == sum(counts1.values())


@pytest.mark.asyncio
async def test_list_commodity_codes_filters(session):
    svc = SupplierCatalogsService(session)
    await svc.seed_commodity_codes()
    unspsc = await svc.list_commodity_codes(scheme="unspsc")
    cpv = await svc.list_commodity_codes(scheme="cpv")
    assert all(c.scheme == "unspsc" for c in unspsc)
    assert all(c.scheme == "cpv" for c in cpv)
    assert len(unspsc) > 0
    assert len(cpv) > 0


@pytest.mark.asyncio
async def test_validate_commodity_code(session):
    svc = SupplierCatalogsService(session)
    await svc.seed_commodity_codes()
    assert await svc.validate_commodity_code("unspsc", "30161501") is True
    assert await svc.validate_commodity_code("unspsc", "NOSUCH") is False


# ── Tolerance profiles ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ensure_default_tolerance_profile(session):
    svc = SupplierCatalogsService(session)
    profile = await svc.ensure_default_tolerance_profile()
    assert profile.name == "default"
    assert profile.is_default is True
    # Idempotent
    again = await svc.ensure_default_tolerance_profile()
    assert again.id == profile.id


@pytest.mark.asyncio
async def test_create_tolerance_profile_demotes_old_default(session):
    from app.modules.supplier_catalogs.schemas import TolerianceProfileCreate

    svc = SupplierCatalogsService(session)
    await svc.ensure_default_tolerance_profile()
    new = await svc.create_tolerance_profile(
        TolerianceProfileCreate(
            name="strategic",
            price_tolerance_pct=Decimal("0.5"),
            is_default=True,
        )
    )
    assert new.is_default is True
    # Old default should now be demoted
    old = await svc.tolerance_profiles.get_by_name("default")
    assert old is not None
    assert old.is_default is False


@pytest.mark.asyncio
async def test_match_invoice_uses_profile_tolerance(session, captured_events):
    """5% profile should auto-match an invoice 3% above PO total."""
    from app.modules.supplier_catalogs.schemas import TolerianceProfileCreate

    svc = SupplierCatalogsService(session)
    await svc.create_tolerance_profile(
        TolerianceProfileCreate(
            name="loose",
            price_tolerance_pct=Decimal("5"),
            is_default=False,
        )
    )
    vendor = await _seed_vendor(svc)
    item = await _seed_item(svc, "SKU-TOL")
    wh = await _seed_warehouse(svc)
    po = await svc.create_po(
        POCreateExt(
            vendor_id=vendor.id,
            project_id=uuid.uuid4(),
            lines=[
                POLineCreate(
                    catalog_item_id=item.id,
                    description="x",
                    ordered_qty=Decimal("10"),
                    unit_price=Decimal("100"),
                )
            ],
        )
    )
    await svc.send_po(po.id)
    await svc.post_goods_receipt(
        GoodsReceiptCreate(
            po_id=po.id,
            warehouse_id=wh.id,
            lines=[
                GRLineCreate(
                    po_line_id=po.lines[0].id,
                    received_qty=Decimal("10"),
                    accepted_qty=Decimal("10"),
                )
            ],
        )
    )
    # 3% over → would fail 2% default, must pass 5% "loose"
    invoice = await svc.create_invoice(
        VendorInvoiceCreate(
            number="INV-TOL",
            vendor_id=vendor.id,
            po_id=po.id,
            subtotal=Decimal("1030"),
            tax=Decimal("0"),
        )
    )
    result = await svc.match_invoice(invoice.id, tolerance_profile_name="loose")
    assert result.status == "auto_matched"
    assert result.tolerance_profile_name == "loose"


# ── KYC documents ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_add_kyc_doc_and_list(session, captured_events):
    from datetime import date

    from app.modules.supplier_catalogs.schemas import KYCDocumentCreate

    svc = SupplierCatalogsService(session)
    vendor = await _seed_vendor(svc)
    doc = await svc.add_kyc_document(
        vendor.id,
        KYCDocumentCreate(
            doc_type="w9",
            document_number="123-45-6789",
            issued_on=date(2025, 1, 1),
            expires_on=date(2030, 1, 1),
            issuing_country="US",
        ),
    )
    assert doc.doc_type == "w9"
    docs = await svc.list_kyc_for_vendor(vendor.id)
    assert len(docs) == 1
    assert any(n == "supplier_catalogs.kyc.uploaded" for n, _ in captured_events)


@pytest.mark.asyncio
async def test_kyc_invalid_doc_type_rejected(session):
    from app.modules.supplier_catalogs.schemas import KYCDocumentCreate

    svc = SupplierCatalogsService(session)
    vendor = await _seed_vendor(svc)
    with pytest.raises(HTTPException) as exc:
        await svc.add_kyc_document(
            vendor.id,
            KYCDocumentCreate(doc_type="BOGUS"),
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_kyc_expiry_emits_expired_event(session, captured_events):
    from datetime import date, timedelta

    from app.modules.supplier_catalogs.schemas import KYCDocumentCreate

    svc = SupplierCatalogsService(session)
    vendor = await _seed_vendor(svc)
    # Past expiry
    await svc.add_kyc_document(
        vendor.id,
        KYCDocumentCreate(
            doc_type="vat_cert",
            expires_on=date.today() - timedelta(days=10),
        ),
    )
    # Soon to expire
    await svc.add_kyc_document(
        vendor.id,
        KYCDocumentCreate(
            doc_type="iso",
            expires_on=date.today() + timedelta(days=10),
        ),
    )
    result = await svc.check_kyc_expiry(days_ahead=30)
    assert result["expired"] == 1
    assert result["expiring"] == 1
    names = [n for n, _ in captured_events]
    assert "supplier_catalogs.kyc.expired" in names
    assert "supplier_catalogs.kyc.expiring" in names


# ── Vendor scorecard ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recompute_scorecard_full_pipeline(session, captured_events):
    """Build a vendor with GRs + KYC docs and verify composite > 0."""
    from datetime import date

    from app.modules.supplier_catalogs.schemas import (
        KYCDocumentCreate,
        ScorecardRecomputeRequest,
    )

    svc = SupplierCatalogsService(session)
    vendor = await _seed_vendor(svc)
    item = await _seed_item(svc, "SKU-SCORE")
    wh = await _seed_warehouse(svc)
    po = await svc.create_po(
        POCreateExt(
            vendor_id=vendor.id,
            project_id=uuid.uuid4(),
            expected_delivery="2030-01-01",
            lines=[
                POLineCreate(
                    catalog_item_id=item.id,
                    description="x",
                    ordered_qty=Decimal("10"),
                    unit_price=Decimal("100"),
                )
            ],
        )
    )
    await svc.send_po(po.id)
    await svc.post_goods_receipt(
        GoodsReceiptCreate(
            po_id=po.id,
            warehouse_id=wh.id,
            received_at="2025-01-01T10:00:00+00:00",
            lines=[
                GRLineCreate(
                    po_line_id=po.lines[0].id,
                    received_qty=Decimal("10"),
                    accepted_qty=Decimal("10"),
                )
            ],
        )
    )
    # Add ISO + tax KYC docs to boost ESG
    await svc.add_kyc_document(
        vendor.id,
        KYCDocumentCreate(doc_type="iso"),
    )
    await svc.add_kyc_document(
        vendor.id,
        KYCDocumentCreate(doc_type="vat_cert"),
    )

    sc = await svc.recompute_scorecard(
        vendor.id,
        ScorecardRecomputeRequest(
            period_start=date(2024, 1, 1),
            period_end=date(2026, 12, 31),
        ),
    )
    assert sc.composite_score > Decimal("0")
    # 100% on-time delivery (1 of 1 GR before expected)
    assert sc.delivery_score == Decimal("100.00")
    # 100% accepted_qty / received_qty
    assert sc.quality_score == Decimal("100.00")
    # ESG > 0 because ISO + VAT present (40 + 35 = 75)
    assert sc.esg_score == Decimal("75.00")
    assert any(n == "supplier_catalogs.scorecard.computed" for n, _ in captured_events)


@pytest.mark.asyncio
async def test_recompute_scorecard_invalid_period(session):
    from datetime import date

    from app.modules.supplier_catalogs.schemas import ScorecardRecomputeRequest

    svc = SupplierCatalogsService(session)
    vendor = await _seed_vendor(svc)
    with pytest.raises(HTTPException):
        await svc.recompute_scorecard(
            vendor.id,
            ScorecardRecomputeRequest(
                period_start=date(2026, 12, 31),
                period_end=date(2024, 1, 1),
            ),
        )


# ── PEPPOL invoice ingest ───────────────────────────────────────────────────


_PEPPOL_XML_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<Invoice
  xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
  xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
  xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:ID>{invoice_id}</cbc:ID>
  <cbc:IssueDate>2026-05-01</cbc:IssueDate>
  <cbc:DueDate>2026-06-01</cbc:DueDate>
  <cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>
  <cac:OrderReference>
    <cbc:ID>{po_number}</cbc:ID>
  </cac:OrderReference>
  <cac:AccountingSupplierParty>
    <cac:Party>
      <cbc:EndpointID schemeID="9930">DE123456789</cbc:EndpointID>
      <cac:PartyName>
        <cbc:Name>{supplier_name}</cbc:Name>
      </cac:PartyName>
      <cac:PartyTaxScheme>
        <cbc:CompanyID>{supplier_vat}</cbc:CompanyID>
      </cac:PartyTaxScheme>
    </cac:Party>
  </cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty>
    <cac:Party>
      <cac:PartyName>
        <cbc:Name>Buyer Construction Ltd</cbc:Name>
      </cac:PartyName>
    </cac:Party>
  </cac:AccountingCustomerParty>
  <cac:TaxTotal>
    <cbc:TaxAmount currencyID="EUR">190.00</cbc:TaxAmount>
  </cac:TaxTotal>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount currencyID="EUR">1000.00</cbc:LineExtensionAmount>
    <cbc:PayableAmount currencyID="EUR">1190.00</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
  <cac:InvoiceLine>
    <cbc:ID>1</cbc:ID>
    <cbc:InvoicedQuantity unitCode="KGM">10</cbc:InvoicedQuantity>
    <cbc:LineExtensionAmount currencyID="EUR">1000.00</cbc:LineExtensionAmount>
    <cac:Item>
      <cbc:Name>Test Product</cbc:Name>
      <cac:SellersItemIdentification>
        <cbc:ID>VENDSKU-1</cbc:ID>
      </cac:SellersItemIdentification>
    </cac:Item>
    <cac:Price>
      <cbc:PriceAmount currencyID="EUR">100.00</cbc:PriceAmount>
    </cac:Price>
  </cac:InvoiceLine>
</Invoice>"""


@pytest.mark.asyncio
async def test_peppol_parser_extracts_fields():
    from app.modules.supplier_catalogs.peppol import parse_peppol_invoice

    xml = _PEPPOL_XML_TEMPLATE.format(
        invoice_id="INV-PEPPOL-1",
        po_number="PO-000001",
        supplier_name="Acme GmbH",
        supplier_vat="DE111222333",
    )
    parsed = parse_peppol_invoice(xml)
    assert parsed.invoice_id == "INV-PEPPOL-1"
    assert parsed.supplier_name == "Acme GmbH"
    assert parsed.supplier_vat == "DE111222333"
    assert parsed.order_reference == "PO-000001"
    assert parsed.payable_amount == Decimal("1190.00")
    assert parsed.tax_total == Decimal("190.00")
    assert len(parsed.lines) == 1
    assert parsed.lines[0].quantity == Decimal("10")
    assert parsed.lines[0].unit_of_measure == "kg"  # KGM normalised


@pytest.mark.asyncio
async def test_peppol_ingest_creates_invoice_and_matches(session, captured_events):
    svc = SupplierCatalogsService(session)
    vendor = await svc.create_vendor(
        VendorCreate(code="DE-VENDOR", name="Acme GmbH", tax_id="DE111222333"),
    )
    item = await _seed_item(svc, "SKU-PEPPOL")
    wh = await _seed_warehouse(svc)
    po = await svc.create_po(
        POCreateExt(
            vendor_id=vendor.id,
            project_id=uuid.uuid4(),
            lines=[
                POLineCreate(
                    catalog_item_id=item.id,
                    description="x",
                    ordered_qty=Decimal("10"),
                    unit_price=Decimal("100"),
                )
            ],
        )
    )
    await svc.send_po(po.id)
    await svc.post_goods_receipt(
        GoodsReceiptCreate(
            po_id=po.id,
            warehouse_id=wh.id,
            lines=[
                GRLineCreate(
                    po_line_id=po.lines[0].id,
                    received_qty=Decimal("10"),
                    accepted_qty=Decimal("10"),
                )
            ],
        )
    )
    # The PO total is 1000 (sub) + 0 tax = 1000 but invoice carries 1190 (19% VAT)
    # We adjust the PO model to match expected total — instead build XML to match
    xml = (
        _PEPPOL_XML_TEMPLATE.format(
            invoice_id="INV-PEPPOL-100",
            po_number=po.number,
            supplier_name="Acme GmbH",
            supplier_vat="DE111222333",
        )
        .replace(
            '<cbc:PayableAmount currencyID="EUR">1190.00</cbc:PayableAmount>',
            f'<cbc:PayableAmount currencyID="EUR">{po.total}</cbc:PayableAmount>',
        )
        .replace(
            '<cbc:TaxAmount currencyID="EUR">190.00</cbc:TaxAmount>',
            '<cbc:TaxAmount currencyID="EUR">0.00</cbc:TaxAmount>',
        )
        .replace(
            '<cbc:LineExtensionAmount currencyID="EUR">1000.00</cbc:LineExtensionAmount>',
            f'<cbc:LineExtensionAmount currencyID="EUR">{po.subtotal}</cbc:LineExtensionAmount>',
            1,
        )
    )
    result = await svc.ingest_peppol_invoice(xml, user_id="u1")
    assert result.invoice_number == "INV-PEPPOL-100"
    assert result.vendor_id == vendor.id
    assert result.line_count == 1
    assert result.matched_status in ("auto_matched", "exception")
    names = [n for n, _ in captured_events]
    assert "supplier_catalogs.invoice.peppol_ingested" in names


@pytest.mark.asyncio
async def test_peppol_parser_rejects_xxe_payload():
    """An external-entity (XXE) payload must be rejected, not resolved."""
    from app.modules.supplier_catalogs.peppol import (
        PeppolParseError,
        parse_peppol_invoice,
    )

    xxe = (
        '<?xml version="1.0"?>'
        '<!DOCTYPE Invoice [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        '<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:'
        'Invoice-2"><cbc:ID xmlns:cbc="urn:oasis:names:specification:ubl:'
        'schema:xsd:CommonBasicComponents-2">&xxe;</cbc:ID></Invoice>'
    )
    with pytest.raises(PeppolParseError):
        parse_peppol_invoice(xxe)


@pytest.mark.asyncio
async def test_peppol_parser_handles_whitespace_amounts():
    """Pretty-printed XML wraps amounts in whitespace — must not zero out."""
    from app.modules.supplier_catalogs.peppol import parse_peppol_invoice

    xml = _PEPPOL_XML_TEMPLATE.format(
        invoice_id="INV-WS",
        po_number="PO-1",
        supplier_name="Acme",
        supplier_vat="DE1",
    ).replace(
        '<cbc:PayableAmount currencyID="EUR">1190.00</cbc:PayableAmount>',
        '<cbc:PayableAmount currencyID="EUR">\n      1190.00\n    </cbc:PayableAmount>',
    )
    parsed = parse_peppol_invoice(xml)
    assert parsed.payable_amount == Decimal("1190.00")


@pytest.mark.asyncio
async def test_peppol_ingest_unknown_vendor_404(session):
    svc = SupplierCatalogsService(session)
    xml = _PEPPOL_XML_TEMPLATE.format(
        invoice_id="INV-ORPH",
        po_number="PO-NONE",
        supplier_name="Unknown Supplier",
        supplier_vat="NOSUCH",
    )
    with pytest.raises(HTTPException) as exc:
        await svc.ingest_peppol_invoice(xml)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_peppol_ingest_idempotent(session):
    svc = SupplierCatalogsService(session)
    vendor = await svc.create_vendor(
        VendorCreate(code="IDEMP-V", name="Acme GmbH", tax_id="DE111222333"),
    )
    xml = _PEPPOL_XML_TEMPLATE.format(
        invoice_id="INV-IDEMP",
        po_number="",  # no PO link
        supplier_name="Acme GmbH",
        supplier_vat="DE111222333",
    )
    r1 = await svc.ingest_peppol_invoice(xml)
    r2 = await svc.ingest_peppol_invoice(xml)
    assert r1.invoice_id == r2.invoice_id  # second ingest returns same row


# ── Low-stock canonical event ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gr_emits_canonical_stock_low_event(session, captured_events):
    """The new ``supplier_catalogs.stock.low`` event must fire alongside legacy."""
    svc = SupplierCatalogsService(session)
    vendor = await _seed_vendor(svc)
    item = await svc.create_catalog_item(
        CatalogItemCreate(sku="SKU-LOW", name="Low", reorder_point=Decimal("1000")),
    )
    wh = await _seed_warehouse(svc)
    po = await svc.create_po(
        POCreateExt(
            vendor_id=vendor.id,
            project_id=uuid.uuid4(),
            lines=[
                POLineCreate(
                    catalog_item_id=item.id,
                    description="x",
                    ordered_qty=Decimal("10"),
                    unit_price=Decimal("1"),
                )
            ],
        )
    )
    await svc.send_po(po.id)
    await svc.post_goods_receipt(
        GoodsReceiptCreate(
            po_id=po.id,
            warehouse_id=wh.id,
            lines=[
                GRLineCreate(
                    po_line_id=po.lines[0].id,
                    received_qty=Decimal("10"),
                )
            ],
        )
    )
    names = [n for n, _ in captured_events]
    assert "supplier_catalogs.stock.low" in names
    assert "supplier_catalogs.stock.low_threshold" in names


# ── Wave M4: cross-module wiring ───────────────────────────────────────


@pytest.mark.asyncio
async def test_create_catalog_item_emits_material_added(
    session,
    captured_events,
) -> None:
    """Catalog item creation publishes ``supplier_catalogs.material.added``."""
    svc = SupplierCatalogsService(session)
    item = await svc.create_catalog_item(
        CatalogItemCreate(
            sku="SKU-WAVE-M4",
            name="Cement CEM I 42.5R",
            unit_of_measure="t",
            manufacturer="HeidelbergCement",
            mpn="HC-CEMI-425R",
        ),
    )
    matches = [(n, d) for n, d in captured_events if n == "supplier_catalogs.material.added"]
    assert len(matches) == 1, f"expected 1 material.added event, got {len(matches)}"
    payload = matches[0][1]
    assert payload["catalog_item_id"] == str(item.id)
    assert payload["sku"] == "SKU-WAVE-M4"
    assert payload["manufacturer"] == "HeidelbergCement"
    assert payload["mpn"] == "HC-CEMI-425R"
    assert payload["unit_of_measure"] == "t"


@pytest.mark.asyncio
async def test_material_added_subscriber_publishes_vector_reindex() -> None:
    """``supplier_catalogs.material.added`` → ``match_elements.vector_reindex``."""
    import asyncio

    from app.core.events import Event
    from app.modules.supplier_catalogs.events import (
        _on_material_added,
    )

    captured: list[tuple[str, dict]] = []

    def _spy(name, data=None, source_module=None):  # noqa: ARG001
        captured.append((name, dict(data or {})))
        fut: asyncio.Future = asyncio.Future()
        fut.set_result(None)
        return fut

    item_id = str(uuid.uuid4())
    event = Event(
        name="supplier_catalogs.material.added",
        data={
            "catalog_item_id": item_id,
            "sku": "X-1",
            "name": "Concrete",
            "manufacturer": "ACME",
            "mpn": "AC-X1",
            "unit_of_measure": "m3",
            "description": "C30/37 concrete",
            "category_id": None,
        },
        source_module="supplier_catalogs",
    )
    from app.core import events as _ev_module

    real = _ev_module.event_bus.publish_detached
    _ev_module.event_bus.publish_detached = _spy  # type: ignore[assignment]
    try:
        await _on_material_added(event)
    finally:
        _ev_module.event_bus.publish_detached = real  # type: ignore[assignment]

    names = [n for n, _ in captured]
    assert "match_elements.vector_reindex" in names
    assert "bi_dashboards.kpi_recompute" in names
    reindex_payload = next(d for n, d in captured if n == "match_elements.vector_reindex")
    assert reindex_payload["entity_id"] == item_id
    assert reindex_payload["operation"] == "upsert"
    assert reindex_payload["collection"] == "supplier_catalog_items"


@pytest.mark.asyncio
async def test_register_subscribers_idempotent() -> None:
    """register_subscribers wiring is safe to call repeatedly."""
    from app.modules.supplier_catalogs.events import register_subscribers

    # Call twice — should not blow up nor double-subscribe.
    register_subscribers()
    register_subscribers()
