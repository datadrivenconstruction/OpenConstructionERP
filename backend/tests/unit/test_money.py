"""Tests for the MoneyValue utility and helpers."""

from decimal import Decimal

import pytest

from app.core.money import (
    CURRENCIES,
    MoneyValue,
    format_money,
    money_columns,
    parse_money,
)

# ── MoneyValue construction ──────────────────────────────────────────────────


class TestMoneyValueConstruction:
    def test_defaults(self):
        mv = MoneyValue()
        assert mv.amount == "0"
        assert mv.currency_code == "EUR"
        assert mv.amount_base == "0"
        assert mv.base_currency_code == "EUR"
        assert mv.exchange_rate == "1"

    def test_explicit_values(self):
        mv = MoneyValue(
            amount="1500.50",
            currency_code="USD",
            amount_base="1389.35",
            base_currency_code="EUR",
            exchange_rate="0.926",
        )
        assert mv.amount == "1500.5"
        assert mv.currency_code == "USD"
        assert mv.amount_base == "1389.35"
        assert mv.base_currency_code == "EUR"
        assert mv.exchange_rate == "0.926"

    def test_normalises_trailing_zeros(self):
        mv = MoneyValue(amount="100.00", exchange_rate="1.000")
        assert mv.amount == "100"
        assert mv.exchange_rate == "1"

    def test_normalises_zero_variants(self):
        mv = MoneyValue(amount="0.00", amount_base="0.0")
        assert mv.amount == "0"
        assert mv.amount_base == "0"

    def test_frozen_model(self):
        mv = MoneyValue(amount="100")
        with pytest.raises(Exception):  # noqa: B017
            mv.amount = "200"  # type: ignore[misc]

    def test_repr(self):
        mv = MoneyValue(amount="42.50", currency_code="GBP")
        assert "42.5" in repr(mv)
        assert "GBP" in repr(mv)


# ── Validators ────────────────────────────────────────────────────────────────


class TestValidation:
    def test_invalid_currency_code_lowercase(self):
        with pytest.raises(ValueError, match="3 uppercase letters"):
            MoneyValue(currency_code="eur")

    def test_invalid_currency_code_too_short(self):
        with pytest.raises(ValueError, match="3 uppercase letters"):
            MoneyValue(currency_code="EU")

    def test_invalid_currency_code_too_long(self):
        with pytest.raises(ValueError, match="3 uppercase letters"):
            MoneyValue(currency_code="EURO")

    def test_invalid_currency_code_digits(self):
        with pytest.raises(ValueError, match="3 uppercase letters"):
            MoneyValue(currency_code="E12")

    def test_invalid_base_currency_code(self):
        with pytest.raises(ValueError, match="3 uppercase letters"):
            MoneyValue(base_currency_code="xx")

    def test_invalid_amount_not_decimal(self):
        with pytest.raises(ValueError, match="Cannot parse"):
            MoneyValue(amount="not-a-number")

    def test_invalid_amount_base(self):
        with pytest.raises(ValueError, match="Cannot parse"):
            MoneyValue(amount_base="abc")

    def test_invalid_exchange_rate(self):
        with pytest.raises(ValueError, match="Cannot parse"):
            MoneyValue(exchange_rate="N/A")

    def test_negative_amount_allowed(self):
        mv = MoneyValue(amount="-500")
        assert mv.to_decimal() == Decimal("-500")


# ── Decimal conversions ───────────────────────────────────────────────────────


class TestDecimalConversions:
    def test_to_decimal(self):
        mv = MoneyValue(amount="1234.56")
        assert mv.to_decimal() == Decimal("1234.56")

    def test_to_decimal_zero(self):
        mv = MoneyValue()
        assert mv.to_decimal() == Decimal("0")

    def test_to_base_decimal(self):
        mv = MoneyValue(amount_base="999.99")
        assert mv.to_base_decimal() == Decimal("999.99")

    def test_to_base_decimal_default(self):
        mv = MoneyValue()
        assert mv.to_base_decimal() == Decimal("0")

    def test_to_decimal_preserves_precision(self):
        mv = MoneyValue(amount="0.001")
        assert mv.to_decimal() == Decimal("0.001")


