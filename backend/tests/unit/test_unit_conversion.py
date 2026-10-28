"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Metric -> imperial conversion helper - GitHub #270.

``app.core.unit_conversion`` is the backend twin of the frontend
``unitConversion.ts``; printed reports (BOQ PDF) convert physical quantities
to imperial through it when the user asks, while money and data-interchange
exports stay canonical metric.

These tests pin:

* the conversion factors match the frontend table (m/m2/m3/kg/km/cm/mm/t/lm)
* the superscript area / volume variants ("m²" / "m³") convert and relabel
* unmapped units (pcs, %, lump, hr) pass through unchanged in both systems
* metric (the default) returns the value unchanged and only tidies the label
* the value math is done in Decimal so a Decimal quantity keeps its precision
* ``display_unit_for`` resolves labels without a value
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.unit_conversion import (
    ConversionResult,
    conversion_factor,
    convert,
    convert_between,
    display_rate,
    display_unit_for,
)

# ── Imperial conversion factors (mirror unitConversion.ts) ────────────────


@pytest.mark.parametrize(
    ("metric_unit", "factor", "display_unit"),
    [
        ("m", "3.2808399", "ft"),
        ("m2", "10.7639", "sq ft"),
        ("m3", "35.3147", "cu ft"),
        ("kg", "2.20462", "lb"),
        ("km", "0.621371", "mi"),
        ("cm", "0.393701", "in"),
        ("mm", "0.0393701", "in"),
        ("t", "1.10231", "ton"),
        ("lm", "3.28084", "l.ft"),
    ],
)
def test_imperial_factors_match_frontend(metric_unit: str, factor: str, display_unit: str) -> None:
    """Each metric unit scales by the documented factor and relabels for imperial."""
    result = convert(Decimal("10"), metric_unit, "imperial")
    assert result.value == Decimal("10") * Decimal(factor)
    assert result.display_unit == display_unit


def test_superscript_area_and_volume_variants_convert() -> None:
    """The takeoff-style "m²" / "m³" codes convert and relabel to "ft²" / "ft³"."""
    area = convert(Decimal("10"), "m²", "imperial")
    assert area.value == Decimal("10") * Decimal("10.7639")
    assert area.display_unit == "ft²"

    volume = convert(Decimal("10"), "m³", "imperial")
    assert volume.value == Decimal("10") * Decimal("35.3147")
    assert volume.display_unit == "ft³"


# ── Passthrough for unmapped units ────────────────────────────────────────


@pytest.mark.parametrize("unmapped", ["pcs", "%", "lump", "hr", "ea", "lsum"])
def test_unmapped_units_pass_through_unchanged(unmapped: str) -> None:
    """Countable / lump / dimensionless units never convert, in either system."""
    metric = convert(Decimal("7.5"), unmapped, "metric")
    assert metric == ConversionResult(Decimal("7.5"), unmapped)

    imperial = convert(Decimal("7.5"), unmapped, "imperial")
    assert imperial == ConversionResult(Decimal("7.5"), unmapped)


def test_none_and_empty_unit_pass_through() -> None:
    """A missing unit is treated as unmapped: value unchanged, empty label."""
    assert convert(Decimal("3"), None, "imperial") == ConversionResult(Decimal("3"), "")
    assert convert(Decimal("3"), "", "imperial") == ConversionResult(Decimal("3"), "")


# ── Metric (default) behaviour ────────────────────────────────────────────


def test_metric_default_keeps_value_and_tidies_label() -> None:
    """The default system returns the value unchanged and only tidies the label."""
    # Default argument is metric.
    result = convert(Decimal("123.45"), "m2")
    assert result.value == Decimal("123.45")
    assert result.display_unit == "m²"


def test_metric_passes_value_through_bit_for_bit() -> None:
    """Metric mode must not perturb the numeric value at all."""
    value = Decimal("999999999.9999")
    result = convert(value, "m", "metric")
    assert result.value == value
    assert result.display_unit == "m"


