# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure quantity-surveying math behind the formwork rate.

No database and no app: these exercise ``compute_cost``, ``single_use_cost``
and ``derive_cycle`` directly, which is where the module's domain claims live.

The claims under test, in the order a formwork engineer would check them:

1. The panel cost amortises over the reuses; the erect-and-strike labour does
   not. Getting that backwards is the classic way to under-price a
   concrete-heavy job.
2. Waste loads the panel cost only.
3. The stored total is derived from the ROUNDED unit cost, so a client
   recomputing ``area * unit`` gets the same number back.
4. The panel set you have to buy is the LARGEST single pour, not the total,
   and the reuse count is the total divided by that set - floored, because
   rounding up prices a turnaround the programme does not deliver.
5. Two pours closer together than the striking time cannot share one set.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.formwork.models import FormworkScheduleLine
from app.modules.formwork.service import compute_cost, derive_cycle, single_use_cost


def _line(pour_no: int, area: str, pour_date: date | None = None) -> FormworkScheduleLine:
    """An unattached pour line - ``derive_cycle`` never touches the session."""
    return FormworkScheduleLine(
        pour_no=pour_no,
        area_m2=Decimal(area),
        pour_date=pour_date,
        level_label=f"L{pour_no:02d}",
    )


# ── compute_cost ────────────────────────────────────────────────────────────


def test_panel_cost_is_divided_by_the_reuse_count():
    """65.00 of panels over 10 uses is 6.50 of panel cost per m2 formed."""
    cost = compute_cost(
        unit_rate=Decimal("65.00"),
        area_m2=Decimal("200"),
        waste_pct=Decimal("0"),
        reuse_count=10,
    )
    assert cost.material == Decimal("6.50")


def test_erect_strike_labour_is_not_divided_by_the_reuse_count():
    """The labour half stays flat while the panel half falls away.

    This is the whole point of the two-component rate. One use and one hundred
    uses of the same system must charge the SAME erect-and-strike labour per
    m2 formed, because the panels are set and struck every single time.
    """
    once = compute_cost(
        unit_rate=Decimal("60.00"),
        area_m2=Decimal("100"),
        waste_pct=Decimal("0"),
        reuse_count=1,
        erect_strike_rate=Decimal("16.00"),
    )
    many = compute_cost(
        unit_rate=Decimal("60.00"),
        area_m2=Decimal("100"),
        waste_pct=Decimal("0"),
        reuse_count=100,
        erect_strike_rate=Decimal("16.00"),
    )
    assert once.labour == many.labour == Decimal("16.00")
    # The panel half did fall away, so the test is not passing by accident.
    assert once.material == Decimal("60.00")
    assert many.material == Decimal("0.60")
    # And the labour dominates once the panels are amortised.
    assert many.labour > many.material
    assert many.unit_cost == Decimal("16.60")


def test_labour_component_dominates_a_long_reuse_run():
    """Ignoring erect/strike under-prices a 100-use run by 96 percent.

    Stated as a ratio rather than as a difference so the number does not drift
    with the seed rates: with the labour component the rate is 16.60, without
    it 0.60.
    """
    with_labour = compute_cost(
        unit_rate=Decimal("60.00"),
        area_m2=Decimal("1000"),
        waste_pct=Decimal("0"),
        reuse_count=100,
        erect_strike_rate=Decimal("16.00"),
    )
    without_labour = compute_cost(
        unit_rate=Decimal("60.00"),
        area_m2=Decimal("1000"),
        waste_pct=Decimal("0"),
        reuse_count=100,
    )
    assert without_labour.total < with_labour.total
    assert without_labour.total / with_labour.total < Decimal("0.05")


def test_waste_loads_the_panel_cost_only():
    """A 10 percent waste allowance moves the material half and nothing else."""
    clean = compute_cost(
        unit_rate=Decimal("50.00"),
        area_m2=Decimal("100"),
        waste_pct=Decimal("0"),
        reuse_count=5,
        erect_strike_rate=Decimal("12.00"),
    )
    wasted = compute_cost(
        unit_rate=Decimal("50.00"),
        area_m2=Decimal("100"),
        waste_pct=Decimal("10"),
        reuse_count=5,
        erect_strike_rate=Decimal("12.00"),
    )
    assert clean.material == Decimal("10.00")
    assert wasted.material == Decimal("11.00")
    assert clean.labour == wasted.labour == Decimal("12.00")


