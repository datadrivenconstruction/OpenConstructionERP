"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the Inspections international helpers (``intl.py``).

These are pure, database-free tests. They pin the international behaviour that
keeps quality and site inspections clear and correct anywhere in the world:

* pass rate is a guarded ratio in a fixed range, never money and never NaN/inf,
  with a defined answer for the empty set;
* defect density is a non-negative per-inspection count, zero-guarded;
* counts by status and by result handle empty, unknown and not-yet-evaluated
  input cleanly;
* the re-inspection overdue check has no hidden clock or locale (explicit
  reference date and SLA window) and treats passes, resolved re-inspections and
  missing due dates correctly;
* status and result words localize to en/de/ru with an English fall-back;
* dates render as ISO 8601;
* the one-line explainers stay plain and never emit banned typographic
  characters (em dashes, smart quotes, zero-width marks).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.modules.inspections.intl import (
    DEFAULT_LOCALE,
    REINSPECTION_RESULTS,
    RESULT_CODES,
    STATUS_CODES,
    counts_by_result,
    counts_by_status,
    defect_density,
    explain_defect_density,
    explain_pass_rate,
    explain_reinspection_overdue,
    explain_result,
    is_reinspection_overdue,
    localize_result,
    localize_status,
    pass_rate,
    pass_rate_breakdown,
    reinspection_due_date,
    to_iso_date,
)

# ── Vocabulary matches the module's real codes ───────────────────────────


def test_vocabulary_matches_service_and_schema() -> None:
    # These must stay in lock-step with schemas.py / service.py.
    assert STATUS_CODES == ("scheduled", "in_progress", "completed", "failed", "cancelled")
    assert RESULT_CODES == ("pass", "fail", "partial")
    assert sorted(REINSPECTION_RESULTS) == ["fail", "partial"]
    assert DEFAULT_LOCALE == "en"


# ── pass_rate: guards and range ──────────────────────────────────────────


def test_pass_rate_basic_ratio() -> None:
    assert pass_rate(3, 4) == 0.75
    assert pass_rate(3, 4, as_percent=True) == 75.0


def test_pass_rate_empty_set_is_zero_not_error() -> None:
    # Division-by-zero guard: nothing evaluated means 0%, not a crash.
    assert pass_rate(0, 0) == 0.0
    assert pass_rate(0, 0, as_percent=True) == 0.0


def test_pass_rate_all_passed_is_one() -> None:
    assert pass_rate(5, 5) == 1.0
    assert pass_rate(5, 5, as_percent=True) == 100.0


def test_pass_rate_stays_in_range() -> None:
    for passed, evaluated in [(0, 7), (1, 3), (7, 7), (2, 9)]:
        ratio = pass_rate(passed, evaluated)
        assert 0.0 <= ratio <= 1.0
        percent = pass_rate(passed, evaluated, as_percent=True)
        assert 0.0 <= percent <= 100.0


def test_pass_rate_negative_counts_raise() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        pass_rate(-1, 4)
    with pytest.raises(ValueError, match="non-negative"):
        pass_rate(1, -4)


def test_pass_rate_passed_exceeds_evaluated_raises() -> None:
    with pytest.raises(ValueError, match="cannot exceed"):
        pass_rate(5, 4)


# ── defect_density: guards and non-negativity ────────────────────────────


def test_defect_density_basic() -> None:
    assert defect_density(12, 4) == 3.0
    assert defect_density(0, 4) == 0.0


def test_defect_density_zero_inspections_is_zero_not_error() -> None:
    # Division-by-zero guard: no inspections means 0.0, never inf/NaN.
    assert defect_density(0, 0) == 0.0
    assert defect_density(5, 0) == 0.0


def test_defect_density_can_exceed_one() -> None:
    # Several defects per inspection is normal, so this is NOT clamped at 1.
    assert defect_density(9, 3) == 3.0


def test_defect_density_negative_counts_raise() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        defect_density(-1, 3)
    with pytest.raises(ValueError, match="non-negative"):
        defect_density(3, -1)


# ── counts_by_status / counts_by_result ──────────────────────────────────


def test_counts_by_status_present_only() -> None:
    tally = counts_by_status(["scheduled", "scheduled", "completed"])
    assert tally == {"scheduled": 2, "completed": 1}


def test_counts_by_status_include_all_fills_zeros() -> None:
    tally = counts_by_status(["completed"], include_all=True)
    assert tally == {
        "scheduled": 0,
        "in_progress": 0,
        "completed": 1,
        "failed": 0,
        "cancelled": 0,
    }


def test_counts_by_status_empty_is_empty_dict() -> None:
    assert counts_by_status([]) == {}


def test_counts_by_result_skips_not_yet_evaluated() -> None:
    # None and blanks mean "no result yet" and must not be tallied.
    tally = counts_by_result(["pass", "pass", "fail", None, ""])
    assert tally == {"pass": 2, "fail": 1}


def test_counts_by_result_include_all_fills_zeros() -> None:
    tally = counts_by_result(["pass"], include_all=True)
    assert tally == {"pass": 1, "fail": 0, "partial": 0}


