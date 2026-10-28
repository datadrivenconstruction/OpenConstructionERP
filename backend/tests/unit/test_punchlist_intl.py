"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the Punch List international helpers (``intl.py``).

These are pure, database-free tests. They pin the international behaviour that
keeps a punch list clear and correct anywhere in the world:

* completion rate is a guarded ratio in a fixed range, never money and never
  NaN/inf, with a defined answer for the empty list;
* counts by status and by severity fold the ``reopened`` alias and handle
  empty and unknown input cleanly;
* the overdue check has no hidden clock or locale (explicit reference date and
  grace threshold) and treats done items and missing due dates correctly;
* status and severity words localize to en/de/ru with an English fall-back;
* dates render as ISO 8601;
* the one-line explainers stay plain and stable.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.modules.punchlist.intl import (
    DONE_STATUSES,
    SEVERITY_CODES,
    STATUS_CODES,
    completion_breakdown,
    completion_rate,
    counts_by_severity,
    counts_by_status,
    explain_completion_rate,
    explain_item,
    explain_open_vs_closed,
    explain_overdue,
    highest_severity,
    is_overdue,
    localize_severity,
    localize_status,
    open_vs_closed,
    to_iso_date,
)

# ── completion_rate: guards and range ────────────────────────────────────


def test_completion_rate_basic_ratio() -> None:
    assert completion_rate(3, 4) == 0.75
    assert completion_rate(3, 4, as_percent=True) == 75.0


def test_completion_rate_empty_list_is_zero_not_error() -> None:
    # Division-by-zero guard: an empty punch list is 0% complete, not a crash.
    assert completion_rate(0, 0) == 0.0
    assert completion_rate(0, 0, as_percent=True) == 0.0


def test_completion_rate_all_done_is_one() -> None:
    assert completion_rate(5, 5) == 1.0
    assert completion_rate(5, 5, as_percent=True) == 100.0


def test_completion_rate_stays_in_range() -> None:
    for closed, total in [(0, 10), (1, 3), (7, 9), (10, 10)]:
        ratio = completion_rate(closed, total)
        assert 0.0 <= ratio <= 1.0
        percent = completion_rate(closed, total, as_percent=True)
        assert 0.0 <= percent <= 100.0


def test_completion_rate_negative_counts_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        completion_rate(-1, 5)
    with pytest.raises(ValueError, match="non-negative"):
        completion_rate(1, -5)


def test_completion_rate_closed_exceeds_total_rejected() -> None:
    with pytest.raises(ValueError, match="cannot exceed"):
        completion_rate(6, 5)


def test_completion_rate_never_nan_or_inf() -> None:
    import math

    value = completion_rate(0, 0)
    assert math.isfinite(value)


# ── counts_by_status / counts_by_severity ────────────────────────────────


def test_counts_by_status_folds_reopened_into_open() -> None:
    counts = counts_by_status(["open", "reopened", "OPEN", " open "])
    assert counts == {"open": 4}


def test_counts_by_status_empty_input() -> None:
    assert counts_by_status([]) == {}
    assert counts_by_status([], include_all=True) == dict.fromkeys(STATUS_CODES, 0)


def test_counts_by_status_include_all_has_every_code() -> None:
    counts = counts_by_status(["open", "closed", "closed"], include_all=True)
    assert set(counts) == set(STATUS_CODES)
    assert counts["closed"] == 2
    assert counts["open"] == 1
    assert counts["verified"] == 0


def test_counts_by_severity_case_insensitive() -> None:
    counts = counts_by_severity(["High", "high", "LOW"])
    assert counts == {"high": 2, "low": 1}


def test_counts_by_severity_include_all() -> None:
    counts = counts_by_severity([], include_all=True)
    assert counts == dict.fromkeys(SEVERITY_CODES, 0)


# ── open_vs_closed / completion_breakdown ────────────────────────────────


