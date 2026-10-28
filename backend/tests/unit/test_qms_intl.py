"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for :mod:`app.modules.qms.intl`.

These tests are deliberately database-free: the ``intl`` helpers are pure
functions over counts, statuses, severities and ISO 8601 dates, so they run
without any session, fixture or PostgreSQL round-trip. They pin the
international-robustness contract: guarded division, defined empty-set
values, rates bounded to ``[0,1]`` / ``[0,100]``, English-fallback
localization, and an ISO 8601 overdue check with a documented default
threshold.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.modules.qms.intl import (
    SEVERITY_ORDER,
    as_percent,
    counts_by_severity,
    counts_by_status,
    explain,
    first_pass_yield,
    inspection_pass_rate,
    is_overdue,
    localize_severity,
    localize_status,
    open_nonconformance_rate,
    overdue_days,
    safe_ratio,
)

# ── safe_ratio ────────────────────────────────────────────────────────────


def test_safe_ratio_basic() -> None:
    assert safe_ratio(2, 4) == 0.5


def test_safe_ratio_zero_denominator_is_zero_not_error() -> None:
    assert safe_ratio(0, 0) == 0.0


def test_safe_ratio_rejects_negative() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        safe_ratio(-1, 4)


def test_safe_ratio_rejects_numerator_over_denominator() -> None:
    with pytest.raises(ValueError, match="cannot exceed"):
        safe_ratio(5, 4)


def test_safe_ratio_stays_within_unit_interval() -> None:
    assert 0.0 <= safe_ratio(3, 7) <= 1.0


# ── as_percent ────────────────────────────────────────────────────────────


def test_as_percent_scales() -> None:
    assert as_percent(0.5) == 50.0


def test_as_percent_bounds_checked() -> None:
    with pytest.raises(ValueError, match="within"):
        as_percent(1.5)


# ── inspection pass rate ──────────────────────────────────────────────────


def test_inspection_pass_rate_components() -> None:
    out = inspection_pass_rate(passed=2, total=3)
    assert out["passed"] == 2
    assert out["total"] == 3
    assert out["rate"] == pytest.approx(2 / 3, abs=1e-6)
    assert out["percent"] == pytest.approx(66.6667, abs=1e-3)


def test_inspection_pass_rate_empty_is_zero() -> None:
    out = inspection_pass_rate(passed=0, total=0)
    assert out["rate"] == 0.0
    assert out["percent"] == 0.0


# ── first-pass yield ──────────────────────────────────────────────────────


def test_first_pass_yield_components() -> None:
    out = first_pass_yield(passed_first_time=8, total=10)
    assert out["rate"] == 0.8
    assert out["percent"] == 80.0


def test_first_pass_yield_rejects_impossible_counts() -> None:
    with pytest.raises(ValueError):
        first_pass_yield(passed_first_time=11, total=10)


# ── open nonconformance rate ──────────────────────────────────────────────


def test_open_nonconformance_rate_derives_closed() -> None:
    out = open_nonconformance_rate(open_count=3, total_count=10)
    assert out["open"] == 3
    assert out["closed"] == 7
    assert out["rate"] == 0.3
    assert out["percent"] == 30.0


def test_open_nonconformance_rate_empty_is_zero() -> None:
    out = open_nonconformance_rate(open_count=0, total_count=0)
    assert out["rate"] == 0.0
    assert out["closed"] == 0


# ── counts by status / severity ───────────────────────────────────────────


def test_counts_by_status_tallies() -> None:
    out = counts_by_status(["open", "open", "closed"])
    assert out == {"open": 2, "closed": 1}


def test_counts_by_status_empty() -> None:
    assert counts_by_status([]) == {}


def test_counts_by_severity_keeps_known_keys_zeroed_and_ordered() -> None:
    out = counts_by_severity(["major", "major", "critical"])
    assert list(out)[: len(SEVERITY_ORDER)] == list(SEVERITY_ORDER)
    assert out["observation"] == 0
    assert out["minor"] == 0
    assert out["major"] == 2
    assert out["critical"] == 1


def test_counts_by_severity_appends_unknown() -> None:
    out = counts_by_severity(["mystery"])
    assert out["mystery"] == 1


# ── localization ──────────────────────────────────────────────────────────


def test_localize_severity_all_langs() -> None:
    assert localize_severity("critical", "en") == "critical"
    assert localize_severity("critical", "de") == "kritisch"
    assert localize_severity("critical", "ru") == "kriticheskoe"


def test_localize_status_all_langs() -> None:
    assert localize_status("in_progress", "en") == "in progress"
    assert localize_status("in_progress", "de") == "in Bearbeitung"
    assert localize_status("in_progress", "ru") == "v rabote"


def test_localize_falls_back_to_english_for_unknown_lang() -> None:
    assert localize_severity("major", "zz") == "major"
    assert localize_status("open", "fr") == "open"


def test_localize_accepts_full_locale_tag() -> None:
    assert localize_status("closed", "de-DE") == "geschlossen"


def test_localize_unknown_key_returns_raw() -> None:
    assert localize_severity("made_up", "de") == "made_up"


def test_explain_known_and_localized() -> None:
    assert "nonconformance" in explain("nonconformance", "en").lower()
    assert explain("first_pass_yield", "de") != ""
    assert explain("overdue", "ru") != ""


def test_explain_unknown_concept_is_empty_not_error() -> None:
    assert explain("not_a_concept") == ""


# ── overdue check ─────────────────────────────────────────────────────────


def test_is_overdue_true_when_past_due_and_open() -> None:
    assert is_overdue("2026-01-01", as_of="2026-01-10") is True


def test_is_overdue_false_when_closed() -> None:
    assert is_overdue("2026-01-01", as_of="2026-01-10", is_closed=True) is False


def test_is_overdue_false_when_no_due_date() -> None:
    assert is_overdue(None, as_of="2026-01-10") is False


def test_is_overdue_respects_grace_days_default_zero() -> None:
    # One day past due with the default zero grace window is overdue.
    assert is_overdue("2026-01-01", as_of="2026-01-02") is True


def test_is_overdue_grace_window_suppresses() -> None:
    assert is_overdue("2026-01-01", as_of="2026-01-03", grace_days=5) is False


def test_is_overdue_accepts_iso_datetime_string() -> None:
    assert is_overdue("2026-01-01T09:00:00+00:00", as_of="2026-01-10") is True


def test_is_overdue_accepts_date_object() -> None:
    assert is_overdue(date(2026, 1, 1), as_of=date(2026, 1, 10)) is True


def test_is_overdue_rejects_negative_grace() -> None:
    with pytest.raises(ValueError, match="grace_days"):
        is_overdue("2026-01-01", as_of="2026-01-10", grace_days=-1)


def test_is_overdue_rejects_bad_iso() -> None:
    with pytest.raises(ValueError, match="ISO 8601"):
        is_overdue("01/01/2026", as_of="2026-01-10")


def test_overdue_days_counts_and_clamps() -> None:
    assert overdue_days("2026-01-01", as_of="2026-01-10") == 9
    # Not yet due clamps to zero rather than going negative.
    assert overdue_days("2026-01-20", as_of="2026-01-10") == 0
