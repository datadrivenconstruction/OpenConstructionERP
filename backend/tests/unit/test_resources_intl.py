"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure international resource-planning helpers.

These tests are database-free: every helper in ``app.modules.resources.intl``
is a pure function, so the suite imports it directly and asserts behaviour,
edge cases and output hygiene without any fixtures or session.

Coverage:
    * utilization_rate: normal, over 100 percent (not clamped), zero-capacity
      guard, negative / non-finite / non-numeric rejection, no NaN / inf ever.
    * overallocation: flag + amount, zero-capacity-with-load, exact-fit, guards.
    * remaining_capacity: headroom, negative when overbooked, guards.
    * counts_by_resource_type: strings / dicts / objects, empty, unknown.
    * available_hours: explicit working-hours parameter (no fixed day assumed).
    * load_report: components + explainers exposed, labels attached, guards.
    * localization: en / de / ru with English then raw-value fallback.
    * ISO 8601: parse_iso8601 + days_between incl. non-positive spans and
      aware / naive mismatch.
    * output hygiene: no em-dash, no en-dash, no smart quotes, no zero-width
      characters in any label or explainer (banned set built from chr()).
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime

import pytest

from app.modules.resources.intl import (
    ASSIGNMENT_STATUS_LABELS,
    EXPLAINERS,
    RESOURCE_STATUS_LABELS,
    RESOURCE_TYPE_LABELS,
    SUPPORTED_LOCALES,
    assignment_status_label,
    available_hours,
    counts_by_resource_type,
    days_between,
    explain,
    load_report,
    overallocation,
    parse_iso8601,
    remaining_capacity,
    resource_status_label,
    resource_type_label,
    utilization_rate,
)

# Banned code points, assembled ONLY from chr() so no literal banned glyph ever
# appears in this file. Covers em-dash, en-dash, all four smart quotes and the
# common zero-width / word-joiner / BOM characters.
_BANNED_CODE_POINTS = (
    0x2014,  # em dash
    0x2013,  # en dash
    0x2018,  # left single smart quote
    0x2019,  # right single smart quote
    0x201C,  # left double smart quote
    0x201D,  # right double smart quote
    0x200B,  # zero width space
    0x200C,  # zero width non-joiner
    0x200D,  # zero width joiner
    0x2060,  # word joiner
    0xFEFF,  # zero width no-break space / BOM
)
_BANNED_CHARS = frozenset(chr(cp) for cp in _BANNED_CODE_POINTS)


# ── utilization_rate ──────────────────────────────────────────────────────


def test_utilization_rate_normal() -> None:
    assert utilization_rate(50, 100) == 50.0
    assert utilization_rate(100, 100) == 100.0
    assert utilization_rate(0, 100) == 0.0


def test_utilization_rate_over_100_not_clamped() -> None:
    # 300 load on 100 capacity is a real overallocation; must not be clamped.
    assert utilization_rate(300, 100) == 300.0
    assert utilization_rate(150, 100) == 150.0


def test_utilization_rate_zero_capacity_guard() -> None:
    # Undefined without capacity -> guarded to 0.0, never a ZeroDivisionError.
    assert utilization_rate(0, 0) == 0.0
    assert utilization_rate(50, 0) == 0.0


def test_utilization_rate_accepts_decimal_and_string() -> None:
    from decimal import Decimal

    assert utilization_rate(Decimal("25"), Decimal("50")) == 50.0
    assert utilization_rate("30", "60") == 50.0


def test_utilization_rate_never_nan_or_inf() -> None:
    for allocated, capacity in [(0, 0), (5, 0), (1, 3), (2, 7)]:
        result = utilization_rate(allocated, capacity)
        assert not math.isnan(result)
        assert not math.isinf(result)


@pytest.mark.parametrize("bad", [-1, -0.5])
def test_utilization_rate_negative_raises(bad: float) -> None:
    with pytest.raises(ValueError):
        utilization_rate(bad, 100)
    with pytest.raises(ValueError):
        utilization_rate(100, bad)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_utilization_rate_non_finite_raises(bad: float) -> None:
    with pytest.raises(ValueError):
        utilization_rate(bad, 100)


def test_utilization_rate_non_numeric_raises() -> None:
    with pytest.raises(ValueError):
        utilization_rate("abc", 100)
    with pytest.raises(ValueError):
        utilization_rate(None, 100)
    # bool is rejected explicitly (an int subclass, but never a load figure).
    with pytest.raises(ValueError):
        utilization_rate(True, 100)


# ── overallocation ────────────────────────────────────────────────────────


