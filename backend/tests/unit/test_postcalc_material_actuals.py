# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠DB-free unit tests for the material half of the post-calculation report.

Post-calculation used to report material cost as unknown on every project, even
where the site had metered its yard: ``actual_cost_known`` was set for labour
and plant and for nothing else. The report could tell a foreman the crew beat
the labour norm and could not say whether the material went over, which is the
half that usually loses the money.

These tests pin down the three things that make the answer trustworthy. The
figure has to come from the site material ledger and agree with what that module
reports for the same movements. It has to stay unknown - not zero - wherever the
site recorded nothing, priced nothing, or priced it in another currency. And the
comparison has to be against the money the estimate allowed for the quantity
actually installed, because a line that is half built has spent about half its
material budget and that is not a saving.

Everything here is plain values: the pure compute layer and the site-inventory
value objects, no database, no ORM, no FastAPI.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.postcalc.model import render_markdown
from app.modules.postcalc.service import (
    aggregate_resources,
    compute_line_productivity,
    compute_project_postcalc,
    consumed_material_cost,
)
from app.modules.price_breakdown import ResourceKind
from app.modules.site_inventory.ledger import (
    Movement,
    MovementType,
    StockItemRef,
    material_cost_variance,
    resolve_positions,
)

_POS_A = "11111111-1111-4111-8111-111111111111"
_POS_B = "22222222-2222-4222-8222-222222222222"


def _line(**overrides: object) -> dict[str, object]:
    """One BoQ line as the compute layer consumes it: 100 m3 of wall.

    Priced at 30 EUR of labour and 110 EUR of material per m3, half installed.
    """
    line: dict[str, object] = {
        "ref": "01.02.0030",
        "description": "RC wall C30/37",
        "unit": "m3",
        "currency": "EUR",
        "planned_quantity": "100",
        "planned_cost": "20000",
        "resources": [
            {"type": "labor", "unit": "h", "quantity": "2", "unit_rate": "15"},
            {"type": "material", "unit": "m3", "quantity": "1", "unit_rate": "110"},
        ],
        "actual_quantity": "50",
        "actual_labour_hours": "110",
        "actual_plant_hours": "0",
        "actual_labour_cost": "1650",
    }
    line.update(overrides)
    return line


def _mv(
    movement_type: MovementType,
    quantity: str,
    *,
    unit_cost: str = "0",
    currency: str = "EUR",
    item_id: str = "item-a",
    boq_position_id: str | None = None,
) -> Movement:
    """Build a stock movement from strings, so no test ever touches a float."""
    return Movement(
        movement_type=movement_type.value,
        quantity=Decimal(quantity),
        unit_cost=Decimal(unit_cost),
        currency=currency,
        item_id=item_id,
        boq_position_id=boq_position_id,
    )


# ── The ledger reading ──────────────────────────────────────────────────────


def test_consumption_is_priced_per_position() -> None:
    """Consumed quantity times what it was bought for, per position."""
    movements = [
        _mv(MovementType.CONSUMPTION, "40", unit_cost="115", boq_position_id=_POS_A),
        _mv(MovementType.CONSUMPTION, "12", unit_cost="115", boq_position_id=_POS_A),
        _mv(MovementType.CONSUMPTION, "5", unit_cost="90", boq_position_id=_POS_B),
    ]
    costs = consumed_material_cost(movements, [], project_currency="EUR")
    assert costs[_POS_A] == Decimal("5980")  # (40 + 12) * 115
    assert costs[_POS_B] == Decimal("450")


def test_only_consumption_counts() -> None:
    """A delivery into stock is not spend on a position, and waste is not either.

    The inventory module's own variance report counts consumption alone, and
    this has to count the same movements or two screens would state two
    different material costs for one position.
    """
    movements = [
        _mv(MovementType.INBOUND, "80", unit_cost="115", boq_position_id=_POS_A),
        _mv(MovementType.CONSUMPTION, "50", unit_cost="115", boq_position_id=_POS_A),
        _mv(MovementType.WASTE, "3", unit_cost="115", boq_position_id=_POS_A),
    ]
    assert consumed_material_cost(movements, [], project_currency="EUR")[_POS_A] == Decimal("5750")


def test_it_agrees_with_the_inventory_modules_own_variance() -> None:
    """One number, one rule: the two reports can never disagree about a position."""
    items = [StockItemRef(item_id="item-a", boq_position_id=_POS_A)]
    movements = [
        _mv(MovementType.INBOUND, "70", unit_cost="120"),
        _mv(MovementType.CONSUMPTION, "48", unit_cost="120"),
        _mv(MovementType.CONSUMPTION, "6", unit_cost="120", boq_position_id=_POS_B),
    ]
    mine = consumed_material_cost(movements, items, project_currency="EUR")
    theirs = {
        line.position_id: line.actual_cost for line in material_cost_variance(resolve_positions(movements, items), {})
    }
    assert mine == theirs


