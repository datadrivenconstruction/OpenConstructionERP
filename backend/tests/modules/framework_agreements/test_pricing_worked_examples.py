"""Framework agreement pricing, from the three worked examples of the domain spec."""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest

from app.modules.framework_agreements.pricing import (
    AdjustmentSpec,
    EscalationUnresolvedError,
    ItemSpec,
    cap_status,
    min_at_risk,
    period_factor,
    price_order,
    term_months,
    term_over_max,
    unknown_condition_tags,
)

# Example 1: DE gas house connections, index_ratio 118.4 -> 123.1, weekend x 1.15.
_DESTATIS = {"DESTATIS-TIEFBAU": {"2025-01": "118.4", "2026-03": "123.1"}}
_WEEKEND = AdjustmentSpec(code="WE", kind="multiplier", value=D("1.15"), scope="all", condition="weekend")
_DE_ITEMS = [
    (ItemSpec("01.010", D("1850.00")), D("1")),
    (ItemSpec("01.020", D("96.50")), D("14")),
    (ItemSpec("01.030", D("78.40")), D("22")),
]


def _factor_de(ordered_at: date = date(2026, 3, 12), fixed_until: date | None = None):
    return period_factor(
        method="index_ratio",
        ordered_at=ordered_at,
        base_period="2025-01",
        fixed_price_until=fixed_until,
        series_refs=[{"series": "DESTATIS-TIEFBAU"}],
        fixed_part=None,
        index_points=_DESTATIS,
    )


def test_example_1_period_factor_is_the_index_ratio_at_six_places() -> None:
    assert _factor_de().factor == D("1.039696")


def test_example_1_weekend_order_prices_every_line_from_the_agreement() -> None:
    order = price_order(_DE_ITEMS, factor=_factor_de().factor, adjustments=[_WEEKEND], tags=["weekend"])
    assert [ln.rate_build["escalated_rate"] for ln in order.lines] == ["1923.44", "100.33", "81.51"]
    assert [ln.unit_rate for ln in order.lines] == [D("2211.96"), D("115.38"), D("93.74")]
    assert [ln.total for ln in order.lines] == [D("2211.96"), D("1615.32"), D("2062.28")]
    assert order.net == D("5889.56")


def test_example_1_cap_use_reaches_the_threshold_not_the_cap() -> None:
    status = cap_status(D("4000000.00"), D("3842150.00"), D("5889.56"), D("80"))
    assert status.headroom_after == D("151960.44")
    assert status.pct_after == D("96.20")
    assert status.threshold_reached and not status.exceeded


def test_without_the_weekend_tag_the_multiplier_does_not_apply() -> None:
    order = price_order(_DE_ITEMS, factor=_factor_de().factor, adjustments=[_WEEKEND], tags=[])
    assert order.lines[0].unit_rate == D("1923.44")


def test_fixed_price_window_sets_the_factor_to_exactly_one() -> None:
    result = _factor_de(fixed_until=date(2026, 6, 30))
    assert result.factor == D("1.000000") and result.fixed


def test_an_unresolved_index_is_an_error_never_a_factor_of_one() -> None:
    with pytest.raises(EscalationUnresolvedError) as exc:
        _factor_de(ordered_at=date(2026, 4, 2))
    assert exc.value.series == "DESTATIS-TIEFBAU"
    assert exc.value.period == "2026-04"


def test_formula_weights_must_sum_to_one() -> None:
    points = {"L": {"2025-01": "100", "2026-03": "110"}, "M": {"2025-01": "100", "2026-03": "120"}}
    ok = period_factor(
        method="formula",
        ordered_at=date(2026, 3, 1),
        base_period="2025-01",
        fixed_price_until=None,
        series_refs=[{"series": "L", "weight": "0.5"}, {"series": "M", "weight": "0.35"}],
        fixed_part=D("0.15"),
        index_points=points,
    )
    assert ok.factor == D("1.120000")
    with pytest.raises(ValueError, match="weights"):
        period_factor(
            method="formula",
            ordered_at=date(2026, 3, 1),
            base_period="2025-01",
            fixed_price_until=None,
            series_refs=[{"series": "L", "weight": "0.5"}],
            fixed_part=D("0.15"),
            index_points=points,
        )