def test_total_is_derived_from_the_rounded_unit_cost():
    """A client recomputing area * unit_cost must land on the stored total.

    65.00 at 5 percent waste over 2 uses is 34.125 before rounding. Storing a
    total off the raw quotient would give 3412.50 against a displayed 3413.00.
    """
    cost = compute_cost(
        unit_rate=Decimal("65.00"),
        area_m2=Decimal("100"),
        waste_pct=Decimal("5"),
        reuse_count=2,
    )
    assert cost.unit_cost == Decimal("34.13")
    assert cost.total == Decimal("3413.00")
    assert cost.total == Decimal("100") * cost.unit_cost


def test_unit_cost_is_the_sum_of_its_two_components():
    cost = compute_cost(
        unit_rate=Decimal("70.00"),
        area_m2=Decimal("340"),
        waste_pct=Decimal("5"),
        reuse_count=7,
        erect_strike_rate=Decimal("14.00"),
    )
    assert cost.unit_cost == cost.material + cost.labour
    assert cost.total == Decimal("340") * cost.unit_cost


def test_zero_reuse_count_is_clamped_to_one_use():
    """Import paths that bypass Pydantic must not divide by zero."""
    cost = compute_cost(
        unit_rate=Decimal("40.00"),
        area_m2=Decimal("10"),
        waste_pct=Decimal("0"),
        reuse_count=0,
    )
    assert cost.material == Decimal("40.00")


def test_single_use_cost_is_the_no_reuse_counterfactual():
    """The saving a reuse claim is worth is the gap against a one-use price."""
    real = compute_cost(
        unit_rate=Decimal("65.00"),
        area_m2=Decimal("1000"),
        waste_pct=Decimal("5"),
        reuse_count=10,
        erect_strike_rate=Decimal("16.00"),
    )
    naive = single_use_cost(
        unit_rate=Decimal("65.00"),
        area_m2=Decimal("1000"),
        waste_pct=Decimal("5"),
        erect_strike_rate=Decimal("16.00"),
    )
    assert naive > real.total
    # 68.25 of panels + 16.00 labour = 84.25/m2 at one use.
    assert naive == Decimal("84250.00")
    # 6.83 + 16.00 = 22.83/m2 at ten uses.
    assert real.total == Decimal("22830.00")


# ── rate basis ──────────────────────────────────────────────────────────────
#
# ``rate_basis`` is the one input that changes the SHAPE of the formula rather
# than its inputs, so it gets its own block. The claim under test is narrow and
# it is the whole reason the field is not just a label: a rate that is already
# quoted per use must not be divided by the reuse count a second time.


def test_purchase_basis_is_the_default_and_the_historical_arithmetic():
    """Omitting the basis prices exactly as the module always did.

    Every row written before ``rate_basis`` existed defaults to ``purchase``,
    so this is the test that says the migration re-prices nothing.
    """
    explicit = compute_cost(
        unit_rate=Decimal("65.00"),
        area_m2=Decimal("200"),
        waste_pct=Decimal("5"),
        reuse_count=10,
        erect_strike_rate=Decimal("16.00"),
        rate_basis="purchase",
    )
    implied = compute_cost(
        unit_rate=Decimal("65.00"),
        area_m2=Decimal("200"),
        waste_pct=Decimal("5"),
        reuse_count=10,
        erect_strike_rate=Decimal("16.00"),
    )
    assert explicit == implied
    assert implied.material == Decimal("6.83")


