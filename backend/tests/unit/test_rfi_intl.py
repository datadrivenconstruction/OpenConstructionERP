"""Unit tests for the RFI international / plain-language helpers.

These tests are database-free: every function under test in
:mod:`app.modules.rfi.intl` is pure, so the suite exercises the maths,
the localisation fallbacks and the edge-case guarantees directly.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.modules.rfi import intl

# ── Response time in whole days ───────────────────────────────────────────────


def test_response_time_days_whole_days() -> None:
    assert intl.response_time_days("2026-04-01", "2026-04-15") == 14


def test_response_time_days_same_day_is_zero() -> None:
    assert intl.response_time_days("2026-04-01", "2026-04-01") == 0


def test_response_time_days_accepts_date_objects() -> None:
    assert intl.response_time_days(date(2026, 4, 1), date(2026, 4, 4)) == 3


def test_response_time_days_accepts_full_timestamp() -> None:
    # Only the calendar date is kept from a full ISO 8601 timestamp.
    assert intl.response_time_days("2026-04-01T09:30:00+00:00", "2026-04-03T23:59:00+00:00") == 2


def test_response_time_days_response_before_request_raises() -> None:
    with pytest.raises(ValueError, match="cannot precede"):
        intl.response_time_days("2026-04-10", "2026-04-01")


def test_response_time_days_never_negative() -> None:
    # Whatever ordering is valid, the value is always non-negative.
    assert intl.response_time_days("2026-01-01", "2026-12-31") >= 0


def test_coerce_date_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        intl.coerce_date("definitely not a date")


# ── Average response time over a set ──────────────────────────────────────────


def test_average_response_time_days_basic() -> None:
    assert intl.average_response_time_days([2, 4, 6]) == 4.0


def test_average_response_time_days_rounds_to_one_decimal() -> None:
    assert intl.average_response_time_days([1, 2]) == 1.5
    assert intl.average_response_time_days([1, 1, 2]) == 1.3


def test_average_response_time_days_empty_returns_none() -> None:
    # Empty set: nothing to average, and the division-by-zero case is guarded.
    assert intl.average_response_time_days([]) is None


def test_average_response_time_days_negative_raises() -> None:
    with pytest.raises(ValueError, match="negative"):
        intl.average_response_time_days([3, -1])


def test_average_response_time_breakdown_exposes_components() -> None:
    breakdown = intl.average_response_time_breakdown([2, 4, 6])
    assert breakdown["count"] == 3
    assert breakdown["total_days"] == 12
    assert breakdown["average_days"] == 4.0
    assert isinstance(breakdown["method"], str) and breakdown["method"]


def test_average_response_time_breakdown_empty() -> None:
    breakdown = intl.average_response_time_breakdown([])
    assert breakdown["count"] == 0
    assert breakdown["total_days"] == 0
    assert breakdown["average_days"] is None


# ── Overdue flag with a parameterised SLA ─────────────────────────────────────


def test_is_overdue_explicit_due_date_past() -> None:
    assert intl.is_overdue("2026-04-10", "2026-04-11") is True


def test_is_overdue_due_today_is_not_overdue() -> None:
    assert intl.is_overdue("2026-04-10", "2026-04-10") is False


def test_is_overdue_before_due_date() -> None:
    assert intl.is_overdue("2026-04-10", "2026-04-01") is False


def test_is_overdue_from_sla_and_raised_date() -> None:
    # Raised 2026-04-01 with a 10-day SLA is due 2026-04-11; 2026-04-12 is late.
    assert intl.is_overdue(None, "2026-04-12", sla_days=10, raised_on="2026-04-01") is True
    assert intl.is_overdue(None, "2026-04-11", sla_days=10, raised_on="2026-04-01") is False


def test_is_overdue_sla_is_a_free_parameter() -> None:
    # The same raised date and reference date flip purely on the SLA length,
    # proving the SLA is not hardcoded anywhere.
    raised, reference = "2026-04-01", "2026-04-15"
    assert intl.is_overdue(None, reference, sla_days=10, raised_on=raised) is True
    assert intl.is_overdue(None, reference, sla_days=21, raised_on=raised) is False


def test_is_overdue_undetermined_returns_false() -> None:
    # No due date and no SLA basis: nothing to miss, never raises.
    assert intl.is_overdue(None, "2026-04-12") is False


def test_sla_due_date() -> None:
    assert intl.sla_due_date("2026-04-01", 14) == date(2026, 4, 15)


def test_sla_due_date_negative_raises() -> None:
    with pytest.raises(ValueError, match="negative"):
        intl.sla_due_date("2026-04-01", -1)


# ── Open vs answered rate ─────────────────────────────────────────────────────


def test_open_answered_rate_basic() -> None:
    assert intl.open_answered_rate(1, 3) == 0.75


def test_open_answered_rate_percent() -> None:
    assert intl.open_answered_rate(1, 3, as_percent=True) == 75.0


def test_open_answered_rate_zero_population_guarded() -> None:
    # Zero open and zero answered: guarded to 0.0, never NaN or a crash.
    assert intl.open_answered_rate(0, 0) == 0.0


def test_open_answered_rate_stays_in_range() -> None:
    rate = intl.open_answered_rate(0, 5)
    assert 0.0 <= rate <= 1.0
    percent = intl.open_answered_rate(0, 5, as_percent=True)
    assert 0.0 <= percent <= 100.0


def test_open_answered_rate_negative_raises() -> None:
    with pytest.raises(ValueError, match="negative"):
        intl.open_answered_rate(-1, 2)


def test_open_answered_breakdown_exposes_components() -> None:
    breakdown = intl.open_answered_breakdown(2, 6)
    assert breakdown["open_count"] == 2
    assert breakdown["answered_count"] == 6
    assert breakdown["total"] == 8
    assert breakdown["rate"] == 0.75
    assert breakdown["rate_percent"] == 75.0


# ── Counts by status ──────────────────────────────────────────────────────────


def test_counts_by_status_basic() -> None:
    result = intl.counts_by_status(["open", "open", "closed", "draft"])
    assert result == {"open": 2, "closed": 1, "draft": 1}


def test_counts_by_status_normalises_case_and_whitespace() -> None:
    result = intl.counts_by_status(["Open", " open ", "OPEN"])
    assert result == {"open": 3}


def test_counts_by_status_empty() -> None:
    assert intl.counts_by_status([]) == {}


def test_counts_by_status_blank_becomes_unknown() -> None:
    assert intl.counts_by_status(["", "  "]) == {"unknown": 2}


def test_counts_by_status_keeps_unknown_values() -> None:
    # An out-of-vocabulary status is counted, never silently dropped.
    assert intl.counts_by_status(["banana"]) == {"banana": 1}


def test_status_distribution_rolls_up() -> None:
    dist = intl.status_distribution(["draft", "open", "answered", "closed", "void"])
    assert dist["total"] == 5
    assert dist["open"] == 2  # draft + open
    assert dist["answered"] == 2  # answered + closed
    assert 0.0 <= dist["resolution_rate"] <= 1.0


def test_status_distribution_empty_resolution_rate_guarded() -> None:
    dist = intl.status_distribution([])
    assert dist["total"] == 0
    assert dist["resolution_rate"] == 0.0


# ── Localisation ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("status", "locale", "expected"),
    [
        ("open", "en", "Open"),
        ("open", "de", "Offen"),
        ("open", "ru", "Открыт"),
        ("answered", "en", "Answered"),
        ("answered", "de", "Beantwortet"),
        ("answered", "ru", "Отвечен"),
    ],
)
def test_localize_status(status: str, locale: str, expected: str) -> None:
    assert intl.localize_status(status, locale) == expected


def test_localize_status_unknown_locale_falls_back_to_english() -> None:
    assert intl.localize_status("closed", "zz") == "Closed"
    # Right-to-left languages stay English: the PDF cannot lay them out.
    assert intl.localize_status("closed", "ar") == "Closed"


def test_localize_status_new_languages_and_regions() -> None:
    assert intl.localize_status("answered", "fr") == "Répondu"
    assert intl.localize_status("open", "pt-BR") == "Aberto"
    assert intl.localize_status("void", "tr") == "Geçersiz"
    assert intl.localize_status("answered", "ja") == "回答済み"
    assert intl.localize_discipline("structural", "es_MX") == "Estructuras"


def test_localize_status_region_tagged_locale() -> None:
    assert intl.localize_status("open", "de-DE") == "Offen"
    assert intl.localize_status("open", "ru_RU") == "Открыт"


def test_localize_status_unknown_status_humanised() -> None:
    assert intl.localize_status("in_review") == "In review"


def test_every_status_localises_in_every_locale() -> None:
    for status in intl.RFI_STATUSES:
        for locale in sorted(intl._SUPPORTED_LOCALES):
            label = intl.localize_status(status, locale)
            assert label and label.strip()


@pytest.mark.parametrize(
    ("discipline", "locale", "expected"),
    [
        ("structural", "en", "Structural"),
        ("structural", "de", "Tragwerk"),
        ("structural", "ru", "Конструктивный"),
        ("mep", "en", "MEP"),
    ],
)
def test_localize_discipline(discipline: str, locale: str, expected: str) -> None:
    assert intl.localize_discipline(discipline, locale) == expected


@pytest.mark.parametrize(
    ("stored", "locale", "expected"),
    [
        ("mechanical", "tr", "Mekanik"),
        ("Mechanical", "tr", "Mekanik"),
        ("hvac", "tr", "İklimlendirme"),
        ("Fire protection", "tr", "Yangın tesisatı"),
        ("low_current", "tr", "Zayıf akım"),
        ("bms", "tr", "Bina otomasyonu"),
        ("civil", "tr", "İnşaat"),
        ("hvac", "en", "HVAC"),
        ("mechanical", "de", "Mechanical"),
    ],
)
def test_building_services_trades_have_a_word(stored: str, locale: str, expected: str) -> None:
    """The column is free text: a trade the picker does not offer still prints in the form's language."""
    assert intl.localize_discipline(stored, locale) == expected


