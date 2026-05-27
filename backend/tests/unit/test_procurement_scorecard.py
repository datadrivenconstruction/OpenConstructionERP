"""Unit tests for :class:`ProcurementService` scorecard + 3-way match (Wave 2 / T4).

Scope:
    * ``get_match_status`` — per-line PO/GR/Invoice classification (ok /
      partial / over_received / over_invoiced / unmatched).
    * ``get_supplier_scorecard`` — on-time %, qty variance %, GR rejection
      rate, edge case (zero POs returns all-zero fields, no crash).
    * ``_classify_line_match`` — pure helper.

The service is exercised against a fully in-memory SQLite engine so the
SQLAlchemy aggregates run against real SQL, not stubs (which would not
catch column-name mismatches between the new code and the model layer).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.modules.procurement.models import (
    GoodsReceipt,
    GoodsReceiptItem,
    PurchaseOrder,
    PurchaseOrderItem,
)
from app.modules.procurement.service import ProcurementService

PROJECT_ID = uuid.uuid4()
SUPPLIER_ID = "11111111-1111-1111-1111-111111111111"


@pytest_asyncio.fixture
async def session() -> AsyncSession:  # type: ignore[misc]
    """Per-test SQLite engine — Base.metadata.create_all gives us every table.

    The procurement module owns four tables; we create the full schema so
    optional cross-module lookups (finance Invoice) degrade gracefully via
    the service's broad ``except Exception``.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as sess:
        yield sess
    await engine.dispose()


def _make_po(
    *,
    project_id: uuid.UUID = PROJECT_ID,
    vendor_contact_id: str | None = SUPPLIER_ID,
    po_number: str = "PO-001",
    delivery_date: str | None = "2026-04-10",
    status: str = "issued",
    amount_total: str = "1000",
    created_at: datetime | None = None,
) -> PurchaseOrder:
    po = PurchaseOrder(
        project_id=project_id,
        vendor_contact_id=vendor_contact_id,
        po_number=po_number,
        po_type="standard",
        delivery_date=delivery_date,
        currency_code="EUR",
        amount_subtotal=amount_total,
        tax_amount="0",
        amount_total=amount_total,
        status=status,
    )
    if created_at is not None:
        po.created_at = created_at
    return po


# ── _classify_line_match (pure helper) ─────────────────────────────────


def test_classify_line_match_ok() -> None:
    assert ProcurementService._classify_line_match(Decimal("10"), Decimal("10"), Decimal("10")) == "ok"


def test_classify_line_match_partial() -> None:
    assert ProcurementService._classify_line_match(Decimal("10"), Decimal("5"), Decimal("0")) == "partial"


def test_classify_line_match_unmatched() -> None:
    assert ProcurementService._classify_line_match(Decimal("10"), Decimal("0"), Decimal("0")) == "unmatched"


def test_classify_line_match_over_received() -> None:
    assert ProcurementService._classify_line_match(Decimal("10"), Decimal("15"), Decimal("10")) == "over_received"


def test_classify_line_match_over_invoiced() -> None:
    assert ProcurementService._classify_line_match(Decimal("10"), Decimal("5"), Decimal("8")) == "over_invoiced"


# ── get_match_status (E2E with SQLite) ─────────────────────────────────