@pytest.mark.parametrize("basis", ["hire_per_use", "subcontract"])
def test_a_per_use_rate_is_not_amortised(basis: str):
    """9.50 per use stays 9.50 per use whether you use it once or forty times.

    On a purchase basis the same numbers would give 0.24, which is the bug this
    branch exists to prevent: the estimator claims more reuses and the price
    falls, even though the hire invoice is per use and does not.
    """
    once = compute_cost(
        unit_rate=Decimal("9.50"),
        area_m2=Decimal("100"),
        waste_pct=Decimal("0"),
        reuse_count=1,
        rate_basis=basis,
    )
    forty = compute_cost(
        unit_rate=Decimal("9.50"),
        area_m2=Decimal("100"),
        waste_pct=Decimal("0"),
        reuse_count=40,
        rate_basis=basis,
    )
    assert once.material == Decimal("9.50")
    assert forty.material == Decimal("9.50")
    assert once == forty


def test_waste_still_loads_a_per_use_rate():
    """Not amortising is not the same as not being loaded for waste.

    Panels get damaged and offcut on a hired set exactly as on a bought one;
    what changes is only the divisor.
    """
    cost = compute_cost(
        unit_rate=Decimal("10.00"),
        area_m2=Decimal("100"),
        waste_pct=Decimal("5"),
        reuse_count=8,
        rate_basis="hire_per_use",
    )
    assert cost.material == Decimal("10.50")


def test_a_per_use_basis_reports_no_reuse_saving():
    """The counterfactual equals the real total, so the saving is zero.

    Reporting a saving here would credit the estimator with money the hire
    invoice never gives back.
    """
    real = compute_cost(
        unit_rate=Decimal("9.50"),
        area_m2=Decimal("1000"),
        waste_pct=Decimal("0"),
        reuse_count=20,
        erect_strike_rate=Decimal("16.00"),
        rate_basis="hire_per_use",
    )
    naive = single_use_cost(
        unit_rate=Decimal("9.50"),
        area_m2=Decimal("1000"),
        waste_pct=Decimal("0"),
        erect_strike_rate=Decimal("16.00"),
        rate_basis="hire_per_use",
    )
    assert naive == real.total


def test_an_unknown_basis_falls_back_to_purchase():
    """A row from a future revision keeps pricing, it does not take a sweep down.

    The schema pattern rejects unknown values on the way in, so this can only
    be reached by a stored row this build does not know about. Refusing to
    price it would fail a whole re-pricing run over one unrecognised string.
    """
    unknown = compute_cost(
        unit_rate=Decimal("40.00"),
        area_m2=Decimal("10"),
        waste_pct=Decimal("0"),
        reuse_count=4,
        rate_basis="hire_monthly_someday",
    )
    assert unknown.material == Decimal("10.00")


# ── derive_cycle ────────────────────────────────────────────────────────────


def test_peak_pour_sizes_the_panel_set_not_the_total():
    """Four pours of 200 m2 need a 200 m2 set, not an 800 m2 one."""
    cycle = derive_cycle(
        [_line(1, "200"), _line(2, "200"), _line(3, "200"), _line(4, "200")],
        strip_time_days=1,
    )
    assert cycle["total_pour_area_m2"] == Decimal("800.00")
    assert cycle["peak_pour_area_m2"] == Decimal("200.00")
    assert cycle["derived_reuse_count"] == 4


def test_uneven_pours_are_sized_by_the_largest_one():
    """A 300 m2 lift among 100 m2 lifts still needs a 300 m2 set.

    Total 600 over a 300 set is two turnarounds, not the four the pour count
    suggests: the set is idle on three of the four pours.
    """
    cycle = derive_cycle(
        [_line(1, "100"), _line(2, "300"), _line(3, "100"), _line(4, "100")],
        strip_time_days=1,
    )
    assert cycle["peak_pour_area_m2"] == Decimal("300.00")
    assert cycle["total_pour_area_m2"] == Decimal("600.00")
    assert cycle["derived_reuse_count"] == 2
    assert cycle["pour_count"] == 4


