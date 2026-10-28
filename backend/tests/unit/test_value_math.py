# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure "value realized" composition engine.

Stdlib + pytest only - mirrors the engine's constraint so it runs on the local
Python 3.11 test runner without app.* or SQLAlchemy on the path. Money is
exercised exclusively with Decimal literals; rates and the risk proxy are
checked as exact Decimal fractions in [0, 1]. Every per-currency roll-up is
asserted to keep currencies separate and to reconcile to its inputs.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.value.value_math import (
    CONFIDENCE_HIGH,
    CONFIDENCE_HIGH_MIN,
    CONFIDENCE_LOW,
    CONFIDENCE_LOW_MIN,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_MEDIUM_MIN,
    CONFIDENCE_NONE,
    RATEPLACES,
    RISK_WEIGHT_RECOVERY,
    RISK_WEIGHT_TRACEABILITY,
    TWOPLACES,
    ActivityInput,
    BenchmarkInput,
    CurrencyValue,
    HoursSavedInput,
    ImpactInput,
    RecoveryInput,
    ValueSummary,
    compose_portfolio_summary,
    compose_value_summary,
    confidence_for,
    dispute_risk_reduction,
    quantize_money,
    quantize_rate,
    recovery_rate,
    weakest_confidence,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _impact(
    committed_cost: Decimal = Decimal("1000.00"),
    currency: str = "USD",
    schedule_days: Decimal = Decimal("0"),
    kind: str = "co",
) -> ImpactInput:
    return ImpactInput(
        kind=kind,
        currency=currency,
        committed_cost=committed_cost,
        schedule_days=schedule_days,
    )


def _recovery(
    chargeable: Decimal = Decimal("1000.00"),
    recovered: Decimal = Decimal("0"),
    absorbed: Decimal = Decimal("0"),
    currency: str = "USD",
) -> RecoveryInput:
    return RecoveryInput(
        currency=currency,
        chargeable=chargeable,
        recovered=recovered,
        absorbed=absorbed,
    )


def _by_cur(summary: ValueSummary, currency: str) -> CurrencyValue:
    return next(r for r in summary.by_currency if r.currency == currency)


# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------


def test_quanta_constants() -> None:
    assert Decimal("0.01") == TWOPLACES
    assert Decimal("0.0001") == RATEPLACES


def test_confidence_thresholds_are_ordered() -> None:
    assert CONFIDENCE_LOW_MIN == 1
    assert CONFIDENCE_MEDIUM_MIN == 3
    assert CONFIDENCE_HIGH_MIN == 10
    assert CONFIDENCE_LOW_MIN < CONFIDENCE_MEDIUM_MIN < CONFIDENCE_HIGH_MIN


def test_risk_weights_form_a_convex_combination() -> None:
    # The two weights must sum to exactly one so the blend stays in [0, 1].
    assert Decimal("1") == RISK_WEIGHT_RECOVERY + RISK_WEIGHT_TRACEABILITY
    assert Decimal("0") < RISK_WEIGHT_RECOVERY
    assert Decimal("0") < RISK_WEIGHT_TRACEABILITY


# ---------------------------------------------------------------------------
# quantize helpers
# ---------------------------------------------------------------------------


def test_quantize_money_half_up() -> None:
    assert quantize_money(Decimal("1.005")) == Decimal("1.01")
    assert quantize_money(Decimal("1.004")) == Decimal("1.00")


def test_quantize_rate_half_up_four_places() -> None:
    assert quantize_rate(Decimal("0.66665")) == Decimal("0.6667")
    assert quantize_rate(Decimal("0.66664")) == Decimal("0.6666")


# ---------------------------------------------------------------------------
# recovery_rate (mirrors recovery_analytics)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("recovered", "chargeable", "expected"),
    [
        (Decimal("690"), Decimal("1000"), Decimal("0.6900")),
        (Decimal("0"), Decimal("1000"), Decimal("0.0000")),
        (Decimal("1000"), Decimal("1000"), Decimal("1.0000")),
        (Decimal("1"), Decimal("3"), Decimal("0.3333")),
        (Decimal("2"), Decimal("3"), Decimal("0.6667")),
    ],
)
def test_recovery_rate_math(recovered: Decimal, chargeable: Decimal, expected: Decimal) -> None:
    assert recovery_rate(recovered, chargeable) == expected


