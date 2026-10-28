"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the international elemental / parametric cost model helpers.

These pin the behaviour of :mod:`app.modules.costmodel.elemental`, a pure,
database-free layer that builds an early-stage elemental cost estimate. The
focus is international robustness (no hardcoded currency, unit system, region
or locale; Decimal-exact money), clear guards for the edge cases (zero area,
negative or missing rate, empty element list, unknown unit), and explainability
(the total is returned with the breakdown that produced it).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.costmodel.elemental import (
    COST_MODEL_GLOSSARY,
    ElementInput,
    apply_regional_factor,
    build_elemental_estimate,
    cost_per_driver,
    element_total,
    explain,
    from_canonical_quantity,
    normalise_unit,
    supported_units,
    to_canonical_quantity,
    unit_dimension,
)

# ── element_total ───────────────────────────────────────────────────────────


def test_element_total_basic_decimal_exact() -> None:
    """Quantity times rate stays Decimal-exact (no binary-float drift)."""
    # 0.1 * 0.2 = 0.02 exactly under Decimal; float would give 0.020000...004.
    assert element_total(Decimal("0.1"), Decimal("0.2")) == Decimal("0.02")
    assert element_total("125", "12.50") == Decimal("1562.50")


def test_element_total_zero_rate_is_well_defined_zero() -> None:
    """A zero rate is a legitimate zero total, not an error."""
    assert element_total(Decimal("100"), Decimal("0")) == Decimal("0.00")


def test_element_total_negative_quantity_raises() -> None:
    with pytest.raises(ValueError, match="Quantity must be zero or positive"):
        element_total(Decimal("-1"), Decimal("10"))


def test_element_total_negative_rate_raises() -> None:
    with pytest.raises(ValueError, match="must be zero or positive"):
        element_total(Decimal("10"), Decimal("-5"))


def test_element_total_missing_rate_raises() -> None:
    with pytest.raises(ValueError, match="is missing"):
        element_total(Decimal("10"), None)


def test_element_total_non_finite_raises() -> None:
    with pytest.raises(ValueError, match="finite"):
        element_total(float("inf"), Decimal("10"))


# ── apply_regional_factor ───────────────────────────────────────────────────


def test_regional_factor_default_is_worldwide_no_op() -> None:
    """The documented worldwide default is 1: no regional adjustment."""
    assert apply_regional_factor(Decimal("1000")) == Decimal("1000.00")


def test_regional_factor_scales_amount() -> None:
    assert apply_regional_factor(Decimal("1000"), Decimal("1.12")) == Decimal("1120.00")


def test_regional_factor_zero_raises() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        apply_regional_factor(Decimal("1000"), Decimal("0"))


def test_regional_factor_negative_raises() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        apply_regional_factor(Decimal("1000"), Decimal("-0.5"))


# ── unit conversion (metric and imperial in, canonical metric out) ──────────


def test_normalise_unit_handles_superscript_and_spaces() -> None:
    assert normalise_unit("M²") == "m2"
    assert normalise_unit(" ft^2 ") == "ft2"
    assert normalise_unit("m³") == "m3"


def test_to_canonical_area_imperial_to_metric_exact() -> None:
    """100 square feet is exactly 9.290304 m2."""
    value, unit = to_canonical_quantity(Decimal("100"), "ft2")
    assert unit == "m2"
    assert value == Decimal("9.290304")


def test_to_canonical_area_metric_passthrough() -> None:
    value, unit = to_canonical_quantity(Decimal("50"), "m2")
    assert (value, unit) == (Decimal("50"), "m2")


def test_to_canonical_volume_and_length() -> None:
    vol, vol_unit = to_canonical_quantity(Decimal("1"), "ft3")
    assert vol_unit == "m3"
    assert vol == Decimal("0.028316846592")
    length, length_unit = to_canonical_quantity(Decimal("1"), "ft")
    assert (length, length_unit) == (Decimal("0.3048"), "m")


def test_to_canonical_count_is_dimensionless() -> None:
    value, unit = to_canonical_quantity(Decimal("7"), "each")
    assert (value, unit) == (Decimal("7"), "unit")


def test_from_canonical_round_trips_imperial() -> None:
    """Canonical metric converts back to the imperial display unit exactly."""
    assert from_canonical_quantity(Decimal("9.290304"), "ft2") == Decimal("100")


def test_to_canonical_unknown_unit_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported unit"):
        to_canonical_quantity(Decimal("1"), "furlong")


def test_to_canonical_negative_raises() -> None:
    with pytest.raises(ValueError, match="zero or positive"):
        to_canonical_quantity(Decimal("-1"), "m2")


def test_unit_dimension_and_supported_units() -> None:
    assert unit_dimension("ft2") == "area"
    assert unit_dimension("m3") == "volume"
    groups = supported_units()
    assert "ft2" in groups["area"]
    assert "m3" in groups["volume"]
    assert "unit" in groups["count"]


# ── cost_per_driver (cost per m2 of GFA, cost per unit) ──────────────────────


def test_cost_per_driver_metric() -> None:
    """1,000,000 over 500 m2 of GFA is 2000 per m2."""
    assert cost_per_driver(Decimal("1000000"), Decimal("500"), "m2") == Decimal("2000.00")


