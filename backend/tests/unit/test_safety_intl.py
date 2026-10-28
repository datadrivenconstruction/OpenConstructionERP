"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the international, explainable safety helpers.

Scope:
    Pure-logic coverage of :mod:`app.modules.safety.intl`: TRIR/LTIFR/severity
    rates with explicit hours bases, division-by-zero and negative-input
    guards, counts by severity and type, days-since-last-incident, and en/de/ru
    localization with an English fallback. No database, no app lifespan, no I/O.
"""

from __future__ import annotations

import math
from datetime import date
from types import SimpleNamespace

import pytest

from app.modules.safety import intl

# ── Rate helpers: standard constants and explicit bases ───────────────────────


def test_trir_standard_base() -> None:
    result = intl.trir(2, 400_000)
    # 2 / 400000 * 200000 = 1.0
    assert result.value == 1.0
    assert result.status == "ok"
    assert result.base_hours == intl.TRIR_BASE_HOURS == 200_000
    assert result.count == 2.0
    assert result.hours_worked == 400_000.0


def test_ltifr_standard_base() -> None:
    result = intl.ltifr(1, 500_000)
    # 1 / 500000 * 1000000 = 2.0
    assert result.value == 2.0
    assert result.base_hours == intl.LTIFR_BASE_HOURS == 1_000_000


def test_severity_rate_standard_base() -> None:
    result = intl.severity_rate(10, 1_000_000)
    # 10 / 1000000 * 1000000 = 10.0
    assert result.value == 10.0
    assert result.base_hours == intl.SEVERITY_RATE_BASE_HOURS


def test_custom_hours_base_supported() -> None:
    # A company reporting per 100000 hours can pass its own base.
    result = intl.trir(3, 300_000, base_hours=100_000)
    # 3 / 300000 * 100000 = 1.0
    assert result.value == 1.0
    assert result.base_hours == 100_000


def test_generic_incident_rate_matches_wrappers() -> None:
    generic = intl.incident_rate(1, 500_000, base_hours=1_000_000)
    assert generic.value == intl.ltifr(1, 500_000).value


def test_rate_value_is_finite_and_rounded() -> None:
    result = intl.trir(1, 333_333)
    assert result.value is not None
    assert math.isfinite(result.value)
    # Rounded to two decimals: 1 / 333333 * 200000 = 0.600000... -> 0.6
    assert result.value == 0.6


# ── Edge cases: division by zero, negatives, bad base ─────────────────────────


def test_zero_hours_returns_defined_no_exposure_result() -> None:
    result = intl.trir(5, 0)
    assert result.value is None
    assert result.status == "no_exposure_data"
    # No NaN, no infinity, no exception.
    assert result.value is None


def test_negative_count_raises() -> None:
    with pytest.raises(ValueError, match="count must not be negative"):
        intl.ltifr(-1, 100_000)


def test_negative_hours_raises() -> None:
    with pytest.raises(ValueError, match="hours_worked must not be negative"):
        intl.trir(1, -100_000)


def test_non_positive_base_hours_raises() -> None:
    with pytest.raises(ValueError, match="base_hours must be positive"):
        intl.incident_rate(1, 100_000, base_hours=0)
    with pytest.raises(ValueError, match="base_hours must be positive"):
        intl.incident_rate(1, 100_000, base_hours=-200_000)


# ── Explainability: formula, explainer, components ────────────────────────────


def test_result_carries_formula_and_explainer() -> None:
    result = intl.trir(2, 400_000)
    assert "TRIR" in result.formula
    assert "recordable_incidents" in result.formula
    assert "200,000" in result.formula
    assert "Total Recordable Incident Rate" in result.explainer


def test_components_property() -> None:
    result = intl.ltifr(1, 500_000)
    assert result.components == {
        "count": 1.0,
        "hours_worked": 500_000.0,
        "base_hours": 1_000_000.0,
    }


def test_explain_returns_one_liners() -> None:
    for metric in ("trir", "ltifr", "severity_rate", "days_since_last_incident"):
        text = intl.explain(metric)
        assert text
        assert "\n" not in text  # one line
    assert intl.explain("unknown_metric") == ""


# ── Counts by severity and by type ────────────────────────────────────────────


def test_counts_by_severity_from_dicts_ordered() -> None:
    incidents = [
        {"severity": "critical"},
        {"severity": "minor"},
        {"severity": "minor"},
        {"severity": "major"},
    ]
    counts = intl.counts_by_severity(incidents)
    assert counts == {"minor": 2, "major": 1, "critical": 1}
    # Canonical ordering: minor before major before critical.
    assert list(counts.keys()) == ["minor", "major", "critical"]


def test_counts_by_type_from_objects() -> None:
    incidents = [
        SimpleNamespace(incident_type="injury"),
        SimpleNamespace(incident_type="fire"),
        SimpleNamespace(incident_type="injury"),
    ]
    counts = intl.counts_by_type(incidents)
    assert counts == {"injury": 2, "fire": 1}


def test_counts_empty_is_empty_dict() -> None:
    assert intl.counts_by_severity([]) == {}
    assert intl.counts_by_type([]) == {}


def test_counts_unknown_bucket_last() -> None:
    incidents = [
        {"severity": "minor"},
        {"severity": None},
        {"severity": ""},
        {"severity": "made_up"},
    ]
    counts = intl.counts_by_severity(incidents)
    assert counts["minor"] == 1
    assert counts["made_up"] == 1
    assert counts["unknown"] == 2
    # unknown is always the final key.
    assert list(counts.keys())[-1] == "unknown"


# ── Days since last incident ──────────────────────────────────────────────────


def test_days_since_last_incident_with_dates() -> None:
    assert intl.days_since_last_incident(date(2026, 1, 1), date(2026, 1, 11)) == 10


def test_days_since_last_incident_with_iso_strings() -> None:
    assert intl.days_since_last_incident("2026-01-01", "2026-02-01") == 31
    # Date part of an ISO datetime is accepted.
    assert intl.days_since_last_incident("2026-01-01T08:00:00+00:00", "2026-01-02") == 1


def test_days_since_last_incident_same_day_is_zero() -> None:
    assert intl.days_since_last_incident("2026-05-05", "2026-05-05") == 0


def test_days_since_last_incident_none_when_no_incident() -> None:
    assert intl.days_since_last_incident(None, "2026-05-05") is None


def test_days_since_last_incident_future_clamped_non_negative() -> None:
    # A last-incident date after the reference date never goes negative.
    assert intl.days_since_last_incident("2026-05-10", "2026-05-05") == 0


def test_days_since_last_incident_bad_date_raises() -> None:
    with pytest.raises(ValueError, match="ISO 8601"):
        intl.days_since_last_incident("9999-99-99", "2026-05-05")
    with pytest.raises(ValueError, match="ISO 8601"):
        intl.days_since_last_incident("2026-05-05", "not-a-date")


# ── Localization (en / de / ru, English fallback) ─────────────────────────────


def test_localize_incident_severity_all_languages() -> None:
    assert intl.localize_incident_severity("critical", "en") == "Critical"
    assert intl.localize_incident_severity("critical", "de") == "Kritisch"
    # Russian is non-empty and differs from the English label.
    ru = intl.localize_incident_severity("critical", "ru")
    assert ru and ru != "Critical"


def test_localize_incident_type_and_status() -> None:
    assert intl.localize_incident_type("near_miss", "en") == "Near miss"
    assert intl.localize_incident_type("near_miss", "de") == "Beinaheunfall"
    assert intl.localize_incident_status("corrective_action", "en") == "Corrective action"


def test_localize_observation_vocabulary() -> None:
    assert intl.localize_observation_type("unsafe_act", "de") == "Unsichere Handlung"
    assert intl.localize_observation_status("in_progress", "en") == "In progress"


def test_localize_unknown_language_falls_back_to_english() -> None:
    assert intl.localize_incident_severity("major", "fr") == "Major"
    assert intl.localize_incident_severity("major", "zz") == "Major"


def test_localize_locale_tag_is_normalized() -> None:
    assert intl.localize_incident_severity("minor", "de-DE") == "Gering"
    assert intl.localize_incident_severity("minor", "DE") == "Gering"


def test_localize_unknown_value_humanized_fallback() -> None:
    # A value outside the vocabulary never renders blank.
    assert intl.localize_incident_type("space_debris", "en") == "Space debris"
    assert intl.localize("made_up_category", "some_code", "de") == "Some code"


def test_supported_languages_present() -> None:
    assert intl.SUPPORTED_LANGUAGES == ("en", "de", "ru")


# ── Banned-character hygiene of the shipped helper source ─────────────────────


def test_intl_source_has_no_banned_characters() -> None:
    """The module source must use only plain hyphen, comma and period.

    The banned set (em-dash, smart quotes, zero-width joiners) is built from
    code points, never written as literals, so this test file stays clean too.
    """
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
        chr(0xFEFF),  # zero-width no-break space
    }
    source = (intl.__file__ or "").strip()
    assert source
    with open(source, encoding="utf-8") as handle:
        text = handle.read()
    present = sorted(hex(ord(c)) for c in banned if c in text)
    assert present == []
