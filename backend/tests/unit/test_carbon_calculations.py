# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Deterministic calculation tests for the Carbon module.

Covers:
    * BOQ-position embodied carbon (concrete reference case: 100 m³ @ density
      2400 kg/m³, factor 0.13 kgCO2e/kg → 31 200 kgCO2e).
    * Multi-position sum with Decimal precision.
    * Lifecycle stage breakdown: A1-A3 / A4-A5 (product+construction),
      B (use), C (end-of-life), D (credits) totals — each bucket verified
      individually and as a cradle-to-grave total.
    * Extremely small factors (e.g. 0.00012) preserved without float drift.
    * Tonne ↔ kg conversion path in end-to-end calc.
    * Scope-1 / scope-2 emission math.
    * Intensity metric (kgCO2e / m²).
    * Target-met logic edge cases.

All assertions use ``Decimal`` string equality — float is prohibited in
this module (factors like 0.00012 lose precision in float).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.carbon.service import (
    UnitMismatchError,
    compare_alternatives,
    compute_carbon_intensity,
    compute_embodied_entry_carbon,
    compute_inventory_totals,
    compute_scope1_co2e,
    compute_scope2_co2e,
    is_target_met,
    normalise_quantity_to_factor_unit,
)

# ── Reference constants ────────────────────────────────────────────────────

# ICE DB v3.0: concrete (general) GWP ≈ 0.13 kgCO2e/kg
_CONCRETE_FACTOR = Decimal("0.13")  # kgCO2e / kg
_CONCRETE_DENSITY = Decimal("2400")  # kg / m³


# ── Case 1: Classic BOQ concrete slab (the canonical reference) ────────────


def test_concrete_100m3_basic_carbon() -> None:
    """100 m³ concrete @ 0.13 kgCO2e/kg, density 2400 kg/m³ → 31 200 kgCO2e.

    This is the canonical reference case. Any regression in unit normalisation
    or Decimal multiplication would break this first.
    """
    result = compute_embodied_entry_carbon(
        quantity=Decimal("100"),
        quantity_unit="m3",
        factor_value=_CONCRETE_FACTOR,
        factor_unit="kg",
        density=_CONCRETE_DENSITY,
    )
    # 100 m³ × 2400 kg/m³ = 240 000 kg × 0.13 kgCO2e/kg = 31 200 kgCO2e
    assert result == Decimal("31200.00"), f"expected 31200.00, got {result}"


# ── Case 2: Same calc via normalise_quantity_to_factor_unit separately ─────


def test_normalise_then_multiply_matches_combined() -> None:
    """Splitting normalise + multiply must produce identical result."""
    normalised = normalise_quantity_to_factor_unit(
        Decimal("100"),
        "m3",
        "kg",
        density_kg_per_m3=_CONCRETE_DENSITY,
    )
    carbon = normalised * _CONCRETE_FACTOR
    assert carbon == Decimal("31200.00")


# ── Case 3: Multi-position sum ─────────────────────────────────────────────


def test_multi_position_sum_three_materials() -> None:
    """Three BOQ positions; sum must match individual results, no float drift.

    Using Decimal-literal factors to avoid IEEE-754 rounding:
        concrete : 100 m³ @ 0.13 kgCO2e/kg  density 2400  → 31 200 kgCO2e
        steel    : 500 kg  @ 1.46 kgCO2e/kg              →    730 kgCO2e
        timber   : 10  m³  @ 0.46 kgCO2e/kg  density 600   →  2 760 kgCO2e
        ─────────────────────────────────────────────────────────────────────
        total                                              → 34 690 kgCO2e
    """
    concrete = compute_embodied_entry_carbon(
        Decimal("100"),
        "m3",
        Decimal("0.13"),
        "kg",
        density=Decimal("2400"),
    )
    steel = compute_embodied_entry_carbon(
        Decimal("500"),
        "kg",
        Decimal("1.46"),
        "kg",
    )
    timber = compute_embodied_entry_carbon(
        Decimal("10"),
        "m3",
        Decimal("0.46"),
        "kg",
        density=Decimal("600"),
    )
    total = concrete + steel + timber
    assert concrete == Decimal("31200.00")
    assert steel == Decimal("730.00")
    assert timber == Decimal("2760.00")
    assert total == Decimal("34690.00"), f"total mismatch: {total}"


# ── Case 4: Lifecycle stage breakdown (A1-A3/A4/A5/B/C/D) ─────────────────


