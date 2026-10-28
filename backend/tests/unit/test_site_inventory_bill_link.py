# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠DB-free unit tests for the site-inventory link to the priced bill.

The stock ledger answers two questions an inventory is kept for: how much of
what was bought is still to arrive, and what the material standing on site
unfixed is worth. Both are joins onto the BoQ position that priced the
material, and both are arithmetic across units that need not agree.

These tests pin that arithmetic down from plain value objects - no database, no
ORM, no FastAPI - the same way :mod:`tests.unit.test_site_inventory_ledger`
pins the movement core it builds on.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.modules.site_inventory.ledger import (
    Movement,
    MovementType,
    OrderedRef,
    PositionCoverage,
    PositionRef,
    StockItemRef,
    UnitAgreement,
    ValuationBasis,
    average_inbound_unit_cost,
    effective_position_id,
    item_position_map,
    item_valuation,
    material_cost_variance,
    normalise_unit,
    position_coverage,
    resolve_positions,
    unfixed_value,
    unit_agreement,
    units_comparable,
)


def _mv(
    movement_type: MovementType,
    quantity: str,
    *,
    unit_cost: str = "0",
    currency: str = "",
    item_id: str | None = None,
    boq_position_id: str | None = None,
    occurred_at: datetime | None = None,
) -> Movement:
    """Build a :class:`Movement` from strings so tests never touch a float."""
    return Movement(
        movement_type=movement_type.value,
        quantity=Decimal(quantity),
        unit_cost=Decimal(unit_cost),
        currency=currency,
        item_id=item_id,
        boq_position_id=boq_position_id,
        occurred_at=occurred_at,
    )


def _row(rows: list[PositionCoverage], position_id: str) -> PositionCoverage:
    """Pick one position's coverage row out of the report."""
    return next(row for row in rows if row.position_id == position_id)


# -- Units: the gate every quantity comparison passes through ----------------


def test_normalise_unit_folds_typography_only() -> None:
    assert normalise_unit("m³") == "m3"
    assert normalise_unit("M3 ") == "m3"
    assert normalise_unit("m3.") == "m3"
    assert normalise_unit("m²") == "m2"
    # Different units stay different - normalisation must not invent agreement.
    assert normalise_unit("m2") != normalise_unit("pcs")


def test_unit_agreement_distinguishes_blank_from_different() -> None:
    assert unit_agreement("m3", "m³") is UnitAgreement.MATCH
    assert unit_agreement("m2", "pcs") is UnitAgreement.MISMATCH
    # A blank unit is not evidence of disagreement, but not of agreement either.
    assert unit_agreement("", "m3") is UnitAgreement.UNKNOWN
    assert unit_agreement("m3", None) is UnitAgreement.UNKNOWN
    assert unit_agreement("", "") is UnitAgreement.UNKNOWN


def test_units_comparable_only_on_a_confirmed_match() -> None:
    assert units_comparable("m3", "M3") is True
    assert units_comparable("m3", "t") is False
    assert units_comparable("m3", "") is False


# -- Effective position: the item's link stands in for the movement's --------


def test_effective_position_prefers_the_movements_own_link() -> None:
    item = StockItemRef(item_id="I1", boq_position_id="P-ITEM")
    movement = _mv(MovementType.CONSUMPTION, "5", item_id="I1", boq_position_id="P-EXPLICIT")
    assert effective_position_id(movement, item_position_map([item])) == "P-EXPLICIT"


def test_effective_position_inherits_from_the_item() -> None:
    item = StockItemRef(item_id="I1", boq_position_id="P-ITEM")
    movement = _mv(MovementType.CONSUMPTION, "5", item_id="I1")
    assert effective_position_id(movement, item_position_map([item])) == "P-ITEM"


def test_effective_position_is_none_when_nothing_is_linked() -> None:
    item = StockItemRef(item_id="I1")
    movement = _mv(MovementType.CONSUMPTION, "5", item_id="I1")
    assert effective_position_id(movement, item_position_map([item])) is None


