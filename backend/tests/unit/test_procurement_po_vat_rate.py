# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A purchase order carries a VAT rate, and a new order starts at the project's.

Issue #515: a new order ignored the project's default VAT rate and left the tax
at zero, so the buyer had to work the tax out by hand and type it as an amount.
The order now stores ``tax_rate`` (a percentage) beside ``tax_amount`` and the
tax follows the net:

* a create that names neither a rate nor a tax amount takes the project's
  default rate;
* a create or PATCH that names a rate gets tax = net x rate / 100, to the cent;
* a create or PATCH that names only a tax amount keeps that amount as typed and
  clears the rate, because a hand-typed tax is not derived from anything;
* replacing the lines of an order that has a rate re-derives the tax from the
  new net, from the order's own rate and never from the project's current one,
  so changing the project default does not rewrite existing orders.

Repositories are stubbed, mirroring ``test_procurement_po_removal.py``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from app.modules.procurement.schemas import POCreate, POItemCreate, POUpdate
from app.modules.procurement.service import ProcurementService, _tax_from_rate

PROJECT_ID = uuid.uuid4()


class _StubPORepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self._counter = 0
        self._item_repo: _StubPOItemRepo | None = None

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
        po = self.rows.get(po_id)
        if po is not None and self._item_repo is not None:
            po.items = [it for it in self._item_repo.rows.values() if it.po_id == po_id]
        return po

    async def update(self, po_id: uuid.UUID, **kwargs: Any) -> None:
        po = self.rows.get(po_id)
        if po:
            for k, v in kwargs.items():
                setattr(po, k, v)

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


class _EmptyResult:
    def all(self) -> list[Any]:
        return []

    def scalar_one_or_none(self) -> Any:
        return None


class _StubSession:
    def expunge(self, _obj: Any) -> None:
        return None

    async def execute(self, _stmt: Any) -> _EmptyResult:
        return _EmptyResult()


def _make_service(project_rate: str | None) -> ProcurementService:
    svc = ProcurementService.__new__(ProcurementService)
    svc.session = _StubSession()
    svc.po_repo = _StubPORepo()
    svc.po_item_repo = _StubPOItemRepo()
    svc.po_repo._item_repo = svc.po_item_repo

    async def _rate(_project_id: uuid.UUID) -> str | None:
        return project_rate

    svc._project_default_vat_rate = _rate  # type: ignore[method-assign]
    return svc


def _line(qty: str, rate: str) -> POItemCreate:
    return POItemCreate(description="Rebar", quantity=qty, unit="t", unit_rate=rate)


# ── Pure arithmetic ────────────────────────────────────────────────────────


def test_tax_from_rate_rounds_half_up_to_the_cent() -> None:
    assert _tax_from_rate("333.33", "7.5") == "25.00"
    assert _tax_from_rate("1000", "5") == "50.00"
    assert _tax_from_rate("0", "21") == "0.00"


def test_schema_refuses_a_rate_outside_zero_to_hundred() -> None:
    with pytest.raises(ValidationError):
        POCreate(project_id=PROJECT_ID, tax_rate="150")
    with pytest.raises(ValidationError):
        POUpdate(tax_rate="-1")


# ── Create ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_new_order_takes_the_project_default_rate() -> None:
    svc = _make_service("5")
    po = await svc.create_po(POCreate(project_id=PROJECT_ID, items=[_line("10", "100")]))
    assert po.tax_rate == "5"
    assert po.amount_subtotal == "1000"
    assert po.tax_amount == "50.00"
    assert po.amount_total == "1050.00"


@pytest.mark.asyncio
async def test_explicit_rate_wins_over_the_project_default() -> None:
    svc = _make_service("5")
    po = await svc.create_po(POCreate(project_id=PROJECT_ID, tax_rate="21", items=[_line("10", "100")]))
    assert po.tax_rate == "21"
    assert po.tax_amount == "210.00"
    assert po.amount_total == "1210.00"


@pytest.mark.asyncio
async def test_a_typed_tax_amount_is_kept_and_carries_no_rate() -> None:
    svc = _make_service("5")
    po = await svc.create_po(POCreate(project_id=PROJECT_ID, tax_amount="30", items=[_line("10", "100")]))
    assert po.tax_rate is None
    assert po.tax_amount == "30"
    assert po.amount_total == "1030"


@pytest.mark.asyncio
async def test_no_project_default_leaves_the_order_untaxed() -> None:
    svc = _make_service(None)
    po = await svc.create_po(POCreate(project_id=PROJECT_ID, items=[_line("10", "100")]))
    assert po.tax_rate is None
    assert po.tax_amount == "0"
    assert po.amount_total == "1000"


# ── Update ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_replacing_lines_rederives_tax_from_the_orders_own_rate() -> None:
    svc = _make_service("5")
    po = await svc.create_po(POCreate(project_id=PROJECT_ID, items=[_line("10", "100")]))
    # The project default moves on; the order keeps the rate it was raised at.
    svc._project_default_vat_rate = _make_service("20")._project_default_vat_rate  # type: ignore[method-assign]
    updated = await svc.update_po(po.id, POUpdate(items=[_line("20", "100")]))
    assert updated.tax_rate == "5"
    assert updated.amount_subtotal == "2000"
    assert updated.tax_amount == "100.00"
    assert updated.amount_total == "2100.00"


@pytest.mark.asyncio
async def test_changing_the_rate_recomputes_tax_and_total() -> None:
    svc = _make_service("5")
    po = await svc.create_po(POCreate(project_id=PROJECT_ID, items=[_line("10", "100")]))
    updated = await svc.update_po(po.id, POUpdate(tax_rate="19"))
    assert updated.tax_rate == "19"
    assert updated.tax_amount == "190.00"
    assert updated.amount_total == "1190.00"


@pytest.mark.asyncio
async def test_typing_a_tax_amount_clears_the_rate() -> None:
    svc = _make_service("5")
    po = await svc.create_po(POCreate(project_id=PROJECT_ID, items=[_line("10", "100")]))
    updated = await svc.update_po(po.id, POUpdate(tax_amount="12.34"))
    assert updated.tax_rate is None
    assert updated.tax_amount == "12.34"
    assert updated.amount_total == "1012.34"


@pytest.mark.asyncio
async def test_patch_without_tax_fields_keeps_the_rate_and_tax() -> None:
    svc = _make_service("5")
    po = await svc.create_po(POCreate(project_id=PROJECT_ID, items=[_line("10", "100")]))
    updated = await svc.update_po(po.id, POUpdate(notes="call before delivery"))
    assert updated.tax_rate == "5"
    assert updated.tax_amount == "50.00"
    assert updated.amount_total == "1050.00"