# ── Precision: math stays in Decimal ──────────────────────────────────────


def test_conversion_uses_decimal_math_no_float_drift() -> None:
    """A Decimal quantity stays a Decimal and avoids binary-float error."""
    result = convert(Decimal("0.1"), "m", "imperial")
    assert isinstance(result.value, Decimal)
    # Decimal("0.1") * Decimal("3.2808399") is exact; the float product
    # 0.1 * 3.2808399 would be 0.32808399000000003.
    assert result.value == Decimal("0.1") * Decimal("3.2808399")
    assert result.value != Decimal(str(0.1 * 3.2808399))


def test_string_and_float_inputs_are_coerced() -> None:
    """Non-Decimal numeric inputs are accepted and coerced (float / str)."""
    from_float = convert(10.0, "kg", "imperial")
    assert from_float.value == Decimal("10") * Decimal("2.20462")

    from_str = convert("10", "kg", "imperial")
    assert from_str.value == Decimal("10") * Decimal("2.20462")


def test_non_finite_value_collapses_to_zero() -> None:
    """A NaN / Inf quantity collapses to 0 rather than propagating."""
    assert convert(Decimal("NaN"), "m", "imperial").value == Decimal(0)
    assert convert("not-a-number", "m", "imperial").value == Decimal(0)


# ── display_unit_for (label only, no value) ───────────────────────────────


def test_display_unit_for_metric_and_imperial() -> None:
    """The label-only helper resolves the same labels as ``convert``."""
    assert display_unit_for("m2", "metric") == "m²"
    assert display_unit_for("m2", "imperial") == "sq ft"
    assert display_unit_for("m³", "imperial") == "ft³"
    # Default is metric.
    assert display_unit_for("kg") == "kg"
    # Unmapped passes through.
    assert display_unit_for("pcs", "imperial") == "pcs"


def test_case_insensitive_unit_lookup() -> None:
    """Unit lookup tolerates surrounding whitespace and upper-case spelling."""
    assert convert(Decimal("1"), "  M2 ", "imperial").display_unit == "sq ft"
    assert display_unit_for("KG", "imperial") == "lb"


# ── conversion_factor (the reciprocal source) ─────────────────────────────


def test_conversion_factor_metric_is_one() -> None:
    """Metric (and unmapped) units have a factor of exactly 1."""
    assert conversion_factor("m", "metric") == Decimal(1)
    assert conversion_factor("m²", "metric") == Decimal(1)
    assert conversion_factor("pcs", "imperial") == Decimal(1)
    assert conversion_factor(None, "imperial") == Decimal(1)


def test_conversion_factor_imperial_matches_table() -> None:
    """The factor equals the metric -> imperial scale for mapped units."""
    assert conversion_factor("m", "imperial") == Decimal("3.2808399")
    assert conversion_factor("m²", "imperial") == Decimal("10.7639")


# ── display_rate (reciprocal per-unit rate) ───────────────────────────────


def test_display_rate_metric_is_unchanged() -> None:
    """A rate is never restated in metric mode."""
    assert display_rate(Decimal("50"), "m", "metric") == Decimal("50")


def test_display_rate_restates_against_displayed_unit() -> None:
    """50 / m is restated as ~15.24 / ft so a converted line reconciles."""
    rate = display_rate(Decimal("50"), "m", "imperial")
    assert rate == Decimal("50") / Decimal("3.2808399")
    assert round(rate, 2) == Decimal("15.24")


def test_display_rate_unmapped_unit_unchanged() -> None:
    """A rate against a countable / unmapped unit passes through."""
    assert display_rate(Decimal("50"), "pcs", "imperial") == Decimal("50")