def test_a_movement_inherits_the_position_of_the_item_it_moved() -> None:
    """Attribution follows the inventory module, so old movements are not lost."""
    items = [StockItemRef(item_id="item-a", boq_position_id=_POS_A)]
    movements = [_mv(MovementType.CONSUMPTION, "20", unit_cost="100")]
    assert consumed_material_cost(movements, items, project_currency="EUR") == {_POS_A: Decimal("2000")}


def test_unpriced_consumption_leaves_the_position_unknown() -> None:
    """A zero-priced issue makes the total an understatement, not a figure."""
    movements = [
        _mv(MovementType.CONSUMPTION, "30", unit_cost="110", boq_position_id=_POS_A),
        _mv(MovementType.CONSUMPTION, "20", unit_cost="0", boq_position_id=_POS_A),
    ]
    assert _POS_A not in consumed_material_cost(movements, [], project_currency="EUR")


def test_a_foreign_currency_is_not_blended_into_the_project_total() -> None:
    """Two currencies have no common sum, so neither position is claimed."""
    movements = [
        _mv(MovementType.CONSUMPTION, "10", unit_cost="100", currency="USD", boq_position_id=_POS_A),
        _mv(MovementType.CONSUMPTION, "10", unit_cost="100", currency="EUR", boq_position_id=_POS_B),
        _mv(MovementType.CONSUMPTION, "10", unit_cost="100", currency="USD", boq_position_id=_POS_B),
    ]
    costs = consumed_material_cost(movements, [], project_currency="EUR")
    assert _POS_A not in costs  # a currency the project does not report in
    assert _POS_B not in costs  # two currencies on one position
    assert costs == {}


def test_an_unlabelled_movement_is_read_as_the_projects_own_currency() -> None:
    """Blank is the default the create schema writes, not a foreign label."""
    movements = [_mv(MovementType.CONSUMPTION, "10", unit_cost="100", currency="", boq_position_id=_POS_A)]
    assert consumed_material_cost(movements, [], project_currency="EUR") == {_POS_A: Decimal("1000")}


# ── The line view ───────────────────────────────────────────────────────────


def test_a_line_carries_planned_earned_and_actual_material_money() -> None:
    """Half of a 11000 EUR material budget is earned; 6000 was actually spent."""
    line = compute_line_productivity(_line(actual_material_cost="6000"))
    assert line.planned_material_cost == Decimal("11000")
    assert line.earned_material_cost == Decimal("5500")
    assert line.actual_material_cost == Decimal("6000")
    # Against the whole line as priced the position looks 5000 under budget,
    # which is only true because half the wall is not built yet.
    assert line.material_cost_variance == Decimal("-5000")
    # Against what the installed quantity earned it is 500 over, which is the
    # number a foreman can act on.
    assert line.material_cost_variance_earned == Decimal("500")


def test_labour_money_is_earned_the_same_way() -> None:
    """The two money categories answer the performance question identically."""
    line = compute_line_productivity(_line())
    assert line.earned_labour_cost == Decimal("1500")  # 30 EUR/m3 * 50 m3
    assert line.labour_cost_variance_earned == Decimal("150")


def test_a_line_the_site_never_metered_says_it_does_not_know() -> None:
    """Unknown, not zero: nobody metered the yard is not nobody spent anything."""
    line = compute_line_productivity(_line())
    assert line.actual_material_cost is None
    assert line.material_cost_variance is None
    assert line.material_cost_variance_earned is None
    # The estimate side is still stated: the budget is known even when the
    # spend is not.
    assert line.planned_material_cost == Decimal("11000")


def test_a_line_with_no_baseline_earns_nothing() -> None:
    """Zero planned quantity cannot earn its whole budget on one installed unit."""
    line = compute_line_productivity(_line(planned_quantity="0", actual_quantity="5"))
    assert line.earned_material_cost is None
    assert line.material_cost_variance_earned is None


def test_the_line_dict_exports_every_money_figure() -> None:
    """A page cannot show what the response does not carry."""
    data = compute_line_productivity(_line(actual_material_cost="6000")).to_dict()
    assert data["planned_material_cost"] == "11000.00"
    assert data["earned_material_cost"] == "5500.00"
    assert data["actual_material_cost"] == "6000.00"
    assert data["material_cost_variance_earned"] == "500.00"
    assert data["earned_labour_cost"] == "1500.00"
    assert data["labour_cost_variance_earned"] == "150.00"


