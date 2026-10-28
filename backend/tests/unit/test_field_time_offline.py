# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for reading a day's offline journey out of timesheet metadata.

The two findings a day captured with no signal can produce - a device clock that
ran ahead, and an entry that reached the office long after the day it books -
are computed here, with plain dicts and no database, so the rules that surface
them stay thin.

Both are advisory by design. Neither function decides anything; each returns a
number or None, and "None" means there is nothing to judge rather than "fine".
That distinction is what keeps an ordinary desk-entered timesheet, which carries
no offline record at all, from producing a finding it cannot possibly deserve.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from app.modules.field_time import field_time_math as ft

CAPTURED = datetime(2026, 6, 11, 17, 30, tzinfo=UTC)


def _meta(**offline: object) -> dict[str, object]:
    """A timesheet metadata mapping carrying an offline capture record."""
    return {ft.OFFLINE_METADATA_KEY: {"entry_key": "e" * 12, **offline}}


# ── reading the record ───────────────────────────────────────────────────────


def test_a_timesheet_with_no_offline_block_is_not_an_offline_entry() -> None:
    for metadata in (None, {}, {"max_hours_per_day": "10"}, {"offline": "yes"}):
        capture = ft.read_offline_capture(metadata)
        assert capture.recorded is False
        assert capture.captured_at is None


def test_the_record_is_read_back_field_by_field() -> None:
    capture = ft.read_offline_capture(
        _meta(
            captured_at="2026-06-11T17:30:00Z",
            synced_at="2026-06-12T06:05:00+00:00",
            device="site-phone-3",
        )
    )
    assert capture.recorded is True
    assert capture.entry_key == "e" * 12
    assert capture.captured_at == CAPTURED
    assert capture.device == "site-phone-3"


def test_a_malformed_time_degrades_to_absent_rather_than_raising() -> None:
    """A phone writing rubbish still gets its hours in; it just yields no finding."""
    capture = ft.read_offline_capture(_meta(captured_at="yesterday evening", synced_at=17))
    assert capture.recorded is True
    assert capture.captured_at is None
    assert capture.synced_at is None
    assert ft.offline_clock_ahead_minutes(capture) is None
    assert ft.offline_sync_delay_days(capture, date(2026, 6, 11)) is None


def test_a_naive_stamp_is_read_as_utc_so_two_values_still_compare() -> None:
    capture = ft.read_offline_capture(_meta(captured_at="2026-06-11T17:30:00"))
    assert capture.captured_at == CAPTURED


def test_a_stamp_in_another_zone_keeps_its_own_offset() -> None:
    capture = ft.read_offline_capture(_meta(captured_at="2026-06-11T19:30:00+02:00"))
    assert capture.captured_at == CAPTURED


# ── device clock ─────────────────────────────────────────────────────────────


def test_a_clock_behind_the_server_is_not_a_finding() -> None:
    """Writing the day down before sending it is the normal case, not an error."""
    capture = ft.read_offline_capture(
        _meta(captured_at=CAPTURED.isoformat(), synced_at=(CAPTURED + timedelta(hours=13)).isoformat())
    )
    assert ft.offline_clock_ahead_minutes(capture) is None


def test_a_clock_ahead_of_the_server_is_reported_in_whole_minutes() -> None:
    capture = ft.read_offline_capture(
        _meta(captured_at=(CAPTURED + timedelta(minutes=95)).isoformat(), synced_at=CAPTURED.isoformat())
    )
    assert ft.offline_clock_ahead_minutes(capture) == 95


def test_the_comparison_point_can_be_supplied() -> None:
    """A caller with a better clock than the record's own arrival time may say so."""
    capture = ft.read_offline_capture(_meta(captured_at=(CAPTURED + timedelta(hours=25)).isoformat()))
    assert ft.offline_clock_ahead_minutes(capture) is None  # nothing to compare with
    assert ft.offline_clock_ahead_minutes(capture, now=CAPTURED) == 25 * 60


def test_an_hour_of_drift_stays_inside_the_tolerance() -> None:
    """One hour is timezone handling, not a wrong year. The rule ignores it."""
    capture = ft.read_offline_capture(
        _meta(captured_at=(CAPTURED + timedelta(minutes=59)).isoformat(), synced_at=CAPTURED.isoformat())
    )
    ahead = ft.offline_clock_ahead_minutes(capture)
    assert ahead is not None
    assert ahead <= ft.OFFLINE_CLOCK_TOLERANCE_MINUTES


# ── sync delay ───────────────────────────────────────────────────────────────


def test_a_day_synced_the_same_evening_has_no_delay() -> None:
    capture = ft.read_offline_capture(_meta(synced_at="2026-06-11T22:00:00Z"))
    assert ft.offline_sync_delay_days(capture, date(2026, 6, 11)) == 0


def test_a_phone_off_the_network_for_a_fortnight_is_measured_in_days() -> None:
    capture = ft.read_offline_capture(_meta(synced_at="2026-06-25T08:00:00Z"))
    assert ft.offline_sync_delay_days(capture, date(2026, 6, 11)) == 14
    assert ft.offline_sync_delay_days(capture, "2026-06-11") == 14


def test_an_entry_reaching_the_office_before_the_day_it_books_reads_as_zero() -> None:
    """A day booked ahead is a different rule's business, not a negative delay."""
    capture = ft.read_offline_capture(_meta(synced_at="2026-06-01T08:00:00Z"))
    assert ft.offline_sync_delay_days(capture, date(2026, 6, 11)) == 0


def test_an_unreadable_work_date_yields_nothing_to_judge() -> None:
    capture = ft.read_offline_capture(_meta(synced_at="2026-06-25T08:00:00Z"))
    assert ft.offline_sync_delay_days(capture, "11/06/2026") is None
    assert ft.offline_sync_delay_days(capture, None) is None


def test_a_datetime_work_date_is_reduced_to_its_day() -> None:
    capture = ft.read_offline_capture(_meta(synced_at="2026-06-25T08:00:00Z"))
    worked = datetime(2026, 6, 11, 7, 0, tzinfo=timezone(timedelta(hours=-5)))
    assert ft.offline_sync_delay_days(capture, worked) == 14


if __name__ == "__main__":  # pragma: no cover - manual smoke run
    raise SystemExit(pytest.main([__file__, "-q"]))