def test_overallocation_flag_and_amount() -> None:
    result = overallocation(120, 100)
    assert result["overallocated"] is True
    assert result["overallocation_amount"] == 20.0
    assert result["allocated"] == 120.0
    assert result["capacity"] == 100.0


def test_overallocation_exact_fit_not_over() -> None:
    result = overallocation(100, 100)
    assert result["overallocated"] is False
    assert result["overallocation_amount"] == 0.0


def test_overallocation_under_capacity() -> None:
    result = overallocation(40, 100)
    assert result["overallocated"] is False
    assert result["overallocation_amount"] == 0.0


def test_overallocation_zero_capacity_with_load_is_over() -> None:
    result = overallocation(5, 0)
    assert result["overallocated"] is True
    assert result["overallocation_amount"] == 5.0


def test_overallocation_guards() -> None:
    with pytest.raises(ValueError):
        overallocation(-1, 100)
    with pytest.raises(ValueError):
        overallocation(100, float("inf"))


# ── remaining_capacity ────────────────────────────────────────────────────


def test_remaining_capacity_headroom() -> None:
    assert remaining_capacity(30, 100) == 70.0
    assert remaining_capacity(100, 100) == 0.0


def test_remaining_capacity_negative_when_overbooked() -> None:
    assert remaining_capacity(130, 100) == -30.0


def test_remaining_capacity_guards() -> None:
    with pytest.raises(ValueError):
        remaining_capacity(float("nan"), 100)
    with pytest.raises(ValueError):
        remaining_capacity(10, -5)


# ── counts_by_resource_type ───────────────────────────────────────────────


def test_counts_by_resource_type_strings() -> None:
    counts = counts_by_resource_type(["person", "person", "crew", "equipment"])
    assert counts == {"person": 2, "crew": 1, "equipment": 1}


def test_counts_by_resource_type_dicts() -> None:
    rows = [
        {"resource_type": "person"},
        {"resource_type": "subcontractor"},
        {"resource_type": "person"},
    ]
    assert counts_by_resource_type(rows) == {"person": 2, "subcontractor": 1}


def test_counts_by_resource_type_objects() -> None:
    class _Row:
        def __init__(self, rtype: str) -> None:
            self.resource_type = rtype

    rows = [_Row("crew"), _Row("crew"), _Row("equipment")]
    assert counts_by_resource_type(rows) == {"crew": 2, "equipment": 1}


def test_counts_by_resource_type_empty() -> None:
    assert counts_by_resource_type([]) == {}


def test_counts_by_resource_type_unknown_bucket() -> None:
    rows = [{"resource_type": None}, {"no_type": 1}]
    assert counts_by_resource_type(rows) == {"unknown": 2}


# ── available_hours (no fixed working day) ─────────────────────────────────


def test_available_hours_explicit_working_hours() -> None:
    # 5 days at 8 hours -> 40; the working day is a parameter, not baked in.
    assert available_hours(5, 8) == 40.0
    # A different country / shift pattern: 6 days at 10 hours.
    assert available_hours(6, 10) == 60.0
    # A part-time / half-day pattern.
    assert available_hours(10, 4.5) == 45.0


def test_available_hours_guards() -> None:
    with pytest.raises(ValueError):
        available_hours(-1, 8)
    with pytest.raises(ValueError):
        available_hours(5, float("inf"))


# ── load_report (explainability) ──────────────────────────────────────────


def test_load_report_exposes_figures_and_components() -> None:
    report = load_report(150, 100, locale="en")
    assert report["utilization_percent"] == 150.0
    assert report["overallocated"] is True
    assert report["overallocation_amount"] == 50.0
    assert report["remaining_capacity"] == -50.0
    assert report["capacity_defined"] is True
    # Components document how each figure was derived.
    assert report["components"]["utilization_percent"]["formula"] == "allocated / capacity * 100"
    assert report["components"]["remaining_capacity"]["formula"] == "capacity - allocated"
    # Explainers present for every figure.
    for key in ("utilization_rate", "allocation_vs_capacity", "overallocation", "remaining_capacity"):
        assert report["explainers"][key]


def test_load_report_zero_capacity_marks_undefined() -> None:
    report = load_report(5, 0)
    assert report["capacity_defined"] is False
    assert report["utilization_percent"] == 0.0
    # Overallocation still flags positive load against zero capacity.
    assert report["overallocated"] is True
    assert report["overallocation_amount"] == 5.0


def test_load_report_attaches_localized_labels() -> None:
    report = load_report(50, 100, locale="de", resource_type="crew", status="on_leave")
    assert report["type_label"] == "Kolonne"
    assert report["status_label"] == "Abwesend"


def test_load_report_guards() -> None:
    with pytest.raises(ValueError):
        load_report(-1, 100)