def test_resolve_positions_makes_the_variance_attributable() -> None:
    """The regression that matters: an unlinked movement on a linked item.

    Before resolution the consumption carries no position and the variance
    report is empty. After it the spend lands on the position the material was
    bought for, which is the whole benefit of the item link.
    """
    item = StockItemRef(item_id="I1", boq_position_id="P1")
    movements = [_mv(MovementType.CONSUMPTION, "10", unit_cost="30", item_id="I1")]

    assert material_cost_variance(movements, {}) == []

    resolved = resolve_positions(movements, [item])
    lines = material_cost_variance(resolved, {"P1": Decimal("250")})
    assert len(lines) == 1
    assert lines[0].position_id == "P1"
    assert lines[0].actual_cost == Decimal("300")
    assert lines[0].variance == Decimal("50")


def test_resolve_positions_leaves_an_explicit_movement_identical() -> None:
    item = StockItemRef(item_id="I1", boq_position_id="P1")
    explicit = _mv(MovementType.CONSUMPTION, "5", item_id="I1", boq_position_id="P2")
    resolved = resolve_positions([explicit], [item])
    assert resolved[0] is explicit


# -- Valuation of the material standing on site ------------------------------


def test_average_inbound_unit_cost_is_quantity_weighted() -> None:
    movements = [
        _mv(MovementType.INBOUND, "100", unit_cost="10", item_id="I1"),
        _mv(MovementType.INBOUND, "300", unit_cost="14", item_id="I1"),
    ]
    # (100*10 + 300*14) / 400 = 5200/400 = 13
    assert average_inbound_unit_cost(movements, "I1") == Decimal("13")


def test_average_inbound_ignores_unpriced_receipts_on_both_sides() -> None:
    """A receipt with no price is a missing price, not a free delivery."""
    movements = [
        _mv(MovementType.INBOUND, "100", unit_cost="10", item_id="I1"),
        _mv(MovementType.INBOUND, "900", unit_cost="0", item_id="I1"),
    ]
    assert average_inbound_unit_cost(movements, "I1") == Decimal("10")


def test_average_inbound_is_none_without_a_priced_receipt() -> None:
    movements = [_mv(MovementType.INBOUND, "100", unit_cost="0", item_id="I1")]
    assert average_inbound_unit_cost(movements, "I1") is None


def test_item_valuation_falls_back_to_standard_cost() -> None:
    item = StockItemRef(item_id="I1", standard_unit_cost=Decimal("7.50"))
    cost, basis = item_valuation([], item)
    assert cost == Decimal("7.50")
    assert basis is ValuationBasis.STANDARD_COST


def test_item_valuation_prefers_what_was_actually_paid() -> None:
    item = StockItemRef(item_id="I1", standard_unit_cost=Decimal("7.50"))
    movements = [_mv(MovementType.INBOUND, "10", unit_cost="9", item_id="I1")]
    cost, basis = item_valuation(movements, item)
    assert cost == Decimal("9")
    assert basis is ValuationBasis.INBOUND_AVERAGE


def test_unfixed_value_is_stock_on_hand_times_cost() -> None:
    item = StockItemRef(item_id="I1", name="C30/37", unit="m3", currency="EUR")
    movements = [
        _mv(MovementType.INBOUND, "100", unit_cost="12", item_id="I1"),
        _mv(MovementType.CONSUMPTION, "30", unit_cost="12", item_id="I1"),
        _mv(MovementType.WASTE, "5", item_id="I1"),
    ]
    summary = unfixed_value(movements, [item])
    assert len(summary.lines) == 1
    line = summary.lines[0]
    # 100 received - 30 installed - 5 wasted = 65 standing on site
    assert line.on_hand == Decimal("65")
    assert line.value == Decimal("780")
    assert summary.totals_by_currency == {"EUR": Decimal("780")}
    assert summary.is_single_currency is True


