"""The warehouse listing must not return other projects' warehouses."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.dialects import postgresql

import app.dependencies as deps
from app.modules.supplier_catalogs.repository import WarehouseRepository
from app.modules.supplier_catalogs.service import SupplierCatalogsService


class _Repo:
    seen: object = "unset"

    async def list(self, *, project_ids=None, limit=1000):
        _Repo.seen = project_ids
        return []


@pytest.mark.asyncio
async def test_service_scopes_listing_to_accessible_projects(monkeypatch) -> None:
    mine = {uuid.uuid4()}

    async def fake(session, user_id, **kw):
        return mine

    monkeypatch.setattr(deps, "accessible_project_ids", fake)
    svc = SupplierCatalogsService.__new__(SupplierCatalogsService)
    svc.session = None
    svc.warehouses = _Repo()
    await svc.list_warehouses(user_id="u")
    assert _Repo.seen == mine


@pytest.mark.asyncio
async def test_repository_filter_keeps_global_and_own_projects() -> None:
    captured = {}

    class _Sess:
        async def execute(self, stmt):
            captured["sql"] = str(stmt.compile(dialect=postgresql.dialect()))

            class _R:
                def scalars(self):
                    return self

                def all(self):
                    return []

            return _R()

    await WarehouseRepository(_Sess()).list(project_ids={uuid.uuid4()})
    sql = captured["sql"]
    assert "project_id IS NULL" in sql and "project_id IN" in sql and "LIMIT" in sql


class _Wh:
    project_id = None


class _Stock:
    async def get_or_create_balance(self, **kw):
        raise AssertionError("must be refused before touching stock")

    get_balance = get_or_create_balance


class _Whs:
    async def get(self, _id):
        return _Wh()


def _svc_denying_foreign(foreign: uuid.UUID) -> SupplierCatalogsService:
    svc = SupplierCatalogsService.__new__(SupplierCatalogsService)
    svc.session = None
    svc.warehouses = _Whs()
    svc.stock = _Stock()

    async def guard(project_id, user_id):
        if project_id == foreign:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Project not found")

    svc._guard_project = guard  # type: ignore[method-assign]
    return svc


@pytest.mark.asyncio
async def test_issue_to_foreign_project_is_refused() -> None:
    from fastapi import HTTPException

    from app.modules.supplier_catalogs.schemas import StockIssuePayload

    foreign = uuid.uuid4()
    payload = StockIssuePayload(
        catalog_item_id=uuid.uuid4(), warehouse_id=uuid.uuid4(), quantity=1, to_project_id=foreign
    )
    with pytest.raises(HTTPException) as exc:
        await _svc_denying_foreign(foreign).issue_stock(payload, user_id="u")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_reserve_for_foreign_project_is_refused() -> None:
    from fastapi import HTTPException

    from app.modules.supplier_catalogs.schemas import StockReservePayload

    foreign = uuid.uuid4()
    payload = StockReservePayload(
        catalog_item_id=uuid.uuid4(), warehouse_id=uuid.uuid4(), quantity=1, project_id=foreign
    )
    with pytest.raises(HTTPException) as exc:
        await _svc_denying_foreign(foreign).reserve_stock(payload, user_id="u")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_stocktake_below_reserved_clamps_reservation() -> None:
    from decimal import Decimal

    from app.modules.supplier_catalogs.schemas import StocktakeCount, StocktakePayload

    class _Bal:
        id = uuid.uuid4()
        quantity_on_hand = Decimal("10")
        quantity_reserved = Decimal("8")
        unit_cost_avg = None
        currency = None

    updates: list[dict] = []

    class _St:
        async def get_or_create_balance(self, **kw):
            return _Bal()

        async def update_balance(self, _id, **kw):
            updates.append(kw)

        async def record_movement(self, mv):
            return mv

    svc = _svc_denying_foreign(uuid.uuid4())
    svc.stock = _St()
    payload = StocktakePayload(counts=[StocktakeCount(catalog_item_id=uuid.uuid4(), counted_qty=3)])
    await svc.stocktake(uuid.uuid4(), payload, user_id="u")
    assert updates[0]["quantity_reserved"] == Decimal("3")
