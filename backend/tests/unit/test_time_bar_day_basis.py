# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The notice engine counts working days when a standard says working days.

Every notice period configured today is a calendar-day period, so a bare
integer has been the right answer by coincidence rather than by design. These
tests pin the two halves of that: that a period declared in working days is
genuinely counted differently, and that every existing period still lands on
the day it always did.

The first half needs its own negative control. A suite in which both bases
always agree cannot tell a working basis from an ignored one, so one test
asserts a difference and a specific size for it, and another asserts that the
same two bases agree on a period that never leaves a working week.

No database and no app stack: the engine is pure, and the day arithmetic it now
delegates to imports nothing but the standard library.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from app.core.day_basis import add_days as core_add_days
from app.modules.change_intelligence.time_bar import (
    BUSINESS,
    CALENDAR,
    GENERIC_PERIOD_BASES,
    GENERIC_PERIODS,
    NOTICE_CLAIM,
    NOTICE_EOT,
    NOTICE_PERIOD_BASES,
    NOTICE_PERIODS,
    NOTICE_QUOTATION,
    NOTICE_RESPONSE,
    STANDARD_FIDIC,
    STANDARD_UNKNOWN,
    ClockInput,
    add_days,
    basis_for,
    build_clock,
    derive_deadline,
    period_bases_are_complete,
    period_for,
)
from app.modules.change_intelligence.time_bar_service import (
    _co_inputs,
    _eot_inputs,
    _notice_inputs,
    _vr_inputs,
)
from app.modules.changeorders.models import ChangeOrder
from app.modules.variations.models import ExtensionOfTimeClaim, Notice, VariationRequest

#: A Monday, at a time of day that is not midnight so the adapter has something
#: to lose if it rebuilds the moment carelessly.
MONDAY = datetime(2026, 7, 6, 16, 0, 0, tzinfo=UTC)
NOW = datetime(2026, 7, 8, 9, 0, 0, tzinfo=UTC)


def _input(**overrides: object) -> ClockInput:
    """A complete ClockInput, overridable field by field."""
    fields: dict[str, object] = {
        "source_kind": "variation_request",
        "source_id": "1",
        "source_ref": "VR-1",
        "title": "Concealed condition",
        "standard": STANDARD_FIDIC,
        "notice_type": NOTICE_CLAIM,
        "clause_ref": "FIDIC 20.1",
        "trigger_date": MONDAY,
        "explicit_due": None,
        "period_days": 10,
        "satisfied_at": None,
        "requires_notice": True,
        "proof_on_file": True,
        "is_open": True,
    }
    fields.update(overrides)
    return ClockInput(**fields)  # type: ignore[arg-type]


# --- The defect: a working-day period is not a calendar-day period ----------


def test_a_working_day_period_lands_later_than_the_same_count_of_calendar_days() -> None:
    """Ten days from a Monday: Thursday week on calendar, the Monday after on working.

    This is the number that made the defect worth fixing. A standard that
    states ten working days, written into the table as a bare 10, would have
    produced the calendar answer - four days early, on a notice whose lateness
    can invalidate the claim, with a plausible date on screen and nothing to
    contradict it.
    """
    calendar_deadline = add_days(MONDAY, 10, CALENDAR)
    business_deadline = add_days(MONDAY, 10, BUSINESS)

    assert calendar_deadline == datetime(2026, 7, 16, 16, 0, 0, tzinfo=UTC), "Thursday of the following week"
    assert business_deadline == datetime(2026, 7, 20, 16, 0, 0, tzinfo=UTC), "the Monday after that"

    # Two weekends fall inside ten working days, and each costs two days.
    assert (business_deadline - calendar_deadline) == timedelta(days=4)
    assert calendar_deadline.weekday() == 3
    assert business_deadline.weekday() == 0


def test_the_two_bases_agree_on_a_period_that_stays_inside_one_working_week() -> None:
    """The control for the control: a working basis is not just "add more days".

    Three days from a Monday is Thursday whichever way it is counted. Without
    this, the test above is equally consistent with a basis that pads every
    period, which would be a different wrong answer rather than a right one.
    """
    assert add_days(MONDAY, 3, CALENDAR) == add_days(MONDAY, 3, BUSINESS)
    assert add_days(MONDAY, 3, BUSINESS) == datetime(2026, 7, 9, 16, 0, 0, tzinfo=UTC)