def test_the_turkish_trade_words_are_the_submittal_register_s() -> None:
    """One project prints one vocabulary: an RFI and a submittal name a discipline with the same word."""
    from app.modules.submittals.tracking import DISCIPLINES

    for item in DISCIPLINES:
        assert intl.localize_discipline(item.code, "tr") == item.labels["tr"], item.code


def test_localize_discipline_unknown_falls_back() -> None:
    assert intl.localize_discipline("acoustic") == "Acoustic"


def test_every_discipline_localises_in_every_locale() -> None:
    for discipline in intl.RFI_DISCIPLINES:
        for locale in sorted(intl._SUPPORTED_LOCALES):
            label = intl.localize_discipline(discipline, locale)
            assert label and label.strip()


# ── Explainers ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("topic", ["rfi", "average_response_time", "overdue_rfi", "ball_in_court"])
@pytest.mark.parametrize("locale", ["en", "de", "ru"])
def test_explain_returns_text(topic: str, locale: str) -> None:
    text = intl.explain(topic, locale)
    assert text and len(text) > 20


def test_explain_unknown_topic_returns_empty() -> None:
    assert intl.explain("nope") == ""


def test_explain_unknown_locale_falls_back_to_english() -> None:
    assert intl.explain("rfi", "zz") == intl.explain("rfi", "en")