def test_unfixed_value_never_blends_two_currencies() -> None:
    """Two currencies have no common sum; the report must keep them apart."""
    items = [
        StockItemRef(item_id="I1", currency="EUR"),
        StockItemRef(item_id="I2", currency="GBP"),
    ]
    movements = [
        _mv(MovementType.INBOUND, "10", unit_cost="10", item_id="I1"),
        _mv(MovementType.INBOUND, "10", unit_cost="20", item_id="I2"),
    ]
    summary = unfixed_value(movements, items)
    assert summary.totals_by_currency == {"EUR": Decimal("100"), "GBP": Decimal("200")}
    assert summary.is_single_currency is False


def test_unfixed_value_counts_what_it_could_not_price() -> None:
    """Unvalued stock is named, never silently valued at zero."""
    items = [StockItemRef(item_id="I1"), StockItemRef(item_id="I2", currency="EUR")]
    movements = [
        _mv(MovementType.INBOUND, "10", unit_cost="0", item_id="I1"),
        _mv(MovementType.INBOUND, "10", unit_cost="5", item_id="I2"),
    ]
    summary = unfixed_value(movements, items)
    assert summary.unvalued_item_count == 1
    unpriced = next(line for line in summary.lines if line.item_id == "I1")
    assert unpriced.value is None
    assert unpriced.valuation_basis == ValuationBasis.NONE.value
    # The one item it could price is still totalled in full.
    assert summary.totals_by_currency == {"EUR": Decimal("50")}


def test_unfixed_value_takes_the_currency_off_the_receipt() -> None:
    item = StockItemRef(item_id="I1")
    movements = [_mv(MovementType.INBOUND, "10", unit_cost="5", currency="CZK", item_id="I1")]
    assert unfixed_value(movements, [item]).totals_by_currency == {"CZK": Decimal("50")}


def test_unfixed_value_skips_items_with_nothing_on_site() -> None:
    item = StockItemRef(item_id="I1", currency="EUR")
    movements = [
        _mv(MovementType.INBOUND, "10", unit_cost="5", item_id="I1"),
        _mv(MovementType.CONSUMPTION, "10", unit_cost="5", item_id="I1"),
    ]
    assert unfixed_value(movements, [item]).lines == []


def test_unfixed_value_to_dict_splits_currency_totals() -> None:
    items = [
        StockItemRef(item_id="I1", name="Rebar", unit="t", currency="EUR"),
        StockItemRef(item_id="I2", name="Timber", unit="m3", currency="PLN"),
    ]
    movements = [
        _mv(MovementType.INBOUND, "10", unit_cost="800", item_id="I1"),
        _mv(MovementType.INBOUND, "4", unit_cost="250", item_id="I2"),
    ]
    payload = unfixed_value(movements, items).to_dict()
    assert payload["totals_by_currency"] == [
        {"currency": "EUR", "value": "8000.00"},
        {"currency": "PLN", "value": "1000.00"},
    ]
    assert payload["is_single_currency"] is False
    assert payload["lines"][0]["valuation_basis"] == "inbound_average"


# -- Ordered against delivered against the bill ------------------------------


def test_position_coverage_answers_both_questions() -> None:
    item = StockItemRef(item_id="I1", unit="m3", boq_position_id="P1", procurement_req_item_id="R1")
    positions = {"P1": PositionRef(position_id="P1", ordinal="1.1", unit="m3", quantity=Decimal("200"))}
    ordered = {"R1": OrderedRef(req_item_id="R1", unit="m3", quantity_ordered=Decimal("150"))}
    movements = resolve_positions(
        [
            _mv(MovementType.INBOUND, "120", unit_cost="12", item_id="I1"),
            _mv(MovementType.CONSUMPTION, "80", unit_cost="12", item_id="I1"),
        ],
        [item],
    )
    row = _row(position_coverage(movements, [item], positions, ordered), "P1")

    assert row.ordered_quantity == Decimal("150")
    assert row.delivered_quantity == Decimal("120")
    # Still to arrive: ordered 150 - delivered 120 = 30
    assert row.outstanding_quantity == Decimal("30")
    # Standing on site unfixed: 120 delivered - 80 installed = 40
    assert row.on_hand_quantity == Decimal("40")
    # 120 of the bill's 200 m3 has landed; 80 of it is in the works.
    assert row.delivered_pct == Decimal("60")
    assert row.installed_pct == Decimal("40")
    assert row.bill_unit_agreement == UnitAgreement.MATCH.value


