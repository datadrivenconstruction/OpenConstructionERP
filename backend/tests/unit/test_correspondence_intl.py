"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the correspondence international helpers.

These are pure, database-free tests: ``app.modules.correspondence.intl`` has
no ORM, session, or FastAPI dependency, so the whole module can be exercised
directly. Coverage focuses on the international / edge-case contract:

    - ISO 8601 date parsing, including clean errors on bad input.
    - Response time in days, including the "reply before sent" guard.
    - Overdue detection and days-to-due arithmetic against a supplied
      reference date (no reliance on the wall clock).
    - Response rate with the division-by-zero and inconsistent-count guards.
    - en / de / ru localisation of type, direction, and status words with an
      English fallback.
    - Explainable reports exposing the components behind each figure.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.modules.correspondence import intl

# ── Language normalisation ────────────────────────────────────────────────


class TestNormalizeLanguage:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("en", "en"),
            ("DE", "de"),
            ("de-AT", "de"),
            ("ru_RU", "ru"),
            ("fr", "en"),
            ("", "en"),
            (None, "en"),
        ],
    )
    def test_normalize(self, raw, expected):
        assert intl.normalize_language(raw) == expected


# ── ISO date parsing ──────────────────────────────────────────────────────


class TestParseIsoDate:
    def test_parses_iso_string(self):
        assert intl.parse_iso_date("2026-07-05") == date(2026, 7, 5)

    def test_passes_through_date_object(self):
        d = date(2026, 1, 2)
        assert intl.parse_iso_date(d) is d

    @pytest.mark.parametrize("bad", ["", "   ", "2026/07/05", "05-07-2026", "not-a-date", None, 20260705])
    def test_bad_input_raises_valueerror(self, bad):
        with pytest.raises(ValueError):
            intl.parse_iso_date(bad)


# ── Response time in days ─────────────────────────────────────────────────


class TestResponseTimeDays:
    def test_same_day_is_zero(self):
        assert intl.response_time_days("2026-07-05", "2026-07-05") == 0

    def test_counts_whole_days(self):
        assert intl.response_time_days("2026-07-01", "2026-07-08") == 7

    def test_accepts_date_objects(self):
        assert intl.response_time_days(date(2026, 7, 1), date(2026, 7, 3)) == 2

    def test_reply_before_sent_raises(self):
        with pytest.raises(ValueError, match="before the sent date"):
            intl.response_time_days("2026-07-10", "2026-07-01")


# ── Due date, overdue, days until due ─────────────────────────────────────


class TestDueAndOverdue:
    def test_compute_due_date_default_window(self):
        assert intl.compute_due_date("2026-07-01") == date(2026, 7, 15)

    def test_compute_due_date_custom_window(self):
        assert intl.compute_due_date("2026-07-01", response_due_days=7) == date(2026, 7, 8)

    def test_negative_window_raises(self):
        with pytest.raises(ValueError):
            intl.compute_due_date("2026-07-01", response_due_days=-1)

    def test_overdue_true_when_past_due(self):
        assert intl.is_overdue("2026-07-01", "2026-07-02") is True

    def test_due_today_is_not_overdue(self):
        assert intl.is_overdue("2026-07-01", "2026-07-01") is False

    def test_days_until_due_positive_and_negative(self):
        assert intl.days_until_due("2026-07-10", "2026-07-07") == 3
        assert intl.days_until_due("2026-07-10", "2026-07-13") == -3
        assert intl.days_until_due("2026-07-10", "2026-07-10") == 0


# ── Response rate ─────────────────────────────────────────────────────────


class TestResponseRate:
    def test_basic_ratio(self):
        assert intl.response_rate(3, 4) == 0.75

    def test_nothing_sent_is_zero_not_nan(self):
        result = intl.response_rate(0, 0)
        assert result == 0.0

    def test_all_answered_is_one(self):
        assert intl.response_rate(5, 5) == 1.0

    def test_negative_counts_raise(self):
        with pytest.raises(ValueError):
            intl.response_rate(-1, 5)
        with pytest.raises(ValueError):
            intl.response_rate(1, -5)

    def test_more_answered_than_sent_raises(self):
        with pytest.raises(ValueError, match="exceed"):
            intl.response_rate(6, 5)


# ── Localised vocabulary ──────────────────────────────────────────────────


class TestLocalization:
    def test_type_labels(self):
        assert intl.localize_type("letter", "en") == "Letter"
        assert intl.localize_type("letter", "de") == "Brief"
        assert intl.localize_type("letter", "ru") == "Письмо"

    def test_direction_labels(self):
        assert intl.localize_direction("incoming", "de") == "Eingehend"
        assert intl.localize_direction("outgoing", "ru") == "Исходящее"

    def test_status_labels(self):
        assert intl.localize_status("overdue", "en") == "Overdue"
        assert intl.localize_status("responded", "ru") == "Отвечено"

    def test_unknown_language_falls_back_to_english(self):
        assert intl.localize_type("email", "fr") == "Email"

    def test_unknown_code_returned_unchanged(self):
        assert intl.localize_type("carrier_pigeon", "en") == "carrier_pigeon"

    def test_empty_code_is_empty(self):
        assert intl.localize_type(None, "en") == ""


# ── Derived status ────────────────────────────────────────────────────────


