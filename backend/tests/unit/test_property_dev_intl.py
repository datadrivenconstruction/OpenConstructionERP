"""Unit tests for :mod:`app.modules.property_dev.intl`.

Scope:
    Covers the pure, database-free international appraisal helpers: gross
    development value, total development cost, residual land value, profit on
    cost / on GDV (as ratios), the combined feasibility summary, ISO 8601 date
    normalisation, and the en / de / ru localisation of term and status words.

No database, no ORM, no I/O is touched. Every helper is a pure function.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.property_dev.intl import (
    DEFAULT_PROFIT_TARGET_RATIO,
    FALLBACK_LOCALE,
    SUPPORTED_LOCALES,
    build_feasibility_summary,
    explain_figure,
    gross_development_value,
    localize_status,
    localize_term,
    normalise_iso_date,
    normalise_locale,
    profit_on_cost,
    profit_on_gdv,
    residual_land_value,
    total_development_cost,
)

# The characters this module must never emit anywhere: em-dash, en-dash,
# horizontal bar, both smart single quotes, both smart double quotes, and the
# zero-width family. Built from code points, never written as literals, so the
# test file itself stays free of the banned characters it guards against.
_BANNED_CHARS: frozenset[str] = frozenset(
    chr(cp)
    for cp in (
        0x2014,  # em dash
        0x2013,  # en dash
        0x2015,  # horizontal bar
        0x2018,  # left single quotation mark
        0x2019,  # right single quotation mark
        0x201C,  # left double quotation mark
        0x201D,  # right double quotation mark
        0x200B,  # zero width space
        0x200C,  # zero width non-joiner
        0x200D,  # zero width joiner
        0x2060,  # word joiner
        0xFEFF,  # zero width no-break space
    )
)


def _assert_clean(text: str) -> None:
    for ch in _BANNED_CHARS:
        assert ch not in text, f"banned character U+{ord(ch):04X} found in {text!r}"


# ── gross_development_value ──────────────────────────────────────────────


def test_gdv_sums_plain_numbers() -> None:
    assert gross_development_value([Decimal("400000"), Decimal("350000"), 250000]) == Decimal("1000000")


def test_gdv_empty_is_zero() -> None:
    assert gross_development_value([]) == Decimal("0")


def test_gdv_reads_mapping_amounts_and_currency() -> None:
    units = [
        {"sale_price": "400000.50", "currency": "eur"},
        {"value": Decimal("99999.50"), "currency": "EUR"},
    ]
    assert gross_development_value(units) == Decimal("500000.00")


def test_gdv_float_input_is_decimal_exact() -> None:
    # 0.1 + 0.2 must be exactly 0.3, not 0.30000000000000004.
    assert gross_development_value([0.1, 0.2]) == Decimal("0.3")


def test_gdv_rejects_mixed_currency() -> None:
    units = [{"value": 100, "currency": "EUR"}, {"value": 100, "currency": "USD"}]
    with pytest.raises(ValueError, match="cannot sum across currencies"):
        gross_development_value(units)


def test_gdv_rejects_negative() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        gross_development_value([100, -1])


def test_gdv_rejects_nan_and_inf() -> None:
    with pytest.raises(ValueError, match="finite"):
        gross_development_value([Decimal("NaN")])
    with pytest.raises(ValueError, match="finite"):
        gross_development_value([float("inf")])


def test_gdv_expected_currency_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="cannot sum across currencies"):
        gross_development_value([{"value": 100, "currency": "GBP"}], expected_currency="EUR")


def test_gdv_missing_amount_in_mapping_raises() -> None:
    with pytest.raises(ValueError, match="money amount is required"):
        gross_development_value([{"currency": "EUR"}])


# ── total_development_cost ───────────────────────────────────────────────


def test_total_cost_from_named_mapping() -> None:
    costs = {
        "construction": Decimal("6000000"),
        "professional_fees": Decimal("600000"),
        "contingency": Decimal("300000"),
        "finance": Decimal("200000"),
        "sales": Decimal("300000"),
    }
    assert total_development_cost(costs) == Decimal("7400000")


def test_total_cost_from_iterable() -> None:
    assert total_development_cost([Decimal("500000"), 100000]) == Decimal("600000")


def test_total_cost_empty_is_zero() -> None:
    assert total_development_cost([]) == Decimal("0")
    assert total_development_cost({}) == Decimal("0")


def test_total_cost_rejects_negative() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        total_development_cost([100, -50])


# ── residual_land_value ──────────────────────────────────────────────────


def test_residual_basic() -> None:
    # 10m GDV, 7.4m cost, 2m profit -> 600k residual.
    assert residual_land_value(Decimal("10000000"), Decimal("7400000"), Decimal("2000000")) == Decimal("600000")


def test_residual_can_be_negative_when_unviable() -> None:
    # A negative residual is a real, meaningful outcome, not an error.
    assert residual_land_value(Decimal("5000000"), Decimal("6000000")) == Decimal("-1000000")


def test_residual_default_profit_is_zero() -> None:
    assert residual_land_value(Decimal("1000000"), Decimal("400000")) == Decimal("600000")


def test_residual_rejects_negative_inputs() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        residual_land_value(Decimal("-1"), Decimal("0"))


# ── profit_on_cost / profit_on_gdv (ratios with zero guards) ─────────────


def test_profit_on_cost_ratio() -> None:
    # 200k profit on 500k cost -> 0.4 ratio (40 percent).
    assert profit_on_cost(Decimal("200000"), Decimal("500000")) == Decimal("0.4")


def test_profit_on_gdv_ratio() -> None:
    assert profit_on_gdv(Decimal("200000"), Decimal("1000000")) == Decimal("0.2")


def test_profit_on_cost_zero_cost_guarded() -> None:
    # Zero denominator must not raise or produce inf / NaN.
    assert profit_on_cost(Decimal("100"), Decimal("0")) == Decimal("0")


def test_profit_on_gdv_zero_gdv_guarded() -> None:
    assert profit_on_gdv(Decimal("100"), Decimal("0")) == Decimal("0")


def test_profit_ratios_reject_negative() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        profit_on_cost(Decimal("-1"), Decimal("100"))


# ── build_feasibility_summary ────────────────────────────────────────────


def test_feasibility_summary_viable_scheme() -> None:
    out = build_feasibility_summary(
        unit_values=[{"value": 5000000, "currency": "EUR"}, {"value": 5000000, "currency": "EUR"}],
        cost_components={"construction": 6000000, "fees": 1400000},
        developer_profit_target_ratio=Decimal("0.20"),
    )
    assert out["currency"] == "EUR"
    assert out["gross_development_value"] == Decimal("10000000")
    assert out["total_development_cost"] == Decimal("7400000")
    assert out["developer_profit"] == Decimal("2000000.00")
    # Residual = 10m - 7.4m - 2m = 600k.
    assert out["residual_land_value"] == Decimal("600000.00")
    assert out["profit_on_cost"] == Decimal("2000000.00") / Decimal("7400000")
    assert out["profit_on_gdv"] == Decimal("0.2")
    assert out["viable"] is True


def test_feasibility_summary_unviable_scheme() -> None:
    out = build_feasibility_summary(
        unit_values=[5000000],
        cost_components=[6000000],
        developer_profit_target_ratio=Decimal("0.20"),
    )
    assert out["residual_land_value"] < 0
    assert out["viable"] is False


def test_feasibility_summary_default_profit_ratio() -> None:
    out = build_feasibility_summary(unit_values=[1000000], cost_components=[400000])
    assert out["developer_profit_target_ratio"] == DEFAULT_PROFIT_TARGET_RATIO
    assert out["developer_profit"] == Decimal("0")
    assert out["residual_land_value"] == Decimal("600000")


def test_feasibility_summary_rejects_cross_currency_gdv_vs_cost() -> None:
    with pytest.raises(ValueError, match="cannot appraise across currencies"):
        build_feasibility_summary(
            unit_values=[{"value": 100, "currency": "EUR"}],
            cost_components=[{"value": 100, "currency": "USD"}],
        )


def test_feasibility_summary_currency_none_when_unstated() -> None:
    out = build_feasibility_summary(unit_values=[100], cost_components=[50])
    assert out["currency"] is None


# ── normalise_iso_date ───────────────────────────────────────────────────


def test_iso_date_from_date_object() -> None:
    assert normalise_iso_date(date(2026, 7, 5)) == "2026-07-05"


def test_iso_date_from_string_roundtrips() -> None:
    assert normalise_iso_date("2026-12-01") == "2026-12-01"


def test_iso_date_rejects_bad_text() -> None:
    with pytest.raises(ValueError, match="ISO 8601"):
        normalise_iso_date("01/12/2026")


def test_iso_date_rejects_missing() -> None:
    with pytest.raises(ValueError, match="required"):
        normalise_iso_date(None)


# ── localisation: locale + term + status ─────────────────────────────────


def test_normalise_locale_variants() -> None:
    assert normalise_locale("EN") == "en"
    assert normalise_locale("de-DE") == "de"
    assert normalise_locale("ru_RU") == "ru"
    assert normalise_locale("fr") == "fr"
    assert normalise_locale("sw") == FALLBACK_LOCALE
    assert normalise_locale(None) == FALLBACK_LOCALE


def test_localize_term_all_supported_locales() -> None:
    assert localize_term("residual_land_value", "en") == "Residual land value"
    assert localize_term("residual_land_value", "de") == "Residualer Grundstueckswert"
    assert localize_term("residual_land_value", "ru").startswith("О")  # Cyrillic O


def test_localize_term_falls_back_to_english_for_unknown_locale() -> None:
    assert localize_term("profit_on_cost", "xx") == "Profit on cost"


def test_localize_term_unknown_term_is_empty() -> None:
    assert localize_term("no_such_term", "en") == ""


def test_localize_status_words() -> None:
    assert localize_status("viable", "en") == "Viable"
    assert localize_status("unviable", "de") == "Nicht tragfaehig"
    # Unknown status maps to the localised pending word, never a raw code.
    assert localize_status("bogus", "en") == "Not appraised yet"


def test_supported_locales_and_fallback_declared() -> None:
    assert FALLBACK_LOCALE in SUPPORTED_LOCALES
    assert {"en", "de", "ru", "fr", "ja", "ar"} <= set(SUPPORTED_LOCALES)


# ── explainers ───────────────────────────────────────────────────────────


def test_explain_figure_known() -> None:
    text = explain_figure("gross_development_value")
    assert "sales value" in text
    assert text.endswith(".")


def test_explain_figure_unknown_is_empty() -> None:
    assert explain_figure("nope") == ""


# ── banned-character hygiene across every human-facing string ─────────────


def test_no_banned_characters_in_explainers_terms_and_statuses() -> None:
    for figure in (
        "gross_development_value",
        "total_development_cost",
        "residual_land_value",
        "developer_profit",
        "profit_on_cost",
        "profit_on_gdv",
    ):
        _assert_clean(explain_figure(figure))

    terms = (
        "gross_development_value",
        "total_development_cost",
        "residual_land_value",
        "developer_profit",
        "profit_on_cost",
        "profit_on_gdv",
        "construction_cost",
        "professional_fees",
        "contingency",
        "finance_cost",
        "sales_costs",
    )
    for term in terms:
        for loc in SUPPORTED_LOCALES:
            _assert_clean(localize_term(term, loc))

    for status in ("viable", "unviable", "marginal", "pending"):
        for loc in SUPPORTED_LOCALES:
            _assert_clean(localize_status(status, loc))


def test_explain_figure_follows_the_locale() -> None:
    assert explain_figure("profit_on_gdv").startswith("Developer profit divided")
    assert explain_figure("profit_on_gdv", "de").startswith("Entwicklergewinn")
    assert explain_figure("profit_on_gdv", "ru").startswith("Прибыль")
    assert explain_figure("nonsense", "de") == ""
