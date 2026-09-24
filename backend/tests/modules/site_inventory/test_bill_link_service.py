# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Service-level tests for the site-inventory link to the priced bill.

The pure arithmetic is pinned DB-free in
:mod:`tests.unit.test_site_inventory_bill_link`. What is left to prove is the
wiring the service owns and the ledger cannot see:

1. attribution is resolved *before* the BoQ budgets are looked up, so an
   inherited position is priced against its real budget and not against zero;
2. a requisition line from another project is refused, because the database FK
   only rejects an id that does not exist;
3. ``update_item`` writes the fields that were sent and leaves the rest alone.

Following the convention of the neighbouring procurement suite, the session and
the cross-module loaders are stubbed in memory, so these run without Postgres
or the FastAPI lifespan and cannot be silently skipped for want of a database.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.modules.site_inventory.schemas import StockItemUpdate
from app.modules.site_inventory.service import SiteInventoryService

PROJECT_ID = uuid.uuid4()
POSITION_ID = uuid.uuid4()
ITEM_ID = uuid.uuid4()
REQ_ITEM_ID = uuid.uuid4()


class _Row:
    """A stand-in for an ORM row: attributes only, no session behaviour."""

    def __init__(self, **fields: object) -> None:
        for name, value in fields.items():
            setattr(self, name, value)


def _movement(movement_type: str, quantity: str, *, unit_cost: str = "0", **extra: object) -> _Row:
    """A persisted-movement stand-in with every column the projection reads."""
    defaults: dict[str, object] = {
        "movement_type": movement_type,
        "quantity": Decimal(quantity),
        "unit_cost": Decimal(unit_cost),
        "currency": "EUR",
        "item_id": ITEM_ID,
        "location_id": None,
        "to_location_id": None,
        "boq_position_id": None,
        "occurred_at": None,
    }
    defaults.update(extra)
    return _Row(**defaults)


def _item(**extra: object) -> _Row:
    """A persisted-item stand-in with every column the projection reads."""
    defaults: dict[str, object] = {
        "id": ITEM_ID,
        "name": "C30/37",
        "unit": "m3",
        "boq_position_id": None,
        "procurement_req_item_id": None,
        "standard_unit_cost": None,
        "currency": "EUR",
    }
    defaults.update(extra)
    return _Row(**defaults)


def _service() -> SiteInventoryService:
    """A service whose session is never touched, because every loader is stubbed."""
    return SiteInventoryService(session=None)  # type: ignore[arg-type]


# -- 1. Budgets are looked up after attribution is resolved ------------------


@pytest.mark.asyncio
async def test_variance_report_budgets_the_inherited_position() -> None:
    """The blocker: an inherited position must reach ``_position_budgets``.

    The consumption carries no position of its own; the item it moves is linked
    to one. If the budget set were derived from the raw movements, this position
    would never be asked for, the line would be priced at a zero budget, and the
    report would read as broken on exactly the rows the item link enables.
    """
    service = _service()
    asked_for: list[set] = []

    async def _all_movements(_project_id):
        return [_movement("CONSUMPTION", "10", unit_cost="30")]

    async def _list_items(_project_id):
        return [_item(boq_position_id=POSITION_ID)]

    async def _position_budgets(_project_id, position_ids):
        asked_for.append(set(position_ids))
        return {str(POSITION_ID): Decimal("250")}

    service._all_movements = _all_movements  # type: ignore[method-assign]
    service.list_items = _list_items  # type: ignore[method-assign]
    service._position_budgets = _position_budgets  # type: ignore[method-assign]

    payload = await service.material_variance_report(PROJECT_ID)

    assert asked_for == [{str(POSITION_ID)}]
    assert payload["position_count"] == 1
    line = payload["lines"][0]
    assert line["position_id"] == str(POSITION_ID)
    assert line["actual_cost"] == "300.00"
    assert line["budgeted_cost"] == "250.00"
    assert line["variance"] == "50.00"
    # The budget was real, so the percentage is a number rather than "unknown".
    assert line["variance_pct"] == "20.00"


@pytest.mark.asyncio
async def test_variance_report_ignores_an_unlinked_item() -> None:
    """Consumption on an item linked to nothing stays unattributable."""
    service = _service()

    async def _all_movements(_project_id):
        return [_movement("CONSUMPTION", "10", unit_cost="30")]

    async def _list_items(_project_id):
        return [_item()]

    async def _position_budgets(_project_id, position_ids):
        assert not {p for p in position_ids if p}
        return {}

    service._all_movements = _all_movements  # type: ignore[method-assign]
    service.list_items = _list_items  # type: ignore[method-assign]
    service._position_budgets = _position_budgets  # type: ignore[method-assign]

    payload = await service.material_variance_report(PROJECT_ID)
    assert payload["lines"] == []


