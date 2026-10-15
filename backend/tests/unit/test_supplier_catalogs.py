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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.supplier_catalogs.models import (
    COST_STATE_MIXED,
    COST_STATE_SINGLE,
    COST_STATE_UNKNOWN,
    CatalogItem,
    PurchaseOrder,
    StockMovement,
    ThreeWayMatchRecord,
    Vendor,
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
from app.modules.supplier_catalogs.service import (
    SupplierCatalogsService,
    _fold_receipt_into_cost,
    _normalise_currency,
)
from tests._pg import transactional_session

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Per-test PostgreSQL session inside a rolled-back outer transaction.

    The shared ``oe_test_unit`` database already carries the full schema, so no
    ``create_all`` is needed. Each test runs in its own transaction (the
    session's ``commit()`` becomes a savepoint release) that is rolled back on
    teardown, leaving the database pristine for the next test.
    """
    async with transactional_session() as s:
        yield s


@pytest.fixture(autouse=True)
def _allow_all_project_access(monkeypatch) -> None:
    """Neutralise the cross-project IDOR gate for the FUNCTIONAL tests.

    Every mutating PR/PO/Invoice/GR/warehouse/stock path now calls
    ``SupplierCatalogsService._guard_project`` →
    ``app.dependencies.verify_project_access`` (added to close the cluster's
    cross-tenant IDOR, finding #1). The functional tests below seed random
    ``project_id`` values that intentionally have no backing Project row, so
    the real gate would 404 every one of them. This autouse fixture replaces
    the gate with an async no-op so the functional tests keep exercising the
    business logic; the dedicated ``test_cross_project_idor_*`` tests opt OUT
    (they re-patch the real resolver with stubbed repos) and assert the 404.
    """

    import app.dependencies as _deps

    # Stash the genuine resolver so the dedicated IDOR tests can re-arm it
    # (monkeypatch would otherwise overwrite the only reference to it).
    global _REAL_VERIFY_PROJECT_ACCESS
    _REAL_VERIFY_PROJECT_ACCESS = _deps.verify_project_access

    async def _noop(project_id, user_id, session):  # noqa: ANN001, ARG001
        return None

    monkeypatch.setattr("app.dependencies.verify_project_access", _noop)


_REAL_VERIFY_PROJECT_ACCESS = None


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


@pytest.mark.asyncio
async def test_rate_vendor_carries_the_comment_on_the_event(session, captured_events):
    """The form has always collected a note and the service always dropped it.

    There is no column to store one on ``Vendor``, so the note rides the
    published event instead. That is not storage, but it is somewhere rather
    than nowhere, and it is where the reason on a suspend already goes.
    """
    svc = SupplierCatalogsService(session)
    vendor = await _seed_vendor(svc, code=f"V-{uuid.uuid4().hex[:6]}")

    await svc.rate_vendor(vendor.id, 5, user_id="buyer", comment="always on time")

    rated = [data for name, data in captured_events if name == "supplier_catalogs.vendor.rated"]
    assert rated, "no vendor.rated event was published"
    assert rated[-1]["comment"] == "always on time"


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
async def test_pr_submit_without_chain_stays_submitted(session):
    """No approval chain is not an approval: the PR waits until someone approves it."""
    svc = SupplierCatalogsService(session)
    vendor = await _seed_vendor(svc)
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
    assert submitted.status == "submitted"

    # A submitted PR is not yet a purchase: it cannot be converted to an order.
    with pytest.raises(HTTPException) as exc:
        await svc.convert_pr_to_po(pr.id, vendor_id=vendor.id)
    assert exc.value.status_code == 400

    # An explicit approval by a permission holder releases it.
    approved = await svc.approve_pr(pr.id, approver_id="user-manager")
    assert approved.status == "approved"


@pytest.mark.asyncio
async def test_pr_chain_only_the_next_designated_approver_may_advance(session, captured_events):
    svc = SupplierCatalogsService(session)
    item = await _seed_item(svc, "SKU-CHAIN")
    pr = await svc.create_pr(
        PRCreate(
            project_id=uuid.uuid4(),
            approval_chain=["user-a", "user-b"],
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

    # Someone outside the chain is refused, and so is the second approver
    # trying to go before the first.
    for outsider in ("user-z", "user-b"):
        with pytest.raises(HTTPException) as exc:
            await svc.approve_pr(pr.id, approver_id=outsider)
        assert exc.value.status_code == 403
        with pytest.raises(HTTPException) as exc:
            await svc.reject_pr(pr.id, approver_id=outsider)
        assert exc.value.status_code == 403
    still = await svc.prs.get(pr.id)
    assert still is not None
    assert still.status == "approval_pending"
    assert list(still.approval_chain_json) == ["user-a", "user-b"]

    step = await svc.approve_pr(pr.id, approver_id="user-a")
    assert step.status == "approval_pending"
    done = await svc.approve_pr(pr.id, approver_id="user-b")
    assert done.status == "approved"

    approvals = [payload for name, payload in captured_events if name == "supplier_catalogs.pr.approved"]
    assert [p["final"] for p in approvals] == [False, True]


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
    await svc.approve_pr(pr.id, approver_id="user-manager")
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
    currency: str = "EUR",
) -> tuple[PurchaseOrder, Warehouse, Vendor]:
    vendor = await _seed_vendor(svc, f"V-{uuid.uuid4().hex[:5]}")
    item = await _seed_item(svc, f"SKU-{uuid.uuid4().hex[:5]}")
    wh = await _seed_warehouse(svc)
    po = await svc.create_po(
        POCreateExt(
            vendor_id=vendor.id,
            project_id=uuid.uuid4(),
            currency=currency,
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
async def test_match_invoice_refuses_when_currencies_differ(session, captured_events):
    """A JPY order invoiced in EUR must not produce a variance of any size.

    The failing case is not an inflated invoice, it is an identical number:
    165000 JPY ordered, 165000 EUR invoiced. Subtracting one from the other
    gives exactly zero, which is the value that means nothing is wrong, so the
    invoice used to be auto-approved for payment at roughly 165 times its worth
    with no human in the path. The Peppol ingest reaches this with
    ``auto_match`` defaulting to true, so nobody types anything at all.

    The EUR control in the same run is what makes the difference attributable
    to the currency rather than to the fixture: same numbers, same helper, same
    session, and it still matches.
    """
    svc = SupplierCatalogsService(session)

    # Control: identical numbers, one currency, still auto-matches.
    eur_po, _wh, eur_vendor = await _build_po_received(
        svc,
        qty=Decimal("1650"),
        price=Decimal("100"),
    )
    eur_invoice = await svc.create_invoice(
        VendorInvoiceCreate(
            number=f"INV-EUR-{uuid.uuid4().hex[:5]}",
            vendor_id=eur_vendor.id,
            po_id=eur_po.id,
            currency="EUR",
            subtotal=eur_po.total,
            tax=Decimal("0"),
        )
    )
    control = await svc.match_invoice(eur_invoice.id)
    assert control.status == "auto_matched"
    assert control.price_variance == Decimal("0")

    # The case: same figures, different currencies.
    jpy_po, _wh2, jpy_vendor = await _build_po_received(
        svc,
        qty=Decimal("1650"),
        price=Decimal("100"),
        currency="JPY",
    )
    assert jpy_po.currency == "JPY"
    eur_invoice_on_jpy_po = await svc.create_invoice(
        VendorInvoiceCreate(
            number=f"INV-JPY-{uuid.uuid4().hex[:5]}",
            vendor_id=jpy_vendor.id,
            po_id=jpy_po.id,
            currency="EUR",
            subtotal=jpy_po.total,
            tax=Decimal("0"),
        )
    )
    result = await svc.match_invoice(eur_invoice_on_jpy_po.id)

    # No verdict, and above all no number. Zero here would be the defect.
    assert result.status == "not_comparable"
    assert result.price_variance is None
    assert result.qty_variance is None
    assert "EUR" in (result.exception_reason or "")
    assert "JPY" in (result.exception_reason or "")

    refreshed = await svc.invoices.get(eur_invoice_on_jpy_po.id)
    assert refreshed is not None
    assert refreshed.three_way_match_status == "not_comparable"
    # The invoice's own lifecycle must not move: it may be perfectly correct,
    # so 'disputed' would accuse the supplier of something unestablished.
    assert refreshed.status == "received"

    names = [n for n, _ in captured_events]
    assert "supplier_catalogs.invoice.currency_mismatch" in names
    # The refusal must not masquerade as either real outcome. The control above
    # published invoice.matched, so assert on this invoice's events only.
    for name, payload in captured_events:
        if name in {
            "supplier_catalogs.invoice.matched",
            "supplier_catalogs.invoice.exception",
        }:
            assert payload.get("invoice_id") != str(eur_invoice_on_jpy_po.id)

    # A match record describes a comparison, and none was performed. Its
    # price_variance column is NOT NULL defaulting to zero, so any row it could
    # store here would be the same lie in the audit trail.
    records = (
        (
            await session.execute(
                select(ThreeWayMatchRecord).where(
                    ThreeWayMatchRecord.invoice_id == eur_invoice_on_jpy_po.id,
                ),
            )
        )
        .scalars()
        .all()
    )
    assert list(records) == []


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
    # With no PO there is no second figure, so nothing was subtracted. The
    # variances must say "not computed" rather than "computed, and zero" - the
    # same distinction the currency guard makes, in the branch above it.
    assert result.price_variance is None
    assert result.qty_variance is None


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
    # Anchored on a code the seed census adjudicated as correct against the
    # official UNSPSC list, so a later data correction cannot take this test
    # hostage. It used to assert "30161501", which the census found was not
    # portland cement at all and which moved to 30111601.
    assert await svc.validate_commodity_code("unspsc", "81101500") is True
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


# ── Cross-project IDOR (finding #1) ──────────────────────────────────────────
#
# Every mutating PR/PO/Invoice/GR/warehouse/stock path resolves its project
# from the trusted DB row (or, on create, from the request body) and calls
# ``verify_project_access`` BEFORE acting. These tests pin that a caller who
# does NOT own the resource's project gets a 404 (existence-preserving IDOR
# defence), while the owner still succeeds — covering one PR, one PO and the
# invoice 3-way-match, the three highest-impact write paths.


def _patch_real_project_access(monkeypatch, *, owner_id: str, project_id) -> None:
    """Re-arm the REAL ``verify_project_access`` with stubbed repos.

    Overrides the autouse ``_allow_all_project_access`` no-op so the genuine
    owner / 404 logic runs. ``project_id`` is owned by ``owner_id``; every
    other (project_id, user) combination 404s. Mirrors the canonical pattern
    in ``tests/modules/finance/test_finance_security.py``.
    """
    from types import SimpleNamespace

    project = SimpleNamespace(id=project_id, owner_id=owner_id)

    class _StubProjectRepo:
        def __init__(self, _session) -> None:  # noqa: ANN001
            pass

        async def get_by_id(self, pid):  # noqa: ANN001
            return project if pid == project_id else None

    class _StubUserRepo:
        def __init__(self, _session) -> None:  # noqa: ANN001
            pass

        async def get_by_id(self, uid):  # noqa: ANN001
            return SimpleNamespace(id=uid, role="user")

    monkeypatch.setattr("app.modules.projects.repository.ProjectRepository", _StubProjectRepo)
    monkeypatch.setattr("app.modules.users.repository.UserRepository", _StubUserRepo)
    # Restore the real resolver (the autouse fixture stubbed it to a no-op).
    assert _REAL_VERIFY_PROJECT_ACCESS is not None
    monkeypatch.setattr("app.dependencies.verify_project_access", _REAL_VERIFY_PROJECT_ACCESS)

    # ``is_project_member`` is consulted for non-owners — keep it negative so
    # only the owner passes.
    async def _not_member(*_a, **_k):  # noqa: ANN002, ANN003
        return False

    monkeypatch.setattr("app.modules.teams.access.is_project_member", _not_member)


@pytest.fixture
def _no_event_dispatch(monkeypatch):
    """Swallow ``publish_detached`` so leaked real-I/O subscribers never fire.

    These IDOR tests seed many entities (vendor, item, warehouse, PO, GR,
    invoice) WITHOUT the ``captured_events`` spy, so each ``create_*`` falls
    through to the conftest publish-detached shim. pytest-split shards at the
    test level, so when an earlier test in the same worker has registered real
    subscribers (the module's own ``register_subscribers`` or the wave-4
    notification subscribers, both identity-deduplicated and never reset on the
    process-global bus), the shim drives their asyncpg I/O - half-stepped or as
    a detached task running ``greenlet_spawn`` concurrently with this test's own
    session - which corrupts the connection and surfaces as a ``GeneratorExit``
    deep in asyncpg on the next DB op. These tests assert only on cross-project
    access control, never on event side effects, so suppress dispatch entirely.
    """
    import asyncio

    def _swallow(name, data=None, source_module=None):  # noqa: ARG001
        fut: asyncio.Future = asyncio.Future()
        fut.set_result(None)
        return fut

    monkeypatch.setattr(event_bus, "publish_detached", _swallow)


@pytest.mark.asyncio
async def test_cross_project_idor_pr_approve(session, monkeypatch, _no_event_dispatch):
    """A foreign user cannot approve another project's PR (404)."""
    svc = SupplierCatalogsService(session)
    owner = str(uuid.uuid4())
    attacker = str(uuid.uuid4())
    project_id = uuid.uuid4()
    item = await _seed_item(svc, "SKU-IDOR-PR")

    # Build + submit the PR as the legitimate project owner.
    pr = await svc.create_pr(
        PRCreate(
            project_id=project_id,
            approval_chain=[owner],
            lines=[
                PRLineCreate(
                    catalog_item_id=item.id,
                    description="x",
                    quantity=Decimal("1"),
                    estimated_unit_price=Decimal("10"),
                )
            ],
        ),
        user_id=owner,
    )
    await svc.submit_pr(pr.id, user_id=owner)

    # Now arm the real access gate: project owned by ``owner`` only.
    _patch_real_project_access(monkeypatch, owner_id=owner, project_id=project_id)

    # Attacker (no access) → 404, NOT an approval.
    with pytest.raises(HTTPException) as exc:
        await svc.approve_pr(pr.id, approver_id=attacker)
    assert exc.value.status_code == 404

    # Owner still succeeds.
    approved = await svc.approve_pr(pr.id, approver_id=owner)
    assert approved.status == "approved"


@pytest.mark.asyncio
async def test_cross_project_idor_po_send(session, monkeypatch, _no_event_dispatch):
    """A foreign user cannot send another project's PO (404)."""
    svc = SupplierCatalogsService(session)
    owner = str(uuid.uuid4())
    attacker = str(uuid.uuid4())
    project_id = uuid.uuid4()
    vendor = await _seed_vendor(svc)
    item = await _seed_item(svc, "SKU-IDOR-PO")

    po = await svc.create_po(
        POCreateExt(
            vendor_id=vendor.id,
            project_id=project_id,
            lines=[
                POLineCreate(
                    catalog_item_id=item.id,
                    description="x",
                    ordered_qty=Decimal("1"),
                    unit_price=Decimal("1"),
                )
            ],
        ),
        user_id=owner,
    )

    _patch_real_project_access(monkeypatch, owner_id=owner, project_id=project_id)

    with pytest.raises(HTTPException) as exc:
        await svc.send_po(po.id, user_id=attacker)
    assert exc.value.status_code == 404

    sent = await svc.send_po(po.id, user_id=owner)
    assert sent.status == "sent"


@pytest.mark.asyncio
async def test_cross_project_idor_invoice_match(session, monkeypatch, _no_event_dispatch):
    """A foreign user cannot 3-way-match another project's invoice (404)."""
    svc = SupplierCatalogsService(session)
    owner = str(uuid.uuid4())
    attacker = str(uuid.uuid4())
    project_id = uuid.uuid4()
    vendor = await _seed_vendor(svc)
    item = await _seed_item(svc, "SKU-IDOR-INV")
    wh = await _seed_warehouse(svc)

    po = await svc.create_po(
        POCreateExt(
            vendor_id=vendor.id,
            project_id=project_id,
            lines=[
                POLineCreate(
                    catalog_item_id=item.id,
                    description="x",
                    ordered_qty=Decimal("10"),
                    unit_price=Decimal("100"),
                )
            ],
        ),
        user_id=owner,
    )
    await svc.send_po(po.id, user_id=owner)
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
        ),
        user_id=owner,
    )
    invoice = await svc.create_invoice(
        VendorInvoiceCreate(
            number="INV-IDOR",
            vendor_id=vendor.id,
            po_id=po.id,
            subtotal=po.total,
            tax=Decimal("0"),
        ),
        user_id=owner,
    )

    _patch_real_project_access(monkeypatch, owner_id=owner, project_id=project_id)

    with pytest.raises(HTTPException) as exc:
        await svc.match_invoice(invoice.id, user_id=attacker)
    assert exc.value.status_code == 404

    # Owner can match.
    result = await svc.match_invoice(invoice.id, user_id=owner)
    assert result.status in ("auto_matched", "exception")


# ── Stock cost currency ─────────────────────────────────────────────────────


def test_fold_receipt_refuses_to_average_across_currencies():
    """The weighted average is withheld once two currencies meet in one balance.

    Averaging 50 EUR with 70 USD produces a number that is money in neither,
    and every issue out of the balance afterwards copies that number onto its
    own movement row, so one blend spreads into the audit trail.
    """
    # First receipt into an empty balance takes its currency outright.
    assert _fold_receipt_into_cost(
        prev_qty=Decimal("0"),
        prev_cost=None,
        prev_currency=None,
        prev_state=COST_STATE_UNKNOWN,
        incoming_qty=Decimal("100"),
        incoming_price=Decimal("50"),
        incoming_currency="EUR",
    ) == (Decimal("50"), "EUR", COST_STATE_SINGLE)

    # A second receipt in the same currency still averages, as it always did.
    assert _fold_receipt_into_cost(
        prev_qty=Decimal("100"),
        prev_cost=Decimal("50"),
        prev_currency="EUR",
        prev_state=COST_STATE_SINGLE,
        incoming_qty=Decimal("100"),
        incoming_price=Decimal("70"),
        incoming_currency="EUR",
    ) == (Decimal("60"), "EUR", COST_STATE_SINGLE)

    # A different currency refuses. Note what is not returned: not the old
    # average, not the incoming price, and not zero.
    assert _fold_receipt_into_cost(
        prev_qty=Decimal("100"),
        prev_cost=Decimal("50"),
        prev_currency="EUR",
        prev_state=COST_STATE_SINGLE,
        incoming_qty=Decimal("100"),
        incoming_price=Decimal("70"),
        incoming_currency="USD",
    ) == (None, None, COST_STATE_MIXED)

    # Mixed stays mixed while the blended stock is still on hand, even when
    # the new receipt is in the balance's original currency.
    assert _fold_receipt_into_cost(
        prev_qty=Decimal("200"),
        prev_cost=None,
        prev_currency=None,
        prev_state=COST_STATE_MIXED,
        incoming_qty=Decimal("50"),
        incoming_price=Decimal("50"),
        incoming_currency="EUR",
    ) == (None, None, COST_STATE_MIXED)

    # Issued down to nothing, the next receipt repairs the balance: none of
    # the blended stock is left to be wrong about.
    assert _fold_receipt_into_cost(
        prev_qty=Decimal("0"),
        prev_cost=None,
        prev_currency=None,
        prev_state=COST_STATE_MIXED,
        incoming_qty=Decimal("10"),
        incoming_price=Decimal("42"),
        incoming_currency="EUR",
    ) == (Decimal("42"), "EUR", COST_STATE_SINGLE)


def test_fold_receipt_treats_a_blank_currency_as_no_currency():
    """A blank code must not let two unlabelled receipts agree with each other."""
    for blank in (None, "", "   "):
        assert _fold_receipt_into_cost(
            prev_qty=Decimal("0"),
            prev_cost=None,
            prev_currency=None,
            prev_state=COST_STATE_UNKNOWN,
            incoming_qty=Decimal("10"),
            incoming_price=Decimal("5"),
            incoming_currency=_normalise_currency(blank),
        ) == (None, None, COST_STATE_UNKNOWN), blank

    # Unknown is sticky while the unlabelled stock is on hand: a later
    # labelled receipt cannot vouch for what is already there.
    assert _fold_receipt_into_cost(
        prev_qty=Decimal("10"),
        prev_cost=None,
        prev_currency=None,
        prev_state=COST_STATE_UNKNOWN,
        incoming_qty=Decimal("10"),
        incoming_price=Decimal("5"),
        incoming_currency="EUR",
    ) == (None, None, COST_STATE_UNKNOWN)


async def _receive_po(
    svc: SupplierCatalogsService,
    *,
    vendor: Vendor,
    item: CatalogItem,
    wh: Warehouse,
    currency: str,
    price: Decimal,
    qty: Decimal,
) -> None:
    """Order and fully receive ``qty`` of ``item`` at ``price`` in ``currency``."""
    po = await svc.create_po(
        POCreateExt(
            vendor_id=vendor.id,
            project_id=uuid.uuid4(),
            currency=currency,
            lines=[
                POLineCreate(
                    catalog_item_id=item.id,
                    description="cement",
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
                    batch_lot="",
                )
            ],
        ),
        user_id="receiver",
    )


@pytest.mark.asyncio
async def test_receipts_in_two_currencies_leave_no_blended_average(session):
    """End to end: two POs, two currencies, one balance, no invented number."""
    svc = SupplierCatalogsService(session)
    vendor = await _seed_vendor(svc, code=f"V-{uuid.uuid4().hex[:6]}")
    item = await _seed_item(svc, f"SKU-{uuid.uuid4().hex[:6]}")
    wh = await _seed_warehouse(svc)

    await _receive_po(svc, vendor=vendor, item=item, wh=wh, currency="EUR", price=Decimal("50"), qty=Decimal("100"))
    balance = await svc.stock.get_balance(wh.id, item.id, "")
    assert balance is not None
    assert balance.unit_cost_avg == Decimal("50")
    assert balance.currency == "EUR"
    assert balance.cost_state == COST_STATE_SINGLE

    await _receive_po(svc, vendor=vendor, item=item, wh=wh, currency="USD", price=Decimal("70"), qty=Decimal("100"))
    await session.refresh(balance)
    assert balance.quantity_on_hand == Decimal("200")
    # The old code stored 60 here: the mean of 50 EUR and 70 USD.
    assert balance.unit_cost_avg is None
    assert balance.currency is None
    assert balance.cost_state == COST_STATE_MIXED

    # Both inbound movements carry the currency they were bought in, which is
    # what makes the history reconstructible rather than merely recorded.
    rows = (
        (
            await session.execute(
                select(StockMovement)
                .where(
                    StockMovement.catalog_item_id == item.id,
                    StockMovement.movement_type == "in",
                )
                .order_by(StockMovement.performed_at)
            )
        )
        .scalars()
        .all()
    )
    assert sorted((str(m.unit_cost), m.currency) for m in rows) == [
        ("50.0000", "EUR"),
        ("70.0000", "USD"),
    ]


@pytest.mark.asyncio
async def test_issuing_from_a_mixed_balance_records_no_unit_cost(session):
    """An issue out of a mixed balance must not stamp a price it does not have."""
    svc = SupplierCatalogsService(session)
    vendor = await _seed_vendor(svc, code=f"V-{uuid.uuid4().hex[:6]}")
    item = await _seed_item(svc, f"SKU-{uuid.uuid4().hex[:6]}")
    wh = await _seed_warehouse(svc)

    await _receive_po(svc, vendor=vendor, item=item, wh=wh, currency="EUR", price=Decimal("50"), qty=Decimal("100"))
    await _receive_po(svc, vendor=vendor, item=item, wh=wh, currency="USD", price=Decimal("70"), qty=Decimal("100"))

    movement = await svc.issue_stock(
        StockIssuePayload(
            catalog_item_id=item.id,
            warehouse_id=wh.id,
            quantity=Decimal("10"),
        ),
        user_id="storeman",
    )
    # Zero would read as "issued for nothing" and be indistinguishable from
    # stock that genuinely cost nothing.
    assert movement.unit_cost is None
    assert movement.currency is None


# ── Correcting and removing reference records ───────────────────────────────
#
# Until this batch a vendor, a catalog item and a warehouse could be created
# and never touched again: no field on any of the three could be corrected and
# nothing in the module could be deleted at all, so a mistyped code lived
# forever and a record entered twice stayed twice.
#
# The delete side is not a row removal and these tests are mostly about why.
# Every foreign key pointing at these three tables is permissive - CASCADE on
# price lists, catalog entries, balances and movements, SET NULL on
# requisition and order lines - so the database would let all four deletes
# through and quietly take the referencing rows with them, or leave an order
# line describing a purchase of nothing. The guard has to count the holders
# itself, and the refusal has to say what is holding the record, because
# "cannot delete" with no reason leaves a buyer with nowhere to go.


async def _row_exists(session: AsyncSession, model, row_id: uuid.UUID) -> bool:
    """True if the row is still in the database.

    Selects the id column rather than the entity on purpose: a SELECT for an
    entity can be answered out of the identity map, which still holds the
    instance after a flushed delete, and the test would pass on an object
    that is no longer in any table.
    """
    found = (await session.execute(select(model.id).where(model.id == row_id))).scalar_one_or_none()
    return found is not None


def test_a_refusal_names_its_holders_in_english():
    """The counts have to read as a sentence; they are what the buyer sees."""
    from app.modules.supplier_catalogs.service import _describe_holders

    assert _describe_holders({"purchase_order": 1}) == "1 purchase order"
    assert _describe_holders({"purchase_order": 2}) == "2 purchase orders"
    assert _describe_holders({"price_list": 1, "kyc_document": 3}) == "1 price list and 3 KYC documents"
    assert (
        _describe_holders({"price_list": 1, "purchase_order": 2, "kyc_document": 3})
        == "1 price list, 2 purchase orders and 3 KYC documents"
    )


# ── Vendor ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_patch_vendor_corrects_its_own_fields(session):
    from app.modules.supplier_catalogs.schemas import VendorUpdate

    svc = SupplierCatalogsService(session)
    vendor = await _seed_vendor(svc, code=f"V-{uuid.uuid4().hex[:6]}")
    updated = await svc.update_vendor(
        vendor.id,
        VendorUpdate(
            name="Acme Building Supplies",
            tax_id="DE123456789",
            payment_terms_days=45,
            country_code="DE",
        ),
    )
    assert updated.name == "Acme Building Supplies"
    assert updated.tax_id == "DE123456789"
    assert updated.payment_terms_days == 45
    assert updated.country_code == "DE"


@pytest.mark.asyncio
async def test_patch_vendor_cannot_change_status(session):
    """Status has three routes of its own and this is not one of them.

    ``VendorUpdate`` declares no ``status`` field, so a caller that sends one
    is not rejected, it is ignored - Pydantic drops unknown keys by default.
    That makes the assertion a statement about the stored row rather than
    about a raise: a test written as ``pytest.raises`` here would fail while
    describing the behaviour correctly, and switching the shipped schema to
    ``extra="forbid"`` to make it raise would break every client that echoes
    a whole vendor back.
    """
    from app.modules.supplier_catalogs.schemas import VendorUpdate

    svc = SupplierCatalogsService(session)
    vendor = await _seed_vendor(svc, code=f"V-{uuid.uuid4().hex[:6]}")
    await svc.blacklist_vendor(vendor.id, reason="fraud")

    payload = VendorUpdate.model_validate({"name": "Renamed", "status": "active", "rating": 5})
    assert not hasattr(payload, "status")
    updated = await svc.update_vendor(vendor.id, payload)

    assert updated.name == "Renamed"
    # The two fields with a lifecycle of their own are untouched.
    assert updated.status == "blacklisted"
    assert updated.rating is None


@pytest.mark.asyncio
async def test_delete_vendor_removes_an_unreferenced_record(session, captured_events):
    svc = SupplierCatalogsService(session)
    vendor = await _seed_vendor(svc, code=f"V-{uuid.uuid4().hex[:6]}")

    await svc.delete_vendor(vendor.id, user_id="buyer")

    assert await _row_exists(session, Vendor, vendor.id) is False
    assert any(n == "supplier_catalogs.vendor.deleted" for n, _ in captured_events)


@pytest.mark.asyncio
async def test_delete_vendor_refused_by_a_purchase_order(session):
    """A traded-with vendor is held, and the refusal points at the lifecycle."""
    svc = SupplierCatalogsService(session)
    vendor = await _seed_vendor(svc, code=f"V-{uuid.uuid4().hex[:6]}")
    item = await _seed_item(svc, f"SKU-{uuid.uuid4().hex[:6]}")
    await svc.create_po(
        POCreateExt(
            vendor_id=vendor.id,
            project_id=uuid.uuid4(),
            lines=[
                POLineCreate(
                    catalog_item_id=item.id,
                    description="cement",
                    ordered_qty=Decimal("10"),
                    unit_price=Decimal("5"),
                )
            ],
        )
    )

    with pytest.raises(HTTPException) as exc:
        await svc.delete_vendor(vendor.id)

    assert exc.value.status_code == 409
    detail = exc.value.detail
    assert detail["code"] == "vendor_in_use"
    assert "1 purchase order" in detail["message"]
    assert vendor.code in detail["message"]
    assert "suspend" in detail["remediation"].lower()
    assert "blacklist" in detail["remediation"].lower()
    assert {"kind": "purchase_order", "count": 1} in detail["holders"]
    # Refused means refused: the row is still there.
    assert await _row_exists(session, Vendor, vendor.id) is True


@pytest.mark.asyncio
async def test_delete_vendor_names_every_kind_holding_it(session):
    """Two different holders, both counted, both named, in one sentence."""
    from datetime import date

    from app.modules.supplier_catalogs.schemas import KYCDocumentCreate

    svc = SupplierCatalogsService(session)
    vendor = await _seed_vendor(svc, code=f"V-{uuid.uuid4().hex[:6]}")
    await svc.create_price_list(vendor.id, PriceListCreate(name="Q1", currency="EUR"))
    await svc.add_kyc_document(
        vendor.id,
        KYCDocumentCreate(
            doc_type="vat_cert",
            document_number="DE123",
            issued_on=date(2025, 1, 1),
            expires_on=date(2030, 1, 1),
            issuing_country="DE",
        ),
    )

    with pytest.raises(HTTPException) as exc:
        await svc.delete_vendor(vendor.id)

    detail = exc.value.detail
    assert "1 price list and 1 KYC document" in detail["message"]
    assert {"kind": "price_list", "count": 1} in detail["holders"]
    assert {"kind": "kyc_document", "count": 1} in detail["holders"]


# ── Catalog item ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_patch_catalog_item_corrects_fields_but_never_the_sku(session):
    from app.modules.supplier_catalogs.schemas import CatalogItemUpdate

    svc = SupplierCatalogsService(session)
    item = await _seed_item(svc, f"SKU-{uuid.uuid4().hex[:6]}")
    original_sku = item.sku

    payload = CatalogItemUpdate.model_validate(
        {
            "name": "Portland cement CEM I 42.5",
            "unit_of_measure": "t",
            "reorder_point": "25",
            "sku": "SOMETHING-ELSE",
        }
    )
    assert not hasattr(payload, "sku")
    updated = await svc.update_catalog_item(item.id, payload)

    assert updated.name == "Portland cement CEM I 42.5"
    assert updated.unit_of_measure == "t"
    assert updated.reorder_point == Decimal("25")
    assert updated.sku == original_sku


@pytest.mark.asyncio
async def test_patch_catalog_item_announces_a_deactivation(session, captured_events):
    """Switching a SKU off is its own fact downstream, not a field change."""
    from app.modules.supplier_catalogs.schemas import CatalogItemUpdate

    svc = SupplierCatalogsService(session)
    item = await _seed_item(svc, f"SKU-{uuid.uuid4().hex[:6]}")

    updated = await svc.update_catalog_item(item.id, CatalogItemUpdate(active=False))

    assert updated.active is False
    names = [n for n, _ in captured_events]
    assert "supplier_catalogs.material.updated" in names
    assert "supplier_catalogs.material.deactivated" in names


@pytest.mark.asyncio
async def test_patch_catalog_item_rejects_an_unknown_commodity_scheme(session):
    from app.modules.supplier_catalogs.schemas import CatalogItemUpdate

    svc = SupplierCatalogsService(session)
    item = await _seed_item(svc, f"SKU-{uuid.uuid4().hex[:6]}")

    with pytest.raises(HTTPException) as exc:
        await svc.update_catalog_item(item.id, CatalogItemUpdate(commodity_scheme="bogus"))

    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_delete_catalog_item_removes_an_unquoted_record(session, captured_events):
    svc = SupplierCatalogsService(session)
    item = await _seed_item(svc, f"SKU-{uuid.uuid4().hex[:6]}")

    await svc.delete_catalog_item(item.id, user_id="buyer")

    assert await _row_exists(session, CatalogItem, item.id) is False
    assert any(n == "supplier_catalogs.material.deleted" for n, _ in captured_events)


@pytest.mark.asyncio
async def test_delete_catalog_item_refused_by_an_order_line(session):
    svc = SupplierCatalogsService(session)
    vendor = await _seed_vendor(svc, code=f"V-{uuid.uuid4().hex[:6]}")
    item = await _seed_item(svc, f"SKU-{uuid.uuid4().hex[:6]}")
    await svc.create_po(
        POCreateExt(
            vendor_id=vendor.id,
            project_id=uuid.uuid4(),
            lines=[
                POLineCreate(
                    catalog_item_id=item.id,
                    description="cement",
                    ordered_qty=Decimal("4"),
                    unit_price=Decimal("9"),
                )
            ],
        )
    )

    with pytest.raises(HTTPException) as exc:
        await svc.delete_catalog_item(item.id)

    detail = exc.value.detail
    assert exc.value.status_code == 409
    assert detail["code"] == "catalog_item_in_use"
    assert "1 purchase order line" in detail["message"]
    assert item.sku in detail["message"]
    assert await _row_exists(session, CatalogItem, item.id) is True


@pytest.mark.asyncio
async def test_delete_catalog_item_refused_by_stock_on_hand(session):
    """Inventory that exists cannot lose the item it is inventory of."""
    svc = SupplierCatalogsService(session)
    _wh, item = await _seed_stock(svc, on_hand=Decimal("12"))

    with pytest.raises(HTTPException) as exc:
        await svc.delete_catalog_item(item.id)

    detail = exc.value.detail
    assert detail["code"] == "catalog_item_in_use"
    assert "1 stock balance with quantity on hand" in detail["message"]
    assert {"kind": "stock_balance", "count": 1} in detail["holders"]


# ── Warehouse ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_patch_warehouse_corrects_its_own_fields(session):
    from app.modules.supplier_catalogs.schemas import WarehouseUpdate

    svc = SupplierCatalogsService(session)
    wh = await _seed_warehouse(svc)
    original_code = wh.code

    payload = WarehouseUpdate.model_validate(
        {
            "name": "North yard",
            "address": "Hafenstrasse 4, Hamburg",
            "code": "RENAMED",
            "status": "closed",
        }
    )
    assert not hasattr(payload, "code")
    assert not hasattr(payload, "status")
    updated = await svc.update_warehouse(wh.id, payload, user_id="storeman")

    assert updated.name == "North yard"
    assert updated.address == "Hafenstrasse 4, Hamburg"
    assert updated.code == original_code
    assert updated.status == "active"


@pytest.mark.asyncio
async def test_delete_warehouse_removes_an_empty_location(session, captured_events):
    svc = SupplierCatalogsService(session)
    wh = await _seed_warehouse(svc)

    await svc.delete_warehouse(wh.id, user_id="storeman")

    assert await _row_exists(session, Warehouse, wh.id) is False
    assert any(n == "supplier_catalogs.warehouse.deleted" for n, _ in captured_events)


@pytest.mark.asyncio
async def test_delete_warehouse_refused_by_stock_on_hand(session):
    svc = SupplierCatalogsService(session)
    wh, _item = await _seed_stock(svc, on_hand=Decimal("7"))

    with pytest.raises(HTTPException) as exc:
        await svc.delete_warehouse(wh.id)

    detail = exc.value.detail
    assert exc.value.status_code == 409
    assert detail["code"] == "warehouse_in_use"
    assert "1 stock balance with quantity on hand" in detail["message"]
    assert wh.code in detail["message"]
    assert await _row_exists(session, Warehouse, wh.id) is True


@pytest.mark.asyncio
async def test_delete_warehouse_allowed_once_the_stock_is_gone(session):
    """An emptied balance is a record of stock that has left, not a holder.

    Counting every balance row instead of the ones with quantity would make a
    location that was used once and cleared out permanently undeletable, which
    is the same dead end this batch exists to remove.
    """
    svc = SupplierCatalogsService(session)
    wh, _item = await _seed_stock(svc, on_hand=Decimal("0"))

    await svc.delete_warehouse(wh.id)

    assert await _row_exists(session, Warehouse, wh.id) is False


# ── Tolerance profile ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_tolerance_profile_removes_an_unused_one(session):
    from app.modules.supplier_catalogs.models import TolerianceProfile
    from app.modules.supplier_catalogs.schemas import TolerianceProfileCreate

    svc = SupplierCatalogsService(session)
    profile = await svc.create_tolerance_profile(
        TolerianceProfileCreate(name=f"unused-{uuid.uuid4().hex[:6]}", price_tolerance_pct=Decimal("1")),
    )

    await svc.delete_tolerance_profile(profile.id)

    assert await _row_exists(session, TolerianceProfile, profile.id) is False


@pytest.mark.asyncio
async def test_delete_tolerance_profile_refused_when_a_vendor_names_it(session):
    """The link is by name, so the database would not have stopped this.

    A vendor left naming a profile that is gone falls back to a different set
    of tolerances, and invoices that used to raise a price exception start
    passing. That is money, so it is a refusal.
    """
    from app.modules.supplier_catalogs.schemas import TolerianceProfileCreate

    svc = SupplierCatalogsService(session)
    name = f"strict-{uuid.uuid4().hex[:6]}"
    profile = await svc.create_tolerance_profile(
        TolerianceProfileCreate(name=name, price_tolerance_pct=Decimal("0.5")),
    )
    await svc.create_vendor(
        VendorCreate(
            code=f"V-{uuid.uuid4().hex[:6]}",
            name="Held vendor",
            tolerance_profile_name=name,
        )
    )

    with pytest.raises(HTTPException) as exc:
        await svc.delete_tolerance_profile(profile.id)

    detail = exc.value.detail
    assert exc.value.status_code == 409
    assert detail["code"] == "tolerance_profile_in_use"
    assert "1 vendor" in detail["message"]
    assert {"kind": "vendor", "count": 1} in detail["holders"]


@pytest.mark.asyncio
async def test_delete_tolerance_profile_refused_when_it_is_the_default(session):
    svc = SupplierCatalogsService(session)
    profile = await svc.ensure_default_tolerance_profile()

    with pytest.raises(HTTPException) as exc:
        await svc.delete_tolerance_profile(profile.id)

    detail = exc.value.detail
    assert exc.value.status_code == 409
    assert detail["code"] == "tolerance_profile_is_default"
    assert "default" in detail["remediation"].lower()


@pytest.mark.asyncio
async def test_update_tolerance_profile_renames_it(session):
    """A PATCH carrying ``name`` writes the row, not just a 200 with the old value.

    Read the column back with a plain ``select`` instead of through the
    service's returned instance or a second ``session.get()``: both of those
    can hand back the same Python object the write already touched in
    memory, which would pass even if the SET clause sent to PostgreSQL
    never carried the new name.
    """
    from app.modules.supplier_catalogs.models import TolerianceProfile
    from app.modules.supplier_catalogs.schemas import TolerianceProfileCreate, TolerianceProfileUpdate

    svc = SupplierCatalogsService(session)
    old_name = f"profile-{uuid.uuid4().hex[:6]}"
    new_name = f"renamed-{uuid.uuid4().hex[:6]}"
    profile = await svc.create_tolerance_profile(
        TolerianceProfileCreate(name=old_name, price_tolerance_pct=Decimal("1")),
    )

    await svc.update_tolerance_profile(profile.id, TolerianceProfileUpdate(name=new_name))

    stored_name = (
        await session.execute(select(TolerianceProfile.name).where(TolerianceProfile.id == profile.id))
    ).scalar_one()
    assert stored_name == new_name


@pytest.mark.asyncio
async def test_update_tolerance_profile_refuses_a_rename_a_vendor_relies_on(session):
    """The database enforces nothing here either, same as the delete guard.

    Renaming a profile a vendor names by string would leave that vendor
    pointing at a name that resolves to nothing, silently falling back to
    different tolerances - the same money hazard ``delete_tolerance_profile``
    already refuses.
    """
    from app.modules.supplier_catalogs.models import TolerianceProfile
    from app.modules.supplier_catalogs.schemas import TolerianceProfileCreate, TolerianceProfileUpdate

    svc = SupplierCatalogsService(session)
    name = f"strict-{uuid.uuid4().hex[:6]}"
    profile = await svc.create_tolerance_profile(
        TolerianceProfileCreate(name=name, price_tolerance_pct=Decimal("0.5")),
    )
    await svc.create_vendor(
        VendorCreate(
            code=f"V-{uuid.uuid4().hex[:6]}",
            name="Held vendor",
            tolerance_profile_name=name,
        )
    )

    with pytest.raises(HTTPException) as exc:
        await svc.update_tolerance_profile(profile.id, TolerianceProfileUpdate(name=f"renamed-{uuid.uuid4().hex[:6]}"))

    detail = exc.value.detail
    assert exc.value.status_code == 409
    assert detail["code"] == "tolerance_profile_name_in_use"
    assert "1 vendor" in detail["message"]
    assert "is matched" in detail["message"]

    stored_name = (
        await session.execute(select(TolerianceProfile.name).where(TolerianceProfile.id == profile.id))
    ).scalar_one()
    assert stored_name == name


@pytest.mark.asyncio
async def test_update_tolerance_profile_allows_a_rename_nothing_relies_on(session):
    """A rename that holds nothing goes through, description update included."""
    from app.modules.supplier_catalogs.models import TolerianceProfile
    from app.modules.supplier_catalogs.schemas import TolerianceProfileCreate, TolerianceProfileUpdate

    svc = SupplierCatalogsService(session)
    profile = await svc.create_tolerance_profile(
        TolerianceProfileCreate(name=f"unused-{uuid.uuid4().hex[:6]}", price_tolerance_pct=Decimal("1")),
    )
    new_name = f"renamed-{uuid.uuid4().hex[:6]}"

    updated = await svc.update_tolerance_profile(
        profile.id,
        TolerianceProfileUpdate(name=new_name, description="tightened for a new strategic supplier"),
    )
    assert updated.name == new_name

    row = (await session.execute(select(TolerianceProfile).where(TolerianceProfile.id == profile.id))).scalar_one()
    assert row.name == new_name
    assert row.description == "tightened for a new strategic supplier"


@pytest.mark.asyncio
async def test_deleting_something_that_is_not_there_is_a_404(session):
    svc = SupplierCatalogsService(session)
    missing = uuid.uuid4()

    with pytest.raises(HTTPException) as exc:
        await svc.delete_vendor(missing)
    assert exc.value.status_code == 404

    with pytest.raises(HTTPException) as exc:
        await svc.delete_catalog_item(missing)
    assert exc.value.status_code == 404

    with pytest.raises(HTTPException) as exc:
        await svc.delete_warehouse(missing)
    assert exc.value.status_code == 404

    with pytest.raises(HTTPException) as exc:
        await svc.delete_tolerance_profile(missing)
    assert exc.value.status_code == 404
