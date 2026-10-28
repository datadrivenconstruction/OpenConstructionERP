# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure price-index math.

These exercise :mod:`app.modules.price_index.index_math` directly with plain
``Decimal`` / ``dict`` inputs - no database, FastAPI or ORM - so they run on any
interpreter, exactly like the formwork / field-time engine tests.

They lock in the contract the base-to-current adjustment depends on: the
temporal factor is the ratio of two index points, the location factor is the
ratio of two regional factors (missing regions default to the national
baseline of 1), and the adjusted amount is ``amount * temporal * location``
rounded to two decimal places with ``ROUND_HALF_UP`` - never float.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.price_index import index_math as pim

D = Decimal


# ── resolve_factor ────────────────────────────────────────────────────────────


def test_resolve_factor_basic_ratio() -> None:
    points = {"2019-01": "1.000000", "2026-01": "1.400000"}
    assert pim.resolve_factor(points, "2019-01", "2026-01") == D("1.400000")


def test_resolve_factor_same_period_is_one() -> None:
    points = {"2023-01": "1.24"}
    assert pim.resolve_factor(points, "2023-01", "2023-01") == D("1.000000")


def test_resolve_factor_falling_costs_below_one() -> None:
    points = {"a": "2", "b": "1"}
    assert pim.resolve_factor(points, "a", "b") == D("0.500000")


def test_resolve_factor_rounds_half_up_to_six_dp() -> None:
    # 1.10 / 1.07 = 1.0280373831... -> 6 dp
    points = {"base": "1.07", "target": "1.10"}
    assert pim.resolve_factor(points, "base", "target") == D("1.028037")


def test_resolve_factor_accepts_decimal_and_str_values() -> None:
    points = {"base": D("1.0"), "target": "1.25"}
    assert pim.resolve_factor(points, "base", "target") == D("1.250000")


def test_resolve_factor_missing_base_raises() -> None:
    with pytest.raises(pim.PeriodNotFoundError) as excinfo:
        pim.resolve_factor({"2026-01": "1.4"}, "2019-01", "2026-01")
    assert excinfo.value.period == "2019-01"


def test_resolve_factor_missing_target_raises() -> None:
    with pytest.raises(pim.PeriodNotFoundError) as excinfo:
        pim.resolve_factor({"2019-01": "1.0"}, "2019-01", "2026-01")
    assert excinfo.value.period == "2026-01"


def test_resolve_factor_non_positive_base_raises() -> None:
    with pytest.raises(ValueError, match="non-positive"):
        pim.resolve_factor({"a": "0", "b": "1"}, "a", "b")


# ── location_multiplier ───────────────────────────────────────────────────────


def test_location_multiplier_ratio_of_two_regions() -> None:
    regions = {"HIGH_COST_METRO": "1.15", "LOW_COST_RURAL": "0.90"}
    # 1.15 / 0.90 = 1.27777... -> 6 dp HALF_UP
    assert pim.location_multiplier(regions, "LOW_COST_RURAL", "HIGH_COST_METRO") == D("1.277778")


def test_location_multiplier_target_only_applies_that_region() -> None:
    regions = {"HIGH_COST_METRO": "1.15"}
    assert pim.location_multiplier(regions, None, "HIGH_COST_METRO") == D("1.150000")


def test_location_multiplier_unknown_regions_default_to_one() -> None:
    regions = {"HIGH_COST_METRO": "1.15"}
    # target region has no stored factor -> treated as 1, base None -> 1
    assert pim.location_multiplier(regions, None, "SOMEWHERE_ELSE") == D("1.000000")


def test_location_multiplier_both_missing_is_one() -> None:
    assert pim.location_multiplier({}, None, None) == D("1.000000")
    assert pim.location_multiplier({}, "  ", "") == D("1.000000")