def test_open_vs_closed_split_sums_to_total() -> None:
    statuses = ["open", "in_progress", "verified", "closed", "resolved"]
    split = open_vs_closed(statuses)
    assert split["closed"] == 2  # verified + closed
    assert split["open"] == 3
    assert split["total"] == 5
    assert split["open"] + split["closed"] == split["total"]


def test_open_vs_closed_empty() -> None:
    assert open_vs_closed([]) == {"open": 0, "closed": 0, "total": 0}


def test_completion_breakdown_exposes_components() -> None:
    statuses = ["open", "open", "closed", "verified"]
    breakdown = completion_breakdown(statuses)
    assert breakdown["total"] == 4
    assert breakdown["closed"] == 2
    assert breakdown["open"] == 2
    assert breakdown["rate"] == 0.5
    assert breakdown["rate_percent"] == 50.0


def test_completion_breakdown_empty_is_zero() -> None:
    breakdown = completion_breakdown([])
    assert breakdown["total"] == 0
    assert breakdown["rate"] == 0.0
    assert breakdown["rate_percent"] == 0.0


def test_done_statuses_are_verified_and_closed() -> None:
    assert frozenset({"verified", "closed"}) == DONE_STATUSES


# ── highest_severity ─────────────────────────────────────────────────────


def test_highest_severity_picks_worst() -> None:
    assert highest_severity(["low", "critical", "medium"]) == "critical"
    assert highest_severity(["low", "high", "medium"]) == "high"


def test_highest_severity_empty_is_none() -> None:
    assert highest_severity([]) is None


def test_highest_severity_ignores_unknown_codes() -> None:
    # A typo must not masquerade as the most critical item.
    assert highest_severity(["low", "bogus", "medium"]) == "medium"
    assert highest_severity(["bogus", "nonsense"]) is None


# ── is_overdue: explicit clock, no hidden locale ─────────────────────────

_REF = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)


def test_overdue_true_when_past_due_and_open() -> None:
    due = datetime(2026, 6, 1, tzinfo=UTC)
    assert is_overdue(due, _REF, status="open") is True


def test_overdue_false_when_due_in_future() -> None:
    due = datetime(2026, 8, 1, tzinfo=UTC)
    assert is_overdue(due, _REF, status="open") is False


def test_overdue_false_without_due_date() -> None:
    assert is_overdue(None, _REF, status="open") is False


def test_overdue_false_for_done_item() -> None:
    due = datetime(2026, 6, 1, tzinfo=UTC)
    # A verified or closed item is complete and therefore not overdue.
    assert is_overdue(due, _REF, status="verified") is False
    assert is_overdue(due, _REF, status="closed") is False


def test_overdue_grace_threshold_is_a_parameter() -> None:
    due = datetime(2026, 6, 28, 12, 0, tzinfo=UTC)  # 3 days before reference
    assert is_overdue(due, _REF, status="open", grace_days=0) is True
    # A 5-day grace period pushes the deadline past the reference date.
    assert is_overdue(due, _REF, status="open", grace_days=5) is False


def test_overdue_accepts_iso_strings() -> None:
    assert is_overdue("2026-06-01T00:00:00+00:00", "2026-07-01T12:00:00+00:00", status="open") is True


def test_overdue_accepts_z_suffix() -> None:
    assert is_overdue("2026-06-01T00:00:00Z", "2026-07-01T12:00:00Z", status="open") is True


def test_overdue_mixes_naive_and_aware_safely() -> None:
    naive_due = datetime(2026, 6, 1)
    assert is_overdue(naive_due, _REF, status="open") is True


def test_overdue_rejects_non_finite_grace() -> None:
    due = datetime(2026, 6, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="finite"):
        is_overdue(due, _REF, status="open", grace_days=float("inf"))
    with pytest.raises(ValueError, match="finite"):
        is_overdue(due, _REF, status="open", grace_days=float("nan"))


def test_overdue_rejects_bad_iso_string() -> None:
    with pytest.raises(ValueError, match="ISO 8601"):
        is_overdue("not-a-date", _REF, status="open")


