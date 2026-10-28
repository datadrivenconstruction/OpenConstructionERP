# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure labor / crew rate build-up math.

These exercise :mod:`app.modules.labor_rates.rate_math` directly with plain
``Decimal`` inputs -- no database, FastAPI or ORM -- so they run on any
interpreter. They lock in the documented all-in rate model (percentages on the
base wage first, then flat per-hour amounts) and the crew blend, and prove that
every result is an exact ``Decimal`` rounded ROUND_HALF_UP with no float.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.labor_rates import rate_math
from app.modules.labor_rates.rate_math import CrewMemberInput, OnCost

D = Decimal


# ---------------------------------------------------------------------------
# all_in_rate / build_up
# ---------------------------------------------------------------------------


def test_percentage_on_cost_is_a_share_of_the_base_wage() -> None:
    rate = rate_math.all_in_rate(D("30"), [OnCost("Statutory charges", "percentage", D("20"))])
    assert rate == D("36.00")


def test_percentage_then_fixed_adds_both() -> None:
    rate = rate_math.all_in_rate(
        D("30"),
        [
            OnCost("Statutory charges", "percentage", D("20")),
            OnCost("Small tools", "fixed", D("1.5")),
        ],
    )
    assert rate == D("37.50")


def test_fixed_amount_is_never_inflated_by_a_percentage_regardless_of_order() -> None:
    # Fixed 5 must stay flat, and percentages apply to the base wage only, so
    # the interleaved order below yields the same result as the canonical one.
    interleaved = rate_math.all_in_rate(
        D("100"),
        [OnCost("Tools", "fixed", D("5")), OnCost("Statutory", "percentage", D("10"))],
    )
    canonical = rate_math.all_in_rate(
        D("100"),
        [OnCost("Statutory", "percentage", D("10")), OnCost("Tools", "fixed", D("5"))],
    )
    assert interleaved == canonical == D("115.00")


def test_rounding_is_half_up_at_the_minor_unit() -> None:
    build = rate_math.build_up(D("100.00"), [OnCost("Levy", "percentage", D("7.125"))])
    # 100 * 7.125 / 100 = 7.125 -> HALF_UP to 2dp -> 7.13
    assert build.lines[0].amount == D("7.13")
    assert build.all_in_rate == D("107.13")


def test_empty_components_returns_the_quantized_base_wage() -> None:
    build = rate_math.build_up(D("42.5"), [])
    assert build.all_in_rate == D("42.50")
    assert build.base_wage == D("42.50")
    assert build.lines == []
    assert build.percentage_total == D("0.00")
    assert build.fixed_total == D("0.00")


def test_kind_is_case_insensitive_and_unknown_kinds_are_treated_as_fixed() -> None:
    build = rate_math.build_up(
        D("100"),
        [OnCost("A", "PERCENTAGE", D("10")), OnCost("B", "lump", D("3"))],
    )
    assert build.all_in_rate == D("113.00")
    assert build.lines[0].kind == "percentage"
    assert build.lines[1].kind == "fixed"


def test_build_up_breakdown_lines_totals_and_running_subtotals() -> None:
    build = rate_math.build_up(
        D("50"),
        [
            OnCost("Statutory", "percentage", D("10")),
            OnCost("Insurance", "percentage", D("5")),
            OnCost("Small tools", "fixed", D("2")),
        ],
    )
    labels = [line.label for line in build.lines]
    assert labels == ["Statutory", "Insurance", "Small tools"]
    assert build.lines[0].amount == D("5.00")
    assert build.lines[0].subtotal == D("55.00")
    assert build.lines[1].amount == D("2.50")
    assert build.lines[1].subtotal == D("57.50")
    assert build.lines[2].amount == D("2.00")
    assert build.lines[2].subtotal == D("59.50")
    assert build.percentage_total == D("7.50")
    assert build.fixed_total == D("2.00")
    assert build.all_in_rate == D("59.50")


def test_base_wage_is_coerced_from_str_and_int() -> None:
    assert rate_math.all_in_rate("30", [OnCost("s", "percentage", D("10"))]) == D("33.00")
    assert rate_math.all_in_rate(30, []) == D("30.00")


def test_non_finite_base_wage_collapses_to_zero() -> None:
    assert rate_math.all_in_rate(D("NaN"), []) == D("0.00")


# ---------------------------------------------------------------------------
# crew_rate
# ---------------------------------------------------------------------------


def test_crew_blends_trades_by_headcount() -> None:
    build = rate_math.crew_rate(
        [
            CrewMemberInput("Bricklayer", 2, D("40")),
            CrewMemberInput("Labourer", 1, D("25")),
        ]
    )
    assert build.headcount == 3
    assert build.total_cost_per_hour == D("105.00")
    assert build.blended_hourly_rate == D("35.00")
    assert build.members[0].line_cost == D("80.00")
    assert build.members[1].line_cost == D("25.00")


def test_empty_crew_is_zero_not_a_division_error() -> None:
    build = rate_math.crew_rate([])
    assert build.headcount == 0
    assert build.total_cost_per_hour == D("0.00")
    assert build.blended_hourly_rate == D("0.00")


def test_zero_headcount_members_do_not_divide_by_zero() -> None:
    build = rate_math.crew_rate([CrewMemberInput("Foreman", 0, D("50"))])
    assert build.headcount == 0
    assert build.total_cost_per_hour == D("0.00")
    assert build.blended_hourly_rate == D("0.00")
    assert build.members[0].line_cost == D("0.00")


def test_negative_count_is_clamped_to_zero() -> None:
    build = rate_math.crew_rate([CrewMemberInput("Ghost", -3, D("10"))])
    assert build.members[0].count == 0
    assert build.headcount == 0
    assert build.total_cost_per_hour == D("0.00")


def test_blended_rate_rounds_half_up() -> None:
    build = rate_math.crew_rate(
        [
            CrewMemberInput("A", 1, D("10")),
            CrewMemberInput("B", 1, D("10")),
            CrewMemberInput("C", 1, D("11")),
        ]
    )
    # 31.00 / 3 = 10.3333... -> HALF_UP to 2dp -> 10.33
    assert build.total_cost_per_hour == D("31.00")
    assert build.blended_hourly_rate == D("10.33")


# ---------------------------------------------------------------------------
# Money contract: everything is Decimal, never float
# ---------------------------------------------------------------------------


def test_results_are_decimal_never_float() -> None:
    rate = rate_math.all_in_rate(D("30"), [OnCost("s", "percentage", D("10"))])
    assert isinstance(rate, Decimal)
    crew = rate_math.crew_rate([CrewMemberInput("A", 2, D("20"))])
    assert isinstance(crew.blended_hourly_rate, Decimal)
    assert isinstance(crew.total_cost_per_hour, Decimal)
    assert not isinstance(crew.blended_hourly_rate, float)
