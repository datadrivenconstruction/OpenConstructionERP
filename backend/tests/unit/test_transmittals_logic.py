# DDC-CWICR-OE: DataDrivenConstruction / OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Database-free unit tests for the transmittals pure-logic layer.

Covers the numbering scheme, the response-due-date maths and the
readiness-to-issue checks in ``app.modules.transmittals.logic``, plus the
cross-field date validation on the request schemas. None of these touch a
database, so they can be run by explicit path without any fixtures.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.transmittals.logic import (
    PURPOSE_CODES,
    RESPONDABLE_STATUSES,
    STATUS_DRAFT,
    STATUS_ISSUED,
    STATUS_RESPONDED,
    VALID_STATUSES,
    compute_response_due_date,
    issue_blockers,
    next_transmittal_number,
    parse_iso_date,
    response_due_error,
)

# ── Numbering ─────────────────────────────────────────────────────────────


def test_next_number_starts_at_one_when_none() -> None:
    assert next_transmittal_number(None) == "TR-001"


def test_next_number_increments_and_zero_pads() -> None:
    assert next_transmittal_number("TR-001") == "TR-002"
    assert next_transmittal_number("TR-009") == "TR-010"
    assert next_transmittal_number("TR-099") == "TR-100"


def test_next_number_uses_trailing_digits_only() -> None:
    # A project-code style prefix with digits still increments correctly,
    # because only the trailing counter is read.
    assert next_transmittal_number("PRJ2024-007", prefix="PRJ2024") == "PRJ2024-008"


def test_next_number_custom_prefix_and_pad() -> None:
    assert next_transmittal_number(None, prefix="DOC", pad=4) == "DOC-0001"
    assert next_transmittal_number("DOC-0041", prefix="DOC", pad=4) == "DOC-0042"


def test_next_number_falls_back_on_blank_or_bad_config() -> None:
    # Empty prefix and non-positive padding fall back to the safe defaults.
    assert next_transmittal_number(None, prefix="   ", pad=0) == "TR-001"
    assert next_transmittal_number("garbage-no-digits") == "TR-001"


def test_next_number_high_counter_keeps_all_digits() -> None:
    # Padding is a minimum width, never a cap.
    assert next_transmittal_number("TR-1000") == "TR-1001"


# ── Date parsing ──────────────────────────────────────────────────────────


def test_parse_iso_date_accepts_valid_and_blank() -> None:
    assert parse_iso_date("2026-03-31") == "2026-03-31"
    assert parse_iso_date("  2026-03-31  ") == "2026-03-31"
    assert parse_iso_date(None) is None
    assert parse_iso_date("") is None
    assert parse_iso_date("   ") is None


def test_parse_iso_date_rejects_non_iso_format() -> None:
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        parse_iso_date("31/03/2026")


def test_parse_iso_date_rejects_impossible_date() -> None:
    with pytest.raises(ValueError, match="not a real calendar date"):
        parse_iso_date("2026-02-30")


# ── Response due date maths ────────────────────────────────────────────────


def test_compute_response_due_date_adds_calendar_days() -> None:
    assert compute_response_due_date("2026-03-30", 5) == "2026-04-04"
    # Zero days means the response is due the same day it is issued.
    assert compute_response_due_date("2026-03-30", 0) == "2026-03-30"


def test_compute_response_due_date_none_when_inputs_missing() -> None:
    assert compute_response_due_date(None, 5) is None
    assert compute_response_due_date("2026-03-30", None) is None


def test_compute_response_due_date_rejects_negative_period() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        compute_response_due_date("2026-03-30", -1)


# ── Response due consistency ───────────────────────────────────────────────


def test_response_due_error_flags_due_before_issue() -> None:
    error = response_due_error("2026-03-30", "2026-03-29")
    assert error is not None
    assert "cannot be earlier" in error


def test_response_due_error_allows_same_or_later_day() -> None:
    assert response_due_error("2026-03-30", "2026-03-30") is None
    assert response_due_error("2026-03-30", "2026-04-15") is None


def test_response_due_error_none_when_a_date_is_missing() -> None:
    assert response_due_error(None, "2026-03-29") is None
    assert response_due_error("2026-03-30", None) is None


# ── Readiness to issue ─────────────────────────────────────────────────────


def test_issue_blockers_empty_when_ready() -> None:
    assert issue_blockers(recipient_count=1, item_count=1) == []


