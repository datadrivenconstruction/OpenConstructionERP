"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠DB-free unit tests for the international fixed-asset finance helpers.

Covers Decimal-exact depreciation (straight-line and declining-balance),
net book value, per-currency register totals, plain-language explainers,
localized status words, and the edge-case guards (zero useful life, empty
sets, negative or zero cost, salvage above cost, as-of before purchase).

The final test also proves the module source and this test source contain
none of the banned typographic characters. That banned set is built from
``chr()`` code points so the character does not appear literally in this
file.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from app.modules.assets import intl
from tests._watermark import strip_marks

# --- Coercion and parsing --------------------------------------------------


class TestCoercion:
    def test_float_coerces_without_binary_artifact(self):
        assert intl.to_decimal(0.1) == Decimal("0.1")

    def test_string_and_int(self):
        assert intl.to_decimal("1234.56") == Decimal("1234.56")
        assert intl.to_decimal(1000) == Decimal("1000")

    def test_none_rejected(self):
        with pytest.raises(ValueError):
            intl.to_decimal(None)

    def test_empty_string_rejected(self):
        with pytest.raises(ValueError):
            intl.to_decimal("   ")

    def test_bool_rejected(self):
        with pytest.raises(ValueError):
            intl.to_decimal(True)

    def test_nan_and_inf_rejected(self):
        with pytest.raises(ValueError):
            intl.to_decimal("NaN")
        with pytest.raises(ValueError):
            intl.to_decimal("Infinity")

    def test_currency_normalized_upper(self):
        assert intl.normalize_currency(" eur ") == "EUR"
        assert intl.normalize_currency("usd") == "USD"

    def test_currency_empty_rejected(self):
        with pytest.raises(ValueError):
            intl.normalize_currency("")

    def test_currency_non_alpha_rejected(self):
        with pytest.raises(ValueError):
            intl.normalize_currency("US1")

    def test_parse_iso_date_variants(self):
        from datetime import date

        assert intl.parse_iso_date("2026-01-15") == date(2026, 1, 15)
        assert intl.parse_iso_date("2026-01-15T10:30:00Z") == date(2026, 1, 15)

    def test_parse_iso_date_bad_raises(self):
        with pytest.raises(ValueError):
            intl.parse_iso_date("not-a-date")
        with pytest.raises(ValueError):
            intl.parse_iso_date("")


# --- Straight-line depreciation --------------------------------------------


class TestStraightLine:
    def test_half_life_is_half_depreciated(self):
        # Cost 10000, salvage 0, 10 yr life. After 5 years (1826 days) about
        # half the depreciable base is used up.
        r = intl.straight_line_depreciation("10000", "0", 10, "2020-01-01", "2025-01-01", "EUR")
        assert r.currency == "EUR"
        assert r.net_book_value == pytest.approx(Decimal("5000"), abs=Decimal("30"))
        assert r.accumulated_depreciation + r.net_book_value == r.cost

    def test_before_purchase_no_depreciation(self):
        r = intl.straight_line_depreciation("8000", "500", 5, "2026-06-01", "2026-01-01", "GBP")
        assert r.accumulated_depreciation == Decimal("0.00")
        assert r.net_book_value == Decimal("8000.00")
        assert r.fully_depreciated is False

    def test_after_life_rests_at_salvage(self):
        r = intl.straight_line_depreciation("8000", "500", 5, "2010-01-01", "2026-01-01", "JPY")
        assert r.net_book_value == Decimal("500.00")
        assert r.accumulated_depreciation == Decimal("7500.00")
        assert r.fully_depreciated is True

    def test_zero_useful_life_raises(self):
        with pytest.raises(ValueError):
            intl.straight_line_depreciation("1000", "0", 0, "2020-01-01", "2025-01-01", "EUR")

    def test_negative_cost_raises(self):
        with pytest.raises(ValueError):
            intl.straight_line_depreciation("-1", "0", 5, "2020-01-01", "2025-01-01", "EUR")

    def test_zero_cost_is_well_defined(self):
        r = intl.straight_line_depreciation("0", "0", 5, "2020-01-01", "2025-01-01", "EUR")
        assert r.net_book_value == Decimal("0.00")
        assert r.accumulated_depreciation == Decimal("0.00")

    def test_salvage_above_cost_raises(self):
        with pytest.raises(ValueError):
            intl.straight_line_depreciation("1000", "2000", 5, "2020-01-01", "2025-01-01", "EUR")

    def test_negative_salvage_raises(self):
        with pytest.raises(ValueError):
            intl.straight_line_depreciation("1000", "-5", 5, "2020-01-01", "2025-01-01", "EUR")

    def test_result_is_finite_never_nan(self):
        r = intl.straight_line_depreciation("1000", "100", 3, "2020-01-01", "2021-07-01", "EUR")
        assert r.net_book_value.is_finite()
        assert r.accumulated_depreciation.is_finite()


