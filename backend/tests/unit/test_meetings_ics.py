# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the meetings iCalendar (RFC 5545) builder.

Scope:
    Pure, database-free helpers in ``app.modules.meetings.ics``: TEXT escaping,
    75-octet line folding, UTC "Zulu" date-time formatting, RRULE mapping, and
    the end-to-end VCALENDAR/VEVENT assembly for a single meeting and a
    recurring series. Everything is fed plain dicts - no database, ORM, or
    network is touched.

Each assertion is pinned against the relevant RFC 5545 rule so the calendar
feed cannot drift silently.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.modules.meetings import ics
from app.modules.meetings.ics import (
    CalendarEvent,
    ICSAttendee,
    build_calendar,
    build_vevent_lines,
    calendar_from_meeting,
    escape_text,
    event_from_meeting,
    fold_line,
    format_utc,
    map_rrule,
)

# A fixed DTSTAMP so the whole feed is deterministic byte-for-byte.
DTSTAMP = datetime(2026, 7, 16, 8, 30, 0, tzinfo=UTC)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _meeting(**overrides: object) -> dict:
    """A minimal meeting mapping with sensible defaults, overridable per test."""
    base: dict = {
        "id": "abc-123",
        "title": "Weekly progress",
        "meeting_number": "MTG-007",
        "meeting_type": "progress",
        "meeting_date": "2026-07-16",
        "location": "Site office",
        "chairperson_id": None,
        "status": "scheduled",
        "attendees": [],
        "agenda_items": [],
        "minutes": None,
        "recurrence_rule": None,
        "metadata": {},
    }
    base.update(overrides)
    return base


def _unfold(ics_text: str) -> list[str]:
    """Reverse RFC 5545 folding: rejoin continuation lines into logical lines.

    A physical line that begins with a single space or tab is a continuation of
    the previous one; the fold marker (CRLF + one WSP) is removed.
    """
    lines: list[str] = []
    for physical in ics_text.split("\r\n"):
        if physical == "":
            continue
        if physical[:1] in (" ", "\t") and lines:
            lines[-1] += physical[1:]
        else:
            lines.append(physical)
    return lines


def _prop(lines: list[str], name: str) -> list[str]:
    """Return every content line whose property name is ``name``."""
    return [ln for ln in lines if ln.split(":", 1)[0].split(";", 1)[0] == name]


# ── escape_text (RFC 5545 section 3.3.11) ─────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("plain", "plain"),
        ("a,b", "a\\,b"),
        ("a;b", "a\\;b"),
        ("a\\b", "a\\\\b"),
        ("line1\nline2", "line1\\nline2"),
        ("line1\r\nline2", "line1\\nline2"),
        ("line1\rline2", "line1\\nline2"),
        ("a,b;c\nd", "a\\,b\\;c\\nd"),
        ("a:b", "a:b"),  # colon is not escaped in a TEXT value
    ],
)
def test_escape_text(raw: str, expected: str) -> None:
    assert escape_text(raw) == expected


def test_escape_text_backslash_is_escaped_before_specials() -> None:
    # The backslash we insert for \; must not itself be doubled again.
    assert escape_text(";") == "\\;"
    assert escape_text("\\;") == "\\\\\\;"


# ── format_utc (RFC 5545 section 3.3.5, UTC form) ─────────────────────────────


def test_format_utc_naive_is_treated_as_utc() -> None:
    assert format_utc(datetime(2026, 7, 16, 9, 5, 3)) == "20260716T090503Z"


def test_format_utc_converts_aware_to_utc() -> None:
    # 11:00 at +02:00 is 09:00 UTC.
    aware = datetime(2026, 7, 16, 11, 0, 0, tzinfo=timezone(timedelta(hours=2)))
    assert format_utc(aware) == "20260716T090000Z"


# ── fold_line (RFC 5545 section 3.1) ──────────────────────────────────────────


def test_fold_line_short_line_unchanged() -> None:
    assert fold_line("SHORT:value") == "SHORT:value"


def test_fold_line_exactly_75_octets_unchanged() -> None:
    line = "X" * 75
    assert fold_line(line) == line


def test_fold_line_folds_over_75_octets() -> None:
    line = "Y" * 200
    folded = fold_line(line)
    assert "\r\n " in folded
    physical = folded.split("\r\n")
    assert len(physical) > 1
    for seg in physical:
        assert len(seg.encode("utf-8")) <= 75
    # Continuation lines start with exactly one space (the fold marker).
    for seg in physical[1:]:
        assert seg.startswith(" ")
    # Unfolding reconstructs the original exactly.
    recon = physical[0] + "".join(seg[1:] for seg in physical[1:])
    assert recon == line


