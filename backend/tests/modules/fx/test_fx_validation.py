# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the ``fx`` validation rule set.

Each rule gets three cases: one context it must reject, one it must pass, and
one where there is nothing of its kind to look at and it must stay silent. The
silent case matters as much as the other two - a rule that returns a passing
result when it examined nothing lets an empty project accumulate a clean score
out of checks that never ran.

Every assertion names the ``rule_id`` and the ``passed`` flag, so a rule that
quietly returned an empty list cannot be mistaken for a rule that passed.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.validation.engine import (
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
    validation_engine,
)
from app.modules.fx.validators import (
    FX_RULE_SET,
    FxPinnedSetResolvable,
    FxPolicyCurrencyCoverage,
    FxQuoteIntegrity,
    FxQuoteMovement,
    FxRateFreshness,
)

PINNED_SET_ID = "11111111-1111-1111-1111-111111111111"
PROJECT_ID = "22222222-2222-2222-2222-222222222222"


def _rate_set(**overrides: Any) -> dict[str, Any]:
    """A well-formed rate-set block, with overrides applied."""
    block: dict[str, Any] = {
        "id": PINNED_SET_ID,
        "base_currency": "EUR",
        "rate_date": "2026-03-02",
        "source": "ecb",
        "source_ref": "https://example.invalid/eurofxref-daily.xml",
        "is_locked": False,
        "quotes": {"USD": "1.0850", "TRY": "42.5000"},
    }
    block.update(overrides)
    return block


def _policy(**overrides: Any) -> dict[str, Any]:
    """A well-formed policy block, with overrides applied."""
    block: dict[str, Any] = {
        "project_id": PROJECT_ID,
        "estimating_currency": "EUR",
        "procurement_currency": "TRY",
        "reporting_currency": "USD",
        "rate_mode": "live",
        "pinned_rate_set_id": None,
        "max_rate_age_days": 30,
    }
    block.update(overrides)
    return block


def _context(**payload: Any) -> ValidationContext:
    """A validation context over the module's plain-dict payload."""
    metadata = payload.pop("metadata", {})
    data: dict[str, Any] = {"as_of": "2026-03-10", "policy": None, "rate_set": None, "previous_rate_set": None}
    data.update(payload)
    return ValidationContext(data=data, metadata=metadata)


def _failures(results: list[RuleResult], rule: ValidationRule) -> list[RuleResult]:
    """Failing results belonging to ``rule``."""
    return [row for row in results if row.rule_id == rule.rule_id and not row.passed]


def _passes(results: list[RuleResult], rule: ValidationRule) -> list[RuleResult]:
    """Passing results belonging to ``rule``."""
    return [row for row in results if row.rule_id == rule.rule_id and row.passed]


# ── fx.quote_integrity ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_quote_integrity_rejects_a_zero_rate() -> None:
    rule = FxQuoteIntegrity()
    results = await rule.validate(_context(rate_set=_rate_set(quotes={"USD": "1.085", "TRY": "0"})))

    failed = _failures(results, rule)
    assert [row.details["currency"] for row in failed] == ["TRY"]
    assert failed[0].severity == Severity.ERROR
    assert _passes(results, rule)


@pytest.mark.asyncio
async def test_quote_integrity_rejects_the_base_quoted_against_itself() -> None:
    rule = FxQuoteIntegrity()
    results = await rule.validate(_context(rate_set=_rate_set(quotes={"EUR": "1.0"})))
    assert [row.details["currency"] for row in _failures(results, rule)] == ["EUR"]


@pytest.mark.asyncio
async def test_quote_integrity_rejects_a_rate_that_is_not_a_number() -> None:
    rule = FxQuoteIntegrity()
    results = await rule.validate(_context(rate_set=_rate_set(quotes={"USD": "n/a"})))
    assert len(_failures(results, rule)) == 1


@pytest.mark.asyncio
async def test_quote_integrity_passes_a_clean_set() -> None:
    rule = FxQuoteIntegrity()
    results = await rule.validate(_context(rate_set=_rate_set()))
    assert len(_passes(results, rule)) == 2
    assert _failures(results, rule) == []


@pytest.mark.asyncio
async def test_quote_integrity_is_silent_when_there_is_no_set() -> None:
    assert await FxQuoteIntegrity().validate(_context()) == []