def _make_stage_entries() -> list[SimpleNamespace]:
    """Fabricate embodied entries across all six lifecycle buckets."""
    return [
        # Product stage A1-A3: structural frame
        SimpleNamespace(stage="a1a3", carbon_kg=Decimal("15000")),
        SimpleNamespace(stage="a1a3", carbon_kg=Decimal("8000")),
        # Transport A4: concrete delivery 400 tkm × 0.11 kgCO2e/tkm
        SimpleNamespace(stage="a4", carbon_kg=Decimal("44")),
        # Construction installation A5
        SimpleNamespace(stage="a5", carbon_kg=Decimal("320")),
        # Use B (maintenance replacements)
        SimpleNamespace(stage="b", carbon_kg=Decimal("500")),
        # Use-stage sub-codes fold to B
        SimpleNamespace(stage="b3", carbon_kg=Decimal("200")),
        # End-of-life C
        SimpleNamespace(stage="c", carbon_kg=Decimal("180")),
        # C sub-code
        SimpleNamespace(stage="c4", carbon_kg=Decimal("90")),
        # D credits (negative — beyond system boundary, excluded from total)
        SimpleNamespace(stage="d", carbon_kg=Decimal("-1200")),
    ]


def test_lifecycle_stage_breakdown_buckets() -> None:
    """Each stage bucket sums correctly; B sub-codes fold to B, D excluded."""
    entries = _make_stage_entries()
    totals = compute_inventory_totals(uuid.uuid4(), entries)

    assert Decimal(totals["embodied_a1a3"]) == Decimal("23000")
    assert Decimal(totals["embodied_a4"]) == Decimal("44")
    assert Decimal(totals["embodied_a5"]) == Decimal("320")
    assert Decimal(totals["embodied_b"]) == Decimal("700"), "b3 sub-code must fold into b bucket"
    assert Decimal(totals["embodied_c"]) == Decimal("270"), "c4 sub-code must fold into c bucket"
    assert Decimal(totals["embodied_d"]) == Decimal("-1200"), (
        "D credits must be negative (benefits beyond system boundary)"
    )


def test_lifecycle_a1a5_aggregation() -> None:
    """embodied_a1a5 = a1a3 + a4 + a5 (per EN 15978 convention)."""
    entries = _make_stage_entries()
    totals = compute_inventory_totals(uuid.uuid4(), entries)
    expected_a1a5 = Decimal("23000") + Decimal("44") + Decimal("320")
    assert Decimal(totals["embodied_a1a5"]) == expected_a1a5


def test_lifecycle_total_excludes_d_credits() -> None:
    """Total (cradle-to-grave) excludes module D (beyond system boundary).

    total = A1-A5 + B + C + scope1/2/3 (operational)
    D is informational only and must NOT inflate or deflate the headline.
    """
    entries = _make_stage_entries()
    totals = compute_inventory_totals(uuid.uuid4(), entries)

    a1a5 = Decimal("23000") + Decimal("44") + Decimal("320")
    b = Decimal("700")
    c = Decimal("270")
    expected_total = a1a5 + b + c  # scope 1/2/3 = 0 (not provided)
    assert Decimal(totals["total"]) == expected_total, "D credits must not be added to the cradle-to-grave total"


def test_lifecycle_total_with_scopes() -> None:
    """Total includes scope 1 + 2 + 3 operational emissions."""
    from types import SimpleNamespace as NS

    entries = [SimpleNamespace(stage="a1a3", carbon_kg=Decimal("1000"))]
    s1 = [NS(total_co2e_kg=Decimal("200"))]
    s2 = [NS(total_co2e_kg=Decimal("50"))]
    s3 = [NS(total_co2e_kg=Decimal("30"))]
    totals = compute_inventory_totals(uuid.uuid4(), entries, s1, s2, s3)
    # 1000 + 200 + 50 + 30 = 1280
    assert Decimal(totals["total"]) == Decimal("1280")
    assert Decimal(totals["scope1"]) == Decimal("200")
    assert Decimal(totals["scope2"]) == Decimal("50")
    assert Decimal(totals["scope3"]) == Decimal("30")
    assert Decimal(totals["operational"]) == Decimal("250")


# ── Case 5: Very small factor — Decimal precision ──────────────────────────


def test_tiny_factor_no_float_drift() -> None:
    """Factor 0.00012 kgCO2e/kg (e.g. a refrigerant trace) must not lose
    precision. In float: 1000000 × 0.00012 == 119.99999999999998.
    In Decimal: 1000000 × Decimal('0.00012') == 120.00000.
    """
    result = compute_embodied_entry_carbon(
        Decimal("1000000"),
        "kg",
        Decimal("0.00012"),
        "kg",
    )
    assert result == Decimal("120.00000"), f"float drift detected — expected 120.00000, got {result}"