def test_recovery_rate_none_when_nothing_chargeable() -> None:
    assert recovery_rate(Decimal("0"), Decimal("0")) is None
    assert recovery_rate(Decimal("100"), Decimal("0")) is None
    assert recovery_rate(Decimal("0"), Decimal("-5")) is None


def test_recovery_rate_clamped_to_unit() -> None:
    assert recovery_rate(Decimal("1500"), Decimal("1000")) == Decimal("1.0000")
    assert recovery_rate(Decimal("-10"), Decimal("1000")) == Decimal("0.0000")


# ---------------------------------------------------------------------------
# confidence_for (the honest low-n rule + boundaries)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("n", "expected"),
    [
        (-5, CONFIDENCE_NONE),
        (0, CONFIDENCE_NONE),
        (1, CONFIDENCE_LOW),
        (2, CONFIDENCE_LOW),
        (3, CONFIDENCE_MEDIUM),
        (9, CONFIDENCE_MEDIUM),
        (10, CONFIDENCE_HIGH),
        (1000, CONFIDENCE_HIGH),
    ],
)
def test_confidence_for_boundaries(n: int, expected: str) -> None:
    assert confidence_for(n) == expected


# ---------------------------------------------------------------------------
# weakest_confidence (portfolio roll-up of labels)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("labels", "expected"),
    [
        ([], CONFIDENCE_NONE),
        ([CONFIDENCE_HIGH], CONFIDENCE_HIGH),
        ([CONFIDENCE_HIGH, CONFIDENCE_LOW], CONFIDENCE_LOW),
        ([CONFIDENCE_MEDIUM, CONFIDENCE_HIGH, CONFIDENCE_NONE], CONFIDENCE_NONE),
        ([CONFIDENCE_MEDIUM, CONFIDENCE_HIGH], CONFIDENCE_MEDIUM),
        (["garbage", CONFIDENCE_HIGH], CONFIDENCE_NONE),  # unknown -> rank 0 -> none
    ],
)
def test_weakest_confidence(labels: list[str], expected: str) -> None:
    assert weakest_confidence(labels) == expected


# ---------------------------------------------------------------------------
# dispute_risk_reduction (documented proxy)
# ---------------------------------------------------------------------------


def test_risk_proxy_both_terms_is_weighted_blend() -> None:
    # 0.6 * 0.80 + 0.4 * 0.50 = 0.48 + 0.20 = 0.68
    proxy = dispute_risk_reduction(Decimal("0.80"), Decimal("0.50"))
    assert proxy == Decimal("0.6800")


def test_risk_proxy_recovery_only_returns_that_term() -> None:
    # Only the recovery lever present -> it stands alone (weight renormalised).
    assert dispute_risk_reduction(Decimal("0.69"), None) == Decimal("0.6900")


def test_risk_proxy_traceability_only_returns_that_term() -> None:
    assert dispute_risk_reduction(None, Decimal("0.42")) == Decimal("0.4200")


def test_risk_proxy_neither_term_is_none() -> None:
    assert dispute_risk_reduction(None, None) is None


def test_risk_proxy_stays_in_unit_interval() -> None:
    # Both maxed -> 1.0; both floored -> 0.0; the convex blend never escapes.
    assert dispute_risk_reduction(Decimal("1"), Decimal("1")) == Decimal("1.0000")
    assert dispute_risk_reduction(Decimal("0"), Decimal("0")) == Decimal("0.0000")


def test_risk_proxy_clamps_out_of_range_inputs() -> None:
    # Defensive: inputs outside [0, 1] are clamped before blending.
    assert dispute_risk_reduction(Decimal("2"), Decimal("2")) == Decimal("1.0000")
    assert dispute_risk_reduction(Decimal("-1"), Decimal("-1")) == Decimal("0.0000")


