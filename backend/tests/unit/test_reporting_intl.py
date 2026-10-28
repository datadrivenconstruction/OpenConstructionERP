"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the reporting international math + explainer helpers.

Pure (stdlib only) - no app lifespan, no database, no clock. Exercises the
Decimal-exact report total, ratio / percent guards, grouped breakdown,
top-N selector, currency guards, and the localized plain-language
explainers in :mod:`app.modules.reporting.intl`.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.reporting.intl import (
    Breakdown,
    GroupShare,
    classification_label,
    ensure_single_currency,
    explain_breakdown,
    explain_percent_of_total,
    explain_report_total,
    explain_top_n,
    format_money,
    format_ratio_as_percent,
    group_breakdown,
    normalize_currency,
    ratio_of_total,
    report_total,
    to_decimal,
    top_n_by_value,
)

# ── to_decimal ─────────────────────────────────────────────────────────────


def test_to_decimal_accepts_decimal_int_str() -> None:
    assert to_decimal(Decimal("1.5")) == Decimal("1.5")
    assert to_decimal(3) == Decimal("3")
    assert to_decimal("2.50") == Decimal("2.50")
    # Thousands-space tolerated.
    assert to_decimal("1 234.56") == Decimal("1234.56")


def test_to_decimal_float_uses_string_form_no_drift() -> None:
    # 0.1 as a binary float is not exact; going through str keeps the literal.
    assert to_decimal(0.1) == Decimal("0.1")


def test_to_decimal_rejects_none_empty_bool_and_garbage() -> None:
    for bad in (None, "", "   ", True, False, "abc", object()):
        with pytest.raises(ValueError):
            to_decimal(bad)


def test_to_decimal_rejects_non_finite() -> None:
    for bad in ("nan", "inf", "-inf", "Infinity", float("nan"), float("inf")):
        with pytest.raises(ValueError):
            to_decimal(bad)


# ── report_total ───────────────────────────────────────────────────────────


def test_report_total_is_decimal_exact() -> None:
    # Classic float trap: 0.1 + 0.2 == 0.30000000000000004 in float.
    assert report_total(["0.1", "0.2"]) == Decimal("0.3")


def test_report_total_empty_is_zero() -> None:
    assert report_total([]) == Decimal("0")


def test_report_total_allows_negative_lines() -> None:
    # A credit / retention release is a legitimate negative line.
    assert report_total([Decimal("100"), Decimal("-30")]) == Decimal("70")


def test_report_total_rejects_bad_amount() -> None:
    with pytest.raises(ValueError):
        report_total(["10", "oops"])


# ── ratio_of_total (zero-total guard, ratios not percents) ─────────────────


def test_ratio_of_total_is_a_ratio() -> None:
    assert ratio_of_total(25, 100) == Decimal("0.25")


def test_ratio_of_total_zero_total_guarded() -> None:
    # No ZeroDivisionError, no NaN/inf - defined as 0.
    assert ratio_of_total(5, 0) == Decimal("0")
    assert ratio_of_total(0, 0) == Decimal("0")


def test_ratio_of_total_can_exceed_one_and_go_negative() -> None:
    assert ratio_of_total(150, 100) == Decimal("1.5")
    assert ratio_of_total(-25, 100) == Decimal("-0.25")


# ── currency guards (never blend) ──────────────────────────────────────────


def test_normalize_currency_ok_and_bad() -> None:
    assert normalize_currency("eur") == "EUR"
    assert normalize_currency(" usd ") == "USD"
    for bad in (None, "", "EURO", "US", "12", "e u r"):
        with pytest.raises(ValueError):
            normalize_currency(bad)


def test_ensure_single_currency_collapses_and_ignores_blanks() -> None:
    assert ensure_single_currency(["EUR", "eur", None, "  "]) == "EUR"


def test_ensure_single_currency_rejects_blend_and_empty() -> None:
    with pytest.raises(ValueError):
        ensure_single_currency(["EUR", "USD"])
    with pytest.raises(ValueError):
        ensure_single_currency([None, "", "  "])


# ── group_breakdown ────────────────────────────────────────────────────────


def _lines() -> list[dict[str, object]]:
    return [
        {"trade": "concrete", "amount": "100"},
        {"trade": "steel", "amount": "300"},
        {"trade": "concrete", "amount": "100"},
    ]


def test_group_breakdown_totals_shares_and_order() -> None:
    bd = group_breakdown(
        _lines(),
        key_getter=lambda r: r["trade"],
        amount_getter=lambda r: r["amount"],
        currency="EUR",
    )
    assert bd.total == Decimal("500")
    assert bd.currency == "EUR"
    # Sorted by total descending: steel (300) before concrete (200).
    assert [g.key for g in bd.groups] == ["steel", "concrete"]
    steel, concrete = bd.groups
    assert steel.total == Decimal("300")
    assert steel.share == Decimal("0.6")
    assert steel.count == 1
    assert concrete.total == Decimal("200")
    assert concrete.count == 2
    # Shares sum to 1.
    assert sum(g.share for g in bd.groups) == Decimal("1")


def test_group_breakdown_zero_total_shares_are_zero() -> None:
    rows = [{"k": "a", "v": "0"}, {"k": "b", "v": "0"}]
    bd = group_breakdown(rows, key_getter=lambda r: r["k"], amount_getter=lambda r: r["v"])
    assert bd.total == Decimal("0")
    assert all(g.share == Decimal("0") for g in bd.groups)


def test_group_breakdown_empty_is_empty() -> None:
    bd = group_breakdown([], key_getter=lambda r: r, amount_getter=lambda r: 0)
    assert bd.total == Decimal("0")
    assert bd.groups == ()