def test_very_small_factor_string_input() -> None:
    """Accepting factor as string '0.000075' must preserve full precision."""
    result = compute_embodied_entry_carbon(
        "200000",
        "kg",
        "0.000075",
        "kg",
    )
    assert result == Decimal("15.000000")


# ── Case 6: Tonne input → kg factor ───────────────────────────────────────


def test_tonne_to_kg_factor_conversion() -> None:
    """50 t of structural steel × 1.46 kgCO2e/kg → 73 000 kgCO2e.

    Conversion path: 50 t → 50 000 kg (factor ×1000), then × 1.46.
    """
    result = compute_embodied_entry_carbon(
        Decimal("50"),
        "t",
        Decimal("1.46"),
        "kg",
    )
    assert result == Decimal("73000.00")


# ── Case 7: Scope-1 diesel ──────────────────────────────────────────────────


def test_scope1_diesel_2000L() -> None:
    """2000 L diesel × 2.68 kgCO2e/L = 5360 kgCO2e."""
    result = compute_scope1_co2e(Decimal("2000"), "diesel", Decimal("2.68"))
    assert result == Decimal("5360.00")


# ── Case 8: Scope-2 electricity ────────────────────────────────────────────


def test_scope2_uk_electricity_2024() -> None:
    """50 000 kWh × 0.207 kgCO2e/kWh (DEFRA 2024 GB) = 10 350 kgCO2e."""
    result = compute_scope2_co2e(Decimal("50000"), Decimal("0.2070"))
    assert result == Decimal("10350.0000")


# ── Case 9: Intensity (kgCO2e / m²) ───────────────────────────────────────


def test_intensity_per_m2() -> None:
    """31 200 kgCO2e / 2400 m² GFA = 13 kgCO2e/m²."""
    result = compute_carbon_intensity(Decimal("31200"), Decimal("2400"))
    assert result == Decimal("13")


def test_intensity_zero_area_returns_zero() -> None:
    """Non-positive GFA must return 0 (no division-by-zero)."""
    assert compute_carbon_intensity(Decimal("31200"), Decimal("0")) == Decimal("0")
    assert compute_carbon_intensity(Decimal("31200"), Decimal("-1")) == Decimal("0")


# ── Case 10: Target-met logic ──────────────────────────────────────────────


def test_target_met_when_current_le_target() -> None:
    """Current value at exactly target_value counts as met."""
    target = SimpleNamespace(target_value=Decimal("5000"))
    assert is_target_met(target, Decimal("5000")) is True
    assert is_target_met(target, Decimal("4999")) is True
    assert is_target_met(target, Decimal("5001")) is False


def test_target_met_small_decimal() -> None:
    """Works with tiny Decimal values (e.g. intensity targets)."""
    target = SimpleNamespace(target_value=Decimal("12.5000"))
    assert is_target_met(target, Decimal("12.4999")) is True
    assert is_target_met(target, Decimal("12.5001")) is False


# ── Case 11: UnitMismatchError is raised (not silently wrong) ──────────────


def test_m3_to_kg_without_density_raises() -> None:
    """m3 → kg without density must raise UnitMismatchError, not return 0."""
    with pytest.raises(UnitMismatchError, match="density"):
        compute_embodied_entry_carbon(
            Decimal("100"),
            "m3",
            Decimal("0.13"),
            "kg",
        )


# ── Case 12: compare_alternatives ranking ─────────────────────────────────


def test_compare_alternatives_sorted_desc_by_savings() -> None:
    """Alternatives are ranked by savings_kg descending (best saving first)."""
    current = SimpleNamespace(
        factor_value_used=Decimal("0.13"),
        carbon_kg=Decimal("31200"),  # 100 m³ × 2400 × 0.13
    )
    alt_ggbs = SimpleNamespace(
        id=uuid.uuid4(),
        manual_override_factor=Decimal("0.07"),  # blended GGBS cement
        confidence="medium",
    )
    alt_timber = SimpleNamespace(
        id=uuid.uuid4(),
        manual_override_factor=Decimal("0.46"),  # CLT timber (higher than concrete)
        confidence="low",
    )
    results = compare_alternatives(current, [alt_ggbs, alt_timber])
    # GGBS saves more (factor 0.07 < 0.13), timber emits more
    assert results[0]["factor_value"] == Decimal("0.07"), "GGBS should be ranked first"
    # Timber has negative savings (higher factor) — still present in list
    assert results[-1]["factor_value"] == Decimal("0.46")
    # Savings for GGBS: 31200 - (31200/0.13 * 0.07) = 31200 - 16800 = 14400
    assert results[0]["savings_kg"] == Decimal("14400.000000")