@pytest.mark.asyncio
async def test_unfixed_value_report_totals_per_currency() -> None:
    service = _service()

    async def _all_movements(_project_id):
        return [
            _movement("INBOUND", "100", unit_cost="12"),
            _movement("CONSUMPTION", "30", unit_cost="12"),
        ]

    async def _list_items(_project_id):
        return [_item()]

    service._all_movements = _all_movements  # type: ignore[method-assign]
    service.list_items = _list_items  # type: ignore[method-assign]

    payload = await service.unfixed_value_report(PROJECT_ID)
    # 70 m3 still standing on site at 12 = 840
    assert payload["lines"][0]["on_hand"] == "70.0000"
    assert payload["totals_by_currency"] == [{"currency": "EUR", "value": "840.00"}]
    assert payload["project_id"] == str(PROJECT_ID)


@pytest.mark.asyncio
async def test_coverage_report_asks_for_the_inherited_position() -> None:
    """The coverage loaders must be fed the resolved ids, like the budgets are."""
    service = _service()
    wanted_positions: list[set] = []
    wanted_req_items: list[set] = []

    async def _all_movements(_project_id):
        return [_movement("INBOUND", "120", unit_cost="12")]

    async def _list_items(_project_id):
        return [_item(boq_position_id=POSITION_ID, procurement_req_item_id=REQ_ITEM_ID)]

    async def _position_refs(_project_id, position_ids):
        wanted_positions.append(set(position_ids))
        from app.modules.site_inventory import ledger

        return {
            str(POSITION_ID): ledger.PositionRef(
                position_id=str(POSITION_ID),
                ordinal="1.1",
                unit="m3",
                quantity=Decimal("200"),
            ),
        }

    async def _ordered_refs(_project_id, req_item_ids):
        wanted_req_items.append(set(req_item_ids))
        from app.modules.site_inventory import ledger

        return {
            str(REQ_ITEM_ID): ledger.OrderedRef(
                req_item_id=str(REQ_ITEM_ID),
                unit="m3",
                quantity_ordered=Decimal("150"),
            ),
        }

    service._all_movements = _all_movements  # type: ignore[method-assign]
    service.list_items = _list_items  # type: ignore[method-assign]
    service._position_refs = _position_refs  # type: ignore[method-assign]
    service._ordered_refs = _ordered_refs  # type: ignore[method-assign]

    payload = await service.position_coverage_report(PROJECT_ID)

    assert wanted_positions == [{str(POSITION_ID)}]
    assert wanted_req_items == [{str(REQ_ITEM_ID)}]
    line = payload["lines"][0]
    assert line["ordered_quantity"] == "150.0000"
    assert line["delivered_quantity"] == "120.0000"
    assert line["outstanding_quantity"] == "30.0000"
    assert line["delivered_pct"] == "60.00"
    assert payload["unmatched_unit_count"] == 0


@pytest.mark.asyncio
async def test_coverage_report_counts_the_unit_mismatches() -> None:
    """The page needs to know how many rows it had to withhold a figure for."""
    service = _service()

    async def _all_movements(_project_id):
        return [_movement("INBOUND", "40")]

    async def _list_items(_project_id):
        return [_item(unit="pcs", boq_position_id=POSITION_ID)]

    async def _position_refs(_project_id, _position_ids):
        from app.modules.site_inventory import ledger

        return {
            str(POSITION_ID): ledger.PositionRef(
                position_id=str(POSITION_ID),
                unit="m2",
                quantity=Decimal("500"),
            ),
        }

    async def _ordered_refs(_project_id, _req_item_ids):
        return {}

    service._all_movements = _all_movements  # type: ignore[method-assign]
    service.list_items = _list_items  # type: ignore[method-assign]
    service._position_refs = _position_refs  # type: ignore[method-assign]
    service._ordered_refs = _ordered_refs  # type: ignore[method-assign]

    payload = await service.position_coverage_report(PROJECT_ID)
    assert payload["unmatched_unit_count"] == 1
    assert payload["lines"][0]["delivered_pct"] is None