def test_derived_reuse_count_floors_the_ratio():
    """2.5 turnarounds is 2, not 3.

    Rounding up would divide the panel cost by a turnaround the programme does
    not deliver, which under-prices the job. The exact ratio is still reported
    so the estimator can see what was given up.
    """
    cycle = derive_cycle(
        [_line(1, "200"), _line(2, "200"), _line(3, "100")],
        strip_time_days=1,
    )
    assert cycle["reuse_ratio"] == Decimal("2.50")
    assert cycle["derived_reuse_count"] == 2


def test_single_pour_derives_one_use():
    cycle = derive_cycle([_line(1, "450")], strip_time_days=1)
    assert cycle["derived_reuse_count"] == 1
    assert cycle["peak_pour_area_m2"] == Decimal("450.00")


def test_empty_schedule_derives_nothing():
    cycle = derive_cycle([], strip_time_days=7)
    assert cycle["pour_count"] == 0
    assert cycle["derived_reuse_count"] == 0
    assert cycle["total_pour_area_m2"] == Decimal("0.00")
    assert cycle["conflicts"] == []


def test_pours_closer_than_the_striking_time_are_flagged():
    """A 7-day slab strip time cannot serve pours 3 days apart."""
    cycle = derive_cycle(
        [
            _line(1, "300", date(2026, 3, 2)),
            _line(2, "300", date(2026, 3, 5)),
            _line(3, "300", date(2026, 3, 20)),
        ],
        strip_time_days=7,
    )
    assert cycle["min_gap_days"] == 3
    assert len(cycle["conflicts"]) == 1
    conflict = cycle["conflicts"][0]
    assert conflict.from_pour_no == 1
    assert conflict.to_pour_no == 2
    assert conflict.gap_days == 3
    assert conflict.required_days == 7


def test_a_cycle_that_respects_the_striking_time_has_no_conflicts():
    cycle = derive_cycle(
        [
            _line(1, "300", date(2026, 3, 2)),
            _line(2, "300", date(2026, 3, 12)),
        ],
        strip_time_days=7,
    )
    assert cycle["conflicts"] == []
    assert cycle["min_gap_days"] == 10


def test_undated_pours_are_not_assumed_to_clash():
    """A cycle nobody has dated is not evidence of a clash."""
    cycle = derive_cycle(
        [_line(1, "300"), _line(2, "300"), _line(3, "300")],
        strip_time_days=14,
    )
    assert cycle["dated_pour_count"] == 0
    assert cycle["min_gap_days"] is None
    assert cycle["conflicts"] == []


def test_gap_check_only_pairs_pours_that_both_carry_dates():
    """An undated pour between two dated ones does not create a phantom gap."""
    cycle = derive_cycle(
        [
            _line(1, "300", date(2026, 3, 2)),
            _line(2, "300"),
            _line(3, "300", date(2026, 3, 30)),
        ],
        strip_time_days=7,
    )
    assert cycle["dated_pour_count"] == 2
    assert cycle["min_gap_days"] == 28
    assert cycle["conflicts"] == []


def test_duplicate_pour_numbers_do_not_break_the_ordering():
    """Two lines can share a pour number; the cycle math must still run.

    Unattached lines have no id yet, so the sort tie-break has to survive two
    Nones. ``formwork.pour_numbers_unique`` is what reports the duplicate.
    """
    cycle = derive_cycle([_line(1, "100"), _line(1, "100")], strip_time_days=1)
    assert cycle["pour_count"] == 2
    assert cycle["total_pour_area_m2"] == Decimal("200.00")
    assert cycle["derived_reuse_count"] == 2


@pytest.mark.parametrize(
    ("areas", "expected_set", "expected_reuses"),
    [
        (["500", "500", "500", "500", "500", "500"], Decimal("500.00"), 6),
        (["120", "480"], Decimal("480.00"), 1),
        (["1000"], Decimal("1000.00"), 1),
    ],
)
def test_cycle_shapes(areas: list[str], expected_set: Decimal, expected_reuses: int):
    cycle = derive_cycle(
        [_line(i + 1, area) for i, area in enumerate(areas)],
        strip_time_days=1,
    )
    assert cycle["peak_pour_area_m2"] == expected_set
    assert cycle["derived_reuse_count"] == expected_reuses
