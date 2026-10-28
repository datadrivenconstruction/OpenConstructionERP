# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The statutory working-time record: deadlines, retention, and derived durations.

Every test here runs on the pure engine plus the service's own line builder, so
none of it needs a database and none of it can be skipped for the want of one.

The point most of these defend is the one that makes the record worth keeping:
a line that carries clock times has exactly one duration, and it is the one
those times produce. The other half is that none of this reaches anybody who did
not ask for it - a record with no regime is the record this module has always
written.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.modules.field_time import field_time_math as ft
from app.modules.field_time import working_time as wt
from app.modules.field_time.models import FieldTimesheet, FieldTimesheetLine
from app.modules.field_time.schemas import FieldTimesheetLineCreate
from app.modules.field_time.service import FieldTimeService

WORK_DAY = date(2026, 3, 10)
MILOG = wt.regime_for("milog")
TIMESHEET_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
WORKER = uuid.UUID("22222222-2222-2222-2222-222222222222")
OTHER_WORKER = uuid.UUID("33333333-3333-3333-3333-333333333333")


def _at(day: date, hour: int, minute: int = 0) -> datetime:
    """A UTC instant on ``day``."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)


# ── The seven days the record has to exist within ────────────────────────────


def test_a_day_written_up_on_the_eighth_day_is_late() -> None:
    stamp = wt.timeliness(WORK_DAY, _at(date(2026, 3, 18), 9), MILOG)

    assert stamp is not None
    assert stamp.days_taken == 8
    assert stamp.late is True
    assert stamp.deadline == date(2026, 3, 17)


def test_a_day_written_up_on_the_sixth_day_is_not_late() -> None:
    stamp = wt.timeliness(WORK_DAY, _at(date(2026, 3, 16), 9), MILOG)

    assert stamp is not None
    assert stamp.days_taken == 6
    assert stamp.late is False


def test_the_deadline_day_itself_is_still_in_time() -> None:
    """Seven days after the work is the last day, not the first late one."""
    stamp = wt.timeliness(WORK_DAY, _at(date(2026, 3, 17), 23, 59), MILOG)

    assert stamp is not None
    assert stamp.days_taken == 7
    assert stamp.late is False


def test_a_day_recorded_before_it_was_worked_is_not_late() -> None:
    stamp = wt.timeliness(WORK_DAY, _at(date(2026, 3, 9), 8), MILOG)

    assert stamp is not None
    assert stamp.days_taken == -1
    assert stamp.late is False


def test_nothing_is_judged_when_the_record_has_no_creation_time() -> None:
    assert wt.timeliness(WORK_DAY, None, MILOG) is None


# ── Two years of retention, reported and never enforced ──────────────────────


def test_retention_runs_two_years_from_the_day_the_record_was_due() -> None:
    assert wt.retain_until(WORK_DAY, MILOG) == date(2028, 3, 17)


def test_a_leap_day_deadline_clamps_rather_than_failing() -> None:
    """A deadline of 29 February plus two years has to land on a date that exists."""
    assert wt.record_deadline(date(2028, 2, 22), MILOG) == date(2028, 2, 29)
    assert wt.retain_until(date(2028, 2, 22), MILOG) == date(2030, 2, 28)


def test_the_window_is_open_on_its_last_day_and_shut_the_day_after() -> None:
    assert wt.within_retention(WORK_DAY, MILOG, date(2028, 3, 17)) is True
    assert wt.within_retention(WORK_DAY, MILOG, date(2028, 3, 18)) is False


# ── A duration that cannot disagree with the times that produced it ──────────


def test_the_hours_come_from_the_clock_times_and_not_from_the_number_sent() -> None:
    """A figure typed beside a pair of times is overruled by the times."""
    line = FieldTimeService._line_from_create(
        TIMESHEET_ID,
        FieldTimesheetLineCreate(
            resource_id=WORKER,
            hours=Decimal("99"),
            started_at=_at(WORK_DAY, 7),
            ended_at=_at(WORK_DAY, 16),
            break_minutes=30,
        ),
    )

    assert line.hours == Decimal("8.50")
    assert line.started_at == _at(WORK_DAY, 7)
    assert line.break_minutes == 30


def test_a_night_shift_crossing_midnight_keeps_its_real_length() -> None:
    line = FieldTimeService._line_from_create(
        TIMESHEET_ID,
        FieldTimesheetLineCreate(
            resource_id=WORKER,
            started_at=_at(WORK_DAY, 22),
            ended_at=_at(date(2026, 3, 11), 6),
            break_minutes=0,
        ),
    )

    assert line.hours == Decimal("8.00")


def test_a_derived_duration_is_not_rounded_to_a_payroll_step() -> None:
    """07:00 to 15:47 is 8.78 hours, whatever the project rounds its payroll to."""
    derived = ft.derive_line_hours(_at(WORK_DAY, 7), _at(WORK_DAY, 15, 47), 0, booked_hours=0)

    assert derived.derived is True
    assert derived.hours == Decimal("8.78")


def test_one_clock_time_without_the_other_is_refused() -> None:
    with pytest.raises(HTTPException) as caught:
        FieldTimeService._line_from_create(
            TIMESHEET_ID,
            FieldTimesheetLineCreate(resource_id=WORKER, hours=Decimal("8"), started_at=_at(WORK_DAY, 7)),
        )

    assert caught.value.status_code == 422


def test_a_break_longer_than_the_shift_is_refused_rather_than_stored_as_zero() -> None:
    with pytest.raises(HTTPException) as caught:
        FieldTimeService._line_from_create(
            TIMESHEET_ID,
            FieldTimesheetLineCreate(
                resource_id=WORKER,
                hours=Decimal("8"),
                started_at=_at(WORK_DAY, 7),
                ended_at=_at(WORK_DAY, 8),
                break_minutes=90,
            ),
        )

    assert caught.value.status_code == 422


# ── Forced on nobody ─────────────────────────────────────────────────────────


def test_a_line_with_no_clock_times_is_exactly_the_line_it_was_before() -> None:
    """The opt-in half of the feature, stated as an assertion.

    A booking made by somebody who has never heard of any of this keeps the
    hours they typed, and every column the working-time record added stays
    empty. Only the five new columns and ``hours`` are asserted on: the ORM
    applies its other Python-side defaults at INSERT, not here.
    """
    line = FieldTimeService._line_from_create(
        TIMESHEET_ID,
        FieldTimesheetLineCreate(resource_id=WORKER, hours=Decimal("7.25"), cost_code="03.30"),
    )

    assert line.hours == Decimal("7.25")
    assert line.started_at is None
    assert line.ended_at is None
    assert line.break_minutes is None
    assert line.employer_kind is None
    assert line.employer_subcontractor_id is None


def test_an_unknown_or_absent_regime_is_simply_no_regime() -> None:
    assert wt.regime_for(None) is None
    assert wt.regime_for("") is None
    assert wt.regime_for("not-a-regime") is None
    assert wt.regime_for("MiLoG") is not None


# ── The double booking the clock times make visible ──────────────────────────


def _timed(resource, start_hour: int, end_hour: int) -> dict:
    """A line dict shaped like the one the service hands the pure engine."""
    return {
        "resource_id": str(resource),
        "equipment_id": None,
        "hours": Decimal(end_hour - start_hour),
        "cost_code": "03.30",
        "start": _at(WORK_DAY, start_hour),
        "end": _at(WORK_DAY, end_hour),
    }


def test_two_bookings_that_put_one_worker_in_two_places_at_once_are_blocking() -> None:
    checks = ft.check_timesheet([_timed(WORKER, 7, 16), _timed(WORKER, 7, 16)])

    assert checks.overlapping_worker_line_pairs == [(0, 1)]
    assert checks.has_blocking_errors is True


def test_a_day_split_into_touching_segments_is_accepted() -> None:
    checks = ft.check_timesheet([_timed(WORKER, 7, 11), _timed(WORKER, 11, 16)])

    assert checks.overlapping_worker_line_pairs == []


def test_two_workers_on_the_same_hours_are_not_a_double_booking() -> None:
    checks = ft.check_timesheet([_timed(WORKER, 7, 16), _timed(OTHER_WORKER, 7, 16)])

    assert checks.overlapping_worker_line_pairs == []


def test_the_service_hands_the_clock_times_to_the_engine_that_checks_them() -> None:
    """The wiring, not the rule.

    The double-booking check has been in ``check_timesheet`` all along and could
    never fire, because the dicts the service built for it carried no times.
    This is the test that would have caught that: it goes through the service's
    own renderer rather than a hand-written dict.
    """
    timesheet = FieldTimesheet(project_id=TIMESHEET_ID, date=WORK_DAY, reference="FT-000001")
    timesheet.lines = [
        FieldTimesheetLine(
            resource_id=WORKER,
            hours=Decimal("9"),
            cost_code="03.30",
            started_at=_at(WORK_DAY, 7),
            ended_at=_at(WORK_DAY, 16),
        ),
        FieldTimesheetLine(
            resource_id=WORKER,
            hours=Decimal("9"),
            cost_code="03.40",
            started_at=_at(WORK_DAY, 7),
            ended_at=_at(WORK_DAY, 16),
        ),
    ]

    rendered = FieldTimeService._line_dicts(timesheet)

    assert rendered[0]["start"] == _at(WORK_DAY, 7)
    assert ft.check_timesheet(rendered).overlapping_worker_line_pairs == [(0, 1)]


def test_lines_without_clock_times_are_left_alone_by_the_overlap_check() -> None:
    """The check was already there and inert. Untimed lines keep it that way."""
    untimed = {"resource_id": str(WORKER), "equipment_id": None, "hours": Decimal("8"), "cost_code": "03.30"}

    checks = ft.check_timesheet([untimed, dict(untimed)])

    assert checks.overlapping_worker_line_pairs == []


# ── The worker-day an auditor asks for ───────────────────────────────────────


def _entry(**over) -> dict:
    base = {
        "work_date": WORK_DAY,
        "resource_id": str(WORKER),
        "employer_kind": wt.EMPLOYER_OWN,
        "employer_subcontractor_id": None,
        "started_at": _at(WORK_DAY, 7),
        "ended_at": _at(WORK_DAY, 11),
        "break_minutes": 0,
        "hours": Decimal("4"),
        "reference": "FT-000001",
        "status": "approved",
        "recorded_at": _at(WORK_DAY, 18),
    }
    base.update(over)
    return base


def test_a_day_booked_across_two_cost_codes_reads_as_one_working_day() -> None:
    days = wt.worker_day_records(
        [
            _entry(),
            _entry(started_at=_at(WORK_DAY, 11, 30), ended_at=_at(WORK_DAY, 16), hours=Decimal("4.5")),
        ],
    )

    assert len(days) == 1
    day = days[0]
    assert day.started_at == _at(WORK_DAY, 7)
    assert day.ended_at == _at(WORK_DAY, 16)
    assert day.duration_hours == Decimal("8.5")
    assert day.segments == 2
    assert day.segments_without_times == 0


def test_a_booking_with_no_clock_times_is_counted_as_the_gap_it_is() -> None:
    days = wt.worker_day_records([_entry(), _entry(started_at=None, ended_at=None, hours=Decimal("2"))])

    assert days[0].segments_without_times == 1
    assert days[0].duration_hours == Decimal("6")
    assert days[0].started_at == _at(WORK_DAY, 7)


def test_two_employers_for_one_worker_stay_two_rows_instead_of_one_being_picked() -> None:
    days = wt.worker_day_records(
        [
            _entry(),
            _entry(employer_kind=wt.EMPLOYER_SUBCONTRACTOR, employer_subcontractor_id="abc"),
        ],
    )

    assert len(days) == 2
    assert {d.employer_kind for d in days} == {wt.EMPLOYER_OWN, wt.EMPLOYER_SUBCONTRACTOR}


def test_the_day_counts_as_recorded_when_its_last_piece_arrived() -> None:
    late_stamp = _at(date(2026, 3, 20), 9)
    days = wt.worker_day_records([_entry(), _entry(reference="FT-000002", recorded_at=late_stamp)])

    assert days[0].recorded_at == late_stamp
    assert days[0].references == ("FT-000001", "FT-000002")
    stamp = wt.timeliness(days[0].work_date, days[0].recorded_at, MILOG)
    assert stamp is not None and stamp.late is True


def test_machines_are_not_workers_and_have_no_working_time() -> None:
    days = wt.worker_day_records([_entry(resource_id=None)])

    assert days == []


def test_timesheets_in_different_states_read_as_mixed_rather_than_as_one_of_them() -> None:
    days = wt.worker_day_records([_entry(), _entry(reference="FT-000002", status="draft")])

    assert days[0].status == "mixed"