def test_counts_by_result_normalises_case_and_whitespace() -> None:
    tally = counts_by_result([" Pass ", "FAIL"])
    assert tally == {"pass": 1, "fail": 1}


# ── pass_rate_breakdown: explainable components ──────────────────────────


def test_pass_rate_breakdown_exposes_components() -> None:
    breakdown = pass_rate_breakdown(["pass", "pass", "fail", "partial", None])
    assert breakdown["total"] == 5
    assert breakdown["evaluated"] == 4
    assert breakdown["passed"] == 2
    assert breakdown["failed"] == 1
    assert breakdown["partial"] == 1
    assert breakdown["pending"] == 1
    assert breakdown["rate"] == 0.5
    assert breakdown["rate_percent"] == 50.0


def test_pass_rate_breakdown_empty_is_defined() -> None:
    breakdown = pass_rate_breakdown([])
    assert breakdown["total"] == 0
    assert breakdown["evaluated"] == 0
    assert breakdown["rate"] == 0.0
    assert breakdown["rate_percent"] == 0.0


def test_pass_rate_breakdown_all_pending() -> None:
    breakdown = pass_rate_breakdown([None, None])
    assert breakdown["pending"] == 2
    assert breakdown["evaluated"] == 0
    assert breakdown["rate"] == 0.0


# ── dates: ISO 8601 only ─────────────────────────────────────────────────


def test_to_iso_date_none_is_none() -> None:
    assert to_iso_date(None) is None


def test_to_iso_date_normalises_date_string() -> None:
    assert to_iso_date("2026-07-05") == "2026-07-05T00:00:00"


def test_to_iso_date_datetime() -> None:
    dt = datetime(2026, 7, 5, 9, 30, tzinfo=UTC)
    assert to_iso_date(dt) == "2026-07-05T09:30:00+00:00"


def test_to_iso_date_bad_string_raises() -> None:
    with pytest.raises(ValueError, match="ISO 8601"):
        to_iso_date("05/07/2026")


def test_reinspection_due_date_adds_sla_window() -> None:
    assert reinspection_due_date("2026-07-05", sla_days=7) == "2026-07-12T00:00:00"


def test_reinspection_due_date_zero_sla_is_same_day() -> None:
    assert reinspection_due_date("2026-07-05", sla_days=0) == "2026-07-05T00:00:00"


def test_reinspection_due_date_negative_sla_raises() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        reinspection_due_date("2026-07-05", sla_days=-1)


def test_reinspection_due_date_non_finite_sla_raises() -> None:
    with pytest.raises(ValueError, match="finite"):
        reinspection_due_date("2026-07-05", sla_days=float("inf"))


# ── is_reinspection_overdue: no hidden clock or locale ───────────────────


def test_reinspection_overdue_true_when_past_due() -> None:
    assert is_reinspection_overdue("2026-07-01", "2026-07-05", result="fail") is True


def test_reinspection_overdue_false_when_before_due() -> None:
    assert is_reinspection_overdue("2026-07-10", "2026-07-05", result="fail") is False


def test_reinspection_overdue_missing_due_date_is_never_overdue() -> None:
    assert is_reinspection_overdue(None, "2026-07-05", result="fail") is False


def test_reinspection_overdue_pass_needs_no_reinspection() -> None:
    # A clean pass is never overdue, even with a due date in the past.
    assert is_reinspection_overdue("2026-01-01", "2026-07-05", result="pass") is False


def test_reinspection_overdue_partial_still_owes_a_reinspection() -> None:
    assert is_reinspection_overdue("2026-07-01", "2026-07-05", result="partial") is True


def test_reinspection_overdue_resolved_is_never_overdue() -> None:
    assert is_reinspection_overdue("2026-07-01", "2026-07-05", result="fail", resolved=True) is False


def test_reinspection_overdue_sla_window_extends_deadline() -> None:
    # Due 2026-07-01, but a 10-day SLA pushes the deadline past the reference.
    assert is_reinspection_overdue("2026-07-01", "2026-07-05", result="fail", sla_days=10) is False
    assert is_reinspection_overdue("2026-07-01", "2026-07-05", result="fail", sla_days=2) is True


def test_reinspection_overdue_naive_and_aware_dates_are_comparable() -> None:
    aware = datetime(2026, 7, 5, tzinfo=UTC)
    assert is_reinspection_overdue("2026-07-01", aware, result="fail") is True


def test_reinspection_overdue_non_finite_sla_raises() -> None:
    with pytest.raises(ValueError, match="finite"):
        is_reinspection_overdue("2026-07-01", "2026-07-05", result="fail", sla_days=float("nan"))


# ── localization: en / de / ru with English fall-back ────────────────────


def test_localize_status_known_locales() -> None:
    assert localize_status("in_progress", "en") == "In progress"
    assert localize_status("in_progress", "de") == "In Bearbeitung"
    assert localize_status("in_progress", "ru") == "В работе"


def test_localize_status_region_tag_falls_back_to_base() -> None:
    assert localize_status("completed", "de-DE") == "Abgeschlossen"
    assert localize_status("completed", "ru_RU") == "Завершена"