# ── fx.quote_movement ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_quote_movement_flags_a_misplaced_decimal() -> None:
    """A rate that moved tenfold overnight is a typo, not a market."""
    rule = FxQuoteMovement()
    results = await rule.validate(
        _context(
            rate_set=_rate_set(quotes={"USD": "10.850", "TRY": "42.5"}),
            previous_rate_set=_rate_set(rate_date="2026-03-01", quotes={"USD": "1.0850", "TRY": "42.4"}),
        )
    )
    failed = _failures(results, rule)
    assert [row.details["currency"] for row in failed] == ["USD"]
    assert failed[0].severity == Severity.WARNING
    assert [row.element_ref for row in _passes(results, rule)] == [f"{PINNED_SET_ID}:TRY"]


@pytest.mark.asyncio
async def test_quote_movement_passes_an_ordinary_days_drift() -> None:
    rule = FxQuoteMovement()
    results = await rule.validate(
        _context(
            rate_set=_rate_set(quotes={"USD": "1.0900"}),
            previous_rate_set=_rate_set(rate_date="2026-03-01", quotes={"USD": "1.0850"}),
        )
    )
    assert _failures(results, rule) == []
    assert len(_passes(results, rule)) == 1


@pytest.mark.asyncio
async def test_quote_movement_tolerance_can_be_tightened() -> None:
    rule = FxQuoteMovement()
    results = await rule.validate(
        _context(
            rate_set=_rate_set(quotes={"USD": "1.0900"}),
            previous_rate_set=_rate_set(rate_date="2026-03-01", quotes={"USD": "1.0850"}),
            metadata={"max_quote_move_pct": "0.1"},
        )
    )
    assert len(_failures(results, rule)) == 1


@pytest.mark.asyncio
async def test_quote_movement_is_silent_for_the_first_set_ever() -> None:
    assert await FxQuoteMovement().validate(_context(rate_set=_rate_set())) == []


# ── fx.policy_currency_coverage ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_coverage_rejects_a_reporting_currency_the_set_cannot_price() -> None:
    rule = FxPolicyCurrencyCoverage()
    results = await rule.validate(_context(policy=_policy(reporting_currency="GBP"), rate_set=_rate_set()))

    failed = _failures(results, rule)
    assert [row.details["role"] for row in failed] == ["reporting"]
    assert failed[0].severity == Severity.ERROR


@pytest.mark.asyncio
async def test_coverage_accepts_the_base_currency_itself() -> None:
    """EUR is the base, so it is priceable even though it is never quoted."""
    rule = FxPolicyCurrencyCoverage()
    results = await rule.validate(_context(policy=_policy(), rate_set=_rate_set()))
    assert _failures(results, rule) == []
    assert len(_passes(results, rule)) == 3


@pytest.mark.asyncio
async def test_coverage_rejects_a_missing_currency() -> None:
    rule = FxPolicyCurrencyCoverage()
    results = await rule.validate(_context(policy=_policy(procurement_currency=""), rate_set=_rate_set()))
    assert [row.details["role"] for row in _failures(results, rule)] == ["procurement"]


@pytest.mark.asyncio
async def test_coverage_is_silent_without_a_policy() -> None:
    assert await FxPolicyCurrencyCoverage().validate(_context(rate_set=_rate_set())) == []


# ── fx.pinned_set_resolvable ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pin_rejects_a_set_that_is_not_locked() -> None:
    """An unlocked pin is not a pin: the next refresh can rewrite the set."""
    rule = FxPinnedSetResolvable()
    results = await rule.validate(
        _context(
            policy=_policy(rate_mode="pinned", pinned_rate_set_id=PINNED_SET_ID),
            rate_set=_rate_set(is_locked=False),
        )
    )
    failed = _failures(results, rule)
    assert len(failed) == 1
    assert failed[0].details["is_locked"] is False


@pytest.mark.asyncio
async def test_pin_rejects_a_set_that_cannot_be_resolved() -> None:
    rule = FxPinnedSetResolvable()
    results = await rule.validate(
        _context(policy=_policy(rate_mode="pinned", pinned_rate_set_id=PINNED_SET_ID), rate_set=None)
    )
    assert _failures(results, rule)[0].details["pinned_rate_set_id"] == PINNED_SET_ID


