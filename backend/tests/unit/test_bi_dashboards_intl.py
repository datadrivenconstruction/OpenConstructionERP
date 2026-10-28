# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠DB-free unit tests for the BI Dashboards international helpers.

These pin the pure, no-I/O helpers in ``app.modules.bi_dashboards.intl``:
Decimal-exact aggregation, currency-safe money grouping, a zero-prior-guarded
period-over-period delta, and localized labels / one-line explainers with an
English fallback. No database session is used - every test is pure.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.bi_dashboards import intl

# ── Series aggregation ─────────────────────────────────────────────────


def test_series_sum_is_decimal_exact() -> None:
    # 0.1 + 0.2 must be exactly 0.3, not a binary-float 0.30000000000000004.
    assert intl.series_sum(["0.1", "0.2"]) == Decimal("0.3")


def test_series_sum_empty_is_zero() -> None:
    assert intl.series_sum([]) == Decimal("0")


def test_series_count() -> None:
    assert intl.series_count([1, 2, 3]) == 3
    assert intl.series_count([]) == 0


def test_series_average_exact() -> None:
    assert intl.series_average(["2", "4"]) == Decimal("3")


def test_series_average_empty_raises() -> None:
    with pytest.raises(ValueError, match="empty series"):
        intl.series_average([])


def test_series_min_max() -> None:
    assert intl.series_min(["3", "1", "2"]) == Decimal("1")
    assert intl.series_max(["3", "1", "2"]) == Decimal("3")


def test_series_min_max_empty_raises() -> None:
    with pytest.raises(ValueError):
        intl.series_min([])
    with pytest.raises(ValueError):
        intl.series_max([])


def test_aggregate_series_dispatch() -> None:
    values = ["10", "20", "30"]
    assert intl.aggregate_series(values, "sum") == Decimal("60")
    assert intl.aggregate_series(values, "average") == Decimal("20")
    assert intl.aggregate_series(values, "min") == Decimal("10")
    assert intl.aggregate_series(values, "max") == Decimal("30")
    assert intl.aggregate_series(values, "count") == Decimal("3")


def test_aggregate_series_count_and_sum_defined_on_empty() -> None:
    assert intl.aggregate_series([], "sum") == Decimal("0")
    assert intl.aggregate_series([], "count") == Decimal("0")


def test_aggregate_series_unknown_method_raises() -> None:
    with pytest.raises(ValueError, match="unknown aggregation method"):
        intl.aggregate_series([1], "median")


def test_aggregate_series_method_is_case_insensitive() -> None:
    assert intl.aggregate_series(["1", "2"], "SUM") == Decimal("3")
    assert intl.aggregate_series(["1", "2"], "Maximum") == Decimal("2")


# ── Non-finite / invalid input rejection (never NaN / inf) ─────────────


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), "abc", None, True])
def test_non_finite_or_non_numeric_raises(bad: object) -> None:
    with pytest.raises(ValueError):
        intl.series_sum([bad])


# ── Group-by aggregation ───────────────────────────────────────────────


def test_group_aggregate_sum() -> None:
    rows = [
        {"trade": "concrete", "cost": "100"},
        {"trade": "concrete", "cost": "50"},
        {"trade": "steel", "cost": "200"},
    ]
    out = intl.group_aggregate(rows, key="trade", value="cost", method="sum")
    assert out == {"concrete": Decimal("150"), "steel": Decimal("200")}


def test_group_aggregate_count_and_average() -> None:
    rows = [
        {"g": "a", "v": "2"},
        {"g": "a", "v": "4"},
        {"g": "b", "v": "9"},
    ]
    counts = intl.group_aggregate(rows, key="g", value="v", method="count")
    assert counts == {"a": Decimal("2"), "b": Decimal("1")}
    avgs = intl.group_aggregate(rows, key="g", value="v", method="average")
    assert avgs == {"a": Decimal("3"), "b": Decimal("9")}


def test_group_aggregate_missing_key_bucketed_unknown() -> None:
    rows = [{"v": "5"}, {"g": "", "v": "3"}]
    out = intl.group_aggregate(rows, key="g", value="v", method="sum")
    assert out == {"UNKNOWN": Decimal("8")}


def test_group_aggregate_missing_value_counts_as_zero() -> None:
    rows = [{"g": "a"}, {"g": "a", "v": "5"}]
    out = intl.group_aggregate(rows, key="g", value="v", method="sum")
    assert out == {"a": Decimal("5")}


def test_group_aggregate_empty_is_empty_map() -> None:
    assert intl.group_aggregate([], key="g", value="v") == {}


# ── Money: currency-safe ───────────────────────────────────────────────


def test_group_money_by_currency_never_blends() -> None:
    entries = [("100", "EUR"), ("50", "USD"), ("25", "EUR")]
    out = intl.group_money_by_currency(entries)
    assert out == {"EUR": Decimal("125"), "USD": Decimal("50")}


def test_group_money_missing_code_is_unknown() -> None:
    out = intl.group_money_by_currency([("10", None), ("5", "")])
    assert out == {"UNKNOWN": Decimal("15")}


def test_sum_single_currency_ok() -> None:
    total, code = intl.sum_single_currency([("100", "EUR"), ("50", "eur")])
    assert total == Decimal("150")
    assert code == "EUR"


