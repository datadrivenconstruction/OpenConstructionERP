"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the subcontractors international reporting helpers.

Scope (pure, database-free):
    - on-time delivery rate and quality pass rate with zero / empty / negative
      guards, kept inside [0, 1] and [0, 100]
    - weighted performance score from explicit component weights, with a fully
      itemised, explainable derivation
    - spend grouped strictly per currency (never blended), Decimal-exact
    - counts by status
    - status / compliance localization (en / de / ru) with English fallback
    - ISO 8601 date rendering
    - a source hygiene guard that no banned typographic characters leak in

Every helper under test lives in ``app.modules.subcontractors.intl`` and touches
no database, no framework and no I/O.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.subcontractors.intl import (
    DEFAULT_PERFORMANCE_WEIGHTS,
    RateResult,
    counts_by_status,
    format_iso_date,
    localize_compliance,
    localize_status,
    on_time_delivery_rate,
    performance_summary,
    quality_pass_rate,
    spend_by_currency,
    weighted_performance_score,
)

# ── on-time delivery rate ───────────────────────────────────────────────────


def test_on_time_delivery_rate_basic() -> None:
    res = on_time_delivery_rate(8, 10)
    assert isinstance(res, RateResult)
    assert res.defined is True
    assert res.fraction == Decimal("0.8000")
    assert res.percent == Decimal("80.00")
    assert Decimal("0") <= res.fraction <= Decimal("1")
    assert Decimal("0") <= res.percent <= Decimal("100")
    assert "8 of 10" in res.explanation


def test_on_time_delivery_rate_zero_jobs_is_defined_false_not_crash() -> None:
    res = on_time_delivery_rate(0, 0)
    assert res.defined is False
    assert res.fraction == Decimal("0")
    assert res.percent == Decimal("0")
    # A well-defined value, never NaN / inf.
    assert res.fraction.is_finite()


def test_on_time_delivery_rate_perfect() -> None:
    res = on_time_delivery_rate(5, 5)
    assert res.fraction == Decimal("1.0000")
    assert res.percent == Decimal("100.00")


def test_on_time_delivery_rate_rounds_repeating() -> None:
    res = on_time_delivery_rate(1, 3)
    assert res.fraction == Decimal("0.3333")
    assert res.percent == Decimal("33.33")


def test_on_time_delivery_rate_negative_raises() -> None:
    with pytest.raises(ValueError, match="negative"):
        on_time_delivery_rate(-1, 10)


def test_on_time_delivery_rate_over_total_raises() -> None:
    with pytest.raises(ValueError, match="cannot exceed"):
        on_time_delivery_rate(11, 10)


def test_on_time_delivery_rate_bool_rejected() -> None:
    with pytest.raises(ValueError, match="integer"):
        on_time_delivery_rate(True, 10)


def test_on_time_delivery_rate_locale_de() -> None:
    res = on_time_delivery_rate(8, 10, locale="de")
    assert "puenktlich" in res.explanation


# ── quality pass rate ───────────────────────────────────────────────────────


def test_quality_pass_rate_basic() -> None:
    res = quality_pass_rate(9, 12)
    assert res.fraction == Decimal("0.7500")
    assert res.percent == Decimal("75.00")


def test_quality_pass_rate_empty_is_defined_false() -> None:
    res = quality_pass_rate(0, 0)
    assert res.defined is False
    assert res.percent == Decimal("0")


def test_quality_pass_rate_over_total_raises() -> None:
    with pytest.raises(ValueError, match="cannot exceed"):
        quality_pass_rate(5, 4)


def test_quality_pass_rate_locale_ru_fallback_for_unknown() -> None:
    # Unknown locale falls back to English text.
    res = quality_pass_rate(1, 2, locale="zz")
    assert "inspections passed" in res.explanation


# ── weighted performance score ──────────────────────────────────────────────


def test_weighted_performance_score_default_weights() -> None:
    # Same numbers as the module's stored rating example:
    # 80*.30 + 90*.30 + 70*.20 + 60*.20 = 77.
    res = weighted_performance_score(
        {"quality": Decimal("80"), "hse": Decimal("90"), "schedule": Decimal("70"), "cost": Decimal("60")},
    )
    assert res.score == Decimal("77.00")
    assert Decimal("0") <= res.score <= Decimal("100")
    # Weights renormalise to 1 over the four supplied components.
    assert sum(c.weight for c in res.components) == Decimal("1.000000")
    # Contributions sum to the score.
    assert sum(c.contribution for c in res.components) == Decimal("77.00")


