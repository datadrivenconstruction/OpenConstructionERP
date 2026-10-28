# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The ``pay_application`` rules, each held red and green.

A rule that never fires passes every test that only asserts the absence of a
finding, so every rule here gets one input it must reject and one it must
accept, and the rejected input's message is checked for the value that makes
it actionable. The last tests go through the engine by set name, because a
rule registered under a set nobody asks for is a rule that never runs, and
submission refuses to proceed (503) when the set comes back unsupported.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.validation.engine import Severity, ValidationContext, rule_registry, validation_engine
from app.modules.contracts.validators import (
    PAY_APPLICATION_RULE_SET,
    PAY_APPLICATION_RULES,
    ClaimLineOverbilledRule,
    ClaimPeriodGapRule,
    ClaimPeriodOrderRule,
    ClaimPeriodOverlapRule,
    ClaimPeriodPresentRule,
    ClaimPeriodUnparsedRule,
    register_contracts_validation_rules,
)

pytestmark = pytest.mark.asyncio


def _claim(**overrides: Any) -> dict[str, Any]:
    claim = {
        "id": "claim-2",
        "number": "PC-002",
        "status": "draft",
        "period_start": "2026-04-01",
        "period_end": "2026-04-30",
        "claim_date": "2026-04-30",
        "period_from": "2026-04-01",
        "period_to": "2026-04-30",
        "application_date": "2026-04-30",
    }
    claim.update(overrides)
    return claim


def _context(
    claim: dict[str, Any] | None = None,
    previous: dict[str, Any] | None = None,
    lines: list[dict[str, Any]] | None = None,
    currency: str = "USD",
) -> ValidationContext:
    return ValidationContext(
        data={
            "claim": claim if claim is not None else _claim(),
            "previous_claim": previous,
            "lines": lines or [],
            "currency": currency,
            "as_of": "2026-04-30",
        },
        metadata={"locale": "en"},
    )


def _previous(period_to: str) -> dict[str, Any]:
    return {"id": "claim-1", "number": "PC-001", "period_from": "2026-03-01", "period_to": period_to}


async def _failures(rule: Any, context: ValidationContext) -> list[Any]:
    return [result for result in await rule.validate(context) if not result.passed]


async def test_a_claim_without_a_period_end_is_reported() -> None:
    rule = ClaimPeriodPresentRule()
    failed = await _failures(rule, _context(_claim(period_end="", period_to=None)))
    assert len(failed) == 1
    assert "PC-002" in failed[0].message
    # It blocks: billing order is what line 7 is read from, and an undated
    # claim leaves the next one reading nothing before it.
    assert failed[0].severity == Severity.ERROR

    assert await _failures(rule, _context()) == []
    # A period end that was entered and cannot be read is period_unparsed's
    # finding, so it is not reported twice.
    assert await rule.validate(_context(_claim(period_end="31/04/2026", period_to=None))) == []


async def test_a_period_that_ends_before_it_starts_blocks() -> None:
    rule = ClaimPeriodOrderRule()
    failed = await _failures(rule, _context(_claim(period_from="2026-04-30", period_to="2026-04-01")))
    assert len(failed) == 1
    assert failed[0].severity == Severity.ERROR
    assert "2026-04-30" in failed[0].message and "2026-04-01" in failed[0].message

    assert await _failures(rule, _context()) == []
    assert await _failures(rule, _context(_claim(period_from="2026-04-30", period_to="2026-04-30"))) == []


async def test_a_period_that_starts_inside_the_previous_one_is_reported() -> None:
    rule = ClaimPeriodOverlapRule()
    failed = await _failures(rule, _context(previous=_previous("2026-04-01")))
    assert len(failed) == 1
    assert "PC-001" in failed[0].message and "2026-04-01" in failed[0].message

    assert await _failures(rule, _context(previous=_previous("2026-03-31"))) == []
    # The first claim on a contract has nothing to overlap.
    assert await rule.validate(_context(previous=None)) == []


async def test_days_left_between_two_claims_are_reported() -> None:
    rule = ClaimPeriodGapRule()
    failed = await _failures(rule, _context(previous=_previous("2026-03-28")))
    assert len(failed) == 1
    # March 29, 30 and 31 are billed by nobody.
    assert failed[0].details["days"] == "3"
    assert "unbilled days: 3" in failed[0].message

    # Periods that touch leave no gap, and an overlap is the other rule's.
    assert await _failures(rule, _context(previous=_previous("2026-03-31"))) == []
    assert await rule.validate(_context(previous=_previous("2026-04-10"))) == []