def test_group_breakdown_rejects_bad_currency() -> None:
    with pytest.raises(ValueError):
        group_breakdown(
            _lines(),
            key_getter=lambda r: r["trade"],
            amount_getter=lambda r: r["amount"],
            currency="EURO",
        )


# ── top_n_by_value ─────────────────────────────────────────────────────────


def test_top_n_by_value_orders_and_limits() -> None:
    rows = [{"n": "a", "v": 10}, {"n": "b", "v": 50}, {"n": "c", "v": 30}]
    top2 = top_n_by_value(rows, value_getter=lambda r: r["v"], n=2)
    assert [r["n"] for r in top2] == ["b", "c"]


def test_top_n_by_value_zero_and_over_length() -> None:
    rows = [{"v": 1}, {"v": 2}]
    assert top_n_by_value(rows, value_getter=lambda r: r["v"], n=0) == []
    # Asking for more than exists returns all, sorted.
    got = top_n_by_value(rows, value_getter=lambda r: r["v"], n=9)
    assert [r["v"] for r in got] == [2, 1]


def test_top_n_by_value_stable_on_ties() -> None:
    rows = [{"id": 1, "v": 5}, {"id": 2, "v": 5}, {"id": 3, "v": 5}]
    got = top_n_by_value(rows, value_getter=lambda r: r["v"], n=2)
    assert [r["id"] for r in got] == [1, 2]


def test_top_n_by_value_rejects_negative_n() -> None:
    with pytest.raises(ValueError):
        top_n_by_value([{"v": 1}], value_getter=lambda r: r["v"], n=-1)


# ── formatters ─────────────────────────────────────────────────────────────


def test_format_money_keeps_precision_and_currency() -> None:
    assert format_money("1234.50", "eur") == "1234.50 EUR"
    assert format_money(Decimal("10")) == "10"


def test_format_ratio_as_percent() -> None:
    assert format_ratio_as_percent(Decimal("0.25")) == "25.0%"
    assert format_ratio_as_percent(Decimal("0.25"), places=0) == "25%"
    assert format_ratio_as_percent(Decimal("0")) == "0.0%"


def test_format_ratio_as_percent_rejects_negative_places() -> None:
    with pytest.raises(ValueError):
        format_ratio_as_percent(Decimal("0.1"), places=-1)


def test_classification_label_named_standards() -> None:
    assert classification_label("din276", "330") == "DIN 276 330"
    assert classification_label("nrm", "2.6.1") == "NRM 2.6.1"
    assert classification_label("masterformat", "03 30 00") == "MasterFormat 03 30 00"
    # Unknown standard still yields a readable label.
    assert classification_label("mystd") == "MYSTD"


# ── explainers (localized, English fallback) ───────────────────────────────


def test_explain_report_total_en_de_ru() -> None:
    en = explain_report_total(Decimal("1500"), line_count=3, currency="EUR", locale="en")
    assert en == "Report total: 1500 EUR (sum of 3 lines)."
    de = explain_report_total(Decimal("1500"), line_count=3, currency="EUR", locale="de")
    assert de.startswith("Berichtssumme:")
    ru = explain_report_total(Decimal("1500"), line_count=1, currency="EUR", locale="ru")
    assert ru.startswith("Итого по отчету:")
    # Unknown locale falls back to English.
    fb = explain_report_total(Decimal("1"), line_count=1, currency="EUR", locale="zz")
    assert fb.startswith("Report total:")


def test_explain_report_total_singular_plural() -> None:
    one = explain_report_total(Decimal("1"), line_count=1, locale="en")
    assert one.endswith("(sum of 1 line).")
    many = explain_report_total(Decimal("1"), line_count=2, locale="en")
    assert many.endswith("(sum of 2 lines).")


def test_explain_report_total_rejects_negative_count() -> None:
    with pytest.raises(ValueError):
        explain_report_total(Decimal("1"), line_count=-1)


def test_explain_percent_of_total_normal_and_zero_total() -> None:
    normal = explain_percent_of_total(250, 1000, currency="EUR", locale="en")
    assert "25.0%" in normal
    assert normal.endswith("(percent of total).")
    zero = explain_percent_of_total(250, 0, currency="EUR", locale="en")
    assert "0 percent" in zero
    # German zero-total note localized.
    zero_de = explain_percent_of_total(250, 0, currency="EUR", locale="de")
    assert "0 Prozent" in zero_de


def test_explain_breakdown_and_empty() -> None:
    bd = group_breakdown(
        _lines(),
        key_getter=lambda r: r["trade"],
        amount_getter=lambda r: r["amount"],
        currency="EUR",
    )
    text = explain_breakdown(bd, locale="en")
    assert text == "Cost breakdown: 2 groups, report total 500 EUR."
    empty = explain_breakdown(Breakdown(total=Decimal("0"), groups=(), currency=None), locale="en")
    assert empty == "Cost breakdown: no data."


def test_explain_top_n() -> None:
    rows = [{"v": 1}, {"v": 2}, {"v": 3}]
    got = top_n_by_value(rows, value_getter=lambda r: r["v"], n=5)
    text = explain_top_n(got, requested_n=5, locale="en")
    assert text == "Top 5: 3 of 3 lines."


def test_group_share_dataclass_is_frozen() -> None:
    g = GroupShare(key="a", total=Decimal("1"), share=Decimal("1"), count=1)
    with pytest.raises(Exception):  # noqa: B017 - frozen dataclass raises FrozenInstanceError
        g.total = Decimal("2")  # type: ignore[misc]