def test_risk_proxy_rises_with_each_lever() -> None:
    base = dispute_risk_reduction(Decimal("0.5"), Decimal("0.5"))
    more_recovery = dispute_risk_reduction(Decimal("0.9"), Decimal("0.5"))
    more_trace = dispute_risk_reduction(Decimal("0.5"), Decimal("0.9"))
    assert base is not None and more_recovery is not None and more_trace is not None
    assert more_recovery > base
    assert more_trace > base


# ---------------------------------------------------------------------------
# compose_value_summary - empty
# ---------------------------------------------------------------------------


def test_compose_empty_input() -> None:
    summary = compose_value_summary([], [])
    assert isinstance(summary, ValueSummary)
    assert summary.by_currency == ()
    assert summary.primary_currency == ""
    assert summary.estimated_hours_saved == Decimal("0.00")
    assert summary.dispute_risk_reduction is None
    assert summary.exposure_confidence == CONFIDENCE_NONE
    assert summary.recovery_confidence == CONFIDENCE_NONE
    assert summary.hours_confidence == CONFIDENCE_NONE
    assert summary.risk_confidence == CONFIDENCE_NONE
    assert summary.cost_position_percentile is None
    assert summary.impact_count == 0
    assert summary.recovery_item_count == 0


# ---------------------------------------------------------------------------
# compose_value_summary - exposure managed (approved impacts)
# ---------------------------------------------------------------------------


def test_compose_exposure_sums_committed_cost_per_currency() -> None:
    impacts = [
        _impact(committed_cost=Decimal("1000.00"), schedule_days=Decimal("5")),
        _impact(committed_cost=Decimal("2500.50"), schedule_days=Decimal("3")),
    ]
    summary = compose_value_summary(impacts, [])
    usd = _by_cur(summary, "USD")
    assert usd.overrun_exposure_managed == Decimal("3500.50")
    assert usd.schedule_days_managed == Decimal("8")
    assert usd.impact_count == 2
    assert summary.impact_count == 2
    assert summary.primary_currency == "USD"


def test_compose_exposure_never_blends_currencies() -> None:
    impacts = [
        _impact(committed_cost=Decimal("1000.00"), currency="USD"),
        _impact(committed_cost=Decimal("800.00"), currency="EUR"),
        _impact(committed_cost=Decimal("500.00"), currency="USD"),
    ]
    summary = compose_value_summary(impacts, [])
    assert {r.currency for r in summary.by_currency} == {"USD", "EUR"}
    assert _by_cur(summary, "USD").overrun_exposure_managed == Decimal("1500.00")
    assert _by_cur(summary, "EUR").overrun_exposure_managed == Decimal("800.00")
    # No single blended figure exists; each currency stands alone.


def test_compose_currency_rows_sorted_by_exposure_desc_then_code() -> None:
    impacts = [
        _impact(committed_cost=Decimal("300.00"), currency="USD"),
        _impact(committed_cost=Decimal("900.00"), currency="EUR"),
        _impact(committed_cost=Decimal("600.00"), currency="GBP"),
    ]
    summary = compose_value_summary(impacts, [])
    assert [r.currency for r in summary.by_currency] == ["EUR", "GBP", "USD"]
    assert summary.primary_currency == "EUR"


def test_compose_primary_currency_alphabetical_tie_break() -> None:
    impacts = [
        _impact(committed_cost=Decimal("500.00"), currency="USD"),
        _impact(committed_cost=Decimal("500.00"), currency="EUR"),
    ]
    summary = compose_value_summary(impacts, [])
    assert summary.primary_currency == "EUR"


# ---------------------------------------------------------------------------
# compose_value_summary - recovery figures + rate per currency
# ---------------------------------------------------------------------------