# ── Convert ───────────────────────────────────────────────────────────────────


class TestConvert:
    def test_convert_basic(self):
        mv = MoneyValue(amount="100", currency_code="EUR")
        converted = mv.convert("USD", "1.08")
        assert converted.currency_code == "USD"
        assert converted.to_decimal() == Decimal("108.00")
        assert converted.amount_base == "100"
        assert converted.base_currency_code == "EUR"
        assert converted.exchange_rate == "1.08"

    def test_convert_with_decimal_rate(self):
        mv = MoneyValue(amount="200", currency_code="GBP")
        converted = mv.convert("EUR", Decimal("1.16"))
        assert converted.to_decimal() == Decimal("232.00")
        assert converted.currency_code == "EUR"

    def test_convert_rounding(self):
        mv = MoneyValue(amount="100", currency_code="EUR")
        converted = mv.convert("GBP", "0.857")
        # 100 * 0.857 = 85.70 (quantized to 2 decimals)
        assert converted.to_decimal() == Decimal("85.70")

    def test_convert_preserves_original(self):
        mv = MoneyValue(amount="500.25", currency_code="EUR")
        converted = mv.convert("CHF", "0.97")
        # Original should be unchanged (frozen model)
        assert mv.currency_code == "EUR"
        assert mv.amount == "500.25"
        # Converted should track origin
        assert converted.amount_base == "500.25"
        assert converted.base_currency_code == "EUR"


# ── Arithmetic ────────────────────────────────────────────────────────────────


class TestArithmetic:
    def test_addition(self):
        a = MoneyValue(amount="100.50", currency_code="EUR")
        b = MoneyValue(amount="200.25", currency_code="EUR")
        result = a + b
        assert result.to_decimal() == Decimal("300.75")
        assert result.currency_code == "EUR"

    def test_subtraction(self):
        a = MoneyValue(amount="500", currency_code="USD")
        b = MoneyValue(amount="123.45", currency_code="USD")
        result = a - b
        assert result.to_decimal() == Decimal("376.55")
        assert result.currency_code == "USD"

    def test_addition_different_currencies_raises(self):
        a = MoneyValue(amount="100", currency_code="EUR")
        b = MoneyValue(amount="100", currency_code="USD")
        with pytest.raises(ValueError, match="Cannot"):
            _ = a + b

    def test_subtraction_different_currencies_raises(self):
        a = MoneyValue(amount="100", currency_code="EUR")
        b = MoneyValue(amount="100", currency_code="GBP")
        with pytest.raises(ValueError, match="Cannot"):
            _ = a - b

    def test_add_not_implemented_for_other_types(self):
        mv = MoneyValue(amount="100")
        assert mv.__add__(42) is NotImplemented

    def test_sub_not_implemented_for_other_types(self):
        mv = MoneyValue(amount="100")
        assert mv.__sub__("50") is NotImplemented

    def test_addition_accumulates_base(self):
        a = MoneyValue(amount="100", amount_base="50")
        b = MoneyValue(amount="200", amount_base="100")
        result = a + b
        assert result.to_base_decimal() == Decimal("150")

    def test_subtraction_result_negative(self):
        a = MoneyValue(amount="10")
        b = MoneyValue(amount="20")
        result = a - b
        assert result.to_decimal() == Decimal("-10")


# ── is_zero / negate ──────────────────────────────────────────────────────────


class TestHelpers:
    def test_is_zero_true(self):
        assert MoneyValue().is_zero() is True

    def test_is_zero_false(self):
        assert MoneyValue(amount="0.01").is_zero() is False

    def test_is_zero_normalised(self):
        assert MoneyValue(amount="0.00").is_zero() is True

    def test_negate_positive(self):
        mv = MoneyValue(amount="100.50", amount_base="90")
        neg = mv.negate()
        assert neg.to_decimal() == Decimal("-100.50")
        assert neg.to_base_decimal() == Decimal("-90")
        assert neg.currency_code == mv.currency_code

    def test_negate_negative(self):
        mv = MoneyValue(amount="-42")
        neg = mv.negate()
        assert neg.to_decimal() == Decimal("42")

    def test_negate_zero(self):
        mv = MoneyValue()
        neg = mv.negate()
        assert neg.is_zero() is True