def test_position_coverage_withholds_comparison_on_a_unit_mismatch() -> None:
    """The bill prices m2 of formwork, the store counts panels: no percentage."""
    item = StockItemRef(item_id="I1", unit="pcs", boq_position_id="P1")
    positions = {"P1": PositionRef(position_id="P1", unit="m2", quantity=Decimal("500"))}
    movements = resolve_positions(
        [
            _mv(MovementType.INBOUND, "40", item_id="I1"),
            _mv(MovementType.CONSUMPTION, "12", item_id="I1"),
        ],
        [item],
    )
    row = _row(position_coverage(movements, [item], positions), "P1")

    assert row.bill_unit_agreement == UnitAgreement.MISMATCH.value
    assert row.delivered_pct is None
    assert row.installed_pct is None
    # The raw quantities are still true on their own and are still reported.
    assert row.delivered_quantity == Decimal("40")
    assert row.consumed_quantity == Decimal("12")
    assert row.bill_quantity == Decimal("500")


def test_position_coverage_reports_zero_percent_across_a_unit_mismatch() -> None:
    """Nothing is nothing in every unit, so a zero is exact, not withheld.

    A coverage report exists to show what has not arrived; withholding the
    figure on precisely those positions would be the one answer it must give.
    """
    item = StockItemRef(item_id="I1", unit="pcs", boq_position_id="P1")
    positions = {"P1": PositionRef(position_id="P1", unit="m2", quantity=Decimal("500"))}
    movements = resolve_positions([_mv(MovementType.INBOUND, "40", item_id="I1")], [item])
    row = _row(position_coverage(movements, [item], positions), "P1")

    assert row.bill_unit_agreement == UnitAgreement.MISMATCH.value
    # 40 pcs against 500 m2 is refused ...
    assert row.delivered_pct is None
    # ... but nothing has been installed, and that is true in any unit.
    assert row.installed_pct == Decimal("0")


def test_position_coverage_withholds_comparison_on_an_unknown_unit() -> None:
    item = StockItemRef(item_id="I1", unit="", boq_position_id="P1")
    positions = {"P1": PositionRef(position_id="P1", unit="m2", quantity=Decimal("500"))}
    movements = resolve_positions([_mv(MovementType.INBOUND, "40", item_id="I1")], [item])
    row = _row(position_coverage(movements, [item], positions), "P1")
    assert row.bill_unit_agreement == UnitAgreement.UNKNOWN.value
    assert row.delivered_pct is None


def test_position_coverage_gates_outstanding_on_the_order_unit() -> None:
    """Ordered in tonnes, metered in m3: the subtraction is refused."""
    item = StockItemRef(item_id="I1", unit="m3", boq_position_id="P1", procurement_req_item_id="R1")
    positions = {"P1": PositionRef(position_id="P1", unit="m3", quantity=Decimal("200"))}
    ordered = {"R1": OrderedRef(req_item_id="R1", unit="t", quantity_ordered=Decimal("150"))}
    movements = resolve_positions([_mv(MovementType.INBOUND, "120", item_id="I1")], [item])
    row = _row(position_coverage(movements, [item], positions, ordered), "P1")

    assert row.order_unit_agreement == UnitAgreement.MISMATCH.value
    assert row.outstanding_quantity is None
    # The bill comparison is independent and still runs.
    assert row.delivered_pct == Decimal("60")