# ── to_iso_date ──────────────────────────────────────────────────────────


def test_to_iso_date_from_datetime() -> None:
    assert to_iso_date(datetime(2026, 7, 1, tzinfo=UTC)) == "2026-07-01T00:00:00+00:00"


def test_to_iso_date_none_is_none() -> None:
    assert to_iso_date(None) is None


def test_to_iso_date_passthrough_valid_string() -> None:
    assert to_iso_date("2026-07-01T00:00:00+00:00") == "2026-07-01T00:00:00+00:00"


# ── localize_status / localize_severity ──────────────────────────────────


def test_localize_status_english() -> None:
    assert localize_status("in_progress", "en") == "In progress"
    assert localize_status("closed") == "Closed"  # default locale is English


def test_localize_status_german_and_russian() -> None:
    assert localize_status("open", "de") == "Offen"
    assert localize_status("open", "ru") == "Открыт"


def test_localize_status_reopened_alias() -> None:
    assert localize_status("reopened", "en") == "Open"


def test_localize_status_unsupported_locale_falls_back_to_english() -> None:
    assert localize_status("closed", "xx") == "Closed"


def test_localize_status_region_tagged_locale() -> None:
    assert localize_status("open", "de-DE") == "Offen"
    assert localize_status("open", "ru_RU") == "Открыт"


def test_localize_status_unknown_code_never_blank() -> None:
    label = localize_status("weird_state", "de")
    assert label
    assert label == "weird state"


def test_localize_severity_all_locales() -> None:
    assert localize_severity("critical", "en") == "Critical"
    assert localize_severity("critical", "de") == "Kritisch"
    assert localize_severity("critical", "ru") == "Критический"


def test_localize_severity_fallback_and_unknown() -> None:
    assert localize_severity("high", "xx") == "High"  # unsupported locale -> English
    assert localize_severity("unknown") == "unknown"  # unknown code -> raw


def test_every_status_and_severity_has_all_translations() -> None:
    for locale in ("en", "de", "ru"):
        for code in STATUS_CODES:
            assert localize_status(code, locale)
        for code in SEVERITY_CODES:
            assert localize_severity(code, locale)


# ── explainers ───────────────────────────────────────────────────────────


def test_explain_item_reads_plainly() -> None:
    line = explain_item(title="Cracked wall", status="open", severity="high")
    assert line == "'Cracked wall' is a High-severity item, currently Open."


def test_explain_item_localizes_words() -> None:
    line = explain_item(title="Riss", status="in_progress", severity="critical", locale="de")
    assert "In Bearbeitung" in line
    assert "Kritisch" in line


def test_explain_item_handles_blank_title() -> None:
    line = explain_item(title="  ", status="open", severity="low")
    assert "Untitled item" in line


def test_explain_completion_rate_wording() -> None:
    assert explain_completion_rate(12, 20) == "12 of 20 items are done, a completion rate of 60.0%."


def test_explain_completion_rate_empty() -> None:
    assert "nothing to complete" in explain_completion_rate(0, 0)


def test_explain_open_vs_closed_wording() -> None:
    statuses = ["open"] * 8 + ["closed"] * 12
    assert explain_open_vs_closed(statuses) == "8 open, 12 done, out of 20 total."


def test_explain_overdue_names_the_reference_date() -> None:
    line = explain_overdue("2026-06-01T00:00:00+00:00", "2026-07-01T12:00:00+00:00", status="open")
    assert "overdue" in line
    assert "2026-06-01" in line
    assert "2026-07-01" in line


def test_explain_overdue_no_due_date() -> None:
    assert "cannot be overdue" in explain_overdue(None, _REF, status="open")


def test_explain_overdue_on_time() -> None:
    line = explain_overdue("2026-08-01T00:00:00+00:00", "2026-07-01T12:00:00+00:00", status="open")
    assert "on time" in line
