# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure unit tests for the 6D Phase 2 whole-life engine.

Imports only ``app.modules.carbon.lcc`` - a leaf module with no app / database
imports - so the whole file runs on the local Python 3.11 runner (the rest of
the app needs 3.12). Covers the ISO 15686-5 discounting / NPV, the B4/B5
replacement-cycle counting over a study period, the service-life lookup, the B6
operational-carbon math and the whole-life rollups.

Money and carbon are Decimal end to end - a float regression in a present-value
calculation would fail here first.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.carbon import lcc

# -- net_present_value ------------------------------------------------------


def test_npv_year_zero_not_discounted() -> None:
    assert lcc.net_present_value(1000, "0.05", 0) == Decimal("1000")


def test_npv_zero_rate_not_discounted() -> None:
    assert lcc.net_present_value(1000, 0, 5) == Decimal("1000")


def test_npv_discounts_future_cost() -> None:
    # 1000 / 1.05^2 = 907.0294... -> quantize to cents
    result = lcc.net_present_value(1000, "0.05", 2)
    assert result.quantize(Decimal("0.01")) == Decimal("907.03")
    assert isinstance(result, Decimal)


def test_npv_negative_years_raises() -> None:
    with pytest.raises(ValueError, match="years"):
        lcc.net_present_value(1000, "0.05", -1)


def test_npv_rate_at_or_below_minus_one_raises() -> None:
    with pytest.raises(ValueError, match="discount_rate"):
        lcc.net_present_value(1000, "-1", 3)


# -- present_value_annuity --------------------------------------------------


def test_annuity_zero_rate_is_linear() -> None:
    assert lcc.present_value_annuity(2000, 0, 60) == Decimal("120000")


def test_annuity_zero_years_is_zero() -> None:
    assert lcc.present_value_annuity(2000, "0.05", 0) == Decimal("0")


def test_annuity_equals_sum_of_per_year_npvs() -> None:
    # The annuity must be identical, term for term, to discounting each year.
    expected = sum((lcc.net_present_value(100, "0.05", y) for y in range(1, 4)), Decimal("0"))
    assert lcc.present_value_annuity(100, "0.05", 3) == expected


# -- replacement_years ------------------------------------------------------


def test_replacement_years_strictly_inside_period() -> None:
    assert lcc.replacement_years(25, 60) == [25, 50]


def test_replacement_years_final_year_not_replaced() -> None:
    # A replacement in the final year is not modelled (asset is disposed).
    assert lcc.replacement_years(30, 60) == [30]
    assert lcc.replacement_years(60, 60) == []


def test_replacement_years_service_life_outlasts_period() -> None:
    assert lcc.replacement_years(80, 60) == []


def test_replacement_years_guard_non_positive() -> None:
    assert lcc.replacement_years(0, 60) == []
    assert lcc.replacement_years(25, 0) == []


def test_replacement_count_matches_ceil_formula() -> None:
    # count == ceil(P / L) - 1
    assert lcc.replacement_years(20, 60) == [20, 40]  # ceil(3) - 1 = 2


# -- replacement_present_value ----------------------------------------------


def test_replacement_pv_zero_rate_is_count_times_cost() -> None:
    # 25/60 -> replace at 25 and 50 -> 2 x 50000 = 100000 undiscounted
    assert lcc.replacement_present_value(50000, 25, 60, 0) == Decimal("100000")


def test_replacement_pv_zero_cost_is_zero() -> None:
    assert lcc.replacement_present_value(0, 25, 60, "0.05") == Decimal("0")


def test_replacement_pv_discounted_is_below_nominal() -> None:
    discounted = lcc.replacement_present_value(50000, 25, 60, "0.035")
    assert discounted < Decimal("100000")
    assert discounted > Decimal("0")


# -- compute_life_cycle_cost ------------------------------------------------


def test_lcc_zero_discount_is_plain_sum() -> None:
    # capex 100000 + opex 2000*60=120000 + repl 50000*2=100000 + eol 10000
    # = 330000 gross, less the residual value of the component installed at
    # year 50 (15 of its 25 years unexpired at year 60): 50000 * 15/25 = 30000.
    result = lcc.compute_life_cycle_cost(
        capex=100000,
        annual_opex=2000,
        replacement_cost=50000,
        service_life_years=25,
        eol_cost=10000,
        discount_rate=0,
        study_period_years=60,
    )
    assert result["residual_value"] == Decimal("30000")
    # Zero discount rate: the residual present value equals its nominal value.
    assert result["residual_value_pv"] == Decimal("30000")
    assert result["whole_life_cost"] == Decimal("300000")
    assert result["replacement_count"] == 2
    assert result["replacement_years"] == [25, 50]