def test_position_coverage_reads_ordered_as_unknown_not_zero() -> None:
    """No requisition line behind a position is not an order of nothing."""
    item = StockItemRef(item_id="I1", unit="m3", boq_position_id="P1")
    positions = {"P1": PositionRef(position_id="P1", unit="m3", quantity=Decimal("200"))}
    movements = resolve_positions([_mv(MovementType.INBOUND, "120", item_id="I1")], [item])
    row = _row(position_coverage(movements, [item], positions), "P1")
    assert row.ordered_quantity is None
    assert row.outstanding_quantity is None


def test_position_coverage_two_items_in_different_units_read_unknown() -> None:
    """One position fed in two units has no single inventory unit."""
    items = [
        StockItemRef(item_id="I1", unit="m3", boq_position_id="P1"),
        StockItemRef(item_id="I2", unit="t", boq_position_id="P1"),
    ]
    positions = {"P1": PositionRef(position_id="P1", unit="m3", quantity=Decimal("200"))}
    movements = resolve_positions([_mv(MovementType.INBOUND, "10", item_id="I1")], items)
    row = _row(position_coverage(movements, items, positions), "P1")
    assert row.inventory_unit == ""
    assert row.bill_unit_agreement == UnitAgreement.UNKNOWN.value
    assert row.delivered_pct is None


def test_position_coverage_counts_waste_out_of_what_stands_on_site() -> None:
    item = StockItemRef(item_id="I1", unit="m3", boq_position_id="P1")
    positions = {"P1": PositionRef(position_id="P1", unit="m3", quantity=Decimal("200"))}
    movements = resolve_positions(
        [
            _mv(MovementType.INBOUND, "100", item_id="I1"),
            _mv(MovementType.CONSUMPTION, "60", item_id="I1"),
            _mv(MovementType.WASTE, "10", item_id="I1"),
        ],
        [item],
    )
    row = _row(position_coverage(movements, [item], positions), "P1")
    assert row.wasted_quantity == Decimal("10")
    assert row.on_hand_quantity == Decimal("30")


def test_position_coverage_lists_a_budgeted_position_with_no_stock_yet() -> None:
    """A position nothing has been bought for still has to appear, at zero."""
    positions = {"P1": PositionRef(position_id="P1", unit="m3", quantity=Decimal("200"))}
    row = _row(position_coverage([], [], positions), "P1")
    assert row.delivered_quantity == Decimal("0")
    assert row.on_hand_quantity == Decimal("0")
    assert row.delivered_pct == Decimal("0")


def test_position_coverage_to_dict_quantises_and_keeps_none() -> None:
    item = StockItemRef(item_id="I1", unit="pcs", boq_position_id="P1")
    positions = {"P1": PositionRef(position_id="P1", ordinal="2.4", unit="m2", quantity=Decimal("500"))}
    movements = resolve_positions([_mv(MovementType.INBOUND, "40", item_id="I1")], [item])
    payload = _row(position_coverage(movements, [item], positions), "P1").to_dict()

    assert payload["ordinal"] == "2.4"
    assert payload["delivered_quantity"] == "40.0000"
    assert payload["bill_quantity"] == "500.0000"
    assert payload["delivered_pct"] is None
    assert payload["ordered_quantity"] is None
    assert payload["bill_unit_agreement"] == "mismatch"
    assert payload["item_ids"] == ["I1"]


def test_position_ref_budget_falls_back_to_quantity_times_rate() -> None:
    stored = PositionRef(position_id="P1", quantity=Decimal("10"), unit_rate=Decimal("5"), total=Decimal("60"))
    assert stored.budget == Decimal("60")
    derived = PositionRef(position_id="P2", quantity=Decimal("10"), unit_rate=Decimal("5"))
    assert derived.budget == Decimal("50")