@pytest.mark.asyncio
async def test_match_status_two_lines_mixed(session: AsyncSession) -> None:
    """PO with two lines: line A is fully received; line B is over-received."""
    po = _make_po()
    session.add(po)
    await session.flush()

    line_a = PurchaseOrderItem(
        po_id=po.id,
        description="Cement",
        quantity="100",
        unit_rate="10",
        amount="1000",
        sort_order=0,
    )
    line_b = PurchaseOrderItem(
        po_id=po.id,
        description="Sand",
        quantity="50",
        unit_rate="2",
        amount="100",
        sort_order=1,
    )
    session.add_all([line_a, line_b])
    await session.flush()

    gr = GoodsReceipt(
        po_id=po.id,
        receipt_date="2026-04-09",  # on time
        status="confirmed",
    )
    session.add(gr)
    await session.flush()

    session.add_all(
        [
            GoodsReceiptItem(
                receipt_id=gr.id,
                po_item_id=line_a.id,
                quantity_ordered="100",
                quantity_received="100",
                quantity_rejected="0",
            ),
            GoodsReceiptItem(
                receipt_id=gr.id,
                po_item_id=line_b.id,
                quantity_ordered="50",
                quantity_received="75",  # over-received
                quantity_rejected="0",
            ),
        ]
    )
    await session.flush()

    svc = ProcurementService(session)
    result = await svc.get_match_status(po.id)

    assert result["po_id"] == po.id
    assert result["po_number"] == "PO-001"
    assert len(result["lines"]) == 2

    by_desc = {ln["description"]: ln for ln in result["lines"]}
    # Line A: ordered=received=100, no invoice yet → partial (not "ok"
    # because invoiced=0 < ordered=100). The contract requires three-way
    # alignment for "ok".
    assert by_desc["Cement"]["match_status"] == "partial"
    assert by_desc["Cement"]["received_qty"] == "100"
    # Line B: received > ordered → over_received.
    assert by_desc["Sand"]["match_status"] == "over_received"
    assert by_desc["Sand"]["received_qty"] == "75"

    # Overall takes the worst-case tag from the precedence list.
    assert result["overall_status"] == "over_received"


@pytest.mark.asyncio
async def test_match_status_unconfirmed_gr_ignored(session: AsyncSession) -> None:
    """Draft GRs do not count toward received quantities."""
    po = _make_po()
    session.add(po)
    await session.flush()

    line = PurchaseOrderItem(
        po_id=po.id,
        description="Steel",
        quantity="20",
        sort_order=0,
    )
    session.add(line)
    await session.flush()

    gr = GoodsReceipt(po_id=po.id, receipt_date="2026-04-01", status="draft")
    session.add(gr)
    await session.flush()
    session.add(
        GoodsReceiptItem(
            receipt_id=gr.id,
            po_item_id=line.id,
            quantity_ordered="20",
            quantity_received="20",
        )
    )
    await session.flush()

    svc = ProcurementService(session)
    result = await svc.get_match_status(po.id)

    assert result["lines"][0]["received_qty"] == "0"
    assert result["lines"][0]["match_status"] == "unmatched"


# ── get_supplier_scorecard ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scorecard_on_time_and_rejection(session: AsyncSession) -> None:
    """3 GRs: 2 on-time, 1 late, 1 rejected → on-time = 2/3, rejection = 1/3."""
    po = _make_po(delivery_date="2026-04-10")
    session.add(po)
    await session.flush()

    line = PurchaseOrderItem(
        po_id=po.id,
        description="Cement",
        quantity="100",
        sort_order=0,
    )
    session.add(line)
    await session.flush()

    # GR 1 — on time, confirmed
    gr1 = GoodsReceipt(po_id=po.id, receipt_date="2026-04-08", status="confirmed")
    # GR 2 — on time, but rejected (still counts as a GR but flagged as
    # rejection)
    gr2 = GoodsReceipt(po_id=po.id, receipt_date="2026-04-09", status="rejected")
    # GR 3 — late
    gr3 = GoodsReceipt(po_id=po.id, receipt_date="2026-04-15", status="confirmed")
    session.add_all([gr1, gr2, gr3])
    await session.flush()

    # 50 of 100 received via confirmed GR1
    session.add(
        GoodsReceiptItem(
            receipt_id=gr1.id,
            po_item_id=line.id,
            quantity_ordered="100",
            quantity_received="50",
        )
    )
    await session.flush()

    svc = ProcurementService(session)
    scorecard = await svc.get_supplier_scorecard(SUPPLIER_ID, project_id=PROJECT_ID)

    assert scorecard["supplier_contact_id"] == SUPPLIER_ID
    assert scorecard["total_po_count"] == 1
    assert scorecard["total_gr_count"] == 3
    # 2 on-time (GR1, GR2) / 3 total
    assert scorecard["on_time_delivery_pct"] == pytest.approx(2 / 3, rel=1e-6)
    # 1 rejected / 3 total
    assert scorecard["gr_rejection_rate"] == pytest.approx(1 / 3, rel=1e-6)
    # 50 received vs 100 ordered → |(50-100)/100| = 0.5
    assert scorecard["qty_variance_pct"] == pytest.approx(0.5, rel=1e-6)
    assert scorecard["currency"] == "EUR"
    assert scorecard["total_po_value"] == "1000"