def test_a_supplied_holiday_moves_a_working_day_deadline_and_none_is_supplied_by_default() -> None:
    """Holidays come from the caller. The engine ships none and invents none.

    The same period is counted twice, once with the deployment's calendar and
    once without, and only the supplied calendar moves the answer. That is the
    decision the payment clock argues for and it is preserved here rather than
    improved on: a wrong shipped holiday list produces a date nobody can
    reproduce.
    """
    without_holidays = add_days(MONDAY, 3, BUSINESS)
    with_wednesday_off = add_days(MONDAY, 3, BUSINESS, (date(2026, 7, 8),))

    assert without_holidays == datetime(2026, 7, 9, 16, 0, 0, tzinfo=UTC)
    assert with_wednesday_off == datetime(2026, 7, 10, 16, 0, 0, tzinfo=UTC)
    assert with_wednesday_off - without_holidays == timedelta(days=1)


def test_the_time_of_day_survives_a_working_day_count() -> None:
    """A notice raised at 16:00 expires at 16:00, on either basis.

    The shared helper counts in whole dates while a clock is an aware UTC
    moment, so the adapter has to carry the time across. Dropping it to
    midnight would move every existing deadline by part of a day and quietly
    change how ``classify_status`` reads.
    """
    for basis in (CALENDAR, BUSINESS):
        shifted = add_days(MONDAY, 7, basis)
        assert shifted.timetz() == MONDAY.timetz(), basis
        assert shifted.tzinfo is UTC, basis


# --- Nothing that exists today moved ---------------------------------------


def test_no_configured_calendar_period_moved() -> None:
    """Every calendar-day period in the table still lands where it always did.

    "Where it always did" is computed here with the plain ``timedelta``
    arithmetic the engine used before this change, so the comparison is against
    the old behaviour rather than against the new code agreeing with itself.
    The sweep covers every entry in both tables; the floor below is there
    because a sweep that silently matched nothing would otherwise pass.
    """
    expected_entries = [
        (standard, notice_type, days)
        for standard, periods in NOTICE_PERIODS.items()
        for notice_type, days in periods.items()
        if basis_for(standard, notice_type) == CALENDAR
    ]
    expected_entries += [
        (STANDARD_UNKNOWN, notice_type, days)
        for notice_type, days in GENERIC_PERIODS.items()
        if basis_for(STANDARD_UNKNOWN, notice_type) == CALENDAR
    ]

    checked = 0
    for standard, notice_type, days in expected_entries:
        old_behaviour = MONDAY + timedelta(days=days)
        new_behaviour = derive_deadline(
            trigger_date=MONDAY,
            period_days=days,
            explicit_due=None,
            day_basis=basis_for(standard, notice_type),
        )
        assert new_behaviour == old_behaviour, f"{standard}.{notice_type} moved"
        checked += 1

    assert checked == len(expected_entries)
    assert checked >= 25, f"the sweep only covered {checked} periods; it is not reaching the table"


def test_a_named_existing_standard_lands_on_the_date_it_always_did() -> None:
    """One deadline written out in full, independent of any helper.

    The sweep above derives its expectation. This one does not: a FIDIC claim
    notice raised on 6 July 2026 is due on 3 August 2026, and if that literal
    ever needs changing then an existing deadline has moved.
    """
    days = period_for(STANDARD_FIDIC, NOTICE_CLAIM)
    assert days == 28
    assert basis_for(STANDARD_FIDIC, NOTICE_CLAIM) == CALENDAR

    clock = build_clock(_input(period_days=days), now=NOW)
    assert clock.deadline == datetime(2026, 8, 3, 16, 0, 0, tzinfo=UTC)
    assert clock.day_basis == CALENDAR


