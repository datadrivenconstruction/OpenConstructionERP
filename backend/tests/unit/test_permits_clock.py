# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Statutory clocks of the permits module (SPEC rules 4, 5, 7), table driven over the shipped catalogues."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.modules.permits.catalogue import shipped_catalogues
from app.modules.permits.clock import (
    ClockError,
    ClockEvent,
    ClockSpec,
    add_period,
    check_extension,
    check_stop,
    deemed_proposal,
    duration_days,
    forecast,
)


def _mon_fri(d: date) -> bool:
    return d.weekday() < 5


def _shipped_clock(catalogue: str, code: str, variant: str | None = None) -> ClockSpec:
    cats = shipped_catalogues()
    return ClockSpec.from_catalogue(cats[catalogue].type_map()[code].clock, variant)


@pytest.mark.parametrize(
    ("start", "period", "unit", "expected"),
    [
        (date(2026, 3, 15), 7, "months", date(2026, 10, 15)),
        (date(2026, 1, 31), 1, "months", date(2026, 2, 28)),  # end-of-month clamp
        (date(2028, 1, 31), 1, "months", date(2028, 2, 29)),  # leap year
        (date(2026, 11, 30), 3, "months", date(2027, 2, 28)),
        (date(2026, 1, 5), 8, "weeks", date(2026, 3, 2)),
        (date(2026, 1, 5), 10, "calendar_days", date(2026, 1, 15)),
        (date(2024, 2, 29), 1, "years", date(2025, 2, 28)),
    ],
)
def test_add_period_units(start: date, period: int, unit: str, expected: date) -> None:
    assert add_period(start, period, unit) == expected


def test_working_days_use_the_callers_calendar_never_an_assumed_week() -> None:
    friday = date(2026, 10, 9)
    assert add_period(friday, 1, "working_days", _mon_fri) == date(2026, 10, 12)
    # A Sunday-Thursday week gives a different answer for the same input.
    assert add_period(friday, 1, "working_days", lambda d: d.weekday() in (6, 0, 1, 2, 3)) == date(2026, 10, 11)
    with pytest.raises(ClockError) as err:
        add_period(friday, 1, "working_days")
    assert err.value.code == "working_day_calendar_missing"


# Table: (catalogue, type, variant, received, validated, expected base due)
SHIPPED_CLOCKS = [
    # BImSchG §10 Abs. 6a: 7 months from complete documents, not from receipt.
    ("de", "bimschg_genehmigung", None, date(2026, 1, 10), date(2026, 2, 20), date(2026, 9, 20)),
    # §19 simplified procedure: 3 months.
    ("de", "bimschg_genehmigung", "simplified", date(2026, 1, 10), date(2026, 2, 20), date(2026, 5, 20)),
    # DMPO art. 34: 8 weeks beginning with the day after receipt.
    ("uk_england", "full_planning_permission", None, date(2026, 1, 5), None, date(2026, 3, 2)),
    # Major development: 13 weeks.
    ("uk_england", "full_planning_permission", "major", date(2026, 1, 5), None, date(2026, 4, 6)),
    # DMPO art. 27: discharge of conditions, 8 weeks from the day after receipt.
    ("uk_england", "discharge_of_conditions", None, date(2026, 6, 1), None, date(2026, 7, 27)),
]


@pytest.mark.parametrize(("cat", "code", "variant", "received", "validated", "due"), SHIPPED_CLOCKS)
def test_shipped_clocks(cat: str, code: str, variant: str | None, received: date, validated, due: date) -> None:
    spec = _shipped_clock(cat, code, variant)
    result = forecast(spec, received_at=received, validated_at=validated)
    assert result.base_due == due
    assert result.forecast == due


def test_bimschg_does_not_start_on_receipt_alone() -> None:
    spec = _shipped_clock("de", "bimschg_genehmigung")
    result = forecast(spec, received_at=date(2026, 1, 10), validated_at=None)
    assert result.forecast is None
    assert result.reason == "clock_not_started"