# --- Declining-balance depreciation ----------------------------------------


class TestDecliningBalance:
    def test_faster_than_straight_line_early(self):
        sl = intl.straight_line_depreciation("10000", "0", 10, "2020-01-01", "2022-01-01", "EUR")
        db = intl.declining_balance_depreciation("10000", "0", 10, "2020-01-01", "2022-01-01", "EUR")
        # Declining balance front-loads depreciation, so early NBV is lower.
        assert db.net_book_value < sl.net_book_value
        assert db.annual_rate == Decimal("0.2")

    def test_never_below_salvage(self):
        r = intl.declining_balance_depreciation("10000", "1000", 5, "2010-01-01", "2026-01-01", "EUR")
        assert r.net_book_value >= Decimal("1000.00")

    def test_lands_on_salvage_at_end_of_life(self):
        r = intl.declining_balance_depreciation("10000", "1000", 5, "2019-01-01", "2024-01-01", "EUR")
        assert r.net_book_value == pytest.approx(Decimal("1000"), abs=Decimal("60"))

    def test_custom_rate_used(self):
        r = intl.declining_balance_depreciation("10000", "0", 10, "2020-01-01", "2022-01-01", "EUR", annual_rate="0.15")
        assert r.annual_rate == Decimal("0.15")

    def test_rate_out_of_range_raises(self):
        with pytest.raises(ValueError):
            intl.declining_balance_depreciation("10000", "0", 10, "2020-01-01", "2022-01-01", "EUR", annual_rate="1.5")
        with pytest.raises(ValueError):
            intl.declining_balance_depreciation("10000", "0", 10, "2020-01-01", "2022-01-01", "EUR", annual_rate="0")

    def test_before_purchase_no_depreciation(self):
        r = intl.declining_balance_depreciation("10000", "0", 5, "2026-06-01", "2026-01-01", "EUR")
        assert r.net_book_value == Decimal("10000.00")
        assert r.accumulated_depreciation == Decimal("0.00")

    def test_zero_useful_life_raises(self):
        with pytest.raises(ValueError):
            intl.declining_balance_depreciation("1000", "0", 0, "2020-01-01", "2025-01-01", "EUR")


# --- Net book value helper -------------------------------------------------


class TestNetBookValue:
    def test_basic(self):
        assert intl.net_book_value("1000", "250") == Decimal("750.00")

    def test_floored_at_zero(self):
        assert intl.net_book_value("1000", "5000") == Decimal("0.00")

    def test_negative_inputs_raise(self):
        with pytest.raises(ValueError):
            intl.net_book_value("-1", "0")
        with pytest.raises(ValueError):
            intl.net_book_value("1000", "-1")


# --- Register totals by currency -------------------------------------------