def test_lcc_components_sum_to_whole_life() -> None:
    result = lcc.compute_life_cycle_cost(
        capex="120000",
        annual_opex="3500",
        replacement_cost="40000",
        service_life_years=20,
        eol_cost="8000",
        discount_rate="0.035",
        study_period_years=60,
    )
    parts = result["capex_pv"] + result["opex_pv"] + result["replacement_pv"] + result["eol_pv"]
    # Whole-life cost is the discounted parts less the residual-value credit.
    assert parts - result["residual_value_pv"] == result["whole_life_cost"]
    # The component re-installed at year 40 reaches exactly the end of its
    # 20-year life at the year-60 study end, so nothing is unexpired: residual 0.
    assert result["residual_value"] == Decimal("0")
    assert result["residual_value_pv"] == Decimal("0")
    # Capex is booked at year 0, never discounted.
    assert result["capex_pv"] == Decimal("120000")
    # Everything discounted is strictly below its nominal counterpart.
    assert result["opex_pv"] < Decimal("3500") * 60
    assert result["eol_pv"] < Decimal("8000")


def test_lcc_no_replacement_when_life_exceeds_period() -> None:
    result = lcc.compute_life_cycle_cost(
        capex=1000,
        annual_opex=0,
        replacement_cost=500,
        service_life_years=100,
        eol_cost=0,
        discount_rate="0.05",
        study_period_years=60,
    )
    assert result["replacement_count"] == 0
    assert result["replacement_pv"] == Decimal("0")
    # Original capex-funded component, never replaced, keeps 40 of its 100
    # years at the year-60 study end: nominal residual 1000 * 40/100 = 400,
    # credited back at its year-60 present value.
    assert result["residual_value"] == Decimal("400")
    assert Decimal("0") < result["residual_value_pv"] < Decimal("400")
    # Whole-life cost is capex less the discounted residual credit.
    assert result["whole_life_cost"] == Decimal("1000") - result["residual_value_pv"]
    assert result["whole_life_cost"] < Decimal("1000")


# -- residual_value ---------------------------------------------------------


def test_residual_value_no_replacement_prorates_capex() -> None:
    # Never replaced: basis is capex, 40 of 100 years unexpired at year 60.
    assert lcc.residual_value(
        capex=1000, replacement_cost=500, service_life_years=100, study_period_years=60
    ) == Decimal("400")


def test_residual_value_after_replacement_prorates_replacement_cost() -> None:
    # Replaced at 25 and 50; the year-50 install keeps 15 of 25 years.
    assert lcc.residual_value(
        capex=100000, replacement_cost=50000, service_life_years=25, study_period_years=60
    ) == Decimal("30000")


def test_residual_value_zero_at_exact_end_of_life() -> None:
    # Re-installed at year 40, a 20-year life ends exactly at the year-60 study
    # end - nothing unexpired.
    assert lcc.residual_value(capex=1, replacement_cost=1, service_life_years=20, study_period_years=60) == Decimal("0")


def test_residual_value_guards_non_positive() -> None:
    rv = lcc.residual_value
    # Unknown service life or a zero-length study yields no residual.
    assert rv(capex=1000, replacement_cost=9, service_life_years=0, study_period_years=60) == Decimal("0")
    assert rv(capex=1000, replacement_cost=9, service_life_years=25, study_period_years=0) == Decimal("0")
    # No basis (capex and replacement cost both zero) -> no residual.
    assert rv(capex=0, replacement_cost=0, service_life_years=100, study_period_years=60) == Decimal("0")


def test_lcc_include_residual_value_false_reproduces_pre_residual() -> None:
    common = {
        "capex": 100000,
        "annual_opex": 2000,
        "replacement_cost": 50000,
        "service_life_years": 25,
        "eol_cost": 10000,
        "discount_rate": 0,
        "study_period_years": 60,
    }
    with_residual = lcc.compute_life_cycle_cost(**common)
    without = lcc.compute_life_cycle_cost(**common, include_residual_value=False)
    assert without["residual_value"] == Decimal("0")
    assert without["residual_value_pv"] == Decimal("0")
    assert without["whole_life_cost"] == Decimal("330000")
    # The credit is exactly the difference between the two runs.
    assert without["whole_life_cost"] - with_residual["whole_life_cost"] == with_residual["residual_value_pv"]


