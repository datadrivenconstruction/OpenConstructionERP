# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Database-free tests for the dwg_takeoff international takeoff helpers.

These exercise the pure functions in ``app.modules.dwg_takeoff.intl``:
canonical unit conversion (metric and imperial, exact Decimal, no float
drift), unit classification by physical dimension, explicit scale
application, same-dimension summing with a mixed-dimension guard, and the
plain-language explainers. No session, no engine, no I/O.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.dwg_takeoff.intl import (
    AREA,
    CANONICAL_UNIT,
    COUNT,
    DIMENSIONS,
    LENGTH,
    VOLUME,
    ConvertedQuantity,
    SummedQuantity,
    apply_scale,
    canonical_unit_for,
    classify_unit,
    convert_to_canonical,
    describe_measurement_type,
    explain_concept,
    explain_conversion,
    measurement_type_dimension,
    sum_quantities,
)

# ── Classification ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("unit", "dimension"),
    [
        ("m", LENGTH),
        ("mm", LENGTH),
        ("ft", LENGTH),
        ('"', LENGTH),
        ("lin m", LENGTH),
        ("m2", AREA),
        ("m²", AREA),
        ("sq ft", AREA),
        ("SQM", AREA),
        ("m3", VOLUME),
        ("cu yd", VOLUME),
        ("m^3", VOLUME),
        ("pcs", COUNT),
        ("nos", COUNT),
        ("ea", COUNT),
    ],
)
def test_classify_unit_maps_dimension(unit: str, dimension: str) -> None:
    assert classify_unit(unit) == dimension


def test_classify_unit_unknown_returns_none() -> None:
    assert classify_unit("furlong") is None
    assert classify_unit("") is None
    assert classify_unit(None) is None


def test_canonical_unit_for_each_dimension() -> None:
    assert canonical_unit_for(LENGTH) == "m"
    assert canonical_unit_for(AREA) == "m2"
    assert canonical_unit_for(VOLUME) == "m3"
    assert canonical_unit_for(COUNT) == "pcs"
    for dim in DIMENSIONS:
        assert canonical_unit_for(dim) == CANONICAL_UNIT[dim]


def test_canonical_unit_for_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown dimension"):
        canonical_unit_for("temperature")


# ── Conversion: exact, no float drift ──────────────────────────────────────


def test_convert_metric_is_identity_for_canonical() -> None:
    got = convert_to_canonical("3.5", "m")
    assert isinstance(got, ConvertedQuantity)
    assert got.value == Decimal("3.5")
    assert got.unit == "m"
    assert got.dimension == LENGTH


def test_convert_mm_to_metres_exact() -> None:
    got = convert_to_canonical(1000, "mm")
    assert got.value == Decimal("1.000")
    assert got.unit == "m"


def test_convert_imperial_length_exact() -> None:
    # 1 ft is exactly 0.3048 m; no binary-float tail.
    got = convert_to_canonical(1, "ft")
    assert got.value == Decimal("0.3048")
    assert got.factor == Decimal("0.3048")


def test_convert_imperial_area_exact() -> None:
    got = convert_to_canonical(1, "sqft")
    assert got.value == Decimal("0.09290304")
    assert got.dimension == AREA


def test_convert_imperial_volume_exact() -> None:
    got = convert_to_canonical(1, "cu yd")
    assert got.value == Decimal("0.764554857984")
    assert got.dimension == VOLUME


def test_convert_float_input_no_drift() -> None:
    # 0.1 as a float would carry a binary tail if passed through float math.
    got = convert_to_canonical(0.1, "m")
    assert got.value == Decimal("0.1")


def test_convert_count_is_pieces() -> None:
    got = convert_to_canonical(7, "nos")
    assert got.value == Decimal("7")
    assert got.unit == "pcs"
    assert got.dimension == COUNT


def test_convert_zero_is_well_defined_zero() -> None:
    got = convert_to_canonical(0, "ft")
    assert got.value == Decimal("0.0")
    assert got.dimension == LENGTH


def test_convert_unknown_unit_raises() -> None:
    with pytest.raises(ValueError, match="Unknown unit"):
        convert_to_canonical(1, "furlong")


def test_convert_negative_raises() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        convert_to_canonical("-2", "m")