# Example 2: UK term contract, Task Order TO-0231, out-of-hours on flagged items only.
_OOH = AdjustmentSpec(code="OOH", kind="multiplier", value=D("1.30"), scope="flagged", condition="out_of_hours")


def test_example_2_out_of_hours_applies_only_to_flagged_items() -> None:
    lines = [
        (ItemSpec("PL-101", D("1240.00"), surcharge_flags=("out_of_hours",)), D("1")),
        (ItemSpec("PL-205", D("112.60")), D("6.5")),
        (ItemSpec("PL-310", D("385.00")), D("2")),
    ]
    order = price_order(lines, factor=D("1.000000"), adjustments=[_OOH], tags=["out_of_hours"])
    assert [ln.total for ln in order.lines] == [D("1612.00"), D("731.90"), D("770.00")]
    assert order.net == D("3113.90")
    # The extra is priced as a variation, never as an order line: 6 h x 68.00 + 214.00, fee 12 %.
    extra = D("6") * D("68.00") + D("214.00")
    fee = (extra * D("0.12")).quantize(D("0.01"))
    assert (extra, fee, extra + fee) == (D("622.00"), D("74.64"), D("696.64"))
    assert order.net + extra + fee == D("3810.54")


# Example 3: US IDIQ JOC, normal-hours coefficient 1.0850, the R2 fixture.
_JOC = AdjustmentSpec(code="NH", kind="multiplier", value=D("1.0850"), scope="all", condition="")
_US_ITEMS = [
    (ItemSpec("31 23 16.13", D("14.20")), D("420")),
    (ItemSpec("33 14 13.15", D("68.50")), D("360")),
    (ItemSpec("32 12 16.13", D("31.75")), D("210")),
]


def test_example_3_per_total_and_per_rate_differ_by_cents() -> None:
    per_total = price_order(_US_ITEMS, factor=D("1"), adjustments=[_JOC], tags=["normal_hours"], rounding="per_total")
    per_rate = price_order(_US_ITEMS, factor=D("1"), adjustments=[_JOC], tags=["normal_hours"], rounding="per_rate")
    assert sum(D(ln.rate_build["line_base"]) for ln in per_total.lines) == D("37291.50")
    assert per_total.net == D("40461.28")
    assert per_rate.net == D("40461.90")
    # The per-total lines still add up to the order net.
    assert sum(ln.total for ln in per_total.lines) == per_total.net


def test_example_3_order_over_the_maximum_is_blocked_with_the_headroom_left() -> None:
    status = cap_status(D("5000000.00"), D("4968000.00"), D("40461.28"), D("80"))
    assert status.exceeded
    assert status.total_after == D("5008461.28")
    assert status.headroom_before == D("32000.00")


def test_normal_hours_is_never_reported_as_an_unknown_condition() -> None:
    assert unknown_condition_tags(["normal_hours", "zone:Z3"], [_JOC, _WEEKEND]) == ["zone:Z3"]


def test_four_year_term_is_not_over_a_four_year_limit() -> None:
    assert term_months(date(2025, 1, 1), date(2028, 12, 31)) == 48
    assert not term_over_max(date(2025, 1, 1), date(2028, 12, 31), 4)
    assert term_over_max(date(2025, 1, 1), date(2029, 1, 31), 4)


def test_minimum_at_risk_when_behind_a_straight_line_pace() -> None:
    risk, days, pct = min_at_risk(D("250000"), D("60000"), date(2025, 1, 1), date(2028, 12, 31), date(2027, 6, 1))
    assert risk and pct == D("24.00") and days == 579
    calm, _, _ = min_at_risk(D("250000"), D("200000"), date(2025, 1, 1), date(2028, 12, 31), date(2027, 6, 1))
    assert not calm