def test_compose_recovery_totals_and_rate_per_currency() -> None:
    recoveries = [
        _recovery(chargeable=Decimal("1000.00"), recovered=Decimal("600.00"), currency="USD"),
        _recovery(
            chargeable=Decimal("1000.00"), recovered=Decimal("180.00"), absorbed=Decimal("200.00"), currency="USD"
        ),
        _recovery(chargeable=Decimal("800.00"), recovered=Decimal("600.00"), currency="EUR"),
    ]
    summary = compose_value_summary([], recoveries)
    usd = _by_cur(summary, "USD")
    eur = _by_cur(summary, "EUR")
    assert usd.chargeable_total == Decimal("2000.00")
    assert usd.recovered_total == Decimal("780.00")
    assert usd.absorbed_total == Decimal("200.00")
    # 780 / 2000 = 0.39
    assert usd.recovery_rate == Decimal("0.3900")
    # EUR computed independently, never mixed with USD.
    assert eur.recovery_rate == Decimal("0.7500")
    assert summary.recovery_item_count == 3


def test_compose_recovery_rate_none_when_nothing_chargeable() -> None:
    recoveries = [_recovery(chargeable=Decimal("0"), recovered=Decimal("0"), absorbed=Decimal("0"))]
    summary = compose_value_summary([], recoveries)
    usd = _by_cur(summary, "USD")
    assert usd.chargeable_total == Decimal("0.00")
    assert usd.recovery_rate is None


def test_compose_rate_uses_exact_sums_then_quantizes() -> None:
    # Three items, 1/3 recovered each: rate from exact sums, not rounded money.
    recoveries = [_recovery(chargeable=Decimal("10.00"), recovered=Decimal("3.33")) for _ in range(3)]
    summary = compose_value_summary([], recoveries)
    usd = _by_cur(summary, "USD")
    assert usd.chargeable_total == Decimal("30.00")
    assert usd.recovered_total == Decimal("9.99")
    # 9.99 / 30.00 = 0.333 -> 0.3330
    assert usd.recovery_rate == Decimal("0.3330")


def test_compose_over_recovery_does_not_push_rate_above_one() -> None:
    recoveries = [_recovery(chargeable=Decimal("500.00"), recovered=Decimal("900.00"))]
    summary = compose_value_summary([], recoveries)
    usd = _by_cur(summary, "USD")
    # recovered_total carries the raw figure the integrator supplied, but the
    # RATE is clamped to [0, 1].
    assert usd.recovery_rate == Decimal("1.0000")


def test_compose_currency_present_with_recovery_but_no_impact() -> None:
    # A currency that only appears in the recovery ledger still gets a row, with
    # zero exposure managed.
    summary = compose_value_summary([], [_recovery(currency="GBP", recovered=Decimal("500.00"))])
    gbp = _by_cur(summary, "GBP")
    assert gbp.overrun_exposure_managed == Decimal("0.00")
    assert gbp.impact_count == 0
    assert gbp.recovery_item_count == 1


def test_compose_currency_present_with_impact_but_no_recovery() -> None:
    summary = compose_value_summary([_impact(currency="GBP")], [])
    gbp = _by_cur(summary, "GBP")
    assert gbp.chargeable_total == Decimal("0.00")
    assert gbp.recovery_rate is None
    assert gbp.recovery_item_count == 0


# ---------------------------------------------------------------------------
# compose_value_summary - hours saved (currency-independent headline)
# ---------------------------------------------------------------------------


def test_compose_hours_saved_carried_and_quantized() -> None:
    summary = compose_value_summary([], [], hours=HoursSavedInput(hours=Decimal("12.5"), sample=4))
    assert summary.estimated_hours_saved == Decimal("12.50")
    assert summary.hours_sample == 4
    assert summary.hours_confidence == CONFIDENCE_MEDIUM


def test_compose_hours_default_zero_when_absent() -> None:
    summary = compose_value_summary([_impact()], [])
    assert summary.estimated_hours_saved == Decimal("0.00")
    assert summary.hours_confidence == CONFIDENCE_NONE