@pytest.mark.asyncio
async def test_scorecard_zero_pos_no_crash(session: AsyncSession) -> None:
    """A supplier with no POs returns all-zero fields, no division-by-zero."""
    svc = ProcurementService(session)
    sc = await svc.get_supplier_scorecard("does-not-exist")

    assert sc["total_po_count"] == 0
    assert sc["total_gr_count"] == 0
    assert sc["total_po_value"] == "0"
    assert sc["on_time_delivery_pct"] == 0.0
    assert sc["qty_variance_pct"] == 0.0
    assert sc["gr_rejection_rate"] == 0.0
    assert sc["currency"] == ""


@pytest.mark.asyncio
async def test_scorecard_period_window_excludes_old(session: AsyncSession) -> None:
    """POs older than period_days are excluded."""
    very_old = datetime.now(UTC) - timedelta(days=500)
    po_old = _make_po(po_number="PO-OLD", created_at=very_old)
    po_new = _make_po(po_number="PO-NEW")
    session.add_all([po_old, po_new])
    await session.flush()

    svc = ProcurementService(session)
    sc = await svc.get_supplier_scorecard(SUPPLIER_ID, period_days=365)
    # Only the new PO is in scope.
    assert sc["total_po_count"] == 1


# ── P0-2: Unscheduled PO must NOT inflate on-time score ─────────────────


@pytest.mark.asyncio
async def test_scorecard_unscheduled_po_excluded_from_on_time(
    session: AsyncSession,
) -> None:
    """GRs against POs with no delivery_date are tracked separately and
    excluded from the on-time denominator (P0-2: previously such GRs were
    counted as on-time, inflating the supplier score)."""
    # PO A: scheduled, GR arrived ON TIME.
    po_sched = _make_po(po_number="PO-SCHED", delivery_date="2026-04-10")
    # PO B: NO delivery_date (unscheduled). A GR against it must not
    # inflate the on-time count.
    po_unsched = _make_po(po_number="PO-UNSCHED", delivery_date=None)
    session.add_all([po_sched, po_unsched])
    await session.flush()

    gr_a = GoodsReceipt(po_id=po_sched.id, receipt_date="2026-04-09", status="confirmed")
    gr_b = GoodsReceipt(po_id=po_unsched.id, receipt_date="2026-04-09", status="confirmed")
    session.add_all([gr_a, gr_b])
    await session.flush()

    svc = ProcurementService(session)
    sc = await svc.get_supplier_scorecard(SUPPLIER_ID)

    # Two GRs total, but only one is schedulable.
    assert sc["total_gr_count"] == 2
    assert sc["on_time_count"] == 1
    assert sc["unscheduled_count"] == 1
    # Denominator = scheduled = 1 → on-time = 1/1 = 1.0 (NOT 2/2).
    assert sc["on_time_delivery_pct"] == pytest.approx(1.0, rel=1e-6)


@pytest.mark.asyncio
async def test_scorecard_only_unscheduled_pos_on_time_zero(
    session: AsyncSession,
) -> None:
    """Supplier with only unscheduled POs has on_time_delivery_pct == 0.0
    (no schedulable denominator) instead of inflating to 1.0."""
    po = _make_po(delivery_date=None)
    session.add(po)
    await session.flush()
    gr = GoodsReceipt(po_id=po.id, receipt_date="2026-04-09", status="confirmed")
    session.add(gr)
    await session.flush()

    svc = ProcurementService(session)
    sc = await svc.get_supplier_scorecard(SUPPLIER_ID)

    assert sc["total_gr_count"] == 1
    assert sc["unscheduled_count"] == 1
    assert sc["on_time_count"] == 0
    assert sc["on_time_delivery_pct"] == 0.0
