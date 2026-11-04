# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Pure maths of rate feedback: pooling, spread, confidence, thresholds."""

from decimal import Decimal as D

from app.modules.rate_feedback.rate_math import (
    LineObservation,
    aggregate,
    confidence_of,
    deviates,
    suggested_rate,
)


def obs(project, item="i1", qty="10", earned="100", actual="120", hours=None, planned_hpu=None):
    return LineObservation(
        project_id=project,
        cost_item_id=item,
        quantity=D(qty),
        earned_cost=D(earned) if earned is not None else None,
        actual_cost=D(actual) if actual is not None else None,
        actual_hours=D(hours) if hours is not None else None,
        planned_hours_per_unit=D(planned_hpu) if planned_hpu is not None else None,
    )


def test_pooled_ratio_is_money_weighted_not_a_mean_of_ratios():
    stat = aggregate([obs("a", earned="100", actual="200"), obs("b", earned="900", actual="900")])[0]
    assert stat.cost_ratio == D("1.1000")  # 1100 / 1000, not (2.0 + 1.0) / 2


def test_sample_size_counts_projects_not_lines():
    stat = aggregate([obs("a"), obs("a"), obs("b")])[0]
    assert (stat.project_count, stat.line_count) == (2, 3)


def test_hours_outturn_is_quantity_weighted():
    stat = aggregate(
        [
            obs("a", qty="10", hours="50", planned_hpu="4"),
            obs("b", qty="30", hours="90", planned_hpu="2"),
        ]
    )[0]
    assert stat.observed_hours_per_unit == D("3.5000")  # 140 / 40
    assert stat.planned_hours_per_unit == D("2.5000")  # (40 + 60) / 40
    assert stat.hours_variance_pct == D("40.00")


def test_line_without_cost_data_does_not_dilute_the_ratio():
    stat = aggregate([obs("a", earned="100", actual="130"), obs("b", earned=None, actual=None)])[0]
    assert stat.cost_ratio == D("1.3000")


def test_zero_quantity_lines_are_ignored():
    assert aggregate([obs("a", qty="0")]) == []


def test_unknown_cost_leaves_the_rate_unchanged():
    stat = aggregate([obs("a", earned=None, actual=None, hours="50", planned_hpu="4")])[0]
    assert stat.cost_ratio is None
    assert suggested_rate(D("80"), stat) == D("80.0000")


def test_suggested_rate_scales_by_ratio():
    stat = aggregate([obs("a", earned="100", actual="125")])[0]
    assert suggested_rate(D("80"), stat) == D("100.0000")


def test_confidence_grows_with_projects_and_falls_with_spread():
    assert confidence_of(1, None) == D("0.2000")
    assert confidence_of(5, None) == D("1.0000")
    assert confidence_of(9, None) == D("1.0000")
    assert confidence_of(5, D("0.5")) < confidence_of(5, D("0.1"))
    assert confidence_of(0, None) == D("0")


def test_spread_needs_two_projects():
    one = aggregate([obs("a")])[0]
    two = aggregate([obs("a", actual="100"), obs("b", actual="200")])[0]
    assert one.spread_pct is None
    assert two.spread_pct is not None and two.spread_pct > 0


def test_tolerance_band_on_cost_and_on_hours():
    on_plan = aggregate([obs("a", earned="100", actual="103")])[0]
    off = aggregate([obs("a", earned="100", actual="110")])[0]
    hours_only = aggregate([obs("a", earned="100", actual="100", hours="60", planned_hpu="4")])[0]
    assert not deviates(on_plan)
    assert deviates(off)
    assert deviates(hours_only)  # 6 h/unit against 4 h/unit
    assert not deviates(off, D("0.2"))