class TestRegisterTotals:
    def test_empty_yields_empty(self):
        assert intl.total_register_value_by_currency([]) == {}

    def test_groups_and_never_blends(self):
        entries = [
            ("EUR", "1000.00"),
            ("EUR", "250.50"),
            ("USD", "999.99"),
            ("usd", "0.01"),
        ]
        out = intl.total_register_value_by_currency(entries)
        assert out == {"EUR": Decimal("1250.50"), "USD": Decimal("1000.00")}

    def test_accepts_mappings(self):
        entries = [
            {"currency": "EUR", "net_book_value": "500"},
            {"currency": "EUR", "amount": "500"},
        ]
        out = intl.total_register_value_by_currency(entries)
        assert out == {"EUR": Decimal("1000.00")}

    def test_result_keys_sorted(self):
        out = intl.total_register_value_by_currency([("USD", "1"), ("EUR", "1"), ("CHF", "1")])
        assert list(out.keys()) == ["CHF", "EUR", "USD"]

    def test_bad_entry_raises(self):
        with pytest.raises(ValueError):
            intl.total_register_value_by_currency([("EUR",)])


# --- Explainers and localized status ---------------------------------------


class TestExplainAndLocalize:
    def test_explain_english(self):
        for term in (
            "asset_cost",
            "accumulated_depreciation",
            "net_book_value",
            "useful_life",
            "salvage_value",
        ):
            assert intl.explain(term) != ""

    def test_explain_unknown_is_empty(self):
        assert intl.explain("nope") == ""

    def test_explain_localized_and_fallback(self):
        assert intl.explain("net_book_value", "de") != intl.explain("net_book_value", "en")
        # Unsupported language falls back to English.
        assert intl.explain("net_book_value", "xx") == intl.explain("net_book_value", "en")

    def test_localize_status_languages(self):
        assert intl.localize_status("expired", "en") == "Expired"
        assert intl.localize_status("expired", "de") != "Expired"
        assert intl.localize_status("expired", "ru") != "Expired"

    def test_localize_status_locale_tag_reduced(self):
        assert intl.localize_status("expired", "de-DE") == intl.localize_status("expired", "de")

    def test_localize_status_unknown_humanized(self):
        assert intl.localize_status("under_maintenance", "en") == "Under maintenance"
        assert intl.localize_status("some_new_state") == "Some New State"

    def test_localize_status_fallback_to_english(self):
        assert intl.localize_status("overdue", "xx") == intl.localize_status("overdue", "en")

    def test_en_de_ru_parity_for_every_status(self):
        for table in intl._STATUS_LABELS.values():
            assert set(table.keys()) >= {"en", "de", "ru"}

    def test_en_de_ru_parity_for_every_explainer(self):
        for table in intl._EXPLAINERS.values():
            assert set(table.keys()) >= {"en", "de", "ru"}


# --- Explainability bundle -------------------------------------------------


class TestDescribe:
    def test_describe_has_components_and_explainers(self):
        r = intl.straight_line_depreciation("10000", "1000", 10, "2020-01-01", "2025-01-01", "EUR")
        d = intl.describe_depreciation(r)
        assert d["components"]["currency"] == "EUR"
        # Decimals are serialized as strings for JSON friendliness.
        assert isinstance(d["components"]["net_book_value"], str)
        assert d["explainers"]["net_book_value"] != ""


# --- Typographic hygiene ---------------------------------------------------


class TestNoBannedCharacters:
    def test_module_and_test_sources_have_no_banned_typography(self):
        # Build the banned set from code points so none appear literally here.
        banned = {
            chr(0x2014),  # em dash
            chr(0x2013),  # en dash
            chr(0x2015),  # horizontal bar
            chr(0x2018),  # left single quote
            chr(0x2019),  # right single quote
            chr(0x201C),  # left double quote
            chr(0x201D),  # right double quote
            chr(0x200B),  # zero width space
            chr(0x200C),  # zero width non-joiner
            chr(0x200D),  # zero width joiner
            chr(0x2060),  # word joiner
            chr(0xFEFF),  # byte order mark
        }
        for path in (
            Path(intl.__file__),
            Path(__file__),
        ):
            text = strip_marks(path.read_text(encoding="utf-8"))
            found = {hex(ord(ch)) for ch in text if ch in banned}
            assert not found, f"{path.name} contains banned characters: {found}"