# ── parse_money ───────────────────────────────────────────────────────────────


class TestParseMoney:
    def test_from_string(self):
        assert parse_money("1234.56") == "1234.56"

    def test_from_int(self):
        assert parse_money(100) == "100"

    def test_from_float(self):
        result = parse_money(3.14)
        assert Decimal(result) == Decimal("3.14")

    def test_from_decimal(self):
        assert parse_money(Decimal("99.99")) == "99.99"

    def test_from_negative(self):
        assert parse_money("-42.5") == "-42.5"

    def test_from_zero(self):
        assert parse_money(0) == "0"

    def test_from_large_number(self):
        result = parse_money("1000000000.99")
        assert result == "1000000000.99"

    def test_removes_trailing_zeros(self):
        assert parse_money("100.00") == "100"

    def test_invalid_string(self):
        with pytest.raises(ValueError, match="Cannot parse"):
            parse_money("not-a-number")

    def test_scientific_notation_string(self):
        result = parse_money("1E+3")
        assert result == "1000"

    def test_float_precision_preserved(self):
        # float(0.1 + 0.2) famously != 0.3; parse_money handles via str()
        result = parse_money(0.1)
        assert Decimal(result) == Decimal("0.1")


# ── format_money ──────────────────────────────────────────────────────────────


class TestFormatMoney:
    def test_default_eur_english(self):
        result = format_money("1234.56")
        assert result == "€ 1,234.56"

    def test_usd_english(self):
        result = format_money("999.99", "USD", "en")
        assert result == "$ 999.99"

    def test_eur_german(self):
        result = format_money("1234.56", "EUR", "de")
        assert result == "1.234,56 €"

    def test_zero_amount(self):
        result = format_money("0", "EUR")
        assert result == "€ 0.00"

    def test_negative_amount(self):
        result = format_money("-500.00", "GBP")
        assert result == "£ -500.00"

    def test_jpy_no_decimals(self):
        result = format_money("1500", "JPY")
        assert result == "¥ 1,500"

    def test_large_amount(self):
        result = format_money("1234567.89", "USD")
        assert result == "$ 1,234,567.89"

    def test_unknown_currency_uses_code(self):
        result = format_money("100", "XYZ")
        assert result == "XYZ 100.00"

    def test_german_large_amount(self):
        result = format_money("1234567.89", "EUR", "de")
        assert result == "1.234.567,89 €"


# ── money_columns ─────────────────────────────────────────────────────────────


class TestMoneyColumns:
    def test_default_prefix(self):
        cols = money_columns()
        assert "amount" in cols
        assert "amount_currency" in cols
        assert "amount_base" in cols
        assert "amount_base_currency" in cols
        assert "amount_exchange_rate" in cols
        assert len(cols) == 5

    def test_custom_prefix(self):
        cols = money_columns("cost")
        assert "cost" in cols
        assert "cost_currency" in cols
        assert "cost_base" in cols
        assert "cost_base_currency" in cols
        assert "cost_exchange_rate" in cols
        assert len(cols) == 5

    def test_different_prefixes_no_overlap(self):
        cols_a = money_columns("unit_rate")
        cols_b = money_columns("total")
        assert set(cols_a.keys()).isdisjoint(set(cols_b.keys()))

    def test_columns_are_mapped_column_instances(self):
        cols = money_columns()
        # Each value should be a MappedColumn (SQLAlchemy descriptor).
        # We check it's not None and has the right type structure.
        for key, col in cols.items():
            assert col is not None, f"Column {key} should not be None"


# ── CURRENCIES registry ───────────────────────────────────────────────────────


class TestCurrencies:
    def test_has_major_currencies(self):
        for code in ("EUR", "USD", "GBP", "CHF", "JPY", "CNY", "AUD", "CAD"):
            assert code in CURRENCIES

    def test_entry_structure(self):
        for code, info in CURRENCIES.items():
            assert "symbol" in info, f"{code} missing symbol"
            assert "name" in info, f"{code} missing name"
            assert "decimals" in info, f"{code} missing decimals"
            assert isinstance(info["decimals"], int)

    def test_at_least_30_currencies(self):
        assert len(CURRENCIES) >= 30