def test_compose_hours_confidence_falls_back_to_activity_count() -> None:
    # No per-hours sample, but a large activity count backs the figure.
    summary = compose_value_summary(
        [],
        [],
        hours=HoursSavedInput(hours=Decimal("30.00"), sample=0),
        activity=ActivityInput(count=15),
    )
    assert summary.hours_confidence == CONFIDENCE_HIGH
    assert summary.activity_count == 15


def test_compose_hours_sample_preferred_over_activity_count() -> None:
    # When the hours input carries its own sample, that drives confidence.
    summary = compose_value_summary(
        [],
        [],
        hours=HoursSavedInput(hours=Decimal("30.00"), sample=2),
        activity=ActivityInput(count=100),
    )
    # sample 2 -> low, even though activity is large.
    assert summary.hours_confidence == CONFIDENCE_LOW


# ---------------------------------------------------------------------------
# compose_value_summary - dispute-risk proxy wiring
# ---------------------------------------------------------------------------


def test_compose_risk_proxy_blends_overall_rate_and_percentile() -> None:
    # Overall recovery 0.80 (800/1000), percentile 50 -> trace share 0.50.
    # 0.6 * 0.80 + 0.4 * 0.50 = 0.68
    summary = compose_value_summary(
        [],
        [_recovery(chargeable=Decimal("1000.00"), recovered=Decimal("800.00"))],
        benchmark=BenchmarkInput(percentile=50.0),
    )
    assert summary.dispute_risk_reduction == Decimal("0.6800")


def test_compose_risk_proxy_overall_rate_is_currency_agnostic() -> None:
    # Recovery in two currencies; the rate underlying the proxy pools them as a
    # unitless fraction: (600 + 400) / (1000 + 1000) = 0.50. No percentile.
    summary = compose_value_summary(
        [],
        [
            _recovery(chargeable=Decimal("1000.00"), recovered=Decimal("600.00"), currency="USD"),
            _recovery(chargeable=Decimal("1000.00"), recovered=Decimal("400.00"), currency="EUR"),
        ],
    )
    # recovery-only proxy == the pooled rate itself.
    assert summary.dispute_risk_reduction == Decimal("0.5000")


def test_compose_risk_proxy_percentile_only_when_no_recovery() -> None:
    # No recovery items at all, but a benchmark percentile -> proxy rests on the
    # traceability share alone.
    summary = compose_value_summary(
        [_impact()],
        [],
        benchmark=BenchmarkInput(percentile=70.0),
    )
    assert summary.dispute_risk_reduction == Decimal("0.7000")


def test_compose_risk_proxy_none_without_either_signal() -> None:
    summary = compose_value_summary([_impact()], [])
    assert summary.dispute_risk_reduction is None
    assert summary.risk_confidence == CONFIDENCE_NONE


def test_compose_percentile_echoed_for_dashboard() -> None:
    summary = compose_value_summary([], [], benchmark=BenchmarkInput(percentile=42.5))
    assert summary.cost_position_percentile == 42.5


# ---------------------------------------------------------------------------
# compose_value_summary - confidence labels per metric
# ---------------------------------------------------------------------------


def test_compose_confidence_each_metric_from_its_own_sample() -> None:
    impacts = [_impact() for _ in range(3)]  # exposure -> medium
    recoveries = [_recovery(recovered=Decimal("500.00")) for _ in range(10)]  # recovery -> high
    summary = compose_value_summary(
        impacts,
        recoveries,
        hours=HoursSavedInput(hours=Decimal("5.00"), sample=1),  # hours -> low
    )
    assert summary.exposure_confidence == CONFIDENCE_MEDIUM
    assert summary.recovery_confidence == CONFIDENCE_HIGH
    assert summary.hours_confidence == CONFIDENCE_LOW


