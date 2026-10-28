"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the CRM international helpers (``app.modules.crm.intl``).

Pure, DB-free. Covers Decimal-exact money, ``0..1`` probability, per-currency
grouping (never blended), win-rate zero guard, ISO 8601 date parsing,
localized stage/status words with English fallback, one-line explainers, and
the explainable report helpers.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.crm.intl import (
    coerce_money,
    coerce_probability,
    explain,
    localize_stage,
    localize_status,
    parse_iso_date,
    pipeline_value_by_currency,
    pipeline_value_by_stage,
    quantize_money,
    weighted_value,
    weighted_value_report,
    win_rate,
    win_rate_report,
)

# ── weighted_value ─────────────────────────────────────────────────────────


def test_weighted_value_basic() -> None:
    assert weighted_value(1000, Decimal("0.5")) == Decimal("500.0")
    assert weighted_value(Decimal("1234.56"), Decimal("0.25")) == Decimal("308.6400")


def test_weighted_value_is_decimal_exact() -> None:
    # 0.1 as a float would drift in binary; the helper stays exact.
    assert weighted_value(Decimal("0.10"), 0.1) == Decimal("0.010")


def test_weighted_value_zero_probability() -> None:
    assert weighted_value(99999, 0) == Decimal("0")


def test_weighted_value_clamps_probability_range() -> None:
    assert weighted_value(1000, Decimal("-0.5")) == Decimal("0")
    assert weighted_value(1000, Decimal("2.5")) == Decimal("1000")


def test_weighted_value_rejects_negative_value() -> None:
    with pytest.raises(ValueError, match="zero or positive"):
        weighted_value(-1, Decimal("0.5"))


def test_weighted_value_rejects_non_finite() -> None:
    with pytest.raises(ValueError, match="finite"):
        weighted_value(float("inf"), Decimal("0.5"))
    with pytest.raises(ValueError, match="finite"):
        weighted_value(1000, float("nan"))


# ── coerce_money / coerce_probability ──────────────────────────────────────


def test_coerce_money_none_is_zero() -> None:
    assert coerce_money(None) == Decimal(0)


def test_coerce_money_float_no_binary_drift() -> None:
    assert coerce_money(0.1) == Decimal("0.1")


def test_coerce_money_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="not a valid number"):
        coerce_money("abc")


def test_coerce_probability_clamps() -> None:
    assert coerce_probability(-3) == Decimal(0)
    assert coerce_probability(5) == Decimal(1)
    assert coerce_probability(Decimal("0.42")) == Decimal("0.42")


def test_coerce_probability_rejects_non_finite() -> None:
    with pytest.raises(ValueError, match="finite"):
        coerce_probability(float("inf"))


# ── quantize_money (currency minor units) ──────────────────────────────────


def test_quantize_money_default_two_places() -> None:
    assert quantize_money(Decimal("109.9989")) == Decimal("110.00")


def test_quantize_money_zero_minor_units() -> None:
    # JPY-style currency with no fractional part.
    assert quantize_money(Decimal("1234.56"), minor_units=0) == Decimal("1235")


def test_quantize_money_three_minor_units() -> None:
    # BHD-style currency with three fractional digits.
    assert quantize_money(Decimal("1.23456"), minor_units=3) == Decimal("1.235")


def test_quantize_money_rejects_negative_minor_units() -> None:
    with pytest.raises(ValueError, match="zero or positive"):
        quantize_money(Decimal("1"), minor_units=-1)


# ── win_rate (zero guard) ──────────────────────────────────────────────────


def test_win_rate_zero_guard() -> None:
    assert win_rate(0, 0) == Decimal(0)


def test_win_rate_basic() -> None:
    assert win_rate(3, 1) == Decimal("0.75")


def test_win_rate_all_won() -> None:
    assert win_rate(5, 0) == Decimal(1)


def test_win_rate_rejects_negative() -> None:
    with pytest.raises(ValueError, match="zero or positive"):
        win_rate(-1, 2)


# ── pipeline value grouping (never blend currencies) ───────────────────────


def test_pipeline_value_by_currency_keeps_currencies_separate() -> None:
    deals = [
        {"value": Decimal("1000"), "currency": "EUR"},
        {"value": Decimal("500"), "currency": "eur"},
        {"value": Decimal("2000"), "currency": "USD"},
        {"value": Decimal("300"), "currency": ""},
    ]
    totals = pipeline_value_by_currency(deals)
    assert totals == {"EUR": Decimal("1500"), "USD": Decimal("2000"), "": Decimal("300")}