class TestDeriveStatus:
    def test_draft_when_not_sent(self):
        assert intl.derive_status(date_sent=None, date_responded=None) == "draft"

    def test_responded_when_reply_recorded(self):
        assert intl.derive_status(date_sent="2026-07-01", date_responded="2026-07-03") == "responded"

    def test_no_response_needed(self):
        status = intl.derive_status(date_sent="2026-07-01", date_responded=None, needs_response=False)
        assert status == "no_response_needed"

    def test_awaiting_without_reference(self):
        status = intl.derive_status(date_sent="2026-07-01", date_responded=None)
        assert status == "awaiting_response"

    def test_overdue_with_reference(self):
        status = intl.derive_status(
            date_sent="2026-07-01",
            date_responded=None,
            reference_date="2026-08-01",
            response_due_days=14,
        )
        assert status == "overdue"

    def test_awaiting_within_window(self):
        status = intl.derive_status(
            date_sent="2026-07-01",
            date_responded=None,
            reference_date="2026-07-05",
            response_due_days=14,
        )
        assert status == "awaiting_response"


# ── Response rate report ──────────────────────────────────────────────────


class TestResponseRateReport:
    def test_components_and_percent(self):
        report = intl.build_response_rate_report(3, 4, "en")
        assert report.sent_count == 4
        assert report.responded_count == 3
        assert report.outstanding_count == 1
        assert report.rate == 0.75
        assert report.percent == 75.0
        assert "75%" in report.explanation
        assert "3 of 4" in report.explanation

    def test_empty_set_reads_zero(self):
        report = intl.build_response_rate_report(0, 0, "en")
        assert report.rate == 0.0
        assert report.percent == 0.0
        assert "0%" in report.explanation

    def test_localised_explanations(self):
        de = intl.build_response_rate_report(1, 2, "de")
        ru = intl.build_response_rate_report(1, 2, "ru")
        assert "Antwortquote" in de.explanation
        assert "Доля ответов" in ru.explanation

    def test_as_dict_is_json_friendly(self):
        report = intl.build_response_rate_report(2, 5, "en")
        data = report.as_dict()
        assert data["sent_count"] == 5
        assert data["responded_count"] == 2
        assert "explanation" in data


# ── Item status report ────────────────────────────────────────────────────


class TestItemStatusReport:
    def test_responded_item_shows_turnaround(self):
        report = intl.build_item_status_report(
            type_code="letter",
            direction_code="outgoing",
            date_sent="2026-07-01",
            date_responded="2026-07-06",
            language="en",
        )
        assert report.status == "responded"
        assert report.response_time_days == 5
        assert report.type_label == "Letter"
        assert report.direction_label == "Outgoing"
        assert "5 day" in report.explanation

    def test_overdue_item_shows_days_late(self):
        report = intl.build_item_status_report(
            type_code="notice",
            direction_code="outgoing",
            date_sent="2026-07-01",
            date_responded=None,
            reference_date="2026-08-01",
            response_due_days=14,
            language="en",
        )
        assert report.status == "overdue"
        assert report.due_date == "2026-07-15"
        assert report.days_until_due is not None and report.days_until_due < 0
        assert "Overdue" in report.explanation

    def test_awaiting_item_shows_days_remaining(self):
        report = intl.build_item_status_report(
            type_code="email",
            direction_code="incoming",
            date_sent="2026-07-01",
            date_responded=None,
            reference_date="2026-07-05",
            response_due_days=14,
            language="en",
        )
        assert report.status == "awaiting_response"
        assert report.days_until_due == 10
        assert "remain" in report.explanation

    def test_draft_item_has_no_dates(self):
        report = intl.build_item_status_report(
            type_code="memo",
            direction_code="outgoing",
            date_sent=None,
            date_responded=None,
            language="de",
        )
        assert report.status == "draft"
        assert report.response_time_days is None
        assert report.due_date is None
        assert report.status_label == "Entwurf"

    def test_as_dict_round_trip(self):
        report = intl.build_item_status_report(
            type_code="letter",
            direction_code="outgoing",
            date_sent="2026-07-01",
            date_responded="2026-07-02",
            language="ru",
        )
        data = report.as_dict()
        assert data["status"] == "responded"
        assert data["response_time_days"] == 1


class TestTheTableCoversTheVocabulary:
    """A type this table has never heard of is shown to the reader as its code.

    ``_lookup`` returns the raw value when it finds no entry, which is the
    right fallback because it drops nothing, and it is also why a missing entry
    is invisible until somebody reads a document and sees ``report`` where a
    word should be. The table is a second copy of the schema's vocabulary, and
    the only thing that keeps a second copy honest is a test that compares it
    against the first.
    """

    def test_every_correspondence_type_has_a_word_in_every_language(self):
        from app.modules.correspondence.schemas import CORRESPONDENCE_TYPES

        missing = {
            f"{type_code}/{language}": True
            for type_code in CORRESPONDENCE_TYPES
            for language in intl.SUPPORTED_LANGUAGES
            if intl.localize_type(type_code, language) == type_code
        }
        assert missing == {}, f"these render as the stored token instead of a word: {sorted(missing)}"

    def test_the_check_above_would_notice_a_type_it_does_not_know(self):
        assert intl.localize_type("carrier_pigeon", "de") == "carrier_pigeon"