def test_compose_risk_confidence_capped_by_recovery_sample() -> None:
    # Many impacts but only two recovery items: the risk proxy leans on recovery,
    # so its confidence cannot exceed what two recovery items support (low).
    impacts = [_impact() for _ in range(20)]
    recoveries = [_recovery(recovered=Decimal("500.00")) for _ in range(2)]
    summary = compose_value_summary(impacts, recoveries)
    assert summary.recovery_confidence == CONFIDENCE_LOW
    assert summary.risk_confidence == CONFIDENCE_LOW


def test_compose_risk_confidence_uses_impacts_when_proxy_from_percentile_only() -> None:
    # Proxy rests on the benchmark (no recovery items); confidence then reflects
    # project maturity via the impact count (3 -> medium).
    impacts = [_impact() for _ in range(3)]
    summary = compose_value_summary(impacts, [], benchmark=BenchmarkInput(percentile=60.0))
    assert summary.dispute_risk_reduction == Decimal("0.6000")
    assert summary.risk_confidence == CONFIDENCE_MEDIUM


# ---------------------------------------------------------------------------
# compose_value_summary - determinism + immutability + Decimal exactness
# ---------------------------------------------------------------------------


def test_compose_is_deterministic_regardless_of_input_order() -> None:
    impacts = [
        _impact(committed_cost=Decimal("1000.00"), currency="USD"),
        _impact(committed_cost=Decimal("800.00"), currency="EUR"),
        _impact(committed_cost=Decimal("500.00"), currency="USD"),
    ]
    recoveries = [
        _recovery(chargeable=Decimal("1000.00"), recovered=Decimal("690.00"), currency="USD"),
        _recovery(chargeable=Decimal("800.00"), recovered=Decimal("200.00"), currency="EUR"),
    ]
    first = compose_value_summary(impacts, recoveries)
    second = compose_value_summary(list(reversed(impacts)), list(reversed(recoveries)))
    assert first == second


def test_compose_returns_immutable_dataclasses() -> None:
    summary = compose_value_summary([_impact()], [_recovery()])
    assert all(isinstance(r, CurrencyValue) for r in summary.by_currency)
    with pytest.raises(AttributeError):
        summary.primary_currency = "EUR"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        summary.by_currency[0].overrun_exposure_managed = Decimal("0")  # type: ignore[misc]


def test_compose_decimal_exactness_no_float_drift() -> None:
    # 0.1 * 3 would drift in float; Decimal stays exact.
    impacts = [_impact(committed_cost=Decimal("0.10")) for _ in range(3)]
    summary = compose_value_summary(impacts, [])
    assert _by_cur(summary, "USD").overrun_exposure_managed == Decimal("0.30")


def test_compose_money_is_two_places() -> None:
    summary = compose_value_summary(
        [_impact(committed_cost=Decimal("1234.5"))],
        [_recovery(chargeable=Decimal("1000"), recovered=Decimal("250"))],
    )
    usd = _by_cur(summary, "USD")
    assert usd.overrun_exposure_managed.as_tuple().exponent == -2
    assert usd.recovered_total.as_tuple().exponent == -2
    assert usd.absorbed_total.as_tuple().exponent == -2


# ---------------------------------------------------------------------------
# compose_portfolio_summary - empty
# ---------------------------------------------------------------------------


def test_portfolio_empty_input() -> None:
    portfolio = compose_portfolio_summary([])
    assert portfolio.by_currency == ()
    assert portfolio.primary_currency == ""
    assert portfolio.estimated_hours_saved == Decimal("0.00")
    assert portfolio.dispute_risk_reduction is None
    assert portfolio.exposure_confidence == CONFIDENCE_NONE
    assert portfolio.recovery_confidence == CONFIDENCE_NONE
    assert portfolio.hours_confidence == CONFIDENCE_NONE
    assert portfolio.risk_confidence == CONFIDENCE_NONE


# ---------------------------------------------------------------------------
# compose_portfolio_summary - per-currency aggregation, never blended
# ---------------------------------------------------------------------------