# ── The category rollup ─────────────────────────────────────────────────────


def _by_kind(lines: list[dict[str, object]]) -> dict[ResourceKind, object]:
    return {row.kind: row for row in aggregate_resources(lines)}


def test_material_reports_a_known_actual_cost_when_the_site_priced_it() -> None:
    """The defect this file exists for: material used to be unknown always."""
    rows = _by_kind([_line(actual_material_cost="6000")])
    material = rows[ResourceKind.MATERIAL]
    assert material.actual_cost == Decimal("6000")
    assert material.earned_cost == Decimal("5500")
    assert material.cost_variance_earned == Decimal("500")


def test_material_stays_unknown_without_a_source() -> None:
    """No ledger, no number. The category keeps saying it does not know."""
    material = _by_kind([_line()])[ResourceKind.MATERIAL]
    assert material.actual_cost is None
    assert material.cost_variance is None
    assert material.cost_variance_earned is None


def test_a_category_with_no_actuals_source_anywhere_stays_unknown() -> None:
    """Subcontract has no source in the platform today and must not report zero."""
    line = _line(
        resources=[
            {"type": "labor", "unit": "h", "quantity": "2", "unit_rate": "15"},
            {"type": "subcontractor", "unit": "m3", "quantity": "1", "unit_rate": "40"},
        ],
        actual_material_cost="6000",
    )
    rows = _by_kind([line])
    assert rows[ResourceKind.SUBCONTRACT].actual_cost is None
    assert rows[ResourceKind.SUBCONTRACT].planned_cost == Decimal("4000")


def test_material_spend_survives_a_position_the_estimate_priced_without_material() -> None:
    """A category is dropped for having no demand and no hours; money counts too.

    Consumption can be booked against a position whose estimate carries no
    material line at all. Dropping the row for want of estimate demand would
    make real spend vanish from the report.
    """
    line = _line(
        resources=[{"type": "labor", "unit": "h", "quantity": "2", "unit_rate": "15"}],
        actual_material_cost="900",
    )
    material = _by_kind([line])[ResourceKind.MATERIAL]
    assert material.planned_cost == Decimal("0")
    assert material.actual_cost == Decimal("900")


# ── The project rollup ──────────────────────────────────────────────────────


def test_the_project_total_covers_only_the_lines_the_site_priced() -> None:
    """An earned total over 2 lines against an actual over 1 compares two jobs."""
    report = compute_project_postcalc(
        [_line(actual_material_cost="6000"), _line(ref="01.02.0040")],
        currency="EUR",
    )
    assert report.material_priced_line_count == 1
    assert report.line_count == 2
    assert report.total_actual_material_cost == Decimal("6000")
    # The compared total counts the priced line only, and it is the one the
    # actual may be subtracted from: 6000 spent against 5500 earned is 500 over.
    assert report.total_earned_material_cost_compared == Decimal("5500")
    # The plain earned total counts both lines, because it belongs next to the
    # planned total rather than next to the actual.
    assert report.total_earned_material_cost == Decimal("11000")
    # Planned is the whole estimate either way - it is a statement about the
    # bill, not about what the site metered.
    assert report.total_planned_material_cost == Decimal("22000")


def test_the_labour_total_covers_only_the_lines_with_a_timesheet() -> None:
    """The same coverage rule, on the half that was already shipping.

    Labour actuals come from approved timesheets, and a project routinely has
    positions nobody has booked against yet. Subtracting a two-line earned total
    from a one-line actual would report the unbooked line as a saving, and the
    less the site had booked the better the project would look.
    """
    report = compute_project_postcalc(
        [_line(), _line(ref="01.02.0040", actual_labour_cost=None)],
        currency="EUR",
    )
    assert report.labour_priced_line_count == 1
    assert report.line_count == 2
    assert report.total_actual_labour_cost == Decimal("1650")
    assert report.total_earned_labour_cost_compared == Decimal("1500")
    assert report.total_earned_labour_cost == Decimal("3000")


def test_a_project_with_no_priced_line_has_no_compared_total() -> None:
    """Nothing to compare is not zero earned, and both halves have to say so."""
    report = compute_project_postcalc([_line(actual_labour_cost=None)], currency="EUR")
    assert report.total_actual_labour_cost is None
    assert report.total_earned_labour_cost_compared is None
    assert report.total_actual_material_cost is None
    assert report.total_earned_material_cost_compared is None
    assert report.labour_priced_line_count == 0
    assert report.material_priced_line_count == 0