def test_localize_status_unknown_locale_falls_back_to_english() -> None:
    assert localize_status("failed", "zz") == "Failed"
    assert localize_status("failed", None) == "Failed"


def test_localize_status_unknown_code_is_readable_not_blank() -> None:
    assert localize_status("weird_state") == "weird state"
    assert localize_status("") == ""


def test_localize_result_known_locales() -> None:
    assert localize_result("pass", "en") == "Pass"
    assert localize_result("pass", "de") == "Bestanden"
    assert localize_result("pass", "ru") == "Пройдена"
    assert localize_result("fail", "de") == "Durchgefallen"


def test_localize_result_unknown_falls_back() -> None:
    assert localize_result("pass", "zz") == "Pass"
    assert localize_result("unknown_result") == "unknown result"


# ── one-line explainers ──────────────────────────────────────────────────


def test_explain_pass_rate_plain_sentence() -> None:
    assert explain_pass_rate(8, 10) == "8 of 10 evaluated inspections passed, a pass rate of 80.0%."


def test_explain_pass_rate_nothing_evaluated() -> None:
    assert explain_pass_rate(0, 0) == "No inspections have a result yet, so there is no pass rate (0.0%)."


def test_explain_defect_density_plain_sentence() -> None:
    assert explain_defect_density(12, 4) == ("12 defects across 4 inspections, an average of 3.00 per inspection.")


def test_explain_defect_density_no_inspections() -> None:
    assert explain_defect_density(0, 0) == (
        "No inspections yet, so defect density cannot be measured (0.00 per inspection)."
    )


def test_explain_result_with_result() -> None:
    line = explain_result(title="Foundation pour", status="completed", result="pass")
    assert line == "'Foundation pour' is Completed with a result of Pass."


def test_explain_result_not_yet_evaluated() -> None:
    line = explain_result(title="Foundation pour", status="scheduled")
    assert line == "'Foundation pour' is Scheduled, not yet evaluated."


def test_explain_result_untitled_and_localized() -> None:
    line = explain_result(title="   ", status="in_progress", result="fail", locale="de")
    assert line == "'Untitled inspection' is In Bearbeitung with a result of Durchgefallen."


def test_explain_reinspection_overdue_states_iso_dates() -> None:
    line = explain_reinspection_overdue("2026-07-01", "2026-07-05", result="fail")
    assert line == "Re-inspection due 2026-07-01T00:00:00, measured against 2026-07-05T00:00:00: overdue."


def test_explain_reinspection_overdue_on_time() -> None:
    line = explain_reinspection_overdue("2026-07-10", "2026-07-05", result="fail")
    assert line.endswith(": on time.")


def test_explain_reinspection_overdue_pass_needs_none() -> None:
    line = explain_reinspection_overdue("2026-01-01", "2026-07-05", result="pass")
    assert line == "This inspection passed, so no re-inspection is required."


def test_explain_reinspection_overdue_resolved() -> None:
    line = explain_reinspection_overdue("2026-07-01", "2026-07-05", result="fail", resolved=True)
    assert line == "The re-inspection is already done, so it is not overdue."


def test_explain_reinspection_overdue_no_due_date() -> None:
    line = explain_reinspection_overdue(None, "2026-07-05", result="fail")
    assert line == "No re-inspection due date is set, so it cannot be overdue."


# ── banned typographic characters must never appear in output ────────────


def test_no_banned_typographic_characters_in_output() -> None:
    # Build the banned set from code points, never as literal glyphs: em dash,
    # en dash, left/right single and double smart quotes, and the zero-width
    # marks (ZWNJ, word joiner, ZWJ, zero-width space).
    banned = {
        chr(0x2014),  # em dash
        chr(0x2013),  # en dash
        chr(0x2018),  # left single quote
        chr(0x2019),  # right single quote
        chr(0x201C),  # left double quote
        chr(0x201D),  # right double quote
        chr(0x200B),  # zero-width space
        chr(0x200C),  # zero-width non-joiner
        chr(0x200D),  # zero-width joiner
        chr(0x2060),  # word joiner
    }
    samples = [
        explain_pass_rate(8, 10),
        explain_pass_rate(0, 0),
        explain_defect_density(12, 4),
        explain_defect_density(0, 0),
        explain_result(title="Foundation pour", status="completed", result="pass"),
        explain_result(title="Foundation pour", status="scheduled"),
        explain_reinspection_overdue("2026-07-01", "2026-07-05", result="fail"),
        explain_reinspection_overdue("2026-07-10", "2026-07-05", result="fail"),
        explain_reinspection_overdue("2026-01-01", "2026-07-05", result="pass"),
    ]
    for locale in ("en", "de", "ru"):
        for code in STATUS_CODES:
            samples.append(localize_status(code, locale))
        for code in RESULT_CODES:
            samples.append(localize_result(code, locale))
    for text in samples:
        for ch in banned:
            assert ch not in text, f"banned character U+{ord(ch):04X} found in {text!r}"