def test_priced_line_reconciles_in_imperial() -> None:
    """The headline #285 fix: converted qty * restated rate == invariant total.

    2.31 m @ 50 / m = 115.50. Shown as ~7.58 ft, the rate MUST restate to
    ~15.24 / ft so the printed line still multiplies out to 115.50 - converting
    the quantity while leaving the rate raw was the bug (7.58 * 50 = 379).
    """
    qty_metric = Decimal("2.31")
    rate_metric = Decimal("50")
    total = qty_metric * rate_metric  # 115.50, canonical / invariant

    qty_shown = convert(qty_metric, "m", "imperial").value
    rate_shown = display_rate(rate_metric, "m", "imperial")

    assert (qty_shown * rate_shown) == total


# ── Extended unit coverage (#285) ─────────────────────────────────────────


@pytest.mark.parametrize(
    ("metric_unit", "factor", "display_unit"),
    [
        ("mm2", "0.0015500031", "sq in"),
        ("cm2", "0.15500031", "sq in"),
        ("dm2", "0.107639104", "sq ft"),
        ("cm²", "0.15500031", "in²"),
        ("ha", "2.4710538", "ac"),
        ("l", "0.264172052", "gal"),
    ],
)
def test_extended_units_match_frontend(metric_unit: str, factor: str, display_unit: str) -> None:
    """The added area / land / liquid units convert with the documented factor."""
    result = convert(Decimal("10"), metric_unit, "imperial")
    assert result.value == Decimal("10") * Decimal(factor)
    assert result.display_unit == display_unit


# -- convert_between: unit-to-unit within a dimension (#319 / #320) -----------


@pytest.mark.parametrize(
    ("value", "from_unit", "to_unit", "expected"),
    [
        # Volume: metre cubed into US trade volume units (#320).
        ("10", "m3", "cy", "13.0795"),
        ("1", "m3", "ft3", "35.3147"),
        ("1", "m3", "bdft", "423.776"),
        ("1", "m3", "yd3", "1.30795"),  # yd3 is a cubic-yard spelling
        # Area: metre squared into roofing squares and square feet (#320).
        ("1", "m2", "sq", "0.107639"),
        ("1", "m2", "ft2", "10.7639"),
        # Superscript source folds to the same factor as the ascii code.
        ("2", "m³", "cy", "2.6159"),
        ("3", "m²", "sq", "0.322917"),
        # Identity: same unit both sides passes the value straight through.
        ("5", "m3", "m3", "5"),
        # Metric-to-metric within a dimension still converts.
        ("2", "m3", "l", "2000"),
    ],
)
def test_convert_between_converts_within_dimension(value: str, from_unit: str, to_unit: str, expected: str) -> None:
    """A value converts exactly into another unit of the same dimension."""
    result = convert_between(Decimal(value), from_unit, to_unit)
    assert result is not None
    assert result == Decimal(expected)


@pytest.mark.parametrize(
    ("from_unit", "to_unit"),
    [
        ("m3", "m2"),  # volume into area: different dimension
        ("m2", "m"),  # area into length
        ("m3", "lsum"),  # unknown target unit
        ("kg", "cy"),  # mass into volume
    ],
)
def test_convert_between_refuses_incompatible(from_unit: str, to_unit: str) -> None:
    """Cross-dimension or unknown-unit conversions return None, never a guess."""
    assert convert_between(Decimal("1"), from_unit, to_unit) is None


@pytest.mark.parametrize("missing", [None, "", "   "])
def test_convert_between_passes_through_when_a_unit_is_missing(missing: str | None) -> None:
    """A missing unit on either side leaves the value unchanged (nothing to do)."""
    assert convert_between(Decimal("7"), missing, "m3") == Decimal("7")
    assert convert_between(Decimal("7"), "m3", missing) == Decimal("7")


def test_convert_between_and_display_stay_consistent() -> None:
    """m3 -> ft3 via convert_between matches the metric->imperial display factor."""
    metric = Decimal("4")
    via_between = convert_between(metric, "m3", "ft3")
    via_display = convert(metric, "m3", "imperial").value
    assert via_between == via_display