def test_the_only_working_day_periods_are_ccdc_claim_and_eot() -> None:
    """CCDC is the first standard with working-day periods, and the only one.

    CCDC 2-2020 counts claims (GC 6.6) and EOT (GC 6.5) in working days, while
    its quotation, assessment and response windows are calendar days. Every
    other standard counts in calendar days throughout. This pins exactly which
    entries use a business-day basis so that a new working-day period is a
    deliberate addition, not an oversight.
    """
    non_calendar = {
        f"{standard}.{notice_type}": basis
        for standard, bases in NOTICE_PERIOD_BASES.items()
        for notice_type, basis in bases.items()
        if basis != CALENDAR
    }
    non_calendar.update(
        {f"GENERIC.{notice_type}": basis for notice_type, basis in GENERIC_PERIOD_BASES.items() if basis != CALENDAR}
    )
    assert non_calendar == {
        "CCDC.claim_notice": BUSINESS,
        "CCDC.eot_notice": BUSINESS,
    }


# --- The gate that stops the defect coming back -----------------------------


def test_every_configured_period_states_the_basis_it_is_counted_on() -> None:
    """No period may carry a day count without saying how the days are counted."""
    assert period_bases_are_complete() == []


def test_a_new_standard_with_no_basis_is_reported_rather_than_silently_calendar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The completeness gate is not vacuous: give it a gap and it names the gap.

    Without this, ``period_bases_are_complete`` returning an empty list proves
    only that it returns an empty list. The standard added here is shaped like
    one that counts in working days, which is the case the gate exists for.
    """
    monkeypatch.setitem(NOTICE_PERIODS, "WORKING_DAY_STANDARD", {NOTICE_CLAIM: 10})

    missing = period_bases_are_complete()

    assert "WORKING_DAY_STANDARD.claim_notice" in missing
    # And it still counts in calendar days until someone says otherwise, which
    # is precisely why the gate has to be the thing that catches it.
    assert basis_for("WORKING_DAY_STANDARD", NOTICE_CLAIM) == CALENDAR


def test_an_unknown_standard_falls_back_to_calendar_days() -> None:
    """A standard nobody configured must not silently acquire a working basis."""
    assert basis_for("NOT_A_STANDARD", NOTICE_CLAIM) == CALENDAR
    assert basis_for(STANDARD_UNKNOWN, "not_a_notice_type") == CALENDAR


# --- One engine, not two ----------------------------------------------------


def test_the_notice_clock_counts_with_the_same_function_as_the_payment_clock() -> None:
    """The two engines share the arithmetic rather than each having their own.

    Two implementations was the defect. This asserts the day part of a notice
    deadline equals what the shared helper returns for the same period on the
    same basis, so the notice clock cannot drift away from the statutory
    payment clock that already counted working days correctly.
    """
    for basis in (CALENDAR, BUSINESS):
        for days in (5, 10, 28, 56):
            through_engine = add_days(MONDAY, days, basis).date()
            through_helper = core_add_days(MONDAY.date(), days, basis)
            assert through_engine == through_helper, f"{basis}/{days}"


def test_a_working_day_clock_reports_the_basis_it_was_counted_on() -> None:
    """The register says which kind of day it counted, end to end.

    A ten-working-day deadline and a ten-calendar-day deadline are different
    dates from the same integer, so the answer is only readable if the clock
    carries the basis with it.
    """
    calendar_clock = build_clock(_input(period_days=10, day_basis=CALENDAR), now=NOW)
    business_clock = build_clock(_input(period_days=10, day_basis=BUSINESS), now=NOW)

    assert calendar_clock.day_basis == CALENDAR
    assert business_clock.day_basis == BUSINESS
    assert business_clock.deadline is not None
    assert calendar_clock.deadline is not None
    assert business_clock.deadline - calendar_clock.deadline == timedelta(days=4)
    # The countdown follows the deadline it was given, not the integer.
    assert business_clock.days_remaining is not None
    assert calendar_clock.days_remaining is not None
    assert business_clock.days_remaining > calendar_clock.days_remaining


def test_a_clock_built_without_a_basis_is_a_calendar_clock() -> None:
    """The default is the old behaviour, so an untouched caller is untouched."""
    clock = build_clock(_input(period_days=10), now=NOW)
    assert clock.day_basis == CALENDAR
    assert clock.deadline == MONDAY + timedelta(days=10)


# --- The five call sites that carry the basis out of the table --------------


def _every_builder_input(standard: str = STANDARD_FIDIC) -> list[ClockInput]:
    """Every ClockInput the register builds, from all four record kinds.

    The four builders below are the only places a notice period is read out of
    the table, and between them they cover all five call sites. They are pure
    functions of a record, so transient ORM instances are enough and no database
    is involved.
    """
    day = "2026-07-06"
    change_order = ChangeOrder(id=uuid.uuid4(), code="CO-1", title="Change order", status="submitted", submitted_at=day)
    notice = Notice(id=uuid.uuid4(), code="EW-1", title="Early warning", status="open", raised_at=day)
    variation = VariationRequest(
        id=uuid.uuid4(),
        code="VR-1",
        title="Variation request",
        status="submitted",
        requested_at=day,
        submitted_at=day,
    )
    eot = ExtensionOfTimeClaim(id=uuid.uuid4(), status="submitted", raised_at=day)

    return [
        *_co_inputs(change_order, standard),
        *_notice_inputs(notice, standard),
        *_vr_inputs(variation, standard, []),
        *_eot_inputs(eot, standard, []),
    ]


def test_every_builder_pairs_its_period_with_the_basis_for_the_same_notice_type() -> None:
    """A day count and the basis it is counted on always come from one row.

    The failure this rules out is a mispairing: a clock that takes its period
    from one notice type and its basis from another would still be a plausible
    date, would still pass every register test, and would be wrong only for a
    standard that mixes bases - which is exactly the standard this change exists
    to allow.
    """
    inputs = _every_builder_input()

    for inp in inputs:
        assert inp.period_days == period_for(inp.standard, inp.notice_type), inp.notice_type
        assert inp.day_basis == basis_for(inp.standard, inp.notice_type), inp.notice_type

    assert len(inputs) == 5, "the four builders should produce the five configured clocks"
    assert {inp.notice_type for inp in inputs} == {NOTICE_RESPONSE, NOTICE_CLAIM, NOTICE_QUOTATION, NOTICE_EOT}


@pytest.mark.parametrize("declared", [NOTICE_RESPONSE, NOTICE_CLAIM, NOTICE_QUOTATION, NOTICE_EOT])
def test_only_the_notice_type_declared_in_working_days_is_counted_in_working_days(
    monkeypatch: pytest.MonkeyPatch,
    declared: str,
) -> None:
    """The basis is wired end to end, and each clock gets its own row's basis.

    Every standard configured today counts in calendar days, so the whole
    register suite returns identical answers whether the basis is honoured or
    ignored, and a call site that read its basis from a neighbouring notice type
    would look perfectly correct. Declaring exactly one notice type in working
    days separates all three worlds: the clocks for that notice type move and
    say so, and every other clock stays where it was.
    """
    before = {(i.source_kind, i.notice_type): build_clock(i, now=NOW).deadline for i in _every_builder_input()}

    bases = dict.fromkeys(NOTICE_PERIODS[STANDARD_FIDIC], CALENDAR)
    bases[declared] = BUSINESS
    monkeypatch.setitem(NOTICE_PERIOD_BASES, STANDARD_FIDIC, bases)

    moved = 0
    for inp in _every_builder_input():
        clock = build_clock(inp, now=NOW)
        expected = BUSINESS if inp.notice_type == declared else CALENDAR
        assert inp.day_basis == expected, f"{inp.source_kind}/{inp.notice_type}"
        assert clock.day_basis == expected, f"{inp.source_kind}/{inp.notice_type}"

        was = before[(inp.source_kind, inp.notice_type)]
        assert was is not None and clock.deadline is not None
        if expected == BUSINESS:
            # Every configured FIDIC period is long enough to cross a weekend.
            assert clock.deadline > was, f"{inp.source_kind}/{inp.notice_type} did not move"
            moved += 1
        else:
            assert clock.deadline == was, f"{inp.source_kind}/{inp.notice_type} moved and should not have"

    assert moved >= 1, f"no clock counts {declared} on a working-day basis"
