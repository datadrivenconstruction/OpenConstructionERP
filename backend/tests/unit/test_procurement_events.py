"""Event-emission tests for the Procurement service (slice E).

Verifies the events listed in the service module docstring fire on the
correct mutation paths.  Uses the same stub-based pattern as
``test_procurement.py`` so we exercise the real service code without a
database.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.events import Event, event_bus
from app.modules.procurement.schemas import (
    GRCreate,
    GRItemCreate,
    POCreate,
    POItemCreate,
    POUpdate,
)
from app.modules.procurement.service import ProcurementService

PROJECT_ID = uuid.uuid4()


# ── Reuse the same stubs as test_procurement.py (kept local for isolation) ──


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

    async def update(self, po_id: uuid.UUID, **kwargs: Any) -> None:
        po = self.rows.get(po_id)
        if po:
            for k, v in kwargs.items():
                setattr(po, k, v)
            po.updated_at = datetime.now(UTC)

    async def next_po_number(self, project_id: uuid.UUID) -> str:
        self._counter += 1
        return f"PO-{self._counter:04d}"


class _StubPOItemRepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    async def create(self, item: Any) -> Any:
        if getattr(item, "id", None) is None:
            item.id = uuid.uuid4()
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
        if not hasattr(gr, "items"):
            gr.items = []
        self.rows[gr.id] = gr
        return gr

    async def get(self, gr_id: uuid.UUID) -> Any:
        return self.rows.get(gr_id)

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


def _make_service() -> ProcurementService:
    svc = ProcurementService.__new__(ProcurementService)
    svc.session = SimpleNamespace()
    svc.po_repo = _StubPORepo()
    svc.po_item_repo = _StubPOItemRepo()
    svc.gr_repo = _StubGRRepo()
    svc.gr_item_repo = _StubGRItemRepo()
    return svc


def _po_data(**overrides: Any) -> POCreate:
    defaults = {
        "project_id": PROJECT_ID,
        "po_type": "standard",
        "amount_subtotal": "1000.00",
        "tax_amount": "190.00",
    }
    defaults.update(overrides)
    return POCreate(**defaults)


@pytest.fixture
def captured_events():
    captured: list[Event] = []

    async def _capture(event: Event) -> None:
        captured.append(event)

    event_bus.subscribe("*", _capture)
    try:
        yield captured
    finally:
        event_bus.unsubscribe("*", _capture)


# ── Tests ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_po_emits_po_created(captured_events: list[Event]) -> None:
    svc = _make_service()
    po = await svc.create_po(
        _po_data(items=[POItemCreate(description="Cement", quantity="10", unit="t", unit_rate="100", amount="1000")])
    )

    matches = [e for e in captured_events if e.name == "procurement.po.created"]
    assert len(matches) == 1
    payload = matches[0].data
    assert payload["po_id"] == str(po.id)
    assert payload["po_number"] == po.po_number
    assert payload["status"] == "draft"
    assert payload["item_count"] == 1
    assert payload["amount_total"] == "1190.00"
    assert matches[0].source_module == "oe_procurement"


@pytest.mark.asyncio
async def test_update_po_emits_po_updated(captured_events: list[Event]) -> None:
    svc = _make_service()
    po = await svc.create_po(_po_data())
    captured_events.clear()

    await svc.update_po(po.id, POUpdate(notes="updated"))

    matches = [e for e in captured_events if e.name == "procurement.po.updated"]
    assert len(matches) == 1
    payload = matches[0].data
    assert payload["po_id"] == str(po.id)
    assert "notes" in payload["updated_fields"]


@pytest.mark.asyncio
async def test_issue_po_emits_po_issued(captured_events: list[Event]) -> None:
    svc = _make_service()
    po = await svc.create_po(_po_data())
    captured_events.clear()

    await svc.issue_po(po.id)

    matches = [e for e in captured_events if e.name == "procurement.po.issued"]
    assert len(matches) == 1
    assert matches[0].data["po_id"] == str(po.id)
    assert matches[0].data["po_number"] == po.po_number


@pytest.mark.asyncio
async def test_create_goods_receipt_emits_gr_created(captured_events: list[Event]) -> None:
    svc = _make_service()
    po = await svc.create_po(_po_data())
    # Move PO into a state that accepts GRs
    svc.po_repo.rows[po.id].status = "issued"
    captured_events.clear()

    gr = await svc.create_goods_receipt(
        GRCreate(
            po_id=po.id,
            receipt_date="2026-04-26",
            items=[GRItemCreate(quantity_ordered="1", quantity_received="1")],
        )
    )

    matches = [e for e in captured_events if e.name == "procurement.gr.created"]
    assert len(matches) == 1
    payload = matches[0].data
    assert payload["gr_id"] == str(gr.id)
    assert payload["po_id"] == str(po.id)
    assert payload["item_count"] == 1


@pytest.mark.asyncio
async def test_confirm_goods_receipt_emits_gr_confirmed(captured_events: list[Event]) -> None:
    svc = _make_service()
    po = await svc.create_po(_po_data())
    svc.po_repo.rows[po.id].status = "issued"
    gr = await svc.create_goods_receipt(
        GRCreate(
            po_id=po.id,
            receipt_date="2026-04-26",
            items=[GRItemCreate(quantity_ordered="1", quantity_received="1")],
        )
    )
    captured_events.clear()

    await svc.confirm_goods_receipt(gr.id)

    matches = [e for e in captured_events if e.name == "procurement.gr.confirmed"]
    assert len(matches) == 1
    assert matches[0].data["gr_id"] == str(gr.id)
    assert matches[0].data["po_id"] == str(po.id)