def test_fold_line_never_splits_a_multibyte_char() -> None:
    # "é" is two octets in UTF-8; folding on an octet boundary must not split it.
    line = "é" * 100
    folded = fold_line(line)
    physical = folded.split("\r\n")
    for seg in physical:
        assert len(seg.encode("utf-8")) <= 75
        seg.encode("utf-8").decode("utf-8")  # would raise if a char were split
    recon = physical[0] + "".join(seg[1:] for seg in physical[1:])
    assert recon == line


# ── map_rrule (RFC 5545 section 3.3.10) ───────────────────────────────────────


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ("FREQ=WEEKLY;BYDAY=MO;COUNT=12", "FREQ=WEEKLY;BYDAY=MO;COUNT=12"),
        ("freq=weekly;byday=mo", "FREQ=WEEKLY;BYDAY=MO"),
        ("RRULE:FREQ=DAILY;COUNT=5", "FREQ=DAILY;COUNT=5"),
        ("  FREQ=MONTHLY;INTERVAL=2  ", "FREQ=MONTHLY;INTERVAL=2"),
        ("FREQ=WEEKLY;BYDAY=MO,WE,FR", "FREQ=WEEKLY;BYDAY=MO,WE,FR"),
    ],
)
def test_map_rrule_normalizes(stored: str, expected: str) -> None:
    assert map_rrule(stored) == expected


@pytest.mark.parametrize("stored", [None, "", "   ", "BYDAY=MO", "FREQ=NONSENSE", "no-equals-here"])
def test_map_rrule_rejects_invalid(stored: str | None) -> None:
    assert map_rrule(stored) is None


def test_map_rrule_promotes_date_only_until_to_utc_datetime() -> None:
    # UNTIL must match DTSTART's value type (a UTC date-time here).
    assert map_rrule("FREQ=WEEKLY;UNTIL=2026-12-31") == "FREQ=WEEKLY;UNTIL=20261231T235959Z"
    assert map_rrule("FREQ=WEEKLY;UNTIL=20261231") == "FREQ=WEEKLY;UNTIL=20261231T235959Z"


def test_map_rrule_keeps_datetime_until_and_adds_zulu() -> None:
    assert map_rrule("FREQ=DAILY;UNTIL=20261231T120000") == "FREQ=DAILY;UNTIL=20261231T120000Z"


# ── VCALENDAR / VEVENT structure ──────────────────────────────────────────────


def test_calendar_is_well_formed() -> None:
    text = calendar_from_meeting(_meeting(), dtstamp=DTSTAMP)
    lines = _unfold(text)
    assert lines[0] == "BEGIN:VCALENDAR"
    assert lines[-1] == "END:VCALENDAR"
    assert "VERSION:2.0" in lines
    assert any(ln.startswith("PRODID:") for ln in lines)
    assert lines.count("BEGIN:VEVENT") == 1
    assert lines.count("END:VEVENT") == 1
    # Required VEVENT properties present.
    assert _prop(lines, "UID")
    assert _prop(lines, "DTSTAMP")
    assert _prop(lines, "DTSTART")


def test_prodid_is_the_platform() -> None:
    text = calendar_from_meeting(_meeting(), dtstamp=DTSTAMP)
    assert f"PRODID:{ics.PRODID}" in _unfold(text)


def test_crlf_line_endings_everywhere() -> None:
    text = calendar_from_meeting(
        _meeting(title="Comma, and\nnewline"),
        dtstamp=DTSTAMP,
    )
    # Terminated by CRLF, and no bare CR or LF survives outside the CRLF pairs
    # (an escaped newline in a value is the two characters backslash + n).
    assert text.endswith("\r\n")
    for physical in text.split("\r\n"):
        assert "\r" not in physical
        assert "\n" not in physical


def test_stable_uid_and_determinism() -> None:
    meeting = _meeting(id="abc-123")
    text1 = calendar_from_meeting(meeting, dtstamp=DTSTAMP)
    text2 = calendar_from_meeting(meeting, dtstamp=DTSTAMP)
    assert text1 == text2  # pure + deterministic
    assert "UID:meeting-abc-123@openconstructionerp" in _unfold(text1)