def test_portfolio_sums_money_per_currency() -> None:
    proj_a = compose_value_summary(
        [_impact(committed_cost=Decimal("1000.00"), currency="USD")],
        [_recovery(chargeable=Decimal("1000.00"), recovered=Decimal("600.00"), currency="USD")],
    )
    proj_b = compose_value_summary(
        [
            _impact(committed_cost=Decimal("500.00"), currency="USD"),
            _impact(committed_cost=Decimal("800.00"), currency="EUR"),
        ],
        [_recovery(chargeable=Decimal("1000.00"), recovered=Decimal("400.00"), currency="USD")],
    )
    portfolio = compose_portfolio_summary([proj_a, proj_b])

    usd = _by_cur(portfolio, "USD")
    eur = _by_cur(portfolio, "EUR")
    # USD exposure 1000 + 500 = 1500; EUR exposure 800, kept entirely separate.
    assert usd.overrun_exposure_managed == Decimal("1500.00")
    assert eur.overrun_exposure_managed == Decimal("800.00")
    # USD recovery pooled: 1000 recovered / 2000 chargeable = 0.50
    assert usd.chargeable_total == Decimal("2000.00")
    assert usd.recovered_total == Decimal("1000.00")
    assert usd.recovery_rate == Decimal("0.5000")
    # EUR had no recovery -> rate undefined, kept separate from USD.
    assert eur.recovery_rate is None


def test_portfolio_recovery_rate_recomputed_not_averaged() -> None:
    # Two projects: 1/2 and 1/4 recovered. The pooled rate is (1+1)/(2+4)? No -
    # pooled = (500 + 250) / (1000 + 1000) = 0.375, NOT the mean of 0.5 and 0.25.
    proj_a = compose_value_summary([], [_recovery(chargeable=Decimal("1000.00"), recovered=Decimal("500.00"))])
    proj_b = compose_value_summary([], [_recovery(chargeable=Decimal("1000.00"), recovered=Decimal("250.00"))])
    portfolio = compose_portfolio_summary([proj_a, proj_b])
    usd = _by_cur(portfolio, "USD")
    assert usd.recovery_rate == Decimal("0.3750")
    # The mean of the two rates would be 0.3750 here by coincidence of equal
    # denominators; make denominators unequal to prove pooling.


def test_portfolio_pooling_differs_from_mean_with_unequal_weights() -> None:
    # proj_a: 900/1000 = 0.90 ; proj_b: 0/100 = 0.00
    # pooled = 900 / 1100 = 0.8182  ; mean of rates would be 0.45.
    proj_a = compose_value_summary([], [_recovery(chargeable=Decimal("1000.00"), recovered=Decimal("900.00"))])
    proj_b = compose_value_summary([], [_recovery(chargeable=Decimal("100.00"), recovered=Decimal("0.00"))])
    portfolio = compose_portfolio_summary([proj_a, proj_b])
    usd = _by_cur(portfolio, "USD")
    assert usd.recovery_rate == Decimal("0.8182")


def test_portfolio_rolls_up_hours_and_samples() -> None:
    proj_a = compose_value_summary(
        [_impact()], [_recovery(recovered=Decimal("500.00"))], hours=HoursSavedInput(hours=Decimal("10.00"), sample=4)
    )
    proj_b = compose_value_summary(
        [_impact(), _impact()],
        [_recovery(recovered=Decimal("500.00"))],
        hours=HoursSavedInput(hours=Decimal("5.50"), sample=2),
    )
    portfolio = compose_portfolio_summary([proj_a, proj_b])
    assert portfolio.estimated_hours_saved == Decimal("15.50")
    assert portfolio.impact_count == 3
    assert portfolio.recovery_item_count == 2
    assert portfolio.hours_sample == 6


def test_portfolio_schedule_days_sum_per_currency() -> None:
    proj_a = compose_value_summary([_impact(schedule_days=Decimal("5"))], [])
    proj_b = compose_value_summary([_impact(schedule_days=Decimal("3"))], [])
    portfolio = compose_portfolio_summary([proj_a, proj_b])
    assert _by_cur(portfolio, "USD").schedule_days_managed == Decimal("8")