# -- operational carbon (B6) ------------------------------------------------


def test_annual_operational_carbon() -> None:
    assert lcc.annual_operational_carbon(10000, "0.38") == Decimal("3800.00")


def test_operational_carbon_over_period() -> None:
    rolled = lcc.operational_carbon_over_period(10000, "0.38", 60)
    assert rolled["annual_carbon_kg"] == Decimal("3800.00")
    assert rolled["carbon_kg"] == Decimal("228000.00")
    assert rolled["study_period_years"] == 60


def test_operational_carbon_tiny_factor_no_float_drift() -> None:
    # 1_000_000 kWh x 0.00012 = 120.00 exactly (float would drift).
    assert lcc.annual_operational_carbon(1_000_000, "0.00012") == Decimal("120.00000")


def test_cost_of_carbon() -> None:
    # 2000 kg = 2 t x 100/t = 200
    assert lcc.cost_of_carbon(2000, 100) == Decimal("200")


# -- element_annual_energy_kwh -----------------------------------------------


def test_energy_from_asset_info_explicit() -> None:
    assert lcc.element_annual_energy_kwh({}, {"annual_energy_kwh": "1200"}) == (Decimal("1200"), "asset_info")


def test_energy_from_element_quantities() -> None:
    assert lcc.element_annual_energy_kwh({"energy_kwh_per_year": "900"}, {}) == (Decimal("900"), "element")


def test_energy_from_power_rating() -> None:
    # 1000 W x 2000 h / 1000 = 2000 kWh/yr
    picked = lcc.element_annual_energy_kwh({}, {"power_rating_w": "1000", "annual_operating_hours": "2000"})
    assert picked == (Decimal("2000"), "asset_power_rating")


def test_energy_asset_info_beats_element() -> None:
    picked = lcc.element_annual_energy_kwh({"annual_energy_kwh": "500"}, {"annual_energy_kwh": "800"})
    assert picked == (Decimal("800"), "asset_info")


def test_energy_none_when_absent() -> None:
    assert lcc.element_annual_energy_kwh({}, {}) is None
    assert lcc.element_annual_energy_kwh(None, None) is None
    # Power without hours is not enough.
    assert lcc.element_annual_energy_kwh({}, {"power_rating_w": "1000"}) is None


# -- service_life_from_asset_info --------------------------------------------


def test_service_life_from_asset_info() -> None:
    assert lcc.service_life_from_asset_info({"service_life_years": "25"}) == 25


def test_service_life_from_properties_fallback() -> None:
    assert lcc.service_life_from_asset_info({}, {"design_life_years": "40"}) == 40


def test_service_life_default_when_absent() -> None:
    assert lcc.service_life_from_asset_info({}, {}, default=30) == 30
    assert lcc.service_life_from_asset_info({}, {}) is None


def test_service_life_ignores_zero_and_negative() -> None:
    assert lcc.service_life_from_asset_info({"service_life_years": "0"}, default=30) == 30


# -- derive_lcc_inputs -------------------------------------------------------


def test_derive_high_confidence_from_asset_register() -> None:
    inputs = lcc.derive_lcc_inputs(asset_info={"capex": "5000", "service_life_years": "20"})
    assert inputs is not None
    assert inputs["confidence"] == "high"
    assert inputs["capex"] == Decimal("5000")
    assert inputs["service_life_years"] == 20
    # Modelled opex = 2% of capex by default.
    assert inputs["annual_opex"] == Decimal("5000") * Decimal("0.02")
    # Replacement defaults to like-for-like capex.
    assert inputs["replacement_cost"] == Decimal("5000")


def test_derive_medium_confidence_capex_only() -> None:
    inputs = lcc.derive_lcc_inputs(asset_info={"capex": "5000"}, default_service_life_years=30)
    assert inputs is not None
    assert inputs["confidence"] == "medium"
    assert inputs["service_life_years"] == 30


def test_derive_low_confidence_all_modelled() -> None:
    inputs = lcc.derive_lcc_inputs(asset_info={}, default_capex="1000")
    assert inputs is not None
    assert inputs["confidence"] == "low"
    assert inputs["capex"] == Decimal("1000")


def test_derive_none_without_any_capex() -> None:
    assert lcc.derive_lcc_inputs(asset_info={}, default_capex=None) is None
    assert lcc.derive_lcc_inputs(asset_info={}, default_capex="0") is None