def test_dtstart_dtend_are_utc_zulu_with_default_time_and_duration() -> None:
    text = calendar_from_meeting(_meeting(meeting_date="2026-07-16"), dtstamp=DTSTAMP)
    lines = _unfold(text)
    (dtstart,) = _prop(lines, "DTSTART")
    (dtend,) = _prop(lines, "DTEND")
    assert re.fullmatch(r"DTSTART:\d{8}T\d{6}Z", dtstart)
    assert re.fullmatch(r"DTEND:\d{8}T\d{6}Z", dtend)
    # Default 09:00 UTC start, 60-minute duration.
    assert dtstart == "DTSTART:20260716T090000Z"
    assert dtend == "DTEND:20260716T100000Z"


def test_dtstamp_is_utc_zulu() -> None:
    text = calendar_from_meeting(_meeting(), dtstamp=DTSTAMP)
    (dtstamp,) = _prop(_unfold(text), "DTSTAMP")
    assert dtstamp == "DTSTAMP:20260716T083000Z"


def test_metadata_overrides_start_time_and_duration() -> None:
    text = calendar_from_meeting(
        _meeting(metadata={"start_time": "14:30", "duration_minutes": 90}),
        dtstamp=DTSTAMP,
    )
    lines = _unfold(text)
    assert "DTSTART:20260716T143000Z" in lines
    assert "DTEND:20260716T160000Z" in lines


def test_metadata_end_time_wins_over_default_duration() -> None:
    text = calendar_from_meeting(
        _meeting(metadata={"start_time": "09:00", "end_time": "09:45"}),
        dtstamp=DTSTAMP,
    )
    lines = _unfold(text)
    assert "DTSTART:20260716T090000Z" in lines
    assert "DTEND:20260716T094500Z" in lines


# ── Summary / description / location ──────────────────────────────────────────


def test_summary_is_the_title() -> None:
    lines = _unfold(calendar_from_meeting(_meeting(title="Kickoff"), dtstamp=DTSTAMP))
    assert "SUMMARY:Kickoff" in lines


def test_summary_escapes_specials() -> None:
    lines = _unfold(calendar_from_meeting(_meeting(title="Design, review; phase 2"), dtstamp=DTSTAMP))
    assert "SUMMARY:Design\\, review\\; phase 2" in lines


def test_description_folds_agenda_and_minutes_with_escaped_newlines() -> None:
    meeting = _meeting(
        agenda_items=[{"number": "1", "topic": "Safety"}, {"topic": "Schedule"}],
        minutes="All good",
    )
    lines = _unfold(calendar_from_meeting(meeting, dtstamp=DTSTAMP))
    (desc,) = _prop(lines, "DESCRIPTION")
    # Real newlines in the composed description are escaped to a literal \n.
    assert desc == "DESCRIPTION:Agenda:\\n1. Safety\\n2. Schedule\\n\\nAll good"


def test_location_present_and_omitted() -> None:
    with_loc = _unfold(calendar_from_meeting(_meeting(location="Room 5"), dtstamp=DTSTAMP))
    assert "LOCATION:Room 5" in with_loc
    without_loc = _unfold(calendar_from_meeting(_meeting(location=None), dtstamp=DTSTAMP))
    assert not _prop(without_loc, "LOCATION")


# ── Recurrence ────────────────────────────────────────────────────────────────


def test_recurring_series_emits_rrule() -> None:
    meeting = _meeting(recurrence_rule="FREQ=WEEKLY;BYDAY=MO;COUNT=12")
    lines = _unfold(calendar_from_meeting(meeting, dtstamp=DTSTAMP))
    assert "RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=12" in lines
    # Still a single VEVENT - the RRULE represents the whole series.
    assert lines.count("BEGIN:VEVENT") == 1


def test_one_off_meeting_has_no_rrule() -> None:
    lines = _unfold(calendar_from_meeting(_meeting(recurrence_rule=None), dtstamp=DTSTAMP))
    assert not _prop(lines, "RRULE")


# ── Attendees / organizer ─────────────────────────────────────────────────────


def test_multiple_attendee_lines_one_per_attendee() -> None:
    meeting = _meeting(
        attendees=[
            {"name": "Sam Carter", "email": "sam@example.com"},
            {"name": "Jo Diaz", "email": "jo@example.com"},
            {"name": "Pat Lee"},  # no email -> synthesised placeholder
        ]
    )
    lines = _unfold(calendar_from_meeting(meeting, dtstamp=DTSTAMP))
    attendees = _prop(lines, "ATTENDEE")
    assert len(attendees) == 3
    for ln in attendees:
        assert "PARTSTAT=NEEDS-ACTION" in ln
        assert "mailto:" in ln
    assert any("CN=Sam Carter" in ln and "mailto:sam@example.com" in ln for ln in attendees)
    # Missing email is synthesised on the reserved .invalid TLD.
    assert any("mailto:pat.lee@openconstructionerp.invalid" in ln for ln in attendees)


