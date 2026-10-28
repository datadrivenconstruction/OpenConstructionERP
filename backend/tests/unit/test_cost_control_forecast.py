# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Cost control: the forecast takes the most mature stage, and the findings."""

from decimal import Decimal

import pytest

from app.modules.costmodel.cost_control import (
    FINDING_CERTIFIED_OVER_COMMITTED,
    FINDING_OVER_PLAN,
    FINDING_PARTLY_AWARDED,
    FINDING_PENDING_CHANGES,
    FINDING_STALE_SNAPSHOT,
    FINDING_UNASSIGNED,
    SOURCE_AWARDED,
    SOURCE_BUDGET,
    SOURCE_ESTIMATE,
    SOURCE_FINAL,
    SOURCE_MANUAL,
    SOURCE_MEASURED,
    SOURCE_NONE,
    SOURCE_PARTLY_AWARDED,
    LineFigures,
    LineInput,
    automatic_forecast,
    forecast_for,
    line_findings,
    project_findings,
    sort_findings,
    variance_pct,
)

D = Decimal


@pytest.mark.parametrize(
    ("figures", "amount", "source"),
    [
        (LineFigures(), D("0"), SOURCE_NONE),
        (LineFigures(budget=D("100")), D("100"), SOURCE_BUDGET),
        (LineFigures(budget=D("100"), estimate=D("120")), D("120"), SOURCE_ESTIMATE),
        # Awarded below the estimate: the forecast drops to the award.
        (LineFigures(budget=D("100"), estimate=D("120"), awarded=D("90")), D("90"), SOURCE_AWARDED),
        # Approved changes ride on the award.
        (LineFigures(estimate=D("120"), awarded=D("90"), changes=D("15")), D("105"), SOURCE_AWARDED),
        # Measured work already above the commitment wins.
        (LineFigures(awarded=D("90"), changes=D("5"), certified=D("101")), D("101"), SOURCE_MEASURED),
        # Measured below the commitment on an open contract: the rest is still to come.
        (LineFigures(awarded=D("90"), certified=D("60")), D("90"), SOURCE_AWARDED),
        # Every contract completed: certified work is the final cost, even below the award.
        (LineFigures(awarded=D("90"), certified=D("86.40"), all_final=True), D("86.40"), SOURCE_FINAL),
        # A negative change (omission) lowers the commitment.
        (LineFigures(awarded=D("90"), changes=D("-10")), D("80"), SOURCE_AWARDED),
        # Less than half of the plan let: the rest is still to come, the estimate stands.
        (LineFigures(budget=D("100"), estimate=D("120"), awarded=D("40")), D("120"), SOURCE_PARTLY_AWARDED),
        # Exactly half let reads as awarded: from there a saving shows at once.
        (LineFigures(budget=D("100"), estimate=D("120"), awarded=D("50")), D("50"), SOURCE_AWARDED),
        # Measured work above the commitment still wins on a partly let line.
        (LineFigures(estimate=D("100"), awarded=D("20"), certified=D("30")), D("30"), SOURCE_MEASURED),
    ],
)
def test_automatic_forecast_takes_the_most_mature_stage(figures: LineFigures, amount: Decimal, source: str) -> None:
    result = automatic_forecast(figures)
    assert (result.amount, result.source) == (amount, source)


def test_override_beats_every_stage_and_zero_is_a_real_override() -> None:
    final = LineFigures(awarded=D("90"), certified=D("90"), all_final=True, override=D("95"))
    assert (forecast_for(final).amount, forecast_for(final).source) == (D("95"), SOURCE_MANUAL)
    # A line someone says will cost nothing (scope removed) is not "no override".
    removed = LineFigures(estimate=D("50"), override=D("0"))
    assert (forecast_for(removed).amount, forecast_for(removed).source) == (D("0"), SOURCE_MANUAL)
    # The automatic figure stays visible next to the override.
    assert automatic_forecast(removed).source == SOURCE_ESTIMATE