def test_bimschg_authority_extension_once_up_to_three_months_with_reason() -> None:
    spec = _shipped_clock("de", "bimschg_genehmigung")
    ext = ClockEvent("extension_by_authority", date(2026, 8, 1), 3, "months", "complex expert report")
    check_extension(spec, [], ext)
    result = forecast(spec, received_at=date(2026, 1, 10), validated_at=date(2026, 2, 20), events=[ext])
    assert result.forecast == date(2026, 12, 20)
    for bad, code in [
        (ClockEvent("extension_by_authority", date(2026, 8, 1), 4, "months", "x"), "extension_exceeds_max"),
        (ClockEvent("extension_by_authority", date(2026, 8, 1), 3, "months", " "), "extension_reason_required"),
        (ClockEvent("extension_by_authority", date(2026, 8, 1), 10, "weeks", "x"), "extension_unit_mismatch"),
        (ClockEvent("extension_agreed", date(2026, 8, 1), 1, "months", "x"), "extension_not_allowed"),
    ]:
        with pytest.raises(ClockError) as err:
            check_extension(spec, [], bad)
        assert err.value.code == code
    with pytest.raises(ClockError) as err:
        check_extension(spec, [ext], ClockEvent("extension_by_authority", date(2026, 9, 1), 1, "months", "again"))
    assert err.value.code == "extension_already_used"


def test_uk_extension_by_written_agreement_may_repeat() -> None:
    spec = _shipped_clock("uk_england", "full_planning_permission")
    e1 = ClockEvent("extension_agreed", date(2026, 2, 20), 2, "weeks")
    check_extension(spec, [], e1)
    e2 = ClockEvent("extension_agreed", date(2026, 3, 10), 3, "weeks")
    check_extension(spec, [e1], e2)
    result = forecast(spec, received_at=date(2026, 1, 5), events=[e1, e2])
    assert result.forecast == date(2026, 3, 2) + timedelta(weeks=5)
    with pytest.raises(ClockError):
        check_extension(spec, [], ClockEvent("extension_by_authority", date(2026, 2, 1), 1, "weeks", "x"))


def test_rfi_stops_only_when_the_type_says_so() -> None:
    events = [ClockEvent("stop", date(2026, 2, 1)), ClockEvent("resume", date(2026, 2, 11))]
    stopping = ClockSpec(period=8, unit="weeks", start_event="receipt", stop_on_rfi=True)
    running = ClockSpec(period=8, unit="weeks", start_event="receipt", stop_on_rfi=False)
    assert forecast(stopping, received_at=date(2026, 1, 5), events=events).forecast == date(2026, 3, 12)
    assert forecast(running, received_at=date(2026, 1, 5), events=events).forecast == date(2026, 3, 2)
    open_stop = forecast(
        stopping, received_at=date(2026, 1, 5), events=[ClockEvent("stop", date(2026, 2, 1))], today=date(2026, 2, 6)
    )
    assert open_stop.stopped_now and open_stop.stopped_days == 5


def test_stop_resume_pairing() -> None:
    spec = ClockSpec(period=8, unit="weeks", stop_on_rfi=True)
    stop = ClockEvent("stop", date(2026, 2, 1))
    check_stop(spec, [], stop)
    with pytest.raises(ClockError):
        check_stop(spec, [stop], ClockEvent("stop", date(2026, 2, 2)))
    with pytest.raises(ClockError):
        check_stop(spec, [], ClockEvent("resume", date(2026, 2, 2)))


def test_unknown_clock_is_null_never_a_silent_default() -> None:
    spec = _shipped_clock("us_ibc", "building_permit")
    result = forecast(spec, received_at=date(2026, 1, 5))
    assert result.forecast is None and result.reason == "no_statutory_period"
    estimated = forecast(spec, received_at=date(2026, 1, 5), expected_date=date(2026, 4, 1))
    assert estimated.forecast == date(2026, 4, 1) and estimated.estimate
    assert duration_days(spec, date(2026, 1, 5)) is None


def test_deemed_outcome_is_proposed_only_after_the_clock_runs_out() -> None:
    spec = _shipped_clock("uk_england", "discharge_of_conditions")
    result = forecast(spec, received_at=date(2026, 6, 1))
    assert deemed_proposal(spec, result, today=date(2026, 7, 27), decided=False) is None
    assert deemed_proposal(spec, result, today=date(2026, 7, 28), decided=False) == "deemed_discharged"
    assert deemed_proposal(spec, result, today=date(2026, 7, 28), decided=True) is None
    no_deemed = _shipped_clock("uk_england", "full_planning_permission")
    late = forecast(no_deemed, received_at=date(2026, 1, 5))
    assert deemed_proposal(no_deemed, late, today=date(2027, 1, 1), decided=False) is None


def test_unknown_variant_is_refused() -> None:
    with pytest.raises(ClockError):
        _shipped_clock("de", "bimschg_genehmigung", "nonexistent")