def test_derive_reads_explicit_opex_and_eol() -> None:
    inputs = lcc.derive_lcc_inputs(
        asset_info={"capex": "10000", "annual_opex": "750", "eol_cost": "1200", "replacement_cost": "9000"},
    )
    assert inputs is not None
    assert inputs["annual_opex"] == Decimal("750")
    assert inputs["eol_cost"] == Decimal("1200")
    assert inputs["replacement_cost"] == Decimal("9000")


# -- whole_life_carbon -------------------------------------------------------


def test_whole_life_carbon_breakdown() -> None:
    carbon = lcc.whole_life_carbon(
        a1a3=100,
        a4=10,
        a5=5,
        b_embodied=20,
        b6_operational=200,
        c_end_of_life=15,
        d_beyond=-5,
    )
    assert carbon["a1a5"] == Decimal("115")
    assert carbon["b_total"] == Decimal("220")  # 20 embodied + 200 operational
    # whole-life = A1-A5 + B + C, module D excluded.
    assert carbon["whole_life_total"] == Decimal("350")
    assert carbon["d_beyond"] == Decimal("-5")


def test_whole_life_carbon_default_d_is_zero() -> None:
    carbon = lcc.whole_life_carbon(a1a3=1, a4=0, a5=0, b_embodied=0, b6_operational=0, c_end_of_life=0)
    assert carbon["d_beyond"] == Decimal("0")
    assert carbon["whole_life_total"] == Decimal("1")


# -- summarize_life_cycle_cost -----------------------------------------------


def test_summarize_lcc_from_objects() -> None:
    entries = [
        SimpleNamespace(
            capex=Decimal("100"),
            opex_pv=Decimal("50"),
            replacement_pv=Decimal("30"),
            eol_pv=Decimal("10"),
            residual_value_pv=Decimal("5"),
            whole_life_cost=Decimal("185"),
        ),
        SimpleNamespace(
            capex=Decimal("200"),
            opex_pv=Decimal("60"),
            replacement_pv=Decimal("0"),
            eol_pv=Decimal("20"),
            residual_value_pv=Decimal("15"),
            whole_life_cost=Decimal("265"),
        ),
    ]
    summary = lcc.summarize_life_cycle_cost(entries)
    assert summary["capex"] == Decimal("300")
    assert summary["opex_pv"] == Decimal("110")
    assert summary["residual_value_pv"] == Decimal("20")
    assert summary["whole_life_cost"] == Decimal("450")
    assert summary["entry_count"] == 2


def test_summarize_lcc_from_dicts_and_missing_fields() -> None:
    entries = [{"capex": "100", "whole_life_cost": "100"}, {"opex_pv": "25"}]
    summary = lcc.summarize_life_cycle_cost(entries)
    assert summary["capex"] == Decimal("100")
    assert summary["opex_pv"] == Decimal("25")
    assert summary["whole_life_cost"] == Decimal("100")
    assert summary["entry_count"] == 2


def test_summarize_lcc_derives_residual_for_persisted_rows_without_column() -> None:
    # A persisted LCC row has no residual_value_pv attribute, so the rollup
    # derives the credit from the ISO 15686-5 identity: components minus the
    # stored whole_life_cost. Here 100 + 40 + 0 + 10 - 135 = 15.
    row = SimpleNamespace(
        capex=Decimal("100"),
        opex_pv=Decimal("40"),
        replacement_pv=Decimal("0"),
        eol_pv=Decimal("10"),
        whole_life_cost=Decimal("135"),
    )
    assert not hasattr(row, "residual_value_pv")
    summary = lcc.summarize_life_cycle_cost([row])
    assert summary["residual_value_pv"] == Decimal("15")
    assert summary["whole_life_cost"] == Decimal("135")


def test_summarize_lcc_pre_residual_rows_derive_zero() -> None:
    # A row written before the residual credit has whole_life_cost equal to the
    # sum of its components, so the derived residual is 0 (no spurious credit).
    row = SimpleNamespace(
        capex=Decimal("100"),
        opex_pv=Decimal("40"),
        replacement_pv=Decimal("0"),
        eol_pv=Decimal("10"),
        whole_life_cost=Decimal("150"),
    )
    summary = lcc.summarize_life_cycle_cost([row])
    assert summary["residual_value_pv"] == Decimal("0")


def test_summarize_lcc_empty() -> None:
    summary = lcc.summarize_life_cycle_cost([])
    assert summary["whole_life_cost"] == Decimal("0")
    assert summary["entry_count"] == 0