def test_a_project_with_no_ledger_reports_no_material_actual() -> None:
    report = compute_project_postcalc([_line()], currency="EUR")
    assert report.total_actual_material_cost is None
    assert report.material_priced_line_count == 0


def test_the_report_dict_exports_the_material_totals() -> None:
    data = compute_project_postcalc([_line(actual_material_cost="6000")], currency="EUR").to_dict()
    assert data["total_actual_material_cost"] == "6000.00"
    assert data["total_earned_material_cost"] == "5500.00"
    assert data["total_earned_material_cost_compared"] == "5500.00"
    assert data["total_earned_labour_cost_compared"] == "1500.00"
    assert data["material_priced_line_count"] == 1
    assert data["labour_priced_line_count"] == 1


def test_the_markdown_states_the_material_money() -> None:
    body = render_markdown(compute_project_postcalc([_line(actual_material_cost="6000")], currency="EUR"))
    assert "## Material cost by line" in body
    assert "Actual material cost" in body
    assert "6000.00" in body


def test_the_markdown_says_so_when_nothing_was_metered() -> None:
    """An empty table reads as zero spend; a sentence reads as no data."""
    body = render_markdown(compute_project_postcalc([_line()], currency="EUR"))
    assert "No material consumption has been priced" in body


# ── Coverage: an earned total may only be read against a matching actual ────


def _material_of(lines: list[dict[str, object]]) -> object:
    rows = {row.kind: row for row in aggregate_resources(lines)}
    return rows[ResourceKind.MATERIAL]


def test_the_category_rollup_earns_only_over_the_lines_it_can_price() -> None:
    """Two lines, one metered: the unmetered one must not become a saving.

    This is the arithmetic that decides the headline figure on the page. Both
    lines are priced at 110 EUR of material per m3 with 50 m3 installed, so each
    earns 5500. Only the first has a ledger, and it consumed 6000. The answer is
    500 over on the work that was measured, not 5000 saved on the work that was
    not, and the positive one-line case passes either way, which is why this
    test carries a second line that nobody metered.
    """
    material = _material_of([_line(actual_material_cost="6000"), _line(ref="01.02.0040")])
    assert material.actual_cost == Decimal("6000")
    assert material.earned_cost_compared == Decimal("5500")
    assert material.cost_variance_earned == Decimal("500")
    # The plain earned total still covers both lines: it answers the budget
    # question, next to a planned cost that also covers both.
    assert material.earned_cost == Decimal("11000")
    assert material.planned_cost == Decimal("22000")


def test_the_category_rollup_holds_the_same_line_for_labour() -> None:
    rows = {row.kind: row for row in aggregate_resources([_line(), _line(ref="01.02.0040", actual_labour_cost=None)])}
    labour = rows[ResourceKind.LABOUR]
    assert labour.actual_cost == Decimal("1650")
    assert labour.earned_cost_compared == Decimal("1500")
    assert labour.cost_variance_earned == Decimal("150")
    assert labour.earned_cost == Decimal("3000")


def test_a_category_with_no_actuals_has_no_compared_earned_total() -> None:
    """Zero earned would read as an estimate that allowed nothing."""
    rows = {row.kind: row for row in aggregate_resources([_line(actual_labour_cost=None)])}
    material = rows[ResourceKind.MATERIAL]
    assert material.actual_cost is None
    assert material.earned_cost_compared is None
    assert material.cost_variance_earned is None
    # The estimate's own figures survive: nothing was measured, but the bill
    # still allowed 11000 for the whole line and 5500 for what is installed.
    assert material.earned_cost == Decimal("5500")
    assert material.planned_cost == Decimal("11000")


def test_the_rollup_dict_exports_the_compared_earned_total() -> None:
    data = _material_of([_line(actual_material_cost="6000"), _line(ref="01.02.0040")]).to_dict()
    assert data["earned_cost"] == "11000.00"
    assert data["earned_cost_compared"] == "5500.00"
    assert data["cost_variance_earned"] == "500.00"


def test_the_markdown_prints_both_earned_totals() -> None:
    """A reader who subtracts two columns must land on the delta beside them."""
    report = compute_project_postcalc(
        [_line(actual_material_cost="6000"), _line(ref="01.02.0040")],
        currency="EUR",
    )
    body = render_markdown(report)
    assert "Earned material cost (lines with an actual)" in body
    assert "Earned labour cost (lines with an actual)" in body
    assert "Lines with priced labour | 2 / 2" in body