@pytest.mark.asyncio
async def test_pin_rejects_a_pinned_mode_with_no_set_named() -> None:
    rule = FxPinnedSetResolvable()
    results = await rule.validate(_context(policy=_policy(rate_mode="pinned"), rate_set=_rate_set(is_locked=True)))
    assert len(_failures(results, rule)) == 1


@pytest.mark.asyncio
async def test_pin_passes_a_locked_resolvable_set() -> None:
    rule = FxPinnedSetResolvable()
    results = await rule.validate(
        _context(
            policy=_policy(rate_mode="pinned", pinned_rate_set_id=PINNED_SET_ID),
            rate_set=_rate_set(is_locked=True),
        )
    )
    assert _failures(results, rule) == []
    assert len(_passes(results, rule)) == 1


@pytest.mark.asyncio
async def test_pin_is_silent_for_a_project_on_live_rates() -> None:
    assert await FxPinnedSetResolvable().validate(_context(policy=_policy(), rate_set=_rate_set())) == []


# ── fx.rate_freshness ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_freshness_flags_rates_older_than_the_project_tolerates() -> None:
    rule = FxRateFreshness()
    results = await rule.validate(
        _context(policy=_policy(max_rate_age_days=5), rate_set=_rate_set(rate_date="2026-01-02"))
    )
    failed = _failures(results, rule)
    assert failed[0].details["age_days"] == 67
    assert failed[0].severity == Severity.WARNING


@pytest.mark.asyncio
async def test_freshness_passes_inside_the_tolerance() -> None:
    rule = FxRateFreshness()
    results = await rule.validate(_context(policy=_policy(max_rate_age_days=30), rate_set=_rate_set()))
    assert _failures(results, rule) == []
    assert len(_passes(results, rule)) == 1


@pytest.mark.asyncio
async def test_freshness_does_not_nag_a_deliberately_pinned_project() -> None:
    """Pinning means using old rates on purpose; warning about it trains people to ignore the light."""
    rule = FxRateFreshness()
    results = await rule.validate(
        _context(
            policy=_policy(rate_mode="pinned", pinned_rate_set_id=PINNED_SET_ID, max_rate_age_days=5),
            rate_set=_rate_set(rate_date="2020-01-02", is_locked=True),
        )
    )
    assert results == []


@pytest.mark.asyncio
async def test_freshness_is_silent_without_a_policy() -> None:
    assert await FxRateFreshness().validate(_context(rate_set=_rate_set())) == []


# ── Rule-set wiring ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_fx_rule_set_is_registered_and_reachable() -> None:
    """The engine must find real rules under ``fx``, not report it unsupported."""
    _supported, unsupported = rule_registry.resolve_rule_sets([FX_RULE_SET])
    assert unsupported == []
    assert len(rule_registry.get_rules_for_sets([FX_RULE_SET])) == 5


@pytest.mark.asyncio
async def test_engine_run_over_a_broken_setup_reports_errors_and_warnings() -> None:
    report = await validation_engine.validate(
        data={
            "as_of": "2026-03-10",
            "policy": _policy(reporting_currency="GBP", max_rate_age_days=1),
            "rate_set": _rate_set(quotes={"USD": "1.085", "TRY": "0"}),
            "previous_rate_set": None,
        },
        rule_sets=[FX_RULE_SET],
        target_type="fx_policy",
        target_id=PROJECT_ID,
    )
    assert report.unsupported_rule_sets == []
    assert {row.rule_id for row in report.errors} == {"fx.quote_integrity", "fx.policy_currency_coverage"}
    assert {row.rule_id for row in report.warnings} == {"fx.rate_freshness"}
    assert report.engine_errors == []


@pytest.mark.asyncio
async def test_engine_run_over_a_healthy_setup_is_clean() -> None:
    report = await validation_engine.validate(
        data={
            "as_of": "2026-03-10",
            "policy": _policy(),
            "rate_set": _rate_set(),
            "previous_rate_set": _rate_set(rate_date="2026-03-01", quotes={"USD": "1.08", "TRY": "42.4"}),
        },
        rule_sets=[FX_RULE_SET],
    )
    assert report.errors == []
    assert report.warnings == []
    assert report.passed_rules