async def test_a_period_string_no_date_can_be_read_from_is_reported_per_field() -> None:
    rule = ClaimPeriodUnparsedRule()
    failed = await _failures(
        rule,
        _context(_claim(period_start="01/04/2026", period_from=None, claim_date="soon", application_date=None)),
    )
    assert [result.details["field"] for result in failed] == ["period start", "application date"]
    assert "'01/04/2026'" in failed[0].message

    assert await _failures(rule, _context()) == []
    # A blank string is a missing date, not an unreadable one.
    assert await _failures(rule, _context(_claim(claim_date="", application_date=None))) == []


def _line(scheduled: str, billed: str, code: str = "03 30 00") -> dict[str, Any]:
    return {
        "contract_line_id": f"line-{code}",
        "code": code,
        "description": "Cast-in-place concrete",
        "scheduled_value": scheduled,
        "total_completed_stored": billed,
    }


async def test_a_line_billed_beyond_its_scheduled_value_blocks() -> None:
    rule = ClaimLineOverbilledRule()
    failed = await _failures(rule, _context(lines=[_line("100000.00", "100000.02")]))
    assert len(failed) == 1
    assert failed[0].severity == Severity.ERROR
    assert "03 30 00" in failed[0].message
    # Money is quoted in the claim's currency, not as a bare number.
    assert "$" in failed[0].message or "USD" in failed[0].message

    # Within a cent is the same number.
    assert await _failures(rule, _context(lines=[_line("100000.00", "100000.01")])) == []
    assert await _failures(rule, _context(lines=[_line("100000.00", "40000.00")])) == []


async def test_a_credit_line_is_overbilled_past_its_credit() -> None:
    rule = ClaimLineOverbilledRule()
    assert len(await _failures(rule, _context(lines=[_line("-5000.00", "-5000.50")]))) == 1
    assert await _failures(rule, _context(lines=[_line("-5000.00", "-2500.00")])) == []


async def test_every_rule_is_registered_under_the_set_submission_asks_for() -> None:
    register_contracts_validation_rules()
    assert rule_registry.has_rules(PAY_APPLICATION_RULE_SET)
    registered = {rule.rule_id for rule in rule_registry.get_rules_for_sets([PAY_APPLICATION_RULE_SET])}
    assert {rule_class.rule_id for rule_class in PAY_APPLICATION_RULES} <= registered


async def test_the_engine_runs_the_set_by_name_and_finds_both_ways() -> None:
    register_contracts_validation_rules()
    clean = await validation_engine.validate(
        data=_context(previous=_previous("2026-03-31"), lines=[_line("100.00", "50.00")]).data,
        rule_sets=[PAY_APPLICATION_RULE_SET],
        target_type="progress_claim",
        metadata={"locale": "en"},
    )
    assert clean.unsupported_rule_sets == []
    assert not clean.has_errors

    dirty = await validation_engine.validate(
        data=_context(_claim(period_from="2026-04-30", period_to="2026-04-01"), lines=[_line("100.00", "150.00")]).data,
        rule_sets=[PAY_APPLICATION_RULE_SET],
        target_type="progress_claim",
        metadata={"locale": "en"},
    )
    failed = {result.rule_id for result in dirty.results if not result.passed}
    assert {"pay_application.period_order", "pay_application.line_overbilled"} <= failed
    assert dirty.has_errors


async def test_a_line_whose_percent_went_backwards_is_reported() -> None:
    from app.modules.contracts.validators import ClaimPercentRegressedRule

    rule = ClaimPercentRegressedRule()
    context = _context()
    context.data["percent_regressed"] = [
        {
            "contract_line_id": "line-1",
            "code": "03 30 00",
            "observed_pct": "30.0000",
            "requested_value": "30000.0000",
            "previous_value": "40000.0000",
        }
    ]
    failed = await _failures(rule, context)
    assert len(failed) == 1
    assert failed[0].severity == Severity.WARNING
    assert "03 30 00" in failed[0].message
    # The percent as a person writes it, not as it is stored.
    assert "30%" in failed[0].message
    assert failed[0].element_ref == "line-1"

    assert await _failures(rule, _context()) == []
