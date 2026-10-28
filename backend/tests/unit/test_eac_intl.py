# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠International robustness and explainability tests for EAC forecasting.

These tests exercise :mod:`app.modules.eac.evm` with no database, no HTTP and
no async. They pin the international-safety guarantees (any currency, any
minor-unit count, ISO 8601 dates, Decimal-exact money), the edge-case policy
(clean ValueError or well-defined value, never a 500 / NaN / infinity) and
the explainability surface (plain-language glossary and forecast drivers).
"""

from __future__ import annotations

import math
from decimal import Decimal

import pytest

from app.modules.eac.evm import (
    EAC_METHODS,
    METRIC_GLOSSARY,
    EvmForecast,
    aggregate_elements,
    compute_cpi,
    compute_cv,
    compute_eac_combined,
    compute_eac_cpi,
    compute_etc,
    compute_spi,
    compute_sv,
    compute_tcpi_bac,
    compute_tcpi_eac,
    compute_vac,
    explain_metric,
    forecast,
    metric_label,
    to_decimal,
)


def _d(value: str | int | float) -> Decimal:
    return Decimal(str(value))


class TestToDecimal:
    """Money coercion stays exact and rejects junk cleanly."""

    def test_string_roundtrip_is_exact(self) -> None:
        assert str(to_decimal("123456789.99")) == "123456789.99"

    def test_float_does_not_leak_binary_noise(self) -> None:
        # Naive Decimal(0.1) would be 0.1000000000000000055...; via str it is exact.
        assert to_decimal(0.1) == Decimal("0.1")

    def test_passthrough_decimal(self) -> None:
        value = Decimal("42.42")
        assert to_decimal(value) is value

    def test_invalid_raises_valueerror(self) -> None:
        with pytest.raises(ValueError, match="valid money value"):
            to_decimal("not-a-number")


class TestGlossary:
    """Every cryptic code is explained in plain language."""

    def test_all_core_codes_present(self) -> None:
        for code in ("PV", "EV", "AC", "BAC", "CPI", "SPI", "SV", "CV", "EAC", "ETC", "VAC", "TCPI"):
            assert code in METRIC_GLOSSARY

    def test_explain_is_case_insensitive(self) -> None:
        assert explain_metric("cpi") == explain_metric("CPI")

    def test_explain_returns_plain_sentence(self) -> None:
        text = explain_metric("EAC")
        assert "forecast" in text.lower()

    def test_metric_label_full_name(self) -> None:
        assert metric_label("cpi") == "Cost Performance Index"

    def test_unknown_code_raises_with_known_list(self) -> None:
        with pytest.raises(ValueError, match="Unknown EVM code"):
            explain_metric("xyz")

    def test_glossary_has_no_em_dash(self) -> None:
        # International text must use plain hyphens only. Dash characters are
        # referenced by escape so the source itself stays free of them.
        em_dash = chr(0x2014)
        en_dash = chr(0x2013)
        for name, expl in METRIC_GLOSSARY.values():
            assert em_dash not in name and em_dash not in expl
            assert en_dash not in name and en_dash not in expl


class TestTcpi:
    """To Complete Performance Index and its zero-denominator guards."""

    def test_tcpi_bac_standard(self) -> None:
        # (1000-600)/(1000-700) = 400/300
        tcpi = compute_tcpi_bac(_d(1000), _d(600), _d(700))
        assert tcpi is not None
        assert abs(tcpi - (400 / 300)) < 1e-9

    def test_tcpi_bac_none_when_budget_spent(self) -> None:
        assert compute_tcpi_bac(_d(1000), _d(600), _d(1000)) is None

    def test_tcpi_eac_standard(self) -> None:
        tcpi = compute_tcpi_eac(_d(1000), _d(600), _d(700), _d(1100))
        assert tcpi is not None
        assert abs(tcpi - (400 / 400)) < 1e-9

    def test_tcpi_eac_none_when_eac_none(self) -> None:
        assert compute_tcpi_eac(_d(1000), _d(600), _d(700), None) is None

    def test_tcpi_eac_none_when_no_remaining_spend(self) -> None:
        # EAC == AC -> denominator zero
        assert compute_tcpi_eac(_d(1000), _d(600), _d(700), _d(700)) is None


class TestForecastHighLevel:
    """The validated, explainable entry point."""

    def test_auto_picks_combined_when_defined(self) -> None:
        result = forecast(1000, 800, 600, 700)
        assert isinstance(result, EvmForecast)
        assert result.method == "combined"
        assert result.eac == result.eac_variants["combined"]

    def test_all_variants_present(self) -> None:
        result = forecast(1000, 800, 600, 700)
        assert set(result.eac_variants) == {"remaining", "cpi", "combined"}
        assert result.eac_variants["remaining"] == _d(1100)

    def test_auto_falls_back_to_cpi_when_spi_undefined(self) -> None:
        # PV=0 -> SPI undefined -> combined undefined -> auto uses cpi.
        result = forecast(1000, 0, 600, 700)
        assert result.method == "cpi"
        assert result.eac is not None

    def test_auto_falls_back_to_remaining_when_no_actuals(self) -> None:
        # AC=0 -> CPI undefined, PV=0 -> SPI undefined -> only remaining left.
        result = forecast(1000, 0, 0, 0)
        assert result.method == "remaining"
        assert result.eac == _d(1000)

    def test_explicit_method_selects_that_variant(self) -> None:
        result = forecast(1000, 800, 600, 700, method="remaining")
        assert result.method == "remaining"
        assert result.eac == _d(1100)

    def test_unknown_method_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown method"):
            forecast(1000, 800, 600, 700, method="bogus")

    def test_negative_money_raises(self) -> None:
        with pytest.raises(ValueError, match="cannot be negative"):
            forecast(1000, 800, 600, -1)

    def test_method_names_match_public_tuple(self) -> None:
        assert EAC_METHODS == ("auto", "remaining", "cpi", "combined")

    def test_perfect_project_lands_on_budget(self) -> None:
        result = forecast(500, 500, 500, 500)
        assert result.eac == _d(500)
        assert result.vac == _d(0)
        assert result.cpi == 1.0
        assert result.spi == 1.0

    def test_etc_and_vac_consistent(self) -> None:
        result = forecast(1000, 800, 600, 700, method="remaining")
        assert result.etc == result.eac - result.ac
        assert result.vac == result.bac - result.eac

    def test_drivers_are_plain_language(self) -> None:
        result = forecast(1000, 800, 600, 700, currency="EUR")
        assert result.drivers
        joined = " ".join(result.drivers)
        assert "CPI" in joined and "SPI" in joined
        # Over budget project: driver must say so.
        assert "over budget" in joined.lower()

    def test_drivers_flag_no_actuals(self) -> None:
        result = forecast(1000, 0, 0, 0)
        joined = " ".join(result.drivers).lower()
        assert "no actual cost" in joined


class TestInternationalRobustness:
    """No hardcoded currency, minor-unit count, locale or date format."""

    def test_currency_is_only_a_label(self) -> None:
        eur = forecast(1000, 800, 600, 700, currency="EUR")
        jpy = forecast(1000, 800, 600, 700, currency="JPY")
        # Same maths regardless of the currency label.
        assert eur.eac == jpy.eac
        assert eur.currency == "EUR"
        assert jpy.currency == "JPY"

    def test_no_currency_defaults_to_none(self) -> None:
        result = forecast(1000, 800, 600, 700)
        assert result.currency is None

    def test_zero_decimal_currency_quantum(self) -> None:
        # JPY has no minor unit; forecast should round to whole numbers.
        result = forecast(1000, 800, 600, 700, currency="JPY", quantum=Decimal("1"))
        assert result.eac is not None
        assert result.eac == result.eac.to_integral_value()

    def test_three_decimal_currency_quantum(self) -> None:
        # KWD has three minor digits.
        eac = compute_eac_cpi(_d(1000), compute_cpi(_d(600), _d(700)), quantum=Decimal("0.001"))
        assert eac is not None
        assert eac.as_tuple().exponent == -3

    def test_as_of_defaults_to_iso_8601(self) -> None:
        result = forecast(1000, 800, 600, 700)
        assert result.as_of is not None
        # ISO 8601 date: YYYY-MM-DD, no locale formatting.
        year, month, day = result.as_of.split("-")
        assert len(year) == 4 and len(month) == 2 and len(day) == 2

    def test_as_of_passthrough(self) -> None:
        result = forecast(1000, 800, 600, 700, as_of="2026-01-31")
        assert result.as_of == "2026-01-31"

    def test_money_stays_decimal_ratios_stay_float(self) -> None:
        result = forecast(1000, 800, 600, 700)
        assert isinstance(result.eac, Decimal)
        assert isinstance(result.cpi, float)

    def test_to_dict_is_json_safe_money_as_string(self) -> None:
        payload = forecast(1000, 800, 600, 700, currency="EUR").to_dict()
        assert payload["inputs"]["bac"] == "1000"
        assert isinstance(payload["forecast"]["eac"], str)
        assert isinstance(payload["performance"]["cpi"], float)
        assert payload["currency"] == "EUR"

    def test_large_amounts_stay_exact(self) -> None:
        # Currencies with big nominal values (for example IDR) must not lose
        # precision through float.
        result = forecast("100000000000.99", "50000000000", "40000000000", "42000000000")
        assert result.bac == Decimal("100000000000.99")


class TestEdgeCasesNeverCrash:
    """No input produces a 500, a NaN or an infinity."""

    def test_all_zeros_yield_defined_result(self) -> None:
        result = forecast(0, 0, 0, 0)
        assert result.cpi is None
        assert result.spi is None
        assert result.eac == _d(0)
        assert result.vac == _d(0)

    def test_no_forecast_field_is_nan_or_inf(self) -> None:
        result = forecast(1000, 800, 600, 700)
        for ratio in (result.cpi, result.spi, result.tcpi_bac, result.tcpi_eac):
            if ratio is not None:
                assert math.isfinite(ratio)

    def test_ev_exceeds_bac_after_scope_change(self) -> None:
        # remaining = 1000 - 1200 < 0; must not crash.
        result = forecast(1000, 800, 1200, 900, method="remaining")
        assert result.eac == _d(700)

    def test_eac_cpi_never_infinite(self) -> None:
        # CPI == 0 (EV=0, AC>0) -> cost-trend EAC undefined, not infinity.
        assert compute_eac_cpi(_d(1000), compute_cpi(_d(0), _d(200))) is None

    def test_low_level_indices_guard_zero(self) -> None:
        assert compute_cpi(_d(1), _d(0)) is None
        assert compute_spi(_d(1), _d(0)) is None

    def test_variance_helpers_are_decimal(self) -> None:
        assert isinstance(compute_sv(_d(600), _d(800)), Decimal)
        assert isinstance(compute_cv(_d(600), _d(700)), Decimal)

    def test_etc_vac_none_when_eac_none(self) -> None:
        assert compute_etc(None, _d(1)) is None
        assert compute_vac(_d(1), None) is None

    def test_combined_none_when_index_undefined(self) -> None:
        assert compute_eac_combined(_d(700), _d(1000), _d(600), None, 0.9) is None


class TestAggregateElements:
    """Dataset aggregation, including the empty-dataset guard."""

    def test_sums_elements(self) -> None:
        totals = aggregate_elements(
            [
                {"bac": 600, "pv": 500, "ev": 400, "ac": 450},
                {"bac": 400, "pv": 300, "ev": 200, "ac": 250},
            ],
        )
        assert totals["bac"] == _d(1000)
        assert totals["ev"] == _d(600)

    def test_missing_keys_count_as_zero(self) -> None:
        totals = aggregate_elements([{"bac": 100}])
        assert totals["bac"] == _d(100)
        assert totals["ev"] == _d(0)

    def test_empty_dataset_raises(self) -> None:
        with pytest.raises(ValueError, match="empty dataset"):
            aggregate_elements([])

    def test_invalid_element_value_raises(self) -> None:
        with pytest.raises(ValueError, match="invalid"):
            aggregate_elements([{"bac": "oops"}])

    def test_totals_feed_forecast(self) -> None:
        totals = aggregate_elements(
            [
                {"bac": 600, "pv": 400, "ev": 300, "ac": 350},
                {"bac": 400, "pv": 400, "ev": 300, "ac": 350},
            ],
        )
        result = forecast(totals["bac"], totals["pv"], totals["ev"], totals["ac"])
        assert result.bac == _d(1000)
        assert result.ev == _d(600)
