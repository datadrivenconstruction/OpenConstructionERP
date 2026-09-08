# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The rule that finds a duration counted on another week than the project's.

Until September every recompute in the schedule module counted Monday to
Friday whatever the project's region, while BOQ generation drew dates on the
regional week. The fix rewrites nothing already stored, so a Gulf schedule can
carry rows counted on both weeks until each row's dates are saved again. The
rule under test is how those rows are found, and its safety matters as much as
its reach: it must never fire on a project whose week is Monday to Friday, and
never on a duration somebody entered on purpose.

Sunday 7 June 2026 to Thursday 11 June 2026 is the span used throughout: five
working days in Doha, four counted Monday to Friday.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.core.validation.messages import available_locales, is_key_present
from app.modules.schedule.validators import (
    _SCHEDULE_RULES,
    SCHEDULE_RULE_SET,
    DurationCountedOnProjectWeek,
)

_SUNDAY = "2026-06-07"
_MONDAY = "2026-06-08"
_THURSDAY = "2026-06-11"

# Stored the way the project picker stores it, not as a calendar key.
_GULF = "GulfStates"
_GERMANY = "DACH"


def _ctx(
    activities: list[dict[str, Any]],
    *,
    region: str | None = None,
    locale: str = "en",
    metadata: dict[str, Any] | None = None,
) -> ValidationContext:
    return ValidationContext(
        data={"activities": activities},
        region=region,
        metadata={"locale": locale, **(metadata or {})},
    )


def _task(duration: Any, *, start: str = _SUNDAY, end: str = _THURSDAY, **extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "a1",
        "name": "Pour slab",
        "activity_type": "task",
        "duration_days": duration,
        "start_date": start,
        "end_date": end,
    }
    row.update(extra)
    return row


@pytest.mark.asyncio
async def test_a_gulf_row_counted_monday_to_friday_is_flagged() -> None:
    results = await DurationCountedOnProjectWeek().validate(_ctx([_task(4)], region=_GULF))

    assert len(results) == 1
    finding = results[0]
    assert not finding.passed
    assert finding.severity == Severity.WARNING
    assert finding.element_ref == "a1"
    assert finding.details == {
        "stored_duration_days": 4,
        "on_project_week": 5,
        "on_default_week": 4,
        "calendar": "Gulf (Sun-Thu, 8h)",
    }
    assert "Pour slab" in finding.message
    assert "Sun-Thu" in finding.message, "the message names the week the project works"
    assert finding.suggestion


@pytest.mark.asyncio
async def test_the_same_row_counted_on_the_gulf_week_passes() -> None:
    results = await DurationCountedOnProjectWeek().validate(_ctx([_task(5)], region=_GULF))

    assert len(results) == 1
    assert results[0].passed
    assert results[0].message == "OK"


@pytest.mark.asyncio
async def test_a_project_on_the_default_week_is_never_judged() -> None:
    """Where the project's week is Monday to Friday the two counts cannot differ.

    The rule says nothing rather than handing out a pass it could not have
    withheld, and a payload with no region at all is treated the same way.
    """
    rule = DurationCountedOnProjectWeek()

    assert await rule.validate(_ctx([_task(4)], region=_GERMANY)) == []
    assert await rule.validate(_ctx([_task(4)], region=None)) == []


@pytest.mark.asyncio
async def test_a_duration_matching_neither_week_was_entered_on_purpose() -> None:
    results = await DurationCountedOnProjectWeek().validate(_ctx([_task(12)], region=_GULF))

    assert results == []


@pytest.mark.asyncio
async def test_milestones_and_rows_without_dates_are_left_alone() -> None:
    rows = [
        _task(0, activity_type="milestone", id="m"),
        _task(4, activity_type="summary", id="s"),
        {"id": "no-end", "name": "Open", "activity_type": "task", "duration_days": 4, "start_date": _SUNDAY},
        _task("not a number", id="text"),
        _task(4, start="bad", end="dates", id="unreadable"),
    ]

    assert await DurationCountedOnProjectWeek().validate(_ctx(rows, region=_GULF)) == []


@pytest.mark.asyncio
async def test_dates_both_weeks_count_alike_pass() -> None:
    """Monday to Thursday is four days in Doha and in Berlin; the row is fine either way."""
    results = await DurationCountedOnProjectWeek().validate(_ctx([_task(4, start=_MONDAY)], region=_GULF))

    assert len(results) == 1
    assert results[0].passed


@pytest.mark.asyncio
async def test_the_region_is_read_from_the_metadata_or_the_payload_too() -> None:
    rule = DurationCountedOnProjectWeek()

    via_metadata = await rule.validate(_ctx([_task(4)], metadata={"region": "QA"}))
    via_payload = await rule.validate(
        ValidationContext(data={"activities": [_task(4)], "project_region": "Saudi Arabia"}, metadata={"locale": "en"})
    )

    assert [r.passed for r in via_metadata] == [False]
    assert [r.passed for r in via_payload] == [False]


@pytest.mark.asyncio
async def test_the_finding_reads_in_german() -> None:
    results = await DurationCountedOnProjectWeek().validate(_ctx([_task(4)], region=_GULF, locale="de"))

    assert "Arbeitswoche" in results[0].message
    assert "Monday" not in results[0].message


def test_the_rule_is_registered_in_the_programme_quality_pack() -> None:
    """A rule registered under a set nobody requests never runs."""
    registered = {rule.rule_id for rule in rule_registry.get_rules_for_sets([SCHEDULE_RULE_SET])}

    assert {rule.rule_id for rule in _SCHEDULE_RULES} <= registered
    assert "schedule_quality.missing_duration" in registered, "the pack this rule joins is the core one"


def test_every_message_and_suggestion_resolves_in_every_bundled_locale() -> None:
    """A message that falls back to its raw key is a hardcoded string by another route."""
    missing = [
        f"{locale}:{rule.rule_id}.{leaf}"
        for locale in available_locales()
        for rule in _SCHEDULE_RULES
        for leaf in ("fail", "suggestion")
        if not is_key_present(f"{rule.rule_id}.{leaf}", locale)
    ]

    assert missing == []