def test_issue_blockers_flags_missing_recipients() -> None:
    problems = issue_blockers(recipient_count=0, item_count=2)
    assert len(problems) == 1
    assert "recipient" in problems[0].lower()


def test_issue_blockers_flags_missing_items() -> None:
    problems = issue_blockers(recipient_count=2, item_count=0)
    assert len(problems) == 1
    assert "document" in problems[0].lower()


def test_issue_blockers_flags_both_when_empty() -> None:
    assert len(issue_blockers(recipient_count=0, item_count=0)) == 2


# ── Vocabulary invariants ──────────────────────────────────────────────────


def test_status_vocabulary_is_consistent() -> None:
    assert VALID_STATUSES == (STATUS_DRAFT, STATUS_ISSUED, STATUS_RESPONDED)
    # You can only acknowledge or respond to a transmittal that has been sent.
    assert STATUS_DRAFT not in RESPONDABLE_STATUSES
    assert STATUS_ISSUED in RESPONDABLE_STATUSES
    assert STATUS_RESPONDED in RESPONDABLE_STATUSES


def test_no_smart_quotes_or_em_dashes_in_user_messages() -> None:
    # Guards against accidental non-ASCII punctuation in the strings a user
    # actually reads.
    # Built from code points so this source file itself stays pure ASCII:
    # em-dash, left/right single quotes, left/right double quotes.
    banned = [chr(cp) for cp in (0x2014, 0x2018, 0x2019, 0x201C, 0x201D)]
    samples: list[str] = []
    samples.extend(issue_blockers(0, 0))
    samples.append(response_due_error("2026-03-30", "2026-03-29") or "")
    for text in samples:
        for ch in banned:
            assert ch not in text


# ── Schema-level cross-field validation ────────────────────────────────────


def _valid_create_payload(**overrides: object) -> dict:
    payload: dict = {
        "project_id": str(uuid.uuid4()),
        "subject": "Issue drawings for coordination",
        "purpose_code": "for_information",
    }
    payload.update(overrides)
    return payload


def test_create_schema_rejects_due_before_issue() -> None:
    from pydantic import ValidationError

    from app.modules.transmittals.schemas import TransmittalCreate

    with pytest.raises(ValidationError, match="cannot be earlier"):
        TransmittalCreate(**_valid_create_payload(issued_date="2026-03-30", response_due_date="2026-03-29"))


def test_create_schema_accepts_consistent_dates() -> None:
    from app.modules.transmittals.schemas import TransmittalCreate

    model = TransmittalCreate(**_valid_create_payload(issued_date="2026-03-30", response_due_date="2026-04-10"))
    assert model.response_due_date == "2026-04-10"


def test_create_schema_rejects_unknown_purpose_code() -> None:
    from pydantic import ValidationError

    from app.modules.transmittals.schemas import TransmittalCreate

    with pytest.raises(ValidationError):
        TransmittalCreate(**_valid_create_payload(purpose_code="for_demolition"))


def test_every_purpose_code_is_accepted_by_schema() -> None:
    from app.modules.transmittals.schemas import TransmittalCreate

    for code in PURPOSE_CODES:
        model = TransmittalCreate(**_valid_create_payload(purpose_code=code))
        assert model.purpose_code == code


def test_update_schema_rejects_due_before_issue() -> None:
    from pydantic import ValidationError

    from app.modules.transmittals.schemas import TransmittalUpdate

    with pytest.raises(ValidationError, match="cannot be earlier"):
        TransmittalUpdate(issued_date="2026-03-30", response_due_date="2026-03-01")


def test_the_sequence_ignores_numbers_of_another_shape_and_compares_counters() -> None:
    from app.modules.transmittals.logic import highest_in_sequence, next_transmittal_number

    # Demo data numbers by year; read as text it always sorts above TR-004 and every new number repeats.
    project = ["TR-2026-001", "TR-2026-002", "TR-2026-003", "TR-004", None]
    assert highest_in_sequence(project) == "TR-004"
    assert next_transmittal_number(highest_in_sequence(project)) == "TR-005"
    assert highest_in_sequence(["TR-999", "TR-1000", "TR-0998"]) == "TR-1000"
    assert highest_in_sequence(["TR-2026-001"]) is None
    assert highest_in_sequence(["P1-TR-007", "P1-007"], prefix="P1") == "P1-007"
