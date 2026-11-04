"""Zero-cost consumption is valued, so a position cannot read under budget by omission."""

from __future__ import annotations

from decimal import Decimal

from app.modules.site_inventory.ledger import (
    Movement,
    StockItemRef,
    material_cost_variance,
    price_unpriced_consumption,
)


def _m(kind: str, qty: str, cost: str = "0", pos: str | None = "P1") -> Movement:
    return Movement(
        movement_type=kind, quantity=Decimal(qty), unit_cost=Decimal(cost), item_id="I1", boq_position_id=pos
    )


def test_unpriced_consumption_uses_inbound_average() -> None:
    item = StockItemRef(item_id="I1", standard_unit_cost=Decimal("99"))
    moves = [_m("INBOUND", "10", "5"), _m("CONSUMPTION", "4")]
    lines = material_cost_variance(price_unpriced_consumption(moves, [item]), {"P1": Decimal("100")})
    assert lines[0].actual_cost == Decimal("20")


def test_unpriced_consumption_falls_back_to_standard_cost() -> None:
    item = StockItemRef(item_id="I1", standard_unit_cost=Decimal("3"))
    out = price_unpriced_consumption([_m("CONSUMPTION", "4")], [item])
    assert out[0].unit_cost == Decimal("3")


def test_explicit_price_and_unvaluable_item_are_untouched() -> None:
    item = StockItemRef(item_id="I1")
    moves = [_m("CONSUMPTION", "4", "7"), _m("CONSUMPTION", "1")]
    out = price_unpriced_consumption(moves, [item])
    assert [m.unit_cost for m in out] == [Decimal("7"), Decimal("0")]