def test_weighted_performance_score_partial_components_renormalise() -> None:
    # Only two components supplied; equal 0.30 weights renormalise to 0.5 each.
    res = weighted_performance_score(
        {"quality": Decimal("100"), "hse": Decimal("0")},
    )
    assert res.score == Decimal("50.00")


def test_weighted_performance_score_clamps_out_of_range_rates() -> None:
    res = weighted_performance_score(
        {"quality": Decimal("140")},
        {"quality": Decimal("1")},
    )
    assert res.score == Decimal("100.00")
    res_low = weighted_performance_score(
        {"quality": Decimal("-40")},
        {"quality": Decimal("1")},
    )
    assert res_low.score == Decimal("0.00")


def test_weighted_performance_score_custom_weights() -> None:
    res = weighted_performance_score(
        {"a": Decimal("100"), "b": Decimal("0")},
        {"a": Decimal("3"), "b": Decimal("1")},
    )
    # 100*3/4 + 0 = 75.
    assert res.score == Decimal("75.00")


def test_weighted_performance_score_empty_raises() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        weighted_performance_score({})


def test_weighted_performance_score_missing_weight_raises() -> None:
    with pytest.raises(ValueError, match="no weight supplied"):
        weighted_performance_score({"unknown_component": Decimal("50")})


def test_weighted_performance_score_zero_total_weight_raises() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        weighted_performance_score({"quality": Decimal("50")}, {"quality": Decimal("0")})


def test_weighted_performance_score_negative_weight_raises() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        weighted_performance_score({"quality": Decimal("50")}, {"quality": Decimal("-1")})


def test_default_weights_sum_to_one() -> None:
    assert sum(DEFAULT_PERFORMANCE_WEIGHTS.values()) == Decimal("1.00")


# ── spend by currency (never blended) ───────────────────────────────────────


def test_spend_by_currency_groups_per_code() -> None:
    res = spend_by_currency(
        [
            (Decimal("100.10"), "EUR"),
            (Decimal("50.05"), "EUR"),
            (Decimal("200"), "USD"),
        ],
    )
    assert res.by_currency == {"EUR": Decimal("150.15"), "USD": Decimal("200.00")}


def test_spend_by_currency_never_blends_currencies() -> None:
    res = spend_by_currency([(Decimal("100"), "EUR"), (Decimal("100"), "GBP")])
    # Two independent totals, not one blended sum.
    assert set(res.by_currency) == {"EUR", "GBP"}
    assert res.by_currency["EUR"] == Decimal("100.00")
    assert res.by_currency["GBP"] == Decimal("100.00")


def test_spend_by_currency_decimal_exact() -> None:
    # 0.1 + 0.2 must be exactly 0.30, not 0.30000000000000004.
    res = spend_by_currency([(Decimal("0.1"), "eur"), (Decimal("0.2"), "eur")])
    assert res.by_currency["EUR"] == Decimal("0.30")


def test_spend_by_currency_normalises_code_case() -> None:
    res = spend_by_currency([(Decimal("1"), "eur"), (Decimal("2"), "Eur")])
    assert res.by_currency == {"EUR": Decimal("3.00")}


def test_spend_by_currency_accepts_mappings_and_objects() -> None:
    res = spend_by_currency(
        [
            {"amount": Decimal("10"), "currency": "EUR"},
            SimpleNamespace(amount=Decimal("5"), currency="EUR"),
        ],
    )
    assert res.by_currency == {"EUR": Decimal("15.00")}


def test_spend_by_currency_empty_is_clean() -> None:
    res = spend_by_currency([])
    assert res.by_currency == {}
    assert "No spend" in res.explanation


def test_spend_by_currency_invalid_code_raises() -> None:
    with pytest.raises(ValueError, match="currency"):
        spend_by_currency([(Decimal("10"), "EURO")])


def test_spend_by_currency_blank_code_raises() -> None:
    with pytest.raises(ValueError, match="currency"):
        spend_by_currency([(Decimal("10"), "")])


def test_spend_by_currency_non_numeric_amount_raises() -> None:
    with pytest.raises(ValueError, match="number"):
        spend_by_currency([("not-a-number", "EUR")])


# ── counts by status ────────────────────────────────────────────────────────


def test_counts_by_status_objects() -> None:
    items = [
        SimpleNamespace(status="submitted"),
        SimpleNamespace(status="submitted"),
        SimpleNamespace(status="paid"),
    ]
    assert counts_by_status(items) == {"submitted": 2, "paid": 1}


