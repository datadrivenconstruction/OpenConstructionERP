# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠DB-free unit tests for the site-inventory pure ledger core.

Every test constructs plain :class:`Movement` value objects and asserts against
exact ``Decimal`` results. No database, no ORM, no FastAPI - the whole point of
:mod:`app.modules.site_inventory.ledger` is that the numbers can be pinned down
from first principles here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.modules.site_inventory.ledger import (
    Movement,
    MovementType,
    PositionVariance,
    average_inventory,
    consumed_cost,
    days_on_hand,
    inventory_turnover,
    location_delta,
    material_cost_variance,
    period_days,
    safe_div,
    signed_quantity,
    stock_on_hand,
    stock_on_hand_by_item,
    stock_on_hand_by_item_at_location,
    stock_on_hand_by_location,
    summarize_variance,
    total_consumed,
    total_inbound,
    total_wasted,
    variance_pct,
    waste_ratio,
)


def _mv(
    movement_type: MovementType,
    quantity: str,
    *,
    unit_cost: str = "0",
    item_id: str | None = None,
    location_id: str | None = None,
    to_location_id: str | None = None,
    boq_position_id: str | None = None,
    occurred_at: datetime | None = None,
) -> Movement:
    """Build a :class:`Movement` from strings so tests never touch a float."""
    return Movement(
        movement_type=movement_type.value,
        quantity=Decimal(quantity),
        unit_cost=Decimal(unit_cost),
        item_id=item_id,
        location_id=location_id,
        to_location_id=to_location_id,
        boq_position_id=boq_position_id,
        occurred_at=occurred_at,
    )


# -- signed_quantity ---------------------------------------------------------


def test_signed_quantity_per_type() -> None:
    assert signed_quantity(_mv(MovementType.INBOUND, "10")) == Decimal("10")
    assert signed_quantity(_mv(MovementType.CONSUMPTION, "10")) == Decimal("-10")
    assert signed_quantity(_mv(MovementType.WASTE, "10")) == Decimal("-10")
    assert signed_quantity(_mv(MovementType.TRANSFER, "10")) == Decimal("0")


def test_signed_quantity_unknown_type_is_zero() -> None:
    # A stray type must contribute nothing rather than raising, so one bad row
    # cannot poison a whole-project rollup.
    bogus = Movement(movement_type="BOGUS", quantity=Decimal("99"))
    assert signed_quantity(bogus) == Decimal("0")


# -- stock_on_hand -----------------------------------------------------------


def test_stock_on_hand_mixed_movements() -> None:
    movements = [
        _mv(MovementType.INBOUND, "100"),
        _mv(MovementType.CONSUMPTION, "30"),
        _mv(MovementType.WASTE, "5"),
        _mv(MovementType.TRANSFER, "10"),  # nets to zero project-wide
    ]
    assert stock_on_hand(movements) == Decimal("65")


def test_stock_on_hand_empty_is_zero() -> None:
    result = stock_on_hand([])
    assert result == Decimal("0")
    assert isinstance(result, Decimal)


def test_stock_on_hand_can_go_negative() -> None:
    # Over-consumption relative to receipts is a real (and reportable) state.
    movements = [
        _mv(MovementType.INBOUND, "10"),
        _mv(MovementType.CONSUMPTION, "15"),
    ]
    assert stock_on_hand(movements) == Decimal("-5")


def test_stock_on_hand_decimal_exact_no_float_drift() -> None:
    # 0.1 + 0.2 must be exactly 0.3, which float arithmetic cannot promise.
    movements = [
        _mv(MovementType.INBOUND, "0.1"),
        _mv(MovementType.INBOUND, "0.2"),
    ]
    assert stock_on_hand(movements) == Decimal("0.3")


def test_stock_on_hand_by_item() -> None:
    movements = [
        _mv(MovementType.INBOUND, "100", item_id="steel"),
        _mv(MovementType.CONSUMPTION, "40", item_id="steel"),
        _mv(MovementType.INBOUND, "20", item_id="cement"),
        _mv(MovementType.WASTE, "5", item_id="cement"),
        _mv(MovementType.INBOUND, "7"),  # no item id -> ignored
    ]
    assert stock_on_hand_by_item(movements) == {
        "steel": Decimal("60"),
        "cement": Decimal("15"),
    }


def test_stock_on_hand_by_item_empty() -> None:
    assert stock_on_hand_by_item([]) == {}


# -- stock_on_hand_by_location (transfers relocate, not vanish) ---------------


