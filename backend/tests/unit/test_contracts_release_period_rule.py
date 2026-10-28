# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A completion release waits out the lien period its jurisdiction sets.

Ontario keeps the holdback until 60 days after the certificate of substantial
performance is published; paying it earlier leaves the owner liable to lien
claimants for the same money twice. The figure was in the country defaults and
shown on the contract, and nothing stopped a release being approved on the day
of the certificate. These pin the rule that now does.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.core.validation.engine import Severity, ValidationContext
from app.modules.contracts.service import _release_period_meta
from app.modules.contracts.validators import RETENTION_RELEASE_RULES, RetentionReleasePeriodElapsedRule

ONTARIO = {"days": 60, "reference": "Construction Act, R.S.O. 1990, c. C.30"}


def _context(event: str = "substantial_completion", *, period=ONTARIO, started=None, today="2026-10-16"):
    return ValidationContext(
        data={
            "release": {"id": "r1", "event": event, "status": "proposed", "amount": "5000"},
            "release_period": period,
            "period_started_on": started,
            "today": today,
        },
        metadata={"locale": "en"},
    )


async def _run(context: ValidationContext):
    return await RetentionReleasePeriodElapsedRule().validate(context)


def test_the_rule_is_part_of_the_release_gate() -> None:
    assert RetentionReleasePeriodElapsedRule in RETENTION_RELEASE_RULES
    assert RetentionReleasePeriodElapsedRule.severity is Severity.ERROR


@pytest.mark.asyncio
async def test_a_release_that_does_not_say_when_the_period_started_is_held() -> None:
    (result,) = await _run(_context())
    assert not result.passed
    assert "60-day lien period" in result.message
    assert "Construction Act" in result.message


@pytest.mark.asyncio
async def test_a_release_before_the_period_has_run_is_held_until_the_day_it_ends() -> None:
    (result,) = await _run(_context(started="2026-09-01", today="2026-10-30"))
    assert not result.passed
    assert result.details["ends"] == "2026-10-31"
    assert "2026-10-31" in result.message


@pytest.mark.asyncio
async def test_the_release_goes_through_on_the_day_the_period_ends() -> None:
    (result,) = await _run(_context(started="2026-09-01", today="2026-10-31"))
    assert result.passed


@pytest.mark.parametrize("event", ["defects_period_end", "rate_step_down", "security_substituted"])
@pytest.mark.asyncio
async def test_events_not_paid_against_liens_are_not_held(event: str) -> None:
    assert await _run(_context(event)) == []


@pytest.mark.asyncio
async def test_a_jurisdiction_without_a_lien_period_is_not_held() -> None:
    assert await _run(_context(period=None)) == []


@pytest.mark.asyncio
async def test_the_finishing_holdback_waits_too() -> None:
    (result,) = await _run(_context("final_completion"))
    assert not result.passed


def test_the_release_row_records_when_the_period_ends() -> None:
    assert _release_period_meta("substantial_completion", 60, date(2026, 9, 1)) == {
        "release_period_days": 60,
        "period_started_on": "2026-09-01",
        "earliest_release_on": "2026-10-31",
    }
    assert _release_period_meta("substantial_completion", 60, None) == {"release_period_days": 60}
    assert _release_period_meta("rate_step_down", 60, date(2026, 9, 1)) == {}
    assert _release_period_meta("substantial_completion", None, date(2026, 9, 1)) == {}