def test_planned_is_budget_else_estimate() -> None:
    assert LineFigures(budget=D("100"), estimate=D("120")).planned == D("100")
    assert LineFigures(estimate=D("120")).planned == D("120")


def test_variance_pct_is_none_without_a_plan() -> None:
    assert variance_pct(D("110"), D("100")) == D("10.0")
    assert variance_pct(D("10"), D("0")) is None


def _rules(findings: list) -> set[str]:
    return {f.rule_id for f in findings}


def test_certified_over_committed_is_flagged_once_beyond_a_cent() -> None:
    within = LineInput("a", "330", LineFigures(awarded=D("100"), certified=D("100.01")))
    over = LineInput("b", "340", LineFigures(awarded=D("100"), certified=D("100.02")))
    findings = line_findings([within, over])
    flagged = [f for f in findings if f.rule_id == FINDING_CERTIFIED_OVER_COMMITTED]
    assert [f.line_key for f in flagged] == ["b"]
    assert flagged[0].amount == D("0.02")


def test_over_plan_uses_the_reported_forecast() -> None:
    over = LineInput("a", "330", LineFigures(budget=D("100"), awarded=D("130")))
    findings = line_findings([over])
    assert FINDING_OVER_PLAN in _rules(findings)
    hit = next(f for f in findings if f.rule_id == FINDING_OVER_PLAN)
    assert hit.amount == D("30")
    assert hit.details["pct"] == "30.0"
    # A manual forecast back on budget silences it.
    fixed = LineInput("a", "330", LineFigures(budget=D("100"), awarded=D("130"), override=D("100")))
    assert FINDING_OVER_PLAN not in _rules(line_findings([fixed]))


def test_partly_awarded_only_while_the_line_is_open_and_automatic() -> None:
    part = LineFigures(estimate=D("1000"), awarded=D("300"))
    assert FINDING_PARTLY_AWARDED in _rules(line_findings([LineInput("a", "340", part)]))
    half = LineFigures(estimate=D("1000"), awarded=D("500"))
    assert FINDING_PARTLY_AWARDED not in _rules(line_findings([LineInput("a", "340", half)]))
    overruled = LineFigures(estimate=D("1000"), awarded=D("300"), override=D("950"))
    assert FINDING_PARTLY_AWARDED not in _rules(line_findings([LineInput("a", "340", overruled)]))
    finished = LineFigures(estimate=D("1000"), awarded=D("300"), certified=D("300"), all_final=True)
    assert FINDING_PARTLY_AWARDED not in _rules(line_findings([LineInput("a", "340", finished)]))


def test_project_findings() -> None:
    quiet = project_findings(
        unassigned_committed=D("0"), pending_changes=D("0"), pending_count=0, days_since_snapshot=3, has_money=True
    )
    assert quiet == []
    loud = project_findings(
        unassigned_committed=D("5000"),
        pending_changes=D("1200"),
        pending_count=2,
        days_since_snapshot=None,
        has_money=True,
    )
    assert _rules(loud) == {FINDING_UNASSIGNED, FINDING_PENDING_CHANGES, FINDING_STALE_SNAPSHOT}
    # An empty project is not nagged to take snapshots.
    empty = project_findings(
        unassigned_committed=D("0"), pending_changes=D("0"), pending_count=0, days_since_snapshot=None, has_money=False
    )
    assert empty == []


def test_sort_puts_warnings_first_then_larger_amounts() -> None:
    findings = line_findings(
        [
            LineInput("a", "330", LineFigures(budget=D("100"), awarded=D("110"))),
            LineInput("b", "340", LineFigures(budget=D("100"), awarded=D("190"))),
            LineInput("c", "350", LineFigures(estimate=D("1000"), awarded=D("100"))),
        ]
    )
    ordered = sort_findings(findings)
    assert [(f.rule_id, f.line_key) for f in ordered][:2] == [(FINDING_OVER_PLAN, "b"), (FINDING_OVER_PLAN, "a")]
    assert ordered[-1].rule_id == FINDING_PARTLY_AWARDED
