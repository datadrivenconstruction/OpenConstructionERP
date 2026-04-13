"""Unit tests for :class:`ProcurementService`.

Scope:
    Covers PO creation, status transitions (draft -> issued -> received),
    goods receipt creation with quantity validation, total computation,
    and the _check_po_fully_received helper. Repositories are stubbed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.procurement.schemas import GRCreate, GRItemCreate, POCreate, POItemCreate, POUpdate
from app.modules.procurement.service import (
    ProcurementService,
    _compute_po_total,
    _parse_decimal,
)

# ── Helpers / stubs ───────────────────────────────────────────────────────

PROJECT_ID = uuid.uuid4()


def _make_service() -> ProcurementService:
    service = ProcurementService.__new__(ProcurementService)
    service.session = SimpleNamespace()
    service.po_repo = _StubPORepo()
    service.po_item_repo = _StubPOItemRepo()
    service.gr_repo = _StubGRRepo()
    service.gr_item_repo = _StubGRItemRepo()
    return service


class _StubPORepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self._counter = 0

    async def create(self, po: Any) -> Any:
        if getattr(po, "id", None) is None:
            po.id = uuid.uuid4()
        now = datetime.now(UTC)
        po.created_at = now
        po.updated_at = now
        if not hasattr(po, "items"):
            po.items = []
        if not hasattr(po, "goods_receipts"):
            po.goods_receipts = []
        self.rows[po.id] = po
        return po

    async def get(self, po_id: uuid.UUID) -> Any:
        return self.rows.get(po_id)

    async def list(
        self,
        *,
        project_id: uuid.UUID | None = None,
        status: str | None = None,
        vendor_contact_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Any], int]:
        rows = list(self.rows.values())
        if project_id:
            rows = [r for r in rows if r.project_id == project_id]
        if status:
            rows = [r for r in rows if r.status == status]
        return rows[offset : offset + limit], len(rows)

    async def update(self, po_id: uuid.UUID, **kwargs: Any) -> None:
        po = self.rows.get(po_id)
        if po:
            for k, v in kwargs.items():
                setattr(po, k, v)
            po.updated_at = datetime.now(UTC)

    async def next_po_number(self, project_id: uuid.UUID) -> str:
        self._counter += 1
        return f"PO-{self._counter:04d}"

    async def stats_for_project(self, project_id: uuid.UUID) -> dict:
        return {
            "total_pos": len(self.rows),
            "by_status": {},
            "total_committed": "0",
            "total_received": 0,
            "pending_delivery_count": 0,
        }


class _StubPOItemRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def create(self, item: Any) -> Any:
        if getattr(item, "id", None) is None:
            item.id = uuid.uuid4()
        now = datetime.now(UTC)
        item.created_at = now
        item.updated_at = now
        self.rows[item.id] = item
        return item

    async def delete_by_po(self, po_id: uuid.UUID) -> None:
        self.rows = {k: v for k, v in self.rows.items() if v.po_id != po_id}


class _StubGRRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def create(self, gr: Any) -> Any:
        if getattr(gr, "id", None) is None:
            gr.id = uuid.uuid4()
        now = datetime.now(UTC)
        gr.created_at = now
        gr.updated_at = now
        if not hasattr(gr, "items"):
            gr.items = []
        self.rows[gr.id] = gr
        return gr

    async def get(self, gr_id: uuid.UUID) -> Any:
        return self.rows.get(gr_id)

    async def list(
        self,
        *,
        po_id: uuid.UUID | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Any], int]:
        rows = list(self.rows.values())
        if po_id:
            rows = [r for r in rows if r.po_id == po_id]
        return rows[offset : offset + limit], len(rows)

    async def update(self, gr_id: uuid.UUID, **kwargs: Any) -> None:
        gr = self.rows.get(gr_id)
        if gr:
            for k, v in kwargs.items():
                setattr(gr, k, v)


class _StubGRItemRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def create(self, item: Any) -> Any:
        if getattr(item, "id", None) is None:
            item.id = uuid.uuid4()
        self.rows[item.id] = item
        return item


def _po_data(**overrides: Any) -> POCreate:
    defaults = {
        "project_id": PROJECT_ID,
        "po_type": "standard",
        "amount_subtotal": "1000.00",
        "tax_amount": "190.00",
    }
    defaults.update(overrides)
    return POCreate(**defaults)


# ── Tests ─────────────────────────────────────────────────────────────────


def test_compute_po_total() -> None:
    """amount_total = subtotal + tax."""
    assert _compute_po_total("1000.00", "190.00") == "1190.00"
    assert _compute_po_total("0", "0") == "0"


def test_parse_decimal_invalid() -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        _parse_decimal("not-a-number", "test_field")
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_create_po() -> None:
    svc = _make_service()
    po = await svc.create_po(_po_data(), user_id=str(uuid.uuid4()))

    assert po.id is not None
    assert po.po_number == "PO-0001"
    assert po.amount_total == "1190.00"
    assert po.status == "draft"


@pytest.mark.asyncio
async def test_create_po_with_items() -> None:
    svc = _make_service()
    data = _po_data(
        items=[
            POItemCreate(description="Rebar 12mm", quantity="100", unit="kg", unit_rate="2.50", amount="250"),
            POItemCreate(description="Concrete C30", quantity="10", unit="m3", unit_rate="90", amount="900"),
        ],
    )
    po = await svc.create_po(data)
    # Items are created in the item repo
    assert len(svc.po_item_repo.rows) == 2


@pytest.mark.asyncio
async def test_issue_po() -> None:
    svc = _make_service()
    po = await svc.create_po(_po_data())
    assert po.status == "draft"

    issued = await svc.issue_po(po.id)
    assert issued.status == "issued"


@pytest.mark.asyncio
async def test_issue_po_non_draft_fails() -> None:
    svc = _make_service()
    po = await svc.create_po(_po_data())
    svc.po_repo.rows[po.id].status = "issued"

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await svc.issue_po(po.id)
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_update_po_status_transition_valid() -> None:
    svc = _make_service()
    po = await svc.create_po(_po_data())

    updated = await svc.update_po(po.id, POUpdate(status="issued"))
    assert updated.status == "issued"


@pytest.mark.asyncio
async def test_update_po_status_transition_invalid() -> None:
    """draft -> completed is not a valid transition."""
    svc = _make_service()
    po = await svc.create_po(_po_data())

    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await svc.update_po(po.id, POUpdate(status="completed"))
    assert exc_info.value.status_code == 400
    assert "Cannot transition" in exc_info.value.detail


@pytest.mark.asyncio
async def test_update_po_recomputes_total() -> None:
    svc = _make_service()
    po = await svc.create_po(_po_data())
    assert po.amount_total == "1190.00"

    updated = await svc.update_po(po.id, POUpdate(amount_subtotal="2000.00"))
    assert updated.amount_total == "2190.00"


@pytest.mark.asyncio
async def test_create_goods_receipt_wrong_po_status() -> None:
    """Cannot create GR for a draft PO."""
    svc = _make_service()
    po = await svc.create_po(_po_data())
    assert po.status == "draft"

    from fastapi import HTTPException

    gr_data = GRCreate(po_id=po.id, receipt_date="2026-04-10")
    with pytest.raises(HTTPException) as exc_info:
        await svc.create_goods_receipt(gr_data)
    assert exc_info.value.status_code == 400
    assert "issued or partially_received" in exc_info.value.detail


@pytest.mark.asyncio
async def test_create_goods_receipt_success() -> None:
    svc = _make_service()
    po = await svc.create_po(_po_data())
    svc.po_repo.rows[po.id].status = "issued"

    gr_data = GRCreate(po_id=po.id, receipt_date="2026-04-10")
    gr = await svc.create_goods_receipt(gr_data)
    assert gr.id is not None
    assert gr.po_id == po.id


def test_check_po_fully_received_empty_items() -> None:
    """PO with no items is considered fully received."""
    po = SimpleNamespace(items=[], goods_receipts=[])
    assert ProcurementService._check_po_fully_received(po) is True


def test_check_po_fully_received_partial() -> None:
    """PO with items not fully received returns False."""
    po_item_id = uuid.uuid4()
    po_item = SimpleNamespace(id=po_item_id, quantity="100")
    gr_item = SimpleNamespace(po_item_id=po_item_id, quantity_received="50")
    gr = SimpleNamespace(status="confirmed", items=[gr_item])
    po = SimpleNamespace(items=[po_item], goods_receipts=[gr])

    assert ProcurementService._check_po_fully_received(po) is False


def test_check_po_fully_received_complete() -> None:
    """PO fully received returns True."""
    po_item_id = uuid.uuid4()
    po_item = SimpleNamespace(id=po_item_id, quantity="100")
    gr_item = SimpleNamespace(po_item_id=po_item_id, quantity_received="100")
    gr = SimpleNamespace(status="confirmed", items=[gr_item])
    po = SimpleNamespace(items=[po_item], goods_receipts=[gr])

    assert ProcurementService._check_po_fully_received(po) is True