def test_stock_on_hand_by_location_with_transfer() -> None:
    movements = [
        _mv(MovementType.INBOUND, "100", location_id="A"),
        _mv(MovementType.CONSUMPTION, "30", location_id="A"),
        _mv(MovementType.WASTE, "5", location_id="A"),
        _mv(MovementType.TRANSFER, "10", location_id="A", to_location_id="B"),
    ]
    by_loc = stock_on_hand_by_location(movements)
    assert by_loc["A"] == Decimal("55")  # 100 - 30 - 5 - 10
    assert by_loc["B"] == Decimal("10")
    # Locations still net to the whole-project on hand.
    assert by_loc["A"] + by_loc["B"] == stock_on_hand(movements)


def test_stock_on_hand_by_location_empty() -> None:
    assert stock_on_hand_by_location([]) == {}


def test_location_delta_per_type() -> None:
    assert location_delta(_mv(MovementType.INBOUND, "10", location_id="A"), "A") == Decimal("10")
    assert location_delta(_mv(MovementType.CONSUMPTION, "4", location_id="A"), "A") == Decimal("-4")
    assert location_delta(_mv(MovementType.WASTE, "2", location_id="A"), "A") == Decimal("-2")
    # Not this location -> no contribution.
    assert location_delta(_mv(MovementType.INBOUND, "10", location_id="B"), "A") == Decimal("0")


def test_location_delta_transfer_two_sided() -> None:
    transfer = _mv(MovementType.TRANSFER, "10", location_id="A", to_location_id="B")
    assert location_delta(transfer, "A") == Decimal("-10")
    assert location_delta(transfer, "B") == Decimal("10")
    assert location_delta(transfer, "C") == Decimal("0")


def test_stock_on_hand_by_item_at_location() -> None:
    movements = [
        _mv(MovementType.INBOUND, "100", item_id="steel", location_id="A"),
        _mv(MovementType.CONSUMPTION, "30", item_id="steel", location_id="A"),
        _mv(MovementType.TRANSFER, "20", item_id="steel", location_id="A", to_location_id="B"),
        _mv(MovementType.INBOUND, "50", item_id="cement", location_id="B"),  # other location
    ]
    at_a = stock_on_hand_by_item_at_location(movements, "A")
    assert at_a == {"steel": Decimal("50")}  # 100 - 30 - 20
    at_b = stock_on_hand_by_item_at_location(movements, "B")
    assert at_b == {"steel": Decimal("20"), "cement": Decimal("50")}


def test_stock_on_hand_by_item_at_location_empty() -> None:
    assert stock_on_hand_by_item_at_location([], "A") == {}


# -- totals ------------------------------------------------------------------


def test_totals_by_type() -> None:
    movements = [
        _mv(MovementType.INBOUND, "100"),
        _mv(MovementType.INBOUND, "50"),
        _mv(MovementType.CONSUMPTION, "40"),
        _mv(MovementType.WASTE, "6"),
    ]
    assert total_inbound(movements) == Decimal("150")
    assert total_consumed(movements) == Decimal("40")
    assert total_wasted(movements) == Decimal("6")


def test_totals_empty_are_zero() -> None:
    assert total_inbound([]) == Decimal("0")
    assert total_consumed([]) == Decimal("0")
    assert total_wasted([]) == Decimal("0")


def test_consumed_cost_sums_extended_line_cost() -> None:
    movements = [
        _mv(MovementType.CONSUMPTION, "40", unit_cost="30"),  # 1200
        _mv(MovementType.CONSUMPTION, "10", unit_cost="12.50"),  # 125
        _mv(MovementType.INBOUND, "5", unit_cost="99"),  # not consumption
        _mv(MovementType.WASTE, "2", unit_cost="99"),  # not consumption
    ]
    assert consumed_cost(movements) == Decimal("1325.00")


# -- waste_ratio (incl. the zero-consumed guard) -----------------------------


def test_waste_ratio_normal() -> None:
    movements = [
        _mv(MovementType.CONSUMPTION, "20"),
        _mv(MovementType.WASTE, "5"),
    ]
    assert waste_ratio(movements) == Decimal("0.25")


def test_waste_ratio_zero_consumed_is_none() -> None:
    # Waste but nothing consumed -> guarded division returns None, not a raise.
    movements = [_mv(MovementType.WASTE, "5")]
    assert waste_ratio(movements) is None


def test_waste_ratio_zero_waste_is_zero() -> None:
    movements = [_mv(MovementType.CONSUMPTION, "20")]
    assert waste_ratio(movements) == Decimal("0")


def test_waste_ratio_empty_is_none() -> None:
    assert waste_ratio([]) is None


# -- average inventory, turnover, days on hand -------------------------------


def test_average_inventory() -> None:
    assert average_inventory(Decimal("80"), Decimal("120")) == Decimal("100")


def test_inventory_turnover_normal() -> None:
    assert inventory_turnover(Decimal("200"), Decimal("50")) == Decimal("4")