def test_location_multiplier_non_positive_stored_factor_treated_as_baseline() -> None:
    regions = {"BAD": "0", "GOOD": "1.2"}
    # a stored 0 on either side falls back to 1 rather than dividing by zero
    assert pim.location_multiplier(regions, "BAD", "GOOD") == D("1.200000")


# ── combined_factor ───────────────────────────────────────────────────────────


def test_combined_factor_multiplies_and_quantizes() -> None:
    assert pim.combined_factor("1.4", "1.2") == D("1.680000")
    assert pim.combined_factor("1.1", "1.05") == D("1.155000")


# ── adjust ────────────────────────────────────────────────────────────────────


def test_adjust_multiplies_all_three_and_rounds_two_dp() -> None:
    assert pim.adjust("100", "1.1", "1.05") == D("115.50")


def test_adjust_uses_decimal_half_up_not_float() -> None:
    # 1.005 is exact in Decimal, so HALF_UP rounds it UP to 1.01. A float
    # pipeline would store 1.00499999... and round DOWN to 1.00.
    assert pim.adjust("1.005", "1", "1") == D("1.01")
    assert pim.adjust("2.675", "1", "1") == D("2.68")


def test_adjust_zero_amount_stays_zero() -> None:
    assert pim.adjust("0", "1.4", "1.2") == D("0.00")


def test_adjust_end_to_end_matches_hand_calc() -> None:
    points = {"2019-01": "1.0", "2026-01": "1.4"}
    regions = {"HIGH_COST_METRO": "1.15", "LOW_COST_RURAL": "0.90"}
    temporal = pim.resolve_factor(points, "2019-01", "2026-01")
    location = pim.location_multiplier(regions, "LOW_COST_RURAL", "HIGH_COST_METRO")
    assert temporal == D("1.400000")
    assert location == D("1.277778")
    # 1000 * 1.400000 * 1.277778 = 1788.8892 -> 1788.89
    assert pim.adjust("1000", temporal, location) == D("1788.89")
    assert pim.combined_factor(temporal, location) == D("1.788889")


# ── to_decimal / quantize_factor ──────────────────────────────────────────────


def test_to_decimal_parses_supported_scalars() -> None:
    assert pim.to_decimal("1.23") == D("1.23")
    assert pim.to_decimal(5) == D("5")
    assert pim.to_decimal(D("2.5")) == D("2.5")
    # a float is routed through str() so no binary artefact leaks in
    assert pim.to_decimal(0.1) == D("0.1")


def test_to_decimal_rejects_bool_and_non_finite() -> None:
    with pytest.raises(ValueError, match="boolean"):
        pim.to_decimal(True)
    with pytest.raises(ValueError, match="finite"):
        pim.to_decimal(D("NaN"))
    with pytest.raises(ValueError, match="finite"):
        pim.to_decimal(D("Infinity"))


def test_to_decimal_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="cannot parse"):
        pim.to_decimal("not-a-number")


def test_quantize_factor_six_dp_half_up() -> None:
    assert pim.quantize_factor("1") == D("1.000000")
    assert pim.quantize_factor("1.2777777") == D("1.277778")


# ── period_for_date ───────────────────────────────────────────────────────────


def test_period_for_date_drops_the_day() -> None:
    assert pim.period_for_date(date(2019, 3, 7)) == "2019-03"
    assert pim.period_for_date(date(2019, 3, 31)) == "2019-03"


def test_period_for_date_zero_pads_month() -> None:
    assert pim.period_for_date(date(2026, 1, 1)) == "2026-01"
    assert pim.period_for_date(date(2026, 12, 1)) == "2026-12"


def test_period_for_date_feeds_resolve_factor() -> None:
    # The whole point of period_for_date: two capture dates in the same months
    # as the series points resolve to the series ratio.
    points = {"2019-01": "1.0", "2026-01": "1.4"}
    base = pim.period_for_date(date(2019, 1, 15))
    target = pim.period_for_date(date(2026, 1, 20))
    assert pim.resolve_factor(points, base, target) == D("1.400000")
