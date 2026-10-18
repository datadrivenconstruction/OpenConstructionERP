# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Forecast methods, computed by hand on invented figures.

Line A is let below its budget, half measured and invoiced a little ahead of
the measurement. Line B bills well behind what is measured. Line C is
complete. Line D is still at estimate.
"""

from decimal import Decimal

import pytest

from app.modules.costmodel.cost_control import (
    FORECAST_METHODS,
    METHOD_BEST_AVAILABLE,
    METHOD_EVM_CPI,
    METHOD_MANUAL,
    METHOD_MAXIMUM,
    SOURCE_AWARDED,
    SOURCE_BUDGET,
    SOURCE_ESTIMATE,
    SOURCE_EVM,
    SOURCE_FINAL,
    SOURCE_INVOICED,
    SOURCE_MANUAL,
    SOURCE_MEASURED,
    LineFigures,
    all_method_outcomes,
    forecast_for,
    method_outcome,
)

D = Decimal

LINE_A = dict(
    budget=D("200000"),
    estimate=D("190000"),
    awarded=D("150000"),
    changes=D("10000"),
    measured=D("80000"),
    certified=D("76000"),
    invoiced=D("84000"),
    pending=D("6000"),
)
LINE_B = dict(budget=D("110000"), awarded=D("100000"), measured=D("50000"), invoiced=D("40000"))
LINE_C = dict(budget=D("120000"), awarded=D("100000"), certified=D("95000"), invoiced=D("95000"), all_final=True)
LINE_D = dict(budget=D("45000"), estimate=D("50000"))


def test_the_four_methods_are_offered_in_this_order() -> None:
    assert FORECAST_METHODS == (METHOD_BEST_AVAILABLE, METHOD_MAXIMUM, METHOD_EVM_CPI, METHOD_MANUAL)


def test_best_available_is_the_default_and_keeps_todays_behaviour() -> None:
    figures = LineFigures(**LINE_A)
    assert figures.method == METHOD_BEST_AVAILABLE
    out = method_outcome(figures)
    # 160 000 committed is above half of the 200 000 budget: the award plus changes rules.
    assert (out.amount, out.source, out.applied) == (D("160000"), SOURCE_AWARDED, True)


def test_maximum_takes_the_highest_figure_known() -> None:
    out = method_outcome(LineFigures(**LINE_A, method=METHOD_MAXIMUM))
    # max(200 000 budget, 190 000 estimate, 160 000 committed, 80 000 measured, 76 000 certified, 84 000 invoiced)
    assert (out.amount, out.source, out.applied) == (D("200000"), SOURCE_BUDGET, True)


def test_maximum_prefers_the_more_mature_source_on_a_tie() -> None:
    out = method_outcome(LineFigures(budget=D("100"), awarded=D("100"), method=METHOD_MAXIMUM))
    assert (out.amount, out.source) == (D("100"), SOURCE_AWARDED)


def test_maximum_follows_invoices_running_ahead_of_everything() -> None:
    out = method_outcome(LineFigures(budget=D("100"), awarded=D("90"), invoiced=D("104"), method=METHOD_MAXIMUM))
    assert (out.amount, out.source) == (D("104"), SOURCE_INVOICED)


def test_maximum_reads_measured_quantity_times_rate() -> None:
    out = method_outcome(LineFigures(awarded=D("90"), measured=D("97.50"), method=METHOD_MAXIMUM))
    assert (out.amount, out.source) == (D("97.50"), SOURCE_MEASURED)


def test_cpi_based_on_line_a() -> None:
    out = method_outcome(LineFigures(**LINE_A, method=METHOD_EVM_CPI))
    # progress = 80 000 / 160 000 = 0.5; actual = 84 000 invoiced; CPI = 80 000 / 84 000;
    # forecast = 160 000 / CPI = 160 000 x 84 000 / 80 000 = 168 000.
    assert (out.amount, out.source, out.applied) == (D("168000.00"), SOURCE_EVM, True)
    assert out.progress == D("0.5000")
    assert out.cpi == D("0.9524")
    assert out.actual == D("84000")
    assert out.earned == D("80000")


def test_cpi_based_can_fall_below_the_commitment() -> None:
    out = method_outcome(LineFigures(**LINE_B, method=METHOD_EVM_CPI))
    # CPI = 50 000 / 40 000 = 1.25; forecast = 100 000 / 1.25 = 80 000.
    assert (out.amount, out.source) == (D("80000.00"), SOURCE_EVM)
    assert out.cpi == D("1.2500")


def test_cpi_based_uses_the_measured_value_once_it_exceeds_the_commitment() -> None:
    out = method_outcome(LineFigures(awarded=D("100"), measured=D("120"), invoiced=D("132"), method=METHOD_EVM_CPI))
    # budget at completion = max(100, 120) = 120; CPI = 120 / 132; forecast = 120 x 132 / 120 = 132.
    assert out.amount == D("132.00")
    assert out.progress == D("1.0000")


def test_cpi_based_reads_certified_when_nothing_is_invoiced() -> None:
    out = method_outcome(LineFigures(awarded=D("200"), measured=D("50"), certified=D("60"), method=METHOD_EVM_CPI))
    # actual = 60 certified; forecast = 200 x 60 / 50 = 240.
    assert out.amount == D("240.00")
    assert out.actual == D("60")


def test_cpi_based_falls_back_without_measurement() -> None:
    out = method_outcome(LineFigures(**LINE_D, method=METHOD_EVM_CPI))
    assert (out.amount, out.source, out.applied) == (D("50000"), SOURCE_ESTIMATE, False)
    assert out.method == METHOD_EVM_CPI
    assert out.cpi is None


def test_cpi_based_falls_back_without_cost_to_date() -> None:
    out = method_outcome(LineFigures(awarded=D("100"), measured=D("40"), method=METHOD_EVM_CPI))
    assert (out.amount, out.source, out.applied) == (D("100"), SOURCE_AWARDED, False)


@pytest.mark.parametrize("method", [METHOD_BEST_AVAILABLE, METHOD_MAXIMUM, METHOD_EVM_CPI, METHOD_MANUAL])
def test_a_completed_line_reads_its_final_figure_under_every_method(method: str) -> None:
    out = method_outcome(LineFigures(**LINE_C, method=method))
    assert (out.amount, out.source) == (D("95000"), SOURCE_FINAL)


def test_a_person_s_amount_wins_under_any_method() -> None:
    out = method_outcome(LineFigures(**LINE_A, method=METHOD_MAXIMUM, override=D("171500")))
    assert (out.amount, out.source, out.method, out.applied) == (D("171500"), SOURCE_MANUAL, METHOD_MANUAL, True)


def test_manual_without_an_amount_falls_back_to_best_available() -> None:
    out = method_outcome(LineFigures(**LINE_A, method=METHOD_MANUAL))
    assert (out.amount, out.source, out.method, out.applied) == (D("160000"), SOURCE_AWARDED, METHOD_MANUAL, False)


def test_forecast_for_reads_the_method_of_the_figures() -> None:
    assert forecast_for(LineFigures(**LINE_B, method=METHOD_EVM_CPI)).amount == D("80000.00")
    assert forecast_for(LineFigures(**LINE_B, method=METHOD_MAXIMUM)).amount == D("110000")
    assert forecast_for(LineFigures(**LINE_B)).amount == D("100000")


def test_all_methods_side_by_side_ignore_the_line_method_but_keep_the_override() -> None:
    outcomes = all_method_outcomes(LineFigures(**LINE_A, method=METHOD_EVM_CPI, override=D("171500")))
    assert {m: o.amount for m, o in outcomes.items()} == {
        METHOD_BEST_AVAILABLE: D("160000"),
        METHOD_MAXIMUM: D("200000"),
        METHOD_EVM_CPI: D("168000.00"),
        METHOD_MANUAL: D("171500"),
    }
    without = all_method_outcomes(LineFigures(**LINE_D))
    assert without[METHOD_MANUAL].applied is False


def test_committed_plus_pending_is_what_the_line_already_owes() -> None:
    assert LineFigures(**LINE_A).owed == D("166000")