def test_cost_per_driver_imperial_matches_metric() -> None:
    """The benchmark is identical whether the driver is entered in m2 or ft2.

    5,000 ft2 == 464.5152 m2. Cost per m2 must be the same number regardless of
    which unit the area was captured in, proving the canonical-metric basis.
    """
    metric = cost_per_driver(Decimal("1000000"), Decimal("464.5152"), "m2")
    imperial = cost_per_driver(Decimal("1000000"), Decimal("5000"), "ft2")
    assert metric == imperial


def test_cost_per_driver_zero_driver_raises() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        cost_per_driver(Decimal("1000"), Decimal("0"), "m2")


# ── build_elemental_estimate ─────────────────────────────────────────────────


def test_build_estimate_empty_list_raises() -> None:
    with pytest.raises(ValueError, match="at least one element"):
        build_elemental_estimate([])


def test_build_estimate_missing_rate_raises() -> None:
    with pytest.raises(ValueError, match="no cost per unit"):
        build_elemental_estimate([ElementInput(name="Walls", quantity=Decimal("10"), unit="m2")])


def test_build_estimate_negative_quantity_raises() -> None:
    with pytest.raises(ValueError, match="zero or positive"):
        build_elemental_estimate(
            [ElementInput(name="Slab", quantity=Decimal("-5"), unit="m2", unit_rate=Decimal("100"))]
        )


def test_build_estimate_happy_path_with_factor_and_gfa() -> None:
    """End to end: subtotal, regional factor and GFA benchmark all line up."""
    elements = [
        ElementInput(name="External walls", quantity=Decimal("200"), unit="m2", unit_rate=Decimal("150")),
        ElementInput(name="Slab", quantity=Decimal("100"), unit="m3", unit_rate=Decimal("400")),
    ]
    # Subtotal = 200*150 + 100*400 = 30000 + 40000 = 70000.
    # Regional factor 1.10 -> total 77000.
    estimate = build_elemental_estimate(
        elements,
        regional_factor=Decimal("1.10"),
        gross_floor_area=Decimal("350"),
        gross_floor_area_unit="m2",
        currency="EUR",
    )
    assert estimate.subtotal_base == Decimal("70000.00")
    assert estimate.total == Decimal("77000.00")
    assert estimate.element_count == 2
    assert estimate.currency == "EUR"
    # Cost per m2 of GFA = 77000 / 350 = 220.
    assert estimate.cost_per_gfa == Decimal("220.00")
    assert estimate.gfa_canonical == Decimal("350")
    # Breakdown is present and explains each element.
    assert [e.name for e in estimate.elements] == ["External walls", "Slab"]
    assert estimate.elements[0].adjusted_total == Decimal("33000.00")
    assert "elemental rate" in estimate.notes


def test_build_estimate_mixed_unit_systems_are_consistent() -> None:
    """An element measured in ft2 prices the same as the metric equivalent.

    Element total is quantity times rate in the native unit, so a wall of
    100 ft2 at 10 per ft2 totals 1000, and its canonical quantity is reported
    in m2 for benchmarking without altering the money total.
    """
    estimate = build_elemental_estimate(
        [ElementInput(name="Cladding", quantity=Decimal("100"), unit="ft2", unit_rate=Decimal("10"))]
    )
    assert estimate.total == Decimal("1000.00")
    row = estimate.elements[0]
    assert row.canonical_unit == "m2"
    assert row.canonical_quantity == Decimal("9.290304")


def test_build_estimate_zero_gfa_raises() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        build_elemental_estimate(
            [ElementInput(name="Slab", quantity=Decimal("10"), unit="m2", unit_rate=Decimal("100"))],
            gross_floor_area=Decimal("0"),
        )


def test_build_estimate_default_factor_is_no_op() -> None:
    """Without a regional factor the total equals the subtotal (default 1)."""
    estimate = build_elemental_estimate(
        [ElementInput(name="Doors", quantity=Decimal("5"), unit="unit", unit_rate=Decimal("300"))]
    )
    assert estimate.regional_factor == Decimal("1")
    assert estimate.total == estimate.subtotal_base == Decimal("1500.00")


def test_build_estimate_json_serialises_money_as_strings() -> None:
    """v3 money convention: Decimal fields serialise as plain strings in JSON."""
    estimate = build_elemental_estimate(
        [ElementInput(name="Doors", quantity=Decimal("5"), unit="unit", unit_rate=Decimal("300"))]
    )
    dumped = estimate.model_dump(mode="json")
    assert dumped["total"] == "1500.00"
    assert dumped["subtotal_base"] == "1500.00"
    assert isinstance(dumped["elements"][0]["base_total"], str)


# ── glossary / explain ───────────────────────────────────────────────────────


def test_explain_known_terms() -> None:
    assert "cost of one unit" in explain("elemental_rate")
    assert "worldwide default" in explain("regional_factor")
    # Every glossary key resolves.
    for term in COST_MODEL_GLOSSARY:
        assert explain(term)


def test_explain_unknown_term_raises() -> None:
    with pytest.raises(ValueError, match="Unknown cost-model term"):
        explain("not_a_real_term")
