"""Unit tests for the framework-free payroll intl helpers.

Pure Decimal / date / string math, no database and no FastAPI, so this file
runs on its own without any fixtures. Covers the international guarantees:
Decimal-exact money, no currency blending, ISO 8601 dates, parameterised
overtime and deduction rules with neutral defaults, zero-division guards,
negative-input rejection, and localised pay-component / status labels with an
English fallback.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.payroll import intl

# ── Regular vs overtime split (parameterised threshold) ───────────────────────


def test_split_no_threshold_is_all_regular() -> None:
    # With no overtime rule in force, every hour is regular.
    regular, overtime = intl.split_regular_overtime("42")
    assert regular == Decimal("42")
    assert overtime == Decimal("0")


def test_split_below_threshold_is_all_regular() -> None:
    regular, overtime = intl.split_regular_overtime("6", "8")
    assert regular == Decimal("6")
    assert overtime == Decimal("0")


def test_split_above_threshold_splits() -> None:
    # 10 hours against an 8-hour daily threshold: 8 regular, 2 overtime.
    regular, overtime = intl.split_regular_overtime("10", "8")
    assert regular == Decimal("8")
    assert overtime == Decimal("2")


def test_split_always_sums_back_to_total() -> None:
    regular, overtime = intl.split_regular_overtime("13.5", "8")
    assert regular + overtime == Decimal("13.5")


def test_split_rejects_negative_hours() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        intl.split_regular_overtime("-1", "8")


def test_split_rejects_negative_threshold() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        intl.split_regular_overtime("10", "-8")


def test_split_rejects_non_finite() -> None:
    with pytest.raises(ValueError, match="finite"):
        intl.split_regular_overtime("Infinity", "8")


# ── Pay math (Decimal-exact) ──────────────────────────────────────────────────


def test_regular_pay_hours_times_rate() -> None:
    assert intl.regular_pay("8", "25.50") == Decimal("204.00")


def test_regular_pay_is_decimal_exact() -> None:
    # 0.1 * 3 must be exactly 0.30, never float drift.
    result = intl.regular_pay("3", "0.10")
    assert result == Decimal("0.30")
    assert isinstance(result, Decimal)


def test_overtime_pay_default_multiplier_is_one_and_a_half() -> None:
    # 2 overtime hours at 20/h, default 1.5x = 60.00.
    assert intl.overtime_pay("2", "20") == Decimal("60.00")


def test_overtime_pay_explicit_multiplier() -> None:
    # A different agreement: double time.
    assert intl.overtime_pay("2", "20", "2") == Decimal("80.00")


def test_overtime_pay_zero_hours_is_zero() -> None:
    assert intl.overtime_pay("0", "20") == Decimal("0.00")


def test_gross_pay_regular_plus_overtime() -> None:
    # 8h regular at 20 = 160; 2h overtime at 20 * 1.5 = 60; gross = 220.
    assert intl.gross_pay("8", "2", "20") == Decimal("220.00")


def test_gross_pay_no_overtime() -> None:
    assert intl.gross_pay("8", "0", "20") == Decimal("160.00")


def test_gross_pay_rejects_negative_rate() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        intl.gross_pay("8", "0", "-20")


# ── Deductions and net pay ────────────────────────────────────────────────────


def test_total_deductions_sums() -> None:
    assert intl.total_deductions(["10.00", "5.50", "4.50"]) == Decimal("20.00")


def test_total_deductions_empty_is_zero() -> None:
    # An empty set must not raise; it is a well-defined zero.
    assert intl.total_deductions([]) == Decimal("0.00")


def test_total_deductions_rejects_negative() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        intl.total_deductions(["10", "-5"])


def test_percentage_deduction_applies_rate() -> None:
    # 15% of 200.00 = 30.00. The rate is the caller's explicit input.
    assert intl.percentage_deduction("200.00", "15") == Decimal("30.00")


def test_percentage_deduction_clamps_above_hundred() -> None:
    # A percent over 100 can never withhold more than the base.
    assert intl.percentage_deduction("200.00", "150") == Decimal("200.00")


def test_percentage_deduction_zero_rate_is_zero() -> None:
    assert intl.percentage_deduction("200.00", "0") == Decimal("0.00")


def test_net_pay_gross_minus_deductions() -> None:
    assert intl.net_pay("220.00", ["20.00", "30.00"]) == Decimal("170.00")


def test_net_pay_no_deductions_equals_gross() -> None:
    assert intl.net_pay("220.00") == Decimal("220.00")


def test_net_pay_floored_at_zero() -> None:
    # Over-deduction is clamped, never a negative payslip.
    assert intl.net_pay("100.00", ["80.00", "50.00"]) == Decimal("0.00")


def test_net_pay_rejects_negative_gross() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        intl.net_pay("-100.00", [])


# ── Effective hourly rate (zero-hours guard) ──────────────────────────────────


def test_effective_hourly_rate_divides() -> None:
    # 220.00 gross over 10 hours = 22.00 per hour.
    assert intl.effective_hourly_rate("220.00", "10") == Decimal("22.0000")


def test_effective_hourly_rate_zero_hours_guard() -> None:
    # Zero hours must not divide by zero; the rate is a well-defined zero.
    assert intl.effective_hourly_rate("220.00", "0") == Decimal("0.0000")


def test_effective_hourly_rate_rounds_half_up() -> None:
    # 100 / 3 = 33.333... -> 33.3333 at four decimals.
    assert intl.effective_hourly_rate("100.00", "3") == Decimal("33.3333")


def test_effective_hourly_rate_rejects_negative() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        intl.effective_hourly_rate("220.00", "-10")


# ── Payslip breakdown (explainable components) ────────────────────────────────


def test_payslip_breakdown_with_overtime_and_deductions() -> None:
    report = intl.payslip_breakdown(
        "10",
        "20",
        "USD",
        overtime_threshold="8",
        deductions=["30.00", "10.00"],
    )
    assert report["total_hours"] == "10"
    assert report["regular_hours"] == "8"
    assert report["overtime_hours"] == "2"
    assert report["overtime_threshold"] == "8"
    assert report["rate"] == "20.0000"
    assert report["overtime_multiplier"] == "1.5"
    assert report["currency"] == "USD"
    assert report["regular_pay"] == "160.00"
    assert report["overtime_pay"] == "60.00"
    assert report["gross_pay"] == "220.00"
    assert report["total_deductions"] == "40.00"
    assert report["net_pay"] == "180.00"
    assert report["effective_hourly_rate"] == "22.0000"


def test_payslip_breakdown_no_threshold_no_overtime() -> None:
    report = intl.payslip_breakdown("8", "20")
    assert report["regular_hours"] == "8"
    assert report["overtime_hours"] == "0"
    assert report["overtime_threshold"] == ""
    assert report["gross_pay"] == "160.00"
    assert report["net_pay"] == "160.00"


def test_payslip_breakdown_currency_not_guessed() -> None:
    report = intl.payslip_breakdown("8", "20", None)
    # No currency stated stays empty; we never default to EUR/USD.
    assert report["currency"] == ""


def test_payslip_breakdown_normalizes_currency() -> None:
    report = intl.payslip_breakdown("8", "20", " eur ")
    assert report["currency"] == "EUR"


def test_payslip_breakdown_zero_hours_effective_rate_guard() -> None:
    report = intl.payslip_breakdown("0", "20", "EUR")
    assert report["gross_pay"] == "0.00"
    assert report["effective_hourly_rate"] == "0.0000"


# ── Currency safety ───────────────────────────────────────────────────────────


def test_ensure_single_currency_agrees() -> None:
    assert intl.ensure_single_currency(["USD", "usd", None, ""]) == "USD"


def test_ensure_single_currency_empty_is_blank() -> None:
    assert intl.ensure_single_currency([None, "", "  "]) == ""


def test_ensure_single_currency_rejects_mix() -> None:
    with pytest.raises(ValueError, match="different currencies"):
        intl.ensure_single_currency(["USD", "EUR"])


def test_normalize_currency_never_guesses() -> None:
    assert intl.normalize_currency(None) == ""
    assert intl.normalize_currency("  gbp ") == "GBP"


# ── ISO 8601 dates ────────────────────────────────────────────────────────────


def test_parse_iso_date_accepts_string() -> None:
    assert intl.parse_iso_date("2026-07-05") == date(2026, 7, 5)


def test_parse_iso_date_accepts_date_object() -> None:
    assert intl.parse_iso_date(date(2026, 7, 5)) == date(2026, 7, 5)


def test_parse_iso_date_rejects_bad_value() -> None:
    with pytest.raises(ValueError, match="ISO 8601"):
        intl.parse_iso_date("05/07/2026")


def test_parse_iso_date_rejects_none() -> None:
    with pytest.raises(ValueError, match="required"):
        intl.parse_iso_date(None)


# ── Localised status / component labels (en/de/ru + English fallback) ─────────


def test_describe_batch_status_english() -> None:
    assert intl.describe_batch_status("posted") == "Posted to ledger"


def test_describe_batch_status_german() -> None:
    assert intl.describe_batch_status("approved", "de") == "Genehmigt"


def test_describe_batch_status_russian() -> None:
    assert intl.describe_batch_status("draft", "ru") == "Черновик"


def test_describe_deduction_type_localized() -> None:
    assert intl.describe_deduction_type("pension", "de") == "Rente"
    assert intl.describe_deduction_type("pension", "ru") == "Пенсия"
    assert intl.describe_deduction_type("pension") == "Pension"


def test_describe_pay_component_localized() -> None:
    assert intl.describe_pay_component("net_pay", "de") == "Nettolohn"
    assert intl.describe_pay_component("gross_pay", "ru") == "Начислено (брутто)"
    assert intl.describe_pay_component("gross_pay") == "Gross pay"


def test_unknown_locale_falls_back_to_english() -> None:
    # A locale we do not carry gets the English label, never a raw code.
    assert intl.describe_batch_status("approved", "zz") == "Approved"


def test_locale_region_suffix_is_stripped() -> None:
    assert intl.describe_batch_status("approved", "de-CH") == "Genehmigt"


def test_unknown_code_is_humanised_not_blank() -> None:
    # A status a newer workflow introduced still renders readably.
    assert intl.describe_batch_status("in_review") == "In review"


def test_missing_code_is_localized_unknown() -> None:
    assert intl.describe_batch_status(None) == "Unknown"
    assert intl.describe_batch_status(None, "de") == "Unbekannt"
    assert intl.describe_batch_status("", "ru") == "Неизвестно"


# ── Glossary ──────────────────────────────────────────────────────────────────


def test_explain_gross_pay_states_formula() -> None:
    text = intl.explain("gross_pay")
    assert "regular pay" in text.lower()
    assert "overtime pay" in text.lower()


def test_explain_effective_hourly_rate() -> None:
    text = intl.explain("effective_hourly_rate")
    assert "divided by" in text.lower()


def test_explain_net_pay_mentions_floor() -> None:
    text = intl.explain("net_pay")
    assert "zero" in text.lower()


def test_explain_unknown_concept_raises() -> None:
    with pytest.raises(ValueError, match="Unknown payroll concept"):
        intl.explain("nope")


# ── International text safety (no em-dash / smart quotes / zero-width) ─────────


def _banned_characters() -> set[str]:
    """Build the banned-character set from code points, never as literals.

    Covers the punctuation the house style forbids in any shipped text: the
    em-dash and en-dash, curly single and double quotes, and the zero-width
    joiner / non-joiner / word-joiner used for invisible watermarks.
    """
    code_points = (
        0x2014,  # em dash
        0x2013,  # en dash
        0x2018,  # left single curly quote
        0x2019,  # right single curly quote
        0x201C,  # left double curly quote
        0x201D,  # right double curly quote
        0x200B,  # zero-width space
        0x200C,  # zero-width non-joiner
        0x200D,  # zero-width joiner
        0x2060,  # word joiner
    )
    return {chr(cp) for cp in code_points}


def test_glossary_and_labels_have_no_banned_characters() -> None:
    banned = _banned_characters()
    texts: list[str] = list(intl.CONCEPTS.values())
    for table in (
        intl._BATCH_STATUS_LABELS,
        intl._DEDUCTION_TYPE_LABELS,
        intl._PAY_COMPONENT_LABELS,
    ):
        for per_lang in table.values():
            texts.extend(per_lang.values())
    texts.extend(intl._UNKNOWN_LABELS.values())

    for text in texts:
        offenders = banned.intersection(text)
        assert not offenders, f"banned character(s) {[hex(ord(c)) for c in offenders]} in {text!r}"
