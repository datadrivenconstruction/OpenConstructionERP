"""A purchase order that has left draft keeps the figures it was approved with.

Approval is given to a sum, a vendor and a list of lines, and finance takes
its commitment for exactly that sum. ``update_po`` used to let a PATCH change
all of them afterwards, so a small order could be approved and issued and then
raised to any amount without the approval rules ever seeing it. It also let a
PATCH move an order straight into ``issued``, skipping the vendor re-check the
issue action makes.

Each group below pairs the guard that already existed with the new refusal and
with the corrections that must stay possible.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.procurement.models import GoodsReceipt
from app.modules.procurement.schemas import POItemCreate, POUpdate
from app.modules.procurement.service import ProcurementService
from tests.unit.test_procurement import _approvable_po_data, _make_service


async def _po_in(status: str) -> tuple[ProcurementService, Any]:
    """An approvable order (one line: 10 t cement at 100.00), moved to ``status``."""
    svc = _make_service()
    po = await svc.create_po(_approvable_po_data())
    repo: Any = svc.po_repo  # the in-memory stand-in from test_procurement, which keeps its rows
    row = repo.rows[po.id]
    row.status = status
    return svc, row


def _lines(svc: ProcurementService, po_id: Any) -> list[tuple[str, str, str]]:
    repo: Any = svc.po_item_repo
    return sorted((it.description, it.quantity, it.amount) for it in repo.rows.values() if it.po_id == po_id)


def _cement(quantity: str = "10", amount: str = "1000.00") -> POItemCreate:
    return POItemCreate(
        description="Cement",
        quantity=quantity,
        unit="ton",
        unit_rate="100.00",
        amount=amount,
        cost_category="materials",
    )


# ── Control: the guard that was already there ───────────────────────────────


@pytest.mark.asyncio
async def test_control_lines_of_a_delivered_order_are_still_refused_for_goods_receipts() -> None:
    svc, po = await _po_in("partially_received")
    po.goods_receipts = [GoodsReceipt(po_id=po.id, receipt_date="2026-04-10", status="confirmed")]

    with pytest.raises(HTTPException) as exc:
        await svc.update_po(po.id, POUpdate(items=[_cement(quantity="5", amount="0")]))

    assert exc.value.status_code == 409
    assert "goods receipts" in exc.value.detail
    assert _lines(svc, po.id) == [("Cement", "10", "1000.00")]


# ── The refusal ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_approved_order_cannot_be_raised_in_place() -> None:
    svc, po = await _po_in("approved")

    with pytest.raises(HTTPException) as exc:
        await svc.update_po(po.id, POUpdate(amount_subtotal="900000.00"))

    assert exc.value.status_code == 409
    assert "approved" in exc.value.detail
    assert "amounts" in exc.value.detail
    assert "draft" in exc.value.detail, "the refusal must name the way to correct the order"
    assert po.amount_subtotal == "1000.00"
    assert po.amount_total == "1190.00"


@pytest.mark.asyncio
async def test_an_approved_order_keeps_its_lines() -> None:
    svc, po = await _po_in("approved")

    with pytest.raises(HTTPException) as exc:
        await svc.update_po(po.id, POUpdate(items=[_cement(quantity="900", amount="0")]))

    assert exc.value.status_code == 409
    assert "line items" in exc.value.detail
    assert _lines(svc, po.id) == [("Cement", "10", "1000.00")]
    assert po.amount_subtotal == "1000.00"


@pytest.mark.asyncio
async def test_an_approved_order_keeps_its_vendor_and_currency() -> None:
    svc, po = await _po_in("approved")
    vendor, currency = po.vendor_contact_id, po.currency_code

    with pytest.raises(HTTPException) as exc:
        await svc.update_po(
            po.id,
            POUpdate(vendor_contact_id="00000000-0000-0000-0000-000000000042", currency_code="USD"),
        )

    assert exc.value.status_code == 409
    assert "currency and vendor" in exc.value.detail
    assert (po.vendor_contact_id, po.currency_code) == (vendor, currency)


@pytest.mark.asyncio
async def test_an_issued_order_is_told_to_cancel_and_reopen() -> None:
    svc, po = await _po_in("issued")

    with pytest.raises(HTTPException) as exc:
        await svc.update_po(po.id, POUpdate(amount_subtotal="5000.00", tax_amount="950.00"))

    assert exc.value.status_code == 409
    assert "Cancel it and reopen it as a draft" in exc.value.detail
    assert po.amount_total == "1190.00"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["partially_received", "completed"])
async def test_a_received_order_is_told_to_raise_a_separate_order(status: str) -> None:
    svc, po = await _po_in(status)

    with pytest.raises(HTTPException) as exc:
        await svc.update_po(po.id, POUpdate(tax_amount="0"))

    assert exc.value.status_code == 409
    assert "separate purchase order" in exc.value.detail
    assert po.tax_amount == "190.00"


@pytest.mark.asyncio
async def test_a_cancelled_order_is_not_rewritten_while_it_stays_cancelled() -> None:
    svc, po = await _po_in("cancelled")

    with pytest.raises(HTTPException) as exc:
        await svc.update_po(po.id, POUpdate(amount_subtotal="1.00"))

    assert exc.value.status_code == 409
    assert "Reopen it as a draft" in exc.value.detail
    assert po.amount_subtotal == "1000.00"


@pytest.mark.asyncio
async def test_a_patch_cannot_issue_an_order() -> None:
    svc, po = await _po_in("approved")

    with pytest.raises(HTTPException) as exc:
        await svc.update_po(po.id, POUpdate(status="issued"))

    assert exc.value.status_code == 409
    assert "issue action" in exc.value.detail
    assert po.status == "approved"


# ── What stays possible ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_approved_order_is_corrected_on_its_way_back_to_draft() -> None:
    svc, po = await _po_in("approved")

    updated = await svc.update_po(po.id, POUpdate(status="draft", amount_subtotal="2000.00"))

    assert updated.status == "draft"
    assert updated.amount_total == "2190.00"


@pytest.mark.asyncio
async def test_a_cancelled_order_is_corrected_when_it_is_reopened() -> None:
    svc, po = await _po_in("cancelled")

    updated = await svc.update_po(po.id, POUpdate(status="draft", items=[_cement(quantity="12", amount="0")]))

    assert updated.status == "draft"
    assert _lines(svc, po.id) == [("Cement", "12", "1200.00")]


@pytest.mark.asyncio
async def test_sending_back_the_stored_figures_is_not_a_change() -> None:
    """The same amounts written differently, the same vendor and currency, the line with its amount left to derive."""
    svc, po = await _po_in("issued")

    updated = await svc.update_po(
        po.id,
        POUpdate(
            amount_subtotal="1000",
            tax_amount="190.0",
            currency_code=po.currency_code,
            vendor_contact_id=po.vendor_contact_id,
            items=[_cement(quantity="10.000", amount="0")],
        ),
    )

    assert updated.status == "issued"
    assert Decimal(updated.amount_total) == Decimal("1190")


@pytest.mark.asyncio
async def test_notes_and_dates_stay_editable_on_an_issued_order() -> None:
    svc, po = await _po_in("issued")

    updated = await svc.update_po(
        po.id,
        POUpdate(notes="deliver to gate 3", delivery_date="2026-11-02", payment_terms="Net 45"),
    )

    assert updated.notes == "deliver to gate 3"
    assert updated.delivery_date == "2026-11-02"
    assert updated.payment_terms == "Net 45"


@pytest.mark.asyncio
async def test_a_draft_order_is_still_edited_freely() -> None:
    svc, po = await _po_in("draft")

    updated = await svc.update_po(
        po.id,
        POUpdate(currency_code="USD", items=[_cement(quantity="900", amount="0")]),
    )

    assert updated.currency_code == "USD"
    assert _lines(svc, po.id) == [("Cement", "900", "90000.00")]
