# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the ``full_evm`` validation rule set.

Each rule is exercised both ways: on data it should accept and on data it
should reject. A rule that only ever sees good data proves nothing, and a rule
set that is registered but never fires is a stub wearing a rule's clothes.
"""

from __future__ import annotations

import pytest

from app.core.validation.engine import (
    RuleCategory,
    Severity,
    ValidationContext,
    ValidationStatus,
    rule_registry,
    validation_engine,
)
from app.modules.full_evm.validators import (
    FULL_EVM_RULE_SET,
    BaselineBacPositive,
    BaselinePeriodsOrdered,
    BaselinePvMatchesBac,
    BaselinePvMonotonic,
    BaselineQuantityMonotonic,
    MeasureEacMethodDeclared,
    MeasureEvWithinBac,
    MeasureIndicesDefined,
    MeasureNonNegative,
    MeasurePvFollowsBaseline,
    MeasureTcpiAchievable,
)


def _baseline(bac: str = "1000000", periods: list[dict] | None = None) -> dict:
    """A well-formed baseline payload: a rising curve that ends at the budget."""
    return {
        "kind": "baseline",
        "bac": bac,
        "currency": "EUR",
        "periods": periods
        if periods is not None
        else [
            {"ordinal": 0, "label": "M1", "period_end": "2026-01-31", "planned_value": "250000"},
            {"ordinal": 1, "label": "M2", "period_end": "2026-02-28", "planned_value": "600000"},
            {"ordinal": 2, "label": "M3", "period_end": "2026-03-31", "planned_value": "1000000"},
        ],
    }


def _measure(**overrides: object) -> dict:
    """A well-formed measurement payload with every index defined."""
    payload: dict = {
        "kind": "measure",
        "data_date": "2026-02-28",
        "bac": "1000000",
        "pv": "600000",
        "ev": "550000",
        "ac": "580000",
        "baseline_pv": "600000",
        "spi": "0.916667",
        "cpi": "0.948276",
        "tcpi_bac": "1.071429",
        "eac": "1054545.45",
        "eac_method": "cpi",
        "eac_method_effective": "cpi",
    }
    payload.update(overrides)
    return payload


async def _run(rule: object, data: dict) -> list:
    """Run one rule against a payload and return its results."""
    return await rule.validate(ValidationContext(data=data))  # type: ignore[attr-defined]


def _failures(results: list) -> list:
    """Only the failing results, which is what gets stored on a row."""
    return [r for r in results if not r.passed]


# ── Registration ─────────────────────────────────────────────────────────────


def test_rule_set_resolves_to_registered_rules() -> None:
    """``full_evm`` is a reachable rule set, not a name nothing answers to."""
    assert rule_registry.has_rules(FULL_EVM_RULE_SET)
    assert len(rule_registry.get_rules_for_sets([FULL_EVM_RULE_SET])) >= 11


def test_every_rule_declares_a_severity_and_category() -> None:
    """A rule without a severity cannot be triaged, so the contract is asserted."""
    for rule in rule_registry.get_rules_for_sets([FULL_EVM_RULE_SET]):
        assert isinstance(rule.severity, Severity)
        assert isinstance(rule.category, RuleCategory)
        assert rule.description


# ── Baseline rules ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bac_must_be_positive() -> None:
    """A zero budget makes every index undefined, so it is an ERROR."""
    rule = BaselineBacPositive()

    assert _failures(await _run(rule, _baseline())) == []

    failures = _failures(await _run(rule, _baseline(bac="0")))
    assert len(failures) == 1
    assert failures[0].severity == Severity.ERROR


@pytest.mark.asyncio
async def test_periods_must_run_forward_in_time() -> None:
    """A repeated or reversed period end is a structural fault."""
    rule = BaselinePeriodsOrdered()

    assert _failures(await _run(rule, _baseline())) == []

    reversed_curve = _baseline(
        periods=[
            {"ordinal": 0, "label": "M1", "period_end": "2026-02-28", "planned_value": "250000"},
            {"ordinal": 1, "label": "M2", "period_end": "2026-01-31", "planned_value": "600000"},
        ],
    )
    failures = _failures(await _run(rule, reversed_curve))
    assert len(failures) == 1
    assert "not after" in failures[0].message


@pytest.mark.asyncio
async def test_a_baseline_with_no_curve_is_reported() -> None:
    """No periods means no planned value, so there is nothing to measure against."""
    failures = _failures(await _run(BaselinePeriodsOrdered(), _baseline(periods=[])))

    assert len(failures) == 1
    assert "no periods" in failures[0].message


@pytest.mark.asyncio
async def test_cumulative_planned_value_may_not_decrease() -> None:
    """A dip in the running total is the per-period-amounts mistake."""
    rule = BaselinePvMonotonic()

    assert _failures(await _run(rule, _baseline())) == []

    dipping = _baseline(
        periods=[
            {"ordinal": 0, "label": "M1", "period_end": "2026-01-31", "planned_value": "600000"},
            {"ordinal": 1, "label": "M2", "period_end": "2026-02-28", "planned_value": "250000"},
            {"ordinal": 2, "label": "M3", "period_end": "2026-03-31", "planned_value": "1000000"},
        ],
    )
    failures = _failures(await _run(rule, dipping))
    assert len(failures) == 1
    assert failures[0].element_ref == "M2"
    assert failures[0].severity == Severity.ERROR


@pytest.mark.asyncio
async def test_the_curve_must_end_at_the_budget() -> None:
    """A curve stopping short of BAC flatters SPI as the project completes."""
    rule = BaselinePvMatchesBac()

    assert _failures(await _run(rule, _baseline())) == []

    short = _baseline(
        periods=[
            {"ordinal": 0, "label": "M1", "period_end": "2026-01-31", "planned_value": "250000"},
            {"ordinal": 1, "label": "M2", "period_end": "2026-02-28", "planned_value": "700000"},
        ],
    )
    failures = _failures(await _run(rule, short))
    assert len(failures) == 1
    assert "300000" in failures[0].details["gap"]


@pytest.mark.asyncio
async def test_rounding_across_a_long_curve_does_not_trip_the_budget_check() -> None:
    """A cent of drift is tolerance, not a finding."""
    close = _baseline(
        periods=[{"ordinal": 0, "label": "M1", "period_end": "2026-03-31", "planned_value": "999999.995"}],
    )

    assert _failures(await _run(BaselinePvMatchesBac(), close)) == []


@pytest.mark.asyncio
async def test_planned_quantity_curve_is_checked_only_when_supplied() -> None:
    """Quantity is optional supporting evidence, so its absence is not a finding."""
    rule = BaselineQuantityMonotonic()

    assert await _run(rule, _baseline()) == []

    dipping = _baseline(
        periods=[
            {
                "ordinal": 0,
                "label": "M1",
                "period_end": "2026-01-31",
                "planned_value": "250000",
                "planned_quantity": "80",
            },
            {
                "ordinal": 1,
                "label": "M2",
                "period_end": "2026-02-28",
                "planned_value": "600000",
                "planned_quantity": "40",
            },
            {
                "ordinal": 2,
                "label": "M3",
                "period_end": "2026-03-31",
                "planned_value": "1000000",
                "planned_quantity": "120",
            },
        ],
    )
    failures = _failures(await _run(rule, dipping))
    assert len(failures) == 1
    assert failures[0].severity == Severity.WARNING


# ── Measurement rules ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_negative_cumulative_amounts_are_errors() -> None:
    """A negative running total is a data fault, not a credit."""
    rule = MeasureNonNegative()

    assert _failures(await _run(rule, _measure())) == []

    failures = _failures(await _run(rule, _measure(ac="-5")))
    assert len(failures) == 1
    assert failures[0].element_ref == "ac"


@pytest.mark.asyncio
async def test_earned_value_cannot_exceed_the_budget() -> None:
    """EV > BAC means progress was claimed against a smaller, superseded budget."""
    rule = MeasureEvWithinBac()

    assert _failures(await _run(rule, _measure())) == []

    failures = _failures(await _run(rule, _measure(ev="1200000")))
    assert len(failures) == 1
    assert failures[0].severity == Severity.ERROR


@pytest.mark.asyncio
async def test_a_planned_value_override_is_visible_but_allowed() -> None:
    """Diverging from the curve is a WARNING, not a block."""
    rule = MeasurePvFollowsBaseline()

    assert _failures(await _run(rule, _measure())) == []

    failures = _failures(await _run(rule, _measure(pv="450000")))
    assert len(failures) == 1
    assert failures[0].severity == Severity.WARNING


@pytest.mark.asyncio
async def test_an_early_project_with_no_spend_is_informational_never_an_error() -> None:
    """Zero EV and zero AC is the normal start state, not a defect.

    This is the rule that decides whether a brand-new project shows up in the
    register as broken. It must report INFO so the row stays usable.
    """
    rule = MeasureIndicesDefined()
    early = _measure(pv="0", ev="0", ac="0", spi=None, cpi=None, tcpi_bac=None)

    failures = _failures(await _run(rule, early))
    assert len(failures) == 1
    assert failures[0].severity == Severity.INFO
    assert "CPI" in failures[0].message
    assert "SPI" in failures[0].message


@pytest.mark.asyncio
async def test_a_fully_measurable_project_passes_the_index_rule() -> None:
    """With every denominator non-zero the rule passes rather than staying quiet."""
    results = await _run(MeasureIndicesDefined(), _measure())

    assert len(results) == 1
    assert results[0].passed


@pytest.mark.asyncio
async def test_the_forecast_must_name_the_formula_that_produced_it() -> None:
    """A row that cannot say which EAC formula ran is not auditable."""
    rule = MeasureEacMethodDeclared()

    assert _failures(await _run(rule, _measure())) == []

    failures = _failures(await _run(rule, _measure(eac_method_effective="banana")))
    assert len(failures) == 1
    assert failures[0].severity == Severity.ERROR


@pytest.mark.asyncio
async def test_auto_is_a_strategy_and_can_never_be_the_effective_formula() -> None:
    """``auto`` selects a formula; it is not one, so it cannot be what ran."""
    failures = _failures(await _run(MeasureEacMethodDeclared(), _measure(eac_method_effective="auto")))

    assert len(failures) == 1


@pytest.mark.asyncio
async def test_a_fallback_is_reported_in_the_passing_message() -> None:
    """When the requested formula could not run, the pass says so out loud."""
    results = await _run(
        MeasureEacMethodDeclared(),
        _measure(eac_method="cpi", eac_method_effective="remaining"),
    )

    assert results[0].passed
    assert "was not computable" in results[0].message


@pytest.mark.asyncio
async def test_an_unreachable_recovery_efficiency_is_flagged() -> None:
    """A TCPI above the practitioner alarm line is a WARNING with both numbers."""
    rule = MeasureTcpiAchievable()

    assert _failures(await _run(rule, _measure(tcpi_bac="1.02"))) == []

    failures = _failures(await _run(rule, _measure(tcpi_bac="1.45")))
    assert len(failures) == 1
    assert "1.45" in failures[0].message


@pytest.mark.asyncio
async def test_a_consumed_budget_with_work_outstanding_is_flagged() -> None:
    """An undefined TCPI with scope remaining is the worst case, not a silence."""
    spent_out = _measure(bac="1000000", ev="600000", ac="1000000", tcpi_bac=None)

    failures = _failures(await _run(MeasureTcpiAchievable(), spent_out))
    assert len(failures) == 1
    assert "fully consumed" in failures[0].message


@pytest.mark.asyncio
async def test_a_finished_project_needs_no_recovery_efficiency() -> None:
    """All value earned with the budget spent is a pass, not the alarm."""
    finished = _measure(bac="1000000", ev="1000000", ac="1000000", tcpi_bac=None)

    results = await _run(MeasureTcpiAchievable(), finished)
    assert results[0].passed


# ── Rules only speak about their own kind of row ─────────────────────────────


@pytest.mark.asyncio
async def test_baseline_rules_stay_silent_on_a_measurement() -> None:
    """A rule that fires on the wrong payload would poison every measurement."""
    for rule in (BaselineBacPositive(), BaselinePvMonotonic(), BaselinePvMatchesBac()):
        assert await _run(rule, _measure()) == []


@pytest.mark.asyncio
async def test_measurement_rules_stay_silent_on_a_baseline() -> None:
    """The same guarantee in the other direction."""
    for rule in (MeasureNonNegative(), MeasureEvWithinBac(), MeasureIndicesDefined()):
        assert await _run(rule, _baseline()) == []


# ── End to end through the core engine ───────────────────────────────────────


@pytest.mark.asyncio
async def test_a_broken_baseline_reports_errors_through_the_engine() -> None:
    """The rules are reachable by rule-set name, not only by direct construction."""
    broken = _baseline(
        bac="1000000",
        periods=[
            {"ordinal": 0, "label": "M1", "period_end": "2026-01-31", "planned_value": "600000"},
            {"ordinal": 1, "label": "M2", "period_end": "2026-02-28", "planned_value": "250000"},
        ],
    )

    report = await validation_engine.validate(
        data=broken,
        rule_sets=[FULL_EVM_RULE_SET],
        target_type="evm_baseline",
        target_id="test",
    )

    assert report.unsupported_rule_sets == []
    assert report.status == ValidationStatus.ERRORS
    rule_ids = {r.rule_id for r in report.errors}
    assert "full_evm.baseline_pv_monotonic" in rule_ids
    assert "full_evm.baseline_pv_matches_bac" in rule_ids


@pytest.mark.asyncio
async def test_a_sound_baseline_passes_through_the_engine() -> None:
    """A correct curve produces a clean report with a real score."""
    report = await validation_engine.validate(
        data=_baseline(),
        rule_sets=[FULL_EVM_RULE_SET],
        target_type="evm_baseline",
        target_id="test",
    )

    assert report.status == ValidationStatus.PASSED
    assert report.score == 1.0