# ── Locale parity ─────────────────────────────────────────────────────────────


def test_status_label_parity_across_locales() -> None:
    en_keys = set(intl._STATUS_LABELS["en"])
    assert en_keys == set(intl.RFI_STATUSES)
    for locale, table in intl._STATUS_LABELS.items():
        assert set(table) == en_keys, locale


def test_discipline_label_parity_across_locales() -> None:
    en_keys = set(intl._DISCIPLINE_LABELS["en"])
    assert en_keys == set(intl.RFI_DISCIPLINES)
    assert set(intl._DISCIPLINE_LABELS) == set(intl._STATUS_LABELS)
    for locale, table in intl._DISCIPLINE_LABELS.items():
        assert set(table) == en_keys, locale


def test_explainer_parity_across_locales() -> None:
    for entry in intl._EXPLAINERS.values():
        assert set(entry) == {"en", "de", "ru"}


# ── Source hygiene: no banned punctuation characters ──────────────────────────


def test_intl_source_has_no_banned_characters() -> None:
    """The module source must use only plain hyphen / comma / period punctuation.

    The banned set (em dash, en dash, smart quotes, zero-width and word-joiner
    code points) is built from ``chr()`` so this test file never contains a
    banned character literal itself.
    """
    banned = {
        chr(0x2013),  # en dash
        chr(0x2014),  # em dash
        chr(0x2018),  # left single quotation mark
        chr(0x2019),  # right single quotation mark
        chr(0x201C),  # left double quotation mark
        chr(0x201D),  # right double quotation mark
        chr(0x200B),  # zero-width space
        chr(0x200C),  # zero-width non-joiner
        chr(0x200D),  # zero-width joiner
        chr(0x2060),  # word joiner
        chr(0xFEFF),  # zero-width no-break space / BOM
    }
    source_path = Path(intl.__file__)
    source = source_path.read_text(encoding="utf-8")
    found = {hex(ord(ch)) for ch in source if ch in banned}
    assert not found, f"banned characters present in intl.py: {sorted(found)}"


def test_this_test_source_has_no_banned_characters() -> None:
    """The test file itself must also stay free of banned punctuation."""
    banned = {
        chr(0x2013),
        chr(0x2014),
        chr(0x2018),
        chr(0x2019),
        chr(0x201C),
        chr(0x201D),
        chr(0x200B),
        chr(0x200C),
        chr(0x200D),
        chr(0x2060),
        chr(0xFEFF),
    }
    source = Path(__file__).read_text(encoding="utf-8")
    found = {hex(ord(ch)) for ch in source if ch in banned}
    assert not found, f"banned characters present in test file: {sorted(found)}"
