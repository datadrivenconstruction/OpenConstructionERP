# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The arithmetic of the economics module: spread, discounting, return, coverage, assignment."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.economics import calc
from app.modules.economics.calc import FlowLine, Reading

D = Decimal


def _line(kind: str, mode: str, amount: str, y0: int, y1: int, esc: str = "0") -> FlowLine:
    return FlowLine(kind=kind, mode=mode, amount=D(amount), year_from=y0, year_to=y1, escalation_pct=D(esc))


def test_a_total_spread_over_years_adds_up_exactly() -> None:
    years = calc.yearly(_line("investment", "total", "100", 0, 2))
    assert sum(years.values()) == D("100")
    assert list(years) == [0, 1, 2]
    # the remainder goes on the last year, the others are the rounded share
    assert years[0] == years[1] == D("33.3333")
    assert years[2] == D("33.3334")


def test_a_per_year_line_compounds_its_escalation_from_the_first_year() -> None:
    years = calc.yearly(_line("revenue", "per_year", "1000", 1, 3, "10"))
    assert years == {1: D("1000"), 2: D("1100.0"), 3: D("1210.00")}


def test_a_line_whose_last_year_precedes_its_first_has_no_years() -> None:
    assert calc.yearly(_line("revenue", "per_year", "10", 5, 2)) == {}


def test_outflows_are_negative_and_money_outside_the_horizon_is_ignored() -> None:
    lines = [
        _line("investment", "total", "1000", 0, 0),
        _line("operating_cost", "per_year", "100", 1, 5),
        _line("revenue", "per_year", "400", 1, 9),
    ]
    flows = calc.cash_flows(lines, 5)
    assert flows == [D("-1000"), D("300"), D("300"), D("300"), D("300"), D("300")]


def test_npv_at_zero_percent_is_the_sum() -> None:
    assert calc.npv([D("-100"), D("60"), D("60")], D("0")) == D("20")


def test_npv_discounts_by_the_year() -> None:
    value = calc.npv([D("-100"), D("110")], D("10"))
    assert abs(value) < D("0.0000000001")


def test_irr_finds_the_rate_that_zeroes_the_npv() -> None:
    assert calc.irr([D("-100"), D("110")]) == D("10.00")
    flows = [D("-1000"), D("300"), D("400"), D("500")]
    rate = calc.irr(flows)
    assert rate is not None
    assert abs(calc.npv(flows, rate)) < D("1")


def test_irr_is_none_without_a_sign_change() -> None:
    assert calc.irr([D("100"), D("100")]) is None
    assert calc.irr([D("-100"), D("-100")]) is None


def test_payback_is_the_first_year_the_cumulative_flow_is_not_negative() -> None:
    assert calc.payback_year([D("-100"), D("40"), D("40"), D("40")]) == 3
    assert calc.payback_year([D("-100"), D("40")]) is None
    # a positive flow before any spending is not a payback
    assert calc.payback_year([D("10"), D("-100"), D("100")]) == 2


def test_key_figures_are_none_where_they_cannot_be_computed_never_zero() -> None:
    figures = calc.key_figures([_line("revenue", "per_year", "10", 1, 3)], 5, None)
    assert figures["npv"] is None
    assert figures["irr_pct"] is None
    assert figures["benefit_cost_ratio"] is None
    assert figures["yield_on_cost_pct"] is None
    assert figures["total_revenue"] == D("30")


def test_key_figures_of_a_small_case() -> None:
    lines = [
        _line("investment", "total", "1000", 0, 0),
        _line("revenue", "per_year", "300", 1, 5),
        _line("operating_cost", "per_year", "50", 1, 5),
        _line("residual", "total", "200", 5, 5),
    ]
    figures = calc.key_figures(lines, 5, D("5"))
    assert figures["total_investment"] == D("1000")
    assert figures["total_revenue"] == D("1500")
    assert figures["total_operating_cost"] == D("250")
    assert figures["net_cash_flow"] == D("450")
    assert figures["payback_year"] == 4
    assert figures["yield_on_cost_pct"] == D("25")
    assert figures["npv"] is not None and figures["npv"] > 0
    assert figures["benefit_cost_ratio"] is not None and figures["benefit_cost_ratio"] > 1
    assert figures["irr_pct"] is not None and figures["irr_pct"] > D("5")


def test_assignment_goes_to_the_most_specific_line_and_loose_amounts_are_kept() -> None:
    per, loose, count = calc.assign(
        ["300", "400"],
        [Reading("331", D("10")), Reading("441", D("5")), Reading(None, D("2")), Reading("500", D("1"))],
    )
    assert per == {"300": D("10"), "400": D("5")}
    assert loose == D("3")
    assert count == 2
    # nothing is dropped
    assert sum(per.values()) + loose == D("18")


def test_assignment_prefers_the_deeper_line() -> None:
    per, loose, _ = calc.assign(["300", "330"], [Reading("331", D("7")), Reading("351", D("3"))])
    assert per == {"300": D("3"), "330": D("7")}
    assert loose == 0


def test_coverage_keeps_shortfall_and_surplus_apart() -> None:
    short = calc.coverage(D("100"), [D("60"), D("30")])
    assert short["shortfall"] == D("10") and short["surplus"] == D("0") and short["covered"] is False
    over = calc.coverage(D("100"), [D("60"), D("50")])
    assert over["shortfall"] == D("0") and over["surplus"] == D("10") and over["covered"] is True
    assert calc.coverage(D("0"), [])["covered"] is False


@pytest.mark.parametrize("part,whole,expected", [("5", "50", "10"), ("1", "0", None)])
def test_pct_of_is_none_for_a_zero_whole(part: str, whole: str, expected: str | None) -> None:
    got = calc.pct_of(D(part), D(whole))
    assert got == (D(expected) if expected is not None else None)