def test_attendee_cn_with_comma_is_quoted() -> None:
    meeting = _meeting(attendees=[{"name": "Doe, John", "email": "j@example.com"}])
    (attendee,) = _prop(_unfold(calendar_from_meeting(meeting, dtstamp=DTSTAMP)), "ATTENDEE")
    assert 'CN="Doe, John"' in attendee


def test_organizer_from_chairperson_name() -> None:
    meeting = _meeting(metadata={"chairperson_name": "Alex Stone", "organizer_email": "alex@example.com"})
    (organizer,) = _prop(_unfold(calendar_from_meeting(meeting, dtstamp=DTSTAMP)), "ORGANIZER")
    assert "CN=Alex Stone" in organizer
    assert organizer.endswith("mailto:alex@example.com")


def test_no_organizer_when_only_a_uuid_chairperson() -> None:
    meeting = _meeting(chairperson_id="123e4567-e89b-12d3-a456-426614174000", metadata={})
    assert not _prop(_unfold(calendar_from_meeting(meeting, dtstamp=DTSTAMP)), "ORGANIZER")


# ── Status / sequence ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("draft", "STATUS:TENTATIVE"),
        ("scheduled", "STATUS:CONFIRMED"),
        ("in_progress", "STATUS:CONFIRMED"),
        ("completed", "STATUS:CONFIRMED"),
        ("cancelled", "STATUS:CANCELLED"),
    ],
)
def test_status_mapping(status: str, expected: str) -> None:
    lines = _unfold(calendar_from_meeting(_meeting(status=status), dtstamp=DTSTAMP))
    assert expected in lines


def test_sequence_defaults_to_zero_and_honours_metadata() -> None:
    default = _unfold(calendar_from_meeting(_meeting(), dtstamp=DTSTAMP))
    assert "SEQUENCE:0" in default
    bumped = _unfold(calendar_from_meeting(_meeting(metadata={"ics_sequence": 3}), dtstamp=DTSTAMP))
    assert "SEQUENCE:3" in bumped


# ── Long-line folding in context ──────────────────────────────────────────────


def test_long_summary_is_folded_and_round_trips() -> None:
    title = "Coordination " * 12  # ~156 chars, well over 75 octets with SUMMARY:
    text = calendar_from_meeting(_meeting(title=title), dtstamp=DTSTAMP)
    # Every physical line respects the 75-octet limit.
    for physical in text.split("\r\n"):
        assert len(physical.encode("utf-8")) <= 75
    # After unfolding, the SUMMARY value is intact (escaped title).
    (summary,) = _prop(_unfold(text), "SUMMARY")
    assert summary == "SUMMARY:" + escape_text(title.strip())


# ── Direct builder API (dataclasses) ──────────────────────────────────────────


def test_build_vevent_lines_direct() -> None:
    event = CalendarEvent(
        uid="meeting-9@openconstructionerp",
        start=datetime(2026, 1, 2, 8, 0, tzinfo=UTC),
        end=datetime(2026, 1, 2, 9, 0, tzinfo=UTC),
        summary="Toolbox talk",
        organizer=ICSAttendee(name="Lead", email="lead@example.com"),
        attendees=[ICSAttendee(name="Worker", email="w@example.com")],
        rrule="FREQ=DAILY;COUNT=3",
        status="CONFIRMED",
        sequence=2,
        dtstamp=DTSTAMP,
    )
    lines = build_vevent_lines(event)
    assert lines[0] == "BEGIN:VEVENT"
    assert lines[-1] == "END:VEVENT"
    assert "UID:meeting-9@openconstructionerp" in lines
    assert "DTSTART:20260102T080000Z" in lines
    assert "DTEND:20260102T090000Z" in lines
    assert "RRULE:FREQ=DAILY;COUNT=3" in lines
    assert "SEQUENCE:2" in lines
    assert any(ln.startswith("ORGANIZER") and ln.endswith("mailto:lead@example.com") for ln in lines)
    assert any(ln.startswith("ATTENDEE") and "RSVP=TRUE" in ln for ln in lines)


def test_build_calendar_multiple_events() -> None:
    ev1 = event_from_meeting(_meeting(id="a", title="One"), dtstamp=DTSTAMP)
    ev2 = event_from_meeting(_meeting(id="b", title="Two"), dtstamp=DTSTAMP)
    lines = _unfold(build_calendar([ev1, ev2]))
    assert lines.count("BEGIN:VEVENT") == 2
    assert "UID:meeting-a@openconstructionerp" in lines
    assert "UID:meeting-b@openconstructionerp" in lines