def test_sum_single_currency_empty() -> None:
    total, code = intl.sum_single_currency([])
    assert total == Decimal("0")
    assert code == ""


def test_sum_single_currency_mismatch_raises() -> None:
    with pytest.raises(intl.CurrencyMismatchError):
        intl.sum_single_currency([("100", "EUR"), ("50", "USD")])


def test_currency_mismatch_is_value_error() -> None:
    # Callers guarding only ValueError must still catch a currency mismatch.
    assert issubclass(intl.CurrencyMismatchError, ValueError)


# ── Period-over-period delta ───────────────────────────────────────────


def test_delta_up() -> None:
    d = intl.period_over_period_delta("110", "100")
    assert d.direction == "up"
    assert d.absolute == Decimal("10")
    assert d.ratio == Decimal("0.1")
    assert d.prior_zero is False


def test_delta_down() -> None:
    d = intl.period_over_period_delta("80", "100")
    assert d.direction == "down"
    assert d.ratio == Decimal("-0.2")


def test_delta_flat() -> None:
    d = intl.period_over_period_delta("100", "100")
    assert d.direction == "flat"
    assert d.ratio == Decimal("0")


def test_delta_zero_prior_guard() -> None:
    # Division by zero must never happen; ratio is None, not inf/NaN.
    d = intl.period_over_period_delta("50", "0")
    assert d.prior_zero is True
    assert d.ratio is None
    assert d.direction == "up"
    assert d.absolute == Decimal("50")


def test_delta_ratio_is_a_ratio_not_percent() -> None:
    # A plus-ten-percent change is carried as the fraction 0.1.
    d = intl.period_over_period_delta("11", "10")
    assert d.ratio == Decimal("0.1")


def test_delta_rejects_non_finite() -> None:
    with pytest.raises(ValueError):
        intl.period_over_period_delta(float("inf"), "10")


# ── Percent formatting ─────────────────────────────────────────────────


def test_format_ratio_as_percent() -> None:
    assert intl.format_ratio_as_percent("0.125") == "+12.5%"
    assert intl.format_ratio_as_percent("-0.2") == "-20.0%"
    assert intl.format_ratio_as_percent("0") == "0.0%"


def test_format_ratio_as_percent_places() -> None:
    assert intl.format_ratio_as_percent("0.12345", places=0) == "+12%"


def test_format_ratio_as_percent_negative_places_raises() -> None:
    with pytest.raises(ValueError):
        intl.format_ratio_as_percent("0.1", places=-1)


# ── Localized labels + English fallback ────────────────────────────────


def test_aggregation_label_locales() -> None:
    assert intl.aggregation_label("sum", "en") == "Total"
    assert intl.aggregation_label("sum", "de") == "Summe"
    assert intl.aggregation_label("sum", "ru") == "Сумма"


def test_aggregation_label_unknown_locale_falls_back_to_english() -> None:
    assert intl.aggregation_label("average", "fr") == "Average"


def test_aggregation_label_unknown_method_returns_key() -> None:
    assert intl.aggregation_label("median", "en") == "median"


def test_unit_label_locales_and_fallback() -> None:
    assert intl.unit_label("currency", "en") == "currency"
    assert intl.unit_label("currency", "ru") == "валюта"
    assert intl.unit_label("currency", "zz") == "currency"
    assert intl.unit_label("days", "de") == "Tage"


def test_label_tables_have_en_de_ru_parity() -> None:
    # Every label / explainer table must carry all three canonical locales.
    tables = [
        intl._AGG_LABELS,
        intl._UNIT_LABELS,
        intl._DIRECTION_LABELS,
        intl._AGG_EXPLAIN,
        intl._DELTA_PHRASES,
    ]
    for table in tables:
        for key, entry in table.items():
            assert set(entry) == {"en", "de", "ru"}, key


# ── One-line explainers ────────────────────────────────────────────────


def test_explain_kpi() -> None:
    text = intl.explain_kpi("Cost Performance Index", "ratio", "en")
    assert "Cost Performance Index" in text
    assert "ratio" in text


def test_explain_kpi_locale_fallback() -> None:
    # Unknown locale falls back to the English template but keeps the name.
    text = intl.explain_kpi("CPI", "ratio", "xx")
    assert "CPI" in text


def test_explain_aggregate_locales() -> None:
    assert "Adds every value" in intl.explain_aggregate("sum", "en")
    assert intl.explain_aggregate("average", "de")
    assert intl.explain_aggregate("count", "ru")


def test_explain_aggregate_unknown_method() -> None:
    assert "median" in intl.explain_aggregate("median", "en")


def test_explain_delta_up() -> None:
    d = intl.period_over_period_delta("110", "100")
    text = intl.explain_delta(d, "en")
    assert "10.0%" in text
    assert "up" in text


def test_explain_delta_flat() -> None:
    d = intl.period_over_period_delta("100", "100")
    assert "Unchanged" in intl.explain_delta(d, "en")


def test_explain_delta_prior_zero() -> None:
    d = intl.period_over_period_delta("50", "0")
    text = intl.explain_delta(d, "en")
    assert "no prior value" in text.lower()


def test_explain_delta_locale() -> None:
    d = intl.period_over_period_delta("120", "100")
    # German phrasing renders without raising and localizes the direction.
    assert intl.explain_delta(d, "de")
    assert intl.explain_delta(d, "ru")