def test_convert_non_finite_raises() -> None:
    with pytest.raises(ValueError, match="finite"):
        convert_to_canonical(float("inf"), "m")
    with pytest.raises(ValueError):
        convert_to_canonical(float("nan"), "m")


def test_convert_none_value_raises() -> None:
    with pytest.raises(ValueError):
        convert_to_canonical(None, "m")


def test_convert_derivation_is_explained() -> None:
    got = convert_to_canonical(2, "ft")
    assert "ft" in got.derivation
    assert "0.3048" in got.derivation
    assert got.derivation == explain_conversion(2, "ft")


# ── Scale application ──────────────────────────────────────────────────────


def test_apply_scale_multiplies() -> None:
    assert apply_scale(10, 50) == Decimal("500")


def test_apply_scale_exact_decimal() -> None:
    assert apply_scale("2.5", "0.2") == Decimal("0.50")


def test_apply_scale_zero_raises() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        apply_scale(10, 0)


def test_apply_scale_negative_raises() -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        apply_scale(10, -5)


def test_apply_scale_negative_raw_raises() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        apply_scale(-1, 50)


def test_apply_scale_zero_raw_is_zero() -> None:
    assert apply_scale(0, 50) == Decimal("0")


def test_apply_scale_then_convert_no_drift() -> None:
    real_mm = apply_scale("1234", "1")
    got = convert_to_canonical(real_mm, "mm")
    assert got.value == Decimal("1.234")


# ── Summing with dimension guard ───────────────────────────────────────────


def test_sum_same_dimension_mixed_units() -> None:
    # 1 m + 100 cm + 1 ft = 1 + 1 + 0.3048 = 2.3048 m
    got = sum_quantities([(1, "m"), (100, "cm"), (1, "ft")])
    assert isinstance(got, SummedQuantity)
    assert got.total == Decimal("2.3048")
    assert got.dimension == LENGTH
    assert got.unit == "m"
    assert len(got.components) == 3


def test_sum_areas() -> None:
    got = sum_quantities([(1, "m2"), (1, "sqft")])
    assert got.total == Decimal("1.09290304")
    assert got.dimension == AREA


def test_sum_empty_is_well_defined_zero() -> None:
    got = sum_quantities([])
    assert got.total == Decimal("0")
    assert got.dimension is None
    assert got.unit is None
    assert got.components == []


def test_sum_mixed_dimensions_raises() -> None:
    with pytest.raises(ValueError, match="Cannot sum across dimensions"):
        sum_quantities([(1, "m"), (1, "m2")])


def test_sum_rejects_unknown_unit() -> None:
    with pytest.raises(ValueError, match="Unknown unit"):
        sum_quantities([(1, "m"), (1, "furlong")])


def test_sum_rejects_bad_pair() -> None:
    with pytest.raises(ValueError, match="value, unit"):
        sum_quantities([(1, "m", "extra")])


def test_sum_derivation_lists_parts() -> None:
    got = sum_quantities([(1, "m"), (2, "m")])
    assert got.total == Decimal("3")
    assert "3" in got.derivation


# ── Measurement-type labelling ─────────────────────────────────────────────


def test_measurement_type_dimension() -> None:
    assert measurement_type_dimension("distance") == LENGTH
    assert measurement_type_dimension("area") == AREA
    assert measurement_type_dimension("count") == COUNT
    assert measurement_type_dimension("volume") == VOLUME
    assert measurement_type_dimension("text_pin") is None
    assert measurement_type_dimension(None) is None


def test_describe_measurement_type_known() -> None:
    assert "distance" in describe_measurement_type("distance").lower()
    assert "count" in describe_measurement_type("count").lower()


def test_describe_measurement_type_unknown_readable() -> None:
    assert describe_measurement_type("my_custom_type") == "my custom type"
    assert describe_measurement_type(None) == "unspecified measurement"


# ── Concept explainers ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "concept",
    ["measured_quantity", "scale", "unit_dimension", "canonical_unit", "count_vs_measure"],
)
def test_explain_concept_known(concept: str) -> None:
    text = explain_concept(concept)
    assert isinstance(text, str)
    assert len(text) > 20


def test_explain_concept_unknown_is_generic() -> None:
    text = explain_concept("nonsense")
    assert isinstance(text, str)
    assert len(text) > 20
