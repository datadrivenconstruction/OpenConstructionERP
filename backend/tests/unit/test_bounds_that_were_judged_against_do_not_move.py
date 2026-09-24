"""Bounds that records were judged or valued against do not move under them.

An acceptance criterion's unit, rule, nominal value and tolerances are what the
verdicts on inspections, material records, tests and as-builts were computed
from. Those records keep only the criterion id, so ``update_criterion`` moving
the bounds silently changed what every recorded verdict meant. It now refuses
a real change to a bound once anything was judged against the criterion.

A stock item's unit is the unit its movements were recorded in, and its
standard unit cost is what a zero-cost movement is valued at. ``update_item``
changed both on an item with a movement history; it now refuses that too.

In both cases text edits, unchanged values sent back by a form, and records
nothing depends on yet keep working.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.construction_control.schemas import AcceptanceCriterionUpdate
from app.modules.construction_control.service import ConstructionControlService
from app.modules.site_inventory.schemas import StockItemUpdate
from app.modules.site_inventory.service import SiteInventoryService

pytestmark = pytest.mark.asyncio


# ── C090: acceptance criterion bounds ───────────────────────────────────────


class _Holders:
    def __init__(self, judged: int) -> None:
        self.judged = judged

    async def count_inspections_using_criterion(self, _id: uuid.UUID) -> int:
        return self.judged

    async def count_materials_using_criterion(self, _id: uuid.UUID) -> int:
        return 0

    async def count_tests_using_criterion(self, _id: uuid.UUID) -> int:
        return 0

    async def count_asbuilt_using_criterion(self, _id: uuid.UUID) -> int:
        return 0


class _Criteria:
    def __init__(self, row: Any) -> None:
        self.row = row

    async def update_fields(self, _id: uuid.UUID, **fields: Any) -> None:
        for name, value in fields.items():
            setattr(self.row, name, value)


class _Session:
    async def refresh(self, _obj: Any) -> None:
        return None


def _criterion_service(judged: int) -> tuple[ConstructionControlService, SimpleNamespace]:
    row = SimpleNamespace(
        id=uuid.uuid4(),
        code="ACC-004",
        title="Slab level",
        unit="mm",
        acceptance_rule="range",
        nominal_value="0",
        tolerance_lower="-5",
        tolerance_upper="5",
        metadata_={},
    )
    svc = ConstructionControlService.__new__(ConstructionControlService)
    svc.session = _Session()
    svc.holders = _Holders(judged)
    svc.criteria = _Criteria(row)

    async def _get(_id: uuid.UUID) -> Any:
        return row

    svc.get_criterion = _get
    return svc, row


@pytest.mark.parametrize(
    "patch",
    [
        {"tolerance_upper": "8"},
        {"nominal_value": "2"},
        {"unit": "cm"},
        {"acceptance_rule": "max", "tolerance_upper": "5"},
    ],
)
async def test_a_judged_criterion_keeps_its_bounds(patch: dict[str, str]) -> None:
    svc, row = _criterion_service(judged=3)

    with pytest.raises(HTTPException) as exc:
        await svc.update_criterion(row.id, AcceptanceCriterionUpdate(**patch))

    assert exc.value.status_code == 409
    assert "ACC-004" in exc.value.detail
    assert (row.unit, row.nominal_value, row.tolerance_upper) == ("mm", "0", "5")


async def test_a_judged_criterion_still_takes_text_and_unchanged_bounds() -> None:
    svc, row = _criterion_service(judged=3)

    await svc.update_criterion(
        row.id, AcceptanceCriterionUpdate(title="Slab level, bay 2", tolerance_lower="-5", tolerance_upper="5")
    )

    assert row.title == "Slab level, bay 2"


async def test_an_unused_criterion_moves_its_bounds() -> None:
    svc, row = _criterion_service(judged=0)

    await svc.update_criterion(row.id, AcceptanceCriterionUpdate(tolerance_upper="8"))

    assert row.tolerance_upper == "8"


# ── C458: stock item unit and standard cost ─────────────────────────────────


def _stock_service(movements: int, standard_unit_cost: Decimal | None) -> tuple[SiteInventoryService, Any]:
    row = SimpleNamespace(id=uuid.uuid4(), name="C30/37", unit="m3", standard_unit_cost=standard_unit_cost)
    svc = SiteInventoryService(session=None)  # type: ignore[arg-type]

    async def _get(_project_id: uuid.UUID, _item_id: uuid.UUID) -> Any:
        return row

    async def _count(_project_id: uuid.UUID, _item_id: uuid.UUID) -> int:
        return movements

    class _FlushOnly:
        async def flush(self) -> None:
            return None

    svc.get_item = _get  # type: ignore[method-assign]
    svc._movement_count = _count  # type: ignore[method-assign]
    svc.session = _FlushOnly()  # type: ignore[assignment]
    return svc, row


@pytest.mark.parametrize(
    ("patch", "named"),
    [({"unit": "t"}, "unit"), ({"standard_unit_cost": "140"}, "standard_unit_cost")],
)
async def test_a_moved_item_keeps_its_unit_and_cost(patch: dict[str, str], named: str) -> None:
    svc, row = _stock_service(movements=2, standard_unit_cost=Decimal("120.00"))

    with pytest.raises(HTTPException) as exc:
        await svc.update_item(uuid.uuid4(), row.id, StockItemUpdate(**patch))

    assert exc.value.status_code == 409
    assert named in exc.value.detail
    assert (row.unit, row.standard_unit_cost) == ("m3", Decimal("120.00"))


async def test_a_moved_item_still_takes_a_rename_and_the_same_cost() -> None:
    svc, row = _stock_service(movements=2, standard_unit_cost=Decimal("120.00"))

    await svc.update_item(uuid.uuid4(), row.id, StockItemUpdate(name="C30/37 XC4", unit="m3", standard_unit_cost="120"))

    assert row.name == "C30/37 XC4"


async def test_an_unmoved_item_changes_its_unit_and_cost() -> None:
    svc, row = _stock_service(movements=0, standard_unit_cost=None)

    await svc.update_item(uuid.uuid4(), row.id, StockItemUpdate(unit="t", standard_unit_cost="140"))

    assert (row.unit, row.standard_unit_cost) == ("t", Decimal("140"))