def test_counts_by_status_mappings_and_custom_attr() -> None:
    items = [{"prequalification_status": "approved"}, {"prequalification_status": "rejected"}]
    counts = counts_by_status(items, attribute="prequalification_status")
    assert counts == {"approved": 1, "rejected": 1}


def test_counts_by_status_missing_grouped_unknown() -> None:
    items = [SimpleNamespace(status=None), SimpleNamespace(status="")]
    assert counts_by_status(items) == {"unknown": 2}


def test_counts_by_status_empty() -> None:
    assert counts_by_status([]) == {}


def test_counts_by_status_all_non_negative() -> None:
    items = [SimpleNamespace(status="paid") for _ in range(4)]
    counts = counts_by_status(items)
    assert all(v >= 0 for v in counts.values())


# ── localization ────────────────────────────────────────────────────────────


def test_localize_status_known_locales() -> None:
    assert localize_status("finance_approved", "en") == "Finance approved"
    assert localize_status("finance_approved", "de") == "Von Finanzen freigegeben"
    assert localize_status("finance_approved", "ru") == "Odobreno finansami"


def test_localize_status_english_fallback_for_unknown_locale() -> None:
    assert localize_status("approved", "fr") == "Approved"


def test_localize_status_unknown_term_plain_language() -> None:
    # Unknown canonical term degrades to plain language, not a raw key.
    assert localize_status("brand_new_state") == "Brand new state"


def test_localize_compliance_words() -> None:
    assert localize_compliance("expired", "de") == "Abgelaufen"
    assert localize_compliance("insurance", "ru") == "Strahovanie"
    assert localize_compliance("valid", "en") == "Valid"


def test_localize_compliance_fallback() -> None:
    # de entry exists; a locale with no entry uses English.
    assert localize_compliance("compliant", "zz") == "Compliant"


# ── ISO 8601 dates ──────────────────────────────────────────────────────────


def test_format_iso_date_from_date() -> None:
    assert format_iso_date(date(2026, 7, 5)) == "2026-07-05"


def test_format_iso_date_from_datetime_drops_time() -> None:
    assert format_iso_date(datetime(2026, 7, 5, 13, 30, 15)) == "2026-07-05"


def test_format_iso_date_none() -> None:
    assert format_iso_date(None) is None


def test_format_iso_date_invalid_raises() -> None:
    with pytest.raises(ValueError, match="not a date"):
        format_iso_date("2026-07-05")


# ── composed summary ────────────────────────────────────────────────────────


def test_performance_summary_composes_all_figures() -> None:
    summary = performance_summary(
        on_time_jobs=9,
        total_jobs=10,
        passed_inspections=8,
        total_inspections=10,
        spend_entries=[(Decimal("1000"), "EUR")],
        status_items=[SimpleNamespace(status="paid"), SimpleNamespace(status="paid")],
        locale="en",
    )
    assert summary.on_time_delivery.percent == Decimal("90.00")
    assert summary.quality_pass.percent == Decimal("80.00")
    assert Decimal("0") <= summary.performance_score.score <= Decimal("100")
    assert summary.spend.by_currency == {"EUR": Decimal("1000.00")}
    assert summary.status_counts == {"paid": 2}
    assert "Performance score" in summary.narrative


def test_performance_summary_handles_no_data_without_crash() -> None:
    summary = performance_summary(
        on_time_jobs=0,
        total_jobs=0,
        passed_inspections=0,
        total_inspections=0,
    )
    assert summary.on_time_delivery.defined is False
    assert summary.quality_pass.defined is False
    # Undefined rates count as 0 in the composed score, no NaN / inf.
    assert summary.performance_score.score == Decimal("0.00")
    assert summary.spend.by_currency == {}


# ── source hygiene: no banned typographic characters ────────────────────────


def test_intl_source_has_no_banned_characters() -> None:
    """The module source must use plain hyphen / comma / period only.

    Banned code points (em dash, en dash, curly quotes, zero-width joiners and
    the byte-order mark) are assembled from ``chr()`` so this test file itself
    never contains a literal banned character.
    """
    import app.modules.subcontractors.intl as intl_module

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
        chr(0xFEFF),  # byte-order mark
    }
    with open(intl_module.__file__, encoding="utf-8") as handle:
        source = handle.read()
    present = {hex(ord(ch)) for ch in banned if ch in source}
    assert present == set(), f"banned characters found in intl.py: {present}"