def test_inventory_turnover_zero_average_is_none() -> None:
    assert inventory_turnover(Decimal("200"), Decimal("0")) is None


def test_inventory_turnover_negative_average_is_none() -> None:
    assert inventory_turnover(Decimal("200"), Decimal("-10")) is None


def test_days_on_hand_normal() -> None:
    # avg 100, consumed 50 over 30 days -> 100 * 30 / 50 = 60 days of cover.
    assert days_on_hand(Decimal("100"), Decimal("50"), 30) == Decimal("60")


def test_days_on_hand_zero_consumed_is_none() -> None:
    assert days_on_hand(Decimal("100"), Decimal("0"), 30) is None


def test_days_on_hand_zero_period_is_none() -> None:
    assert days_on_hand(Decimal("100"), Decimal("50"), 0) is None


def test_days_on_hand_matches_period_over_turnover() -> None:
    # days on hand should equal period_days / turnover.
    avg, consumed, days = Decimal("100"), Decimal("50"), Decimal("30")
    turnover = inventory_turnover(consumed, avg)
    assert turnover is not None
    assert days_on_hand(avg, consumed, days) == days / turnover


def test_period_days_from_movement_span() -> None:
    movements = [
        _mv(MovementType.INBOUND, "10", occurred_at=datetime(2026, 1, 1, tzinfo=UTC)),
        _mv(MovementType.CONSUMPTION, "4", occurred_at=datetime(2026, 1, 31, tzinfo=UTC)),
    ]
    assert period_days(movements) == Decimal("30")


def test_period_days_single_stamp_is_none() -> None:
    movements = [_mv(MovementType.INBOUND, "10", occurred_at=datetime(2026, 1, 1, tzinfo=UTC))]
    assert period_days(movements) is None


# -- variance_pct (over / under / zero-budget guard) -------------------------


def test_variance_pct_over_budget() -> None:
    assert variance_pct(Decimal("1200"), Decimal("1000")) == Decimal("20")


def test_variance_pct_under_budget() -> None:
    assert variance_pct(Decimal("800"), Decimal("1000")) == Decimal("-20")


def test_variance_pct_zero_budget_is_none() -> None:
    assert variance_pct(Decimal("500"), Decimal("0")) is None


# -- material_cost_variance --------------------------------------------------


def test_material_cost_variance_over_and_under() -> None:
    movements = [
        _mv(MovementType.CONSUMPTION, "40", unit_cost="30", boq_position_id="P1"),  # 1200
        _mv(MovementType.CONSUMPTION, "10", unit_cost="30", boq_position_id="P2"),  # 300
    ]
    budgets = {"P1": Decimal("1000"), "P2": Decimal("500")}
    lines = material_cost_variance(movements, budgets)
    by_pos = {line.position_id: line for line in lines}

    p1 = by_pos["P1"]
    assert p1.actual_cost == Decimal("1200")
    assert p1.variance == Decimal("200")  # over budget
    assert p1.variance_pct == Decimal("20")
    assert p1.consumed_quantity == Decimal("40")
    assert p1.is_over_budget is True

    p2 = by_pos["P2"]
    assert p2.actual_cost == Decimal("300")
    assert p2.variance == Decimal("-200")  # under budget
    assert p2.variance_pct == Decimal("-40")
    assert p2.is_over_budget is False


def test_material_cost_variance_zero_budget_guard() -> None:
    # Consumption booked against a position the estimate never budgeted.
    movements = [_mv(MovementType.CONSUMPTION, "10", unit_cost="50", boq_position_id="P9")]
    lines = material_cost_variance(movements, {})
    assert len(lines) == 1
    assert lines[0].budgeted_cost == Decimal("0")
    assert lines[0].actual_cost == Decimal("500")
    assert lines[0].variance == Decimal("500")
    assert lines[0].variance_pct is None  # guarded: cannot divide by zero budget


def test_material_cost_variance_budget_without_consumption() -> None:
    # A budgeted position with nothing consumed shows actual zero, full underrun.
    lines = material_cost_variance([], {"P1": Decimal("1000")})
    assert len(lines) == 1
    assert lines[0].actual_cost == Decimal("0")
    assert lines[0].variance == Decimal("-1000")
    assert lines[0].variance_pct == Decimal("-100")


def test_material_cost_variance_ignores_unattributed_consumption() -> None:
    # Consumption with no BoQ position cannot be attributed, so it is excluded.
    movements = [
        _mv(MovementType.CONSUMPTION, "10", unit_cost="50"),  # no position
        _mv(MovementType.CONSUMPTION, "5", unit_cost="20", boq_position_id="P1"),
    ]
    lines = material_cost_variance(movements, {"P1": Decimal("100")})
    assert [line.position_id for line in lines] == ["P1"]
    assert lines[0].actual_cost == Decimal("100")