# ── localization ──────────────────────────────────────────────────────────


def test_resource_type_label_locales() -> None:
    assert resource_type_label("person", "en") == "Person"
    assert resource_type_label("subcontractor", "de") == "Nachunternehmer"
    assert resource_type_label("crew", "ru") == "Бригада"


def test_resource_status_label_locales() -> None:
    assert resource_status_label("active", "en") == "Active"
    assert resource_status_label("on_leave", "de") == "Abwesend"
    assert resource_status_label("inactive", "ru") == "Неактивен"


def test_assignment_status_label_locales() -> None:
    assert assignment_status_label("in_progress", "en") == "In progress"
    assert assignment_status_label("completed", "de") == "Abgeschlossen"
    assert assignment_status_label("cancelled", "ru") == "Отменено"


def test_label_unknown_locale_falls_back_to_english() -> None:
    assert resource_type_label("person", "fr") == "Person"
    assert resource_type_label("person", "zh-CN") == "Person"
    assert resource_type_label("person", None) == "Person"


def test_label_regional_locale_reduced_to_base() -> None:
    assert resource_type_label("crew", "de-CH") == "Kolonne"
    assert resource_type_label("crew", "de_AT") == "Kolonne"


def test_label_unknown_value_falls_back_to_raw() -> None:
    # Unknown value passes through unchanged so nothing is silently dropped.
    assert resource_type_label("robot", "en") == "robot"
    assert resource_status_label("suspended", "de") == "suspended"


def test_label_none_value_is_empty_string() -> None:
    assert resource_type_label(None, "en") == ""


def test_explain_locales_and_fallback() -> None:
    assert explain("utilization_rate", "en")
    assert explain("utilization_rate", "de")
    assert explain("utilization_rate", "ru")
    # Unknown locale -> English text.
    assert explain("utilization_rate", "fr") == explain("utilization_rate", "en")
    # Unknown topic -> empty string.
    assert explain("nonsense_topic", "en") == ""


# ── ISO 8601 helpers ──────────────────────────────────────────────────────


def test_parse_iso8601_date_and_datetime_strings() -> None:
    assert parse_iso8601("2026-07-05") == datetime(2026, 7, 5)
    parsed = parse_iso8601("2026-07-05T14:30:00+02:00")
    assert parsed.year == 2026
    assert parsed.tzinfo is not None


def test_parse_iso8601_trailing_z_is_utc() -> None:
    parsed = parse_iso8601("2026-07-05T12:00:00Z")
    assert parsed.utcoffset() is not None
    assert parsed.utcoffset().total_seconds() == 0


def test_parse_iso8601_accepts_date_and_datetime_objects() -> None:
    assert parse_iso8601(date(2026, 7, 5)) == datetime(2026, 7, 5)
    dt = datetime(2026, 7, 5, 9, 0, tzinfo=UTC)
    assert parse_iso8601(dt) == dt


@pytest.mark.parametrize("bad", ["", "   ", "not-a-date", "2026-13-40", 12345])
def test_parse_iso8601_bad_input_raises(bad: object) -> None:
    with pytest.raises(ValueError):
        parse_iso8601(bad)  # type: ignore[arg-type]


def test_days_between_positive_span() -> None:
    assert days_between("2026-07-01", "2026-07-08") == 7.0


def test_days_between_non_positive_is_zero() -> None:
    # End at or before start -> 0.0, never a negative period.
    assert days_between("2026-07-08", "2026-07-01") == 0.0
    assert days_between("2026-07-01", "2026-07-01") == 0.0


def test_days_between_aware_naive_mismatch_raises() -> None:
    with pytest.raises(ValueError):
        days_between("2026-07-01", "2026-07-08T00:00:00+00:00")


# ── output hygiene: no banned characters anywhere ─────────────────────────


def _iter_all_strings() -> list[str]:
    strings: list[str] = []
    for table in (RESOURCE_TYPE_LABELS, RESOURCE_STATUS_LABELS, ASSIGNMENT_STATUS_LABELS, EXPLAINERS):
        for catalog in table.values():
            strings.extend(catalog.values())
    return strings


def test_no_banned_characters_in_labels_and_explainers() -> None:
    for text in _iter_all_strings():
        offending = _BANNED_CHARS.intersection(text)
        assert not offending, f"banned character(s) {[hex(ord(c)) for c in offending]} in {text!r}"


def test_supported_locales_present_in_every_table() -> None:
    for lang in SUPPORTED_LOCALES:
        assert lang in RESOURCE_TYPE_LABELS
        assert lang in RESOURCE_STATUS_LABELS
        assert lang in ASSIGNMENT_STATUS_LABELS
        assert lang in EXPLAINERS