# ---------------------------------------------------------------------------
# compose_portfolio_summary - confidence roll-up (most cautious wins)
# ---------------------------------------------------------------------------


def test_portfolio_confidence_is_most_cautious_of_pool_and_members() -> None:
    # Each project has 5 recovery items (medium). Pooled = 10 items (would be
    # high), but the weakest member is medium, so the portfolio is medium - a
    # large pool of merely-medium projects does not become high.
    proj_a = compose_value_summary([], [_recovery(recovered=Decimal("100.00")) for _ in range(5)])
    proj_b = compose_value_summary([], [_recovery(recovered=Decimal("100.00")) for _ in range(5)])
    portfolio = compose_portfolio_summary([proj_a, proj_b])
    assert proj_a.recovery_confidence == CONFIDENCE_MEDIUM
    assert portfolio.recovery_item_count == 10
    assert confidence_for(10) == CONFIDENCE_HIGH  # the pool alone would say high
    assert portfolio.recovery_confidence == CONFIDENCE_MEDIUM  # but a member caps it


def test_portfolio_confidence_weakest_member_drags_down() -> None:
    # One strong project, one with nothing: the portfolio recovery confidence is
    # dragged to the weakest member (none).
    strong = compose_value_summary([], [_recovery(recovered=Decimal("100.00")) for _ in range(10)])
    empty = compose_value_summary([], [])
    portfolio = compose_portfolio_summary([strong, empty])
    assert strong.recovery_confidence == CONFIDENCE_HIGH
    assert empty.recovery_confidence == CONFIDENCE_NONE
    assert portfolio.recovery_confidence == CONFIDENCE_NONE


# ---------------------------------------------------------------------------
# compose_portfolio_summary - determinism + reconciliation
# ---------------------------------------------------------------------------


def test_portfolio_is_deterministic() -> None:
    proj_a = compose_value_summary(
        [_impact(committed_cost=Decimal("1000.00"), currency="USD")],
        [_recovery(chargeable=Decimal("1000.00"), recovered=Decimal("690.00"), currency="USD")],
    )
    proj_b = compose_value_summary(
        [_impact(committed_cost=Decimal("800.00"), currency="EUR")],
        [_recovery(chargeable=Decimal("800.00"), recovered=Decimal("200.00"), currency="EUR")],
    )
    first = compose_portfolio_summary([proj_a, proj_b])
    second = compose_portfolio_summary([proj_b, proj_a])
    assert first == second


def test_portfolio_reconciles_to_project_exposure() -> None:
    # The portfolio's per-currency exposure equals the sum of the projects' rows.
    projects = [
        compose_value_summary([_impact(committed_cost=Decimal("100.00"))], []),
        compose_value_summary([_impact(committed_cost=Decimal("250.00"))], []),
        compose_value_summary([_impact(committed_cost=Decimal("75.50"))], []),
    ]
    portfolio = compose_portfolio_summary(projects)
    expected = sum(
        (p.by_currency[0].overrun_exposure_managed for p in projects),
        Decimal("0"),
    )
    assert _by_cur(portfolio, "USD").overrun_exposure_managed == expected
    assert expected == Decimal("425.50")


def test_portfolio_of_one_matches_that_project_money() -> None:
    proj = compose_value_summary(
        [_impact(committed_cost=Decimal("1234.56"))],
        [_recovery(chargeable=Decimal("1000.00"), recovered=Decimal("500.00"))],
        hours=HoursSavedInput(hours=Decimal("9.00"), sample=5),
    )
    portfolio = compose_portfolio_summary([proj])
    usd_p = _by_cur(proj, "USD")
    usd_port = _by_cur(portfolio, "USD")
    assert usd_port.overrun_exposure_managed == usd_p.overrun_exposure_managed
    assert usd_port.recovered_total == usd_p.recovered_total
    assert usd_port.recovery_rate == usd_p.recovery_rate
    assert portfolio.estimated_hours_saved == proj.estimated_hours_saved