def test_pipeline_value_by_currency_empty() -> None:
    assert pipeline_value_by_currency([]) == {}


def test_pipeline_value_by_stage_nested_by_currency() -> None:
    deals = [
        SimpleNamespace(stage="proposal", value=Decimal("1000"), currency="EUR"),
        SimpleNamespace(stage="proposal", value=Decimal("2000"), currency="USD"),
        SimpleNamespace(stage="negotiation", value=Decimal("500"), currency="EUR"),
    ]
    by_stage = pipeline_value_by_stage(deals)
    assert by_stage["proposal"] == {"EUR": Decimal("1000"), "USD": Decimal("2000")}
    assert by_stage["negotiation"] == {"EUR": Decimal("500")}


def test_pipeline_value_by_stage_rejects_negative_value() -> None:
    with pytest.raises(ValueError, match="zero or positive"):
        pipeline_value_by_stage([{"stage": "lead", "value": Decimal("-5"), "currency": "EUR"}])


# ── ISO 8601 date parsing ──────────────────────────────────────────────────


def test_parse_iso_date_plain() -> None:
    assert parse_iso_date("2026-07-05") == date(2026, 7, 5)


def test_parse_iso_date_with_time_suffix() -> None:
    assert parse_iso_date("2026-07-05T12:30:00Z") == date(2026, 7, 5)


def test_parse_iso_date_empty_is_none() -> None:
    assert parse_iso_date(None) is None
    assert parse_iso_date("") is None


def test_parse_iso_date_bad_format_raises() -> None:
    with pytest.raises(ValueError, match="ISO 8601"):
        parse_iso_date("05/07/2026")


# ── Localization (en / de / ru, English fallback) ──────────────────────────


def test_localize_stage_known() -> None:
    assert localize_stage("proposal", "en") == "Proposal"
    assert localize_stage("proposal", "de") == "Angebot"
    assert localize_stage("proposal", "ru") == "Предложение"


def test_localize_stage_unknown_locale_falls_back_to_english() -> None:
    assert localize_stage("proposal", "fr") == "Proposal"


def test_localize_stage_unknown_code_is_humanized() -> None:
    assert localize_stage("cold_outreach", "de") == "Cold Outreach"


def test_localize_status_known_and_locale_variant() -> None:
    assert localize_status("won", "en") == "Won"
    assert localize_status("won", "de") == "Gewonnen"
    assert localize_status("abandoned", "ru") == "Отменено"


def test_localize_locale_region_tag_normalized() -> None:
    assert localize_status("open", "de-DE") == "Offen"


# ── Explainers ─────────────────────────────────────────────────────────────


def test_explain_known_metrics_all_locales() -> None:
    for metric in ("pipeline_value", "weighted_value", "win_rate", "stage"):
        for loc in ("en", "de", "ru"):
            assert explain(metric, loc)


def test_explain_unknown_metric_is_empty() -> None:
    assert explain("nonsense", "en") == ""


def test_explain_defaults_to_english() -> None:
    assert explain("win_rate") == explain("win_rate", "en")


# ── Explainable reports ────────────────────────────────────────────────────


def test_weighted_value_report_exposes_components() -> None:
    report = weighted_value_report(1000, Decimal("0.4"), currency="eur", locale="en")
    assert report["value"] == Decimal("1000")
    assert report["probability"] == Decimal("0.4")
    assert report["weighted"] == Decimal("400.0")
    assert report["currency"] == "EUR"
    assert report["formula"] == "weighted = value * probability"
    assert report["explanation"]


def test_win_rate_report_exposes_components() -> None:
    report = win_rate_report(3, 1, locale="de")
    assert report["won"] == 3
    assert report["lost"] == 1
    assert report["closed"] == 4
    assert report["win_rate"] == Decimal("0.75")
    assert report["formula"] == "win_rate = won / (won + lost)"
    assert report["explanation"]


def test_win_rate_report_zero_guard() -> None:
    report = win_rate_report(0, 0)
    assert report["win_rate"] == Decimal(0)
    assert report["closed"] == 0