# -- 2. A foreign requisition line is refused --------------------------------


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_update_item_rejects_a_foreign_requisition_line() -> None:
    """The FK accepts another project's line; the ownership guard must not."""
    service = _service()

    async def _get_item(_project_id, _item_id):
        return _item()

    async def _require_req_item_in_project(_project_id, _req_item_id):
        raise HTTPException(status_code=404, detail="Requisition line not found in this project")

    service.get_item = _get_item  # type: ignore[method-assign]
    service._require_req_item_in_project = _require_req_item_in_project  # type: ignore[method-assign]

    with pytest.raises(HTTPException) as excinfo:
        await service.update_item(
            PROJECT_ID,
            ITEM_ID,
            StockItemUpdate(procurement_req_item_id=REQ_ITEM_ID),
        )
    assert excinfo.value.status_code == 404


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_update_item_rejects_a_foreign_position() -> None:
    service = _service()

    async def _get_item(_project_id, _item_id):
        return _item()

    async def _require_boq_position_in_project(_project_id, _position_id):
        raise HTTPException(status_code=404, detail="BoQ position not found in this project")

    service.get_item = _get_item  # type: ignore[method-assign]
    service._require_boq_position_in_project = _require_boq_position_in_project  # type: ignore[method-assign]

    with pytest.raises(HTTPException) as excinfo:
        await service.update_item(PROJECT_ID, ITEM_ID, StockItemUpdate(boq_position_id=POSITION_ID))
    assert excinfo.value.status_code == 404


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_update_item_404s_on_an_item_from_another_project() -> None:
    service = _service()

    async def _get_item(_project_id, _item_id):
        return None

    service.get_item = _get_item  # type: ignore[method-assign]

    with pytest.raises(HTTPException) as excinfo:
        await service.update_item(PROJECT_ID, ITEM_ID, StockItemUpdate(name="X"))
    assert excinfo.value.status_code == 404


# -- 3. update_item writes only what was sent --------------------------------


@pytest.mark.asyncio
async def test_update_item_links_without_disturbing_the_rest() -> None:
    """Linking an existing item must not blank the fields nobody sent."""
    service = _service()
    row = _item(name="C30/37", unit="m3", standard_unit_cost=Decimal("12"))
    flushed: list[bool] = []

    class _Session:
        async def flush(self) -> None:
            flushed.append(True)

    service.session = _Session()  # type: ignore[assignment]

    async def _get_item(_project_id, _item_id):
        return row

    async def _require_boq_position_in_project(_project_id, _position_id):
        return None

    service.get_item = _get_item  # type: ignore[method-assign]
    service._require_boq_position_in_project = _require_boq_position_in_project  # type: ignore[method-assign]

    await service.update_item(PROJECT_ID, ITEM_ID, StockItemUpdate(boq_position_id=POSITION_ID))

    assert row.boq_position_id == POSITION_ID
    # Everything the request did not mention is untouched.
    assert row.name == "C30/37"
    assert row.unit == "m3"
    assert row.standard_unit_cost == Decimal("12")
    assert flushed == [True]


@pytest.mark.asyncio
async def test_update_item_clears_a_link_on_an_explicit_null() -> None:
    """A wrong attribution has to be correctable, so null must reach the column."""
    service = _service()
    row = _item(boq_position_id=POSITION_ID)

    class _Session:
        async def flush(self) -> None:
            return None

    service.session = _Session()  # type: ignore[assignment]

    async def _get_item(_project_id, _item_id):
        return row

    service.get_item = _get_item  # type: ignore[method-assign]

    await service.update_item(
        PROJECT_ID,
        ITEM_ID,
        StockItemUpdate.model_validate({"boq_position_id": None}),
    )
    assert row.boq_position_id is None


@pytest.mark.asyncio
async def test_update_item_parses_money_to_decimal() -> None:
    """Money arrives as a string and must land in the column as a Decimal."""
    service = _service()
    row = _item()

    class _Session:
        async def flush(self) -> None:
            return None

    service.session = _Session()  # type: ignore[assignment]

    async def _get_item(_project_id, _item_id):
        return row

    service.get_item = _get_item  # type: ignore[method-assign]

    async def _no_movements(_project_id, _item_id):
        return 0

    # A cost change asks the ledger first; this item has never moved.
    service._movement_count = _no_movements  # type: ignore[method-assign]

    await service.update_item(PROJECT_ID, ITEM_ID, StockItemUpdate(standard_unit_cost="18.75"))
    assert row.standard_unit_cost == Decimal("18.75")


def test_update_schema_rejects_a_negative_cost() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        StockItemUpdate(standard_unit_cost="-1")