def test_material_cost_variance_only_counts_consumption() -> None:
    # Inbound / waste against a position must not count as consumed material.
    movements = [
        _mv(MovementType.INBOUND, "100", unit_cost="30", boq_position_id="P1"),
        _mv(MovementType.WASTE, "5", unit_cost="30", boq_position_id="P1"),
        _mv(MovementType.CONSUMPTION, "10", unit_cost="30", boq_position_id="P1"),
    ]
    lines = material_cost_variance(movements, {"P1": Decimal("1000")})
    assert lines[0].actual_cost == Decimal("300")
    assert lines[0].consumed_quantity == Decimal("10")


def test_material_cost_variance_sorted_and_unioned() -> None:
    movements = [_mv(MovementType.CONSUMPTION, "1", unit_cost="1", boq_position_id="P3")]
    budgets = {"P1": Decimal("10"), "P2": Decimal("20")}
    lines = material_cost_variance(movements, budgets)
    assert [line.position_id for line in lines] == ["P1", "P2", "P3"]


def test_material_cost_variance_empty() -> None:
    assert material_cost_variance([], {}) == []


# -- summarize_variance ------------------------------------------------------


def test_summarize_variance_rollup() -> None:
    movements = [
        _mv(MovementType.CONSUMPTION, "40", unit_cost="30", boq_position_id="P1"),  # 1200
        _mv(MovementType.CONSUMPTION, "10", unit_cost="20", boq_position_id="P3"),  # 200
    ]
    budgets = {"P1": Decimal("1000"), "P2": Decimal("500")}
    summary = summarize_variance(material_cost_variance(movements, budgets))
    assert summary.total_budgeted_cost == Decimal("1500")  # 1000 + 500 + 0
    assert summary.total_actual_cost == Decimal("1400")  # 1200 + 0 + 200
    assert summary.total_variance == Decimal("-100")
    assert summary.position_count == 3
    assert summary.over_budget_count == 2  # P1 (over) and P3 (unbudgeted, actual>0)


def test_summarize_variance_empty() -> None:
    summary = summarize_variance([])
    assert summary.total_budgeted_cost == Decimal("0")
    assert summary.total_actual_cost == Decimal("0")
    assert summary.total_variance == Decimal("0")
    assert summary.variance_pct is None  # zero budget -> guarded
    assert summary.position_count == 0
    assert summary.over_budget_count == 0
    assert summary.lines == []


# -- safe_div primitive + Decimal exactness / serialization ------------------


def test_safe_div_guards_zero() -> None:
    assert safe_div(Decimal("10"), Decimal("0")) is None
    assert safe_div(Decimal("10"), Decimal("4")) == Decimal("2.5")


def test_results_are_decimal_not_float() -> None:
    movements = [_mv(MovementType.INBOUND, "3"), _mv(MovementType.CONSUMPTION, "1")]
    assert isinstance(stock_on_hand(movements), Decimal)
    assert isinstance(consumed_cost(movements), Decimal)
    assert isinstance(average_inventory(Decimal("1"), Decimal("3")), Decimal)


def test_position_variance_to_dict_serialises_strings() -> None:
    line = PositionVariance(
        position_id="P1",
        budgeted_cost=Decimal("1000"),
        actual_cost=Decimal("1200"),
        variance=Decimal("200"),
        variance_pct=Decimal("20"),
        consumed_quantity=Decimal("40"),
    )
    payload = line.to_dict()
    assert payload["budgeted_cost"] == "1000.00"
    assert payload["actual_cost"] == "1200.00"
    assert payload["variance_pct"] == "20.00"
    assert payload["consumed_quantity"] == "40.0000"
    assert payload["is_over_budget"] is True


def test_summary_to_dict_none_pct_passthrough() -> None:
    summary = summarize_variance([])
    payload = summary.to_dict()
    assert payload["variance_pct"] is None
    assert payload["total_budgeted_cost"] == "0.00"
    assert payload["lines"] == []


def test_summary_to_dict_quantises_nonterminating_pct() -> None:
    # 200 / 1500 * 100 = 13.333...; the report must pin it to 2 dp.
    movements = [
        _mv(MovementType.CONSUMPTION, "40", unit_cost="30", boq_position_id="P1"),  # 1200
        _mv(MovementType.CONSUMPTION, "10", unit_cost="50", boq_position_id="P2"),  # 500
    ]
    budgets = {"P1": Decimal("1000"), "P2": Decimal("500")}
    summary = summarize_variance(material_cost_variance(movements, budgets))
    # actual 1700, budget 1500 -> +200 -> 13.33%
    assert summary.to_dict()["variance_pct"] == "13.33"
