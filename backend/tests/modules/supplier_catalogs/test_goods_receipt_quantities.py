"""Goods receipt quantities cannot exceed what arrived or what is outstanding."""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.supplier_catalogs.schemas import GoodsReceiptCreate, GRLineCreate
from app.modules.supplier_catalogs.service import SupplierCatalogsService


def test_accepted_more_than_received_is_rejected() -> None:
    with pytest.raises(ValidationError):
        GRLineCreate(po_line_id=uuid.uuid4(), received_qty=Decimal("5"), accepted_qty=Decimal("50"))


def test_rejected_more_than_received_is_rejected() -> None:
    with pytest.raises(ValidationError):
        GRLineCreate(po_line_id=uuid.uuid4(), received_qty=Decimal("5"), rejected_qty=Decimal("6"))


def test_accepted_plus_rejected_over_received_is_rejected() -> None:
    with pytest.raises(ValidationError):
        GRLineCreate(
            po_line_id=uuid.uuid4(), received_qty=Decimal("5"), accepted_qty=Decimal("4"), rejected_qty=Decimal("3")
        )


def test_valid_split_passes() -> None:
    GRLineCreate(
        po_line_id=uuid.uuid4(), received_qty=Decimal("5"), accepted_qty=Decimal("4"), rejected_qty=Decimal("1")
    )


def _svc(po, warehouse, foreign: uuid.UUID | None = None) -> SupplierCatalogsService:
    svc = SupplierCatalogsService.__new__(SupplierCatalogsService)
    svc.session = None

    class _Pos:
        async def get(self, _id):
            return po

    class _Whs:
        async def get(self, _id):
            return warehouse

    svc.pos = _Pos()
    svc.warehouses = _Whs()

    async def guard(project_id, user_id):
        if project_id is not None and project_id == foreign:
            raise HTTPException(status_code=404, detail="Project not found")

    svc._guard_project = guard  # type: ignore[method-assign]
    return svc


def _po(line_id: uuid.UUID):
    line = SimpleNamespace(id=line_id, ordered_qty=Decimal("10"), received_qty=Decimal("0"), description="x")
    return SimpleNamespace(id=uuid.uuid4(), project_id=uuid.uuid4(), migrated_to_id=None, status="sent", lines=[line])


@pytest.mark.asyncio
async def test_receipt_into_foreign_projects_warehouse_is_refused() -> None:
    line_id = uuid.uuid4()
    foreign = uuid.uuid4()
    svc = _svc(_po(line_id), SimpleNamespace(project_id=foreign), foreign=foreign)
    data = GoodsReceiptCreate(
        po_id=uuid.uuid4(),
        warehouse_id=uuid.uuid4(),
        lines=[GRLineCreate(po_line_id=line_id, received_qty=Decimal("1"))],
    )
    with pytest.raises(HTTPException) as exc:
        await svc.post_goods_receipt(data, user_id="u")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_same_po_line_twice_cannot_exceed_outstanding() -> None:
    line_id = uuid.uuid4()
    svc = _svc(_po(line_id), SimpleNamespace(project_id=None))
    data = GoodsReceiptCreate(
        po_id=uuid.uuid4(),
        warehouse_id=uuid.uuid4(),
        lines=[GRLineCreate(po_line_id=line_id, received_qty=Decimal("6")) for _ in range(2)],
    )
    with pytest.raises(HTTPException) as exc:
        await svc.post_goods_receipt(data, user_id="u")
    assert exc.value.status_code == 400
    assert "exceeds outstanding" in exc.value.detail
