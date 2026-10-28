# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure production-norm expansion math.

These exercise :mod:`app.modules.norm_expansion.expand_math` directly with plain
``Decimal`` / ``int`` / ``str`` inputs - no database, FastAPI or ORM - so they
run on any interpreter, exactly like the other pure-engine tests in this suite.

They pin: the core coefficient x quantity expansion, four-decimal-place
half-up quantisation, deterministic material ordering, the non-negative
quantity guard, the float rejection (money / rates / factors never enter as
binary floats), the non-finite guard, and the Decimal-as-string rendering.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.norm_expansion.expand_math import (
    MaterialCoefficient,
    NormCoefficients,
    expand,
    expand_many,
)

D = Decimal


def _plastering() -> NormCoefficients:
    """A small norm: 0.45 labour-h, 0.02 machine-h, 12 kg plaster per m2."""
    return NormCoefficients(
        labor_hours_per_unit=D("0.45"),
        machine_hours_per_unit=D("0.02"),
        materials=(
            MaterialCoefficient(name="Gypsum plaster", unit="kg", qty_per_unit=D("12.0")),
            MaterialCoefficient(name="Water", unit="l", qty_per_unit=D("6.0")),
        ),
    )


def test_expand_multiplies_every_coefficient_by_quantity() -> None:
    result = expand(_plastering(), D("10"))
    assert result.labor_hours == D("4.5000")
    assert result.machine_hours == D("0.2000")
    assert [m.qty for m in result.materials] == [D("120.0000"), D("60.0000")]


def test_expand_preserves_material_name_and_unit() -> None:
    result = expand(_plastering(), D("3"))
    assert result.materials[0].name == "Gypsum plaster"
    assert result.materials[0].unit == "kg"
    assert result.materials[1].name == "Water"
    assert result.materials[1].unit == "l"


def test_expand_is_quantised_to_four_dp_half_up() -> None:
    # 0.12345 * 1 = 0.12345 -> rounds half-up to 0.1235 (fourth dp).
    norm = NormCoefficients(
        labor_hours_per_unit=D("0.12345"),
        machine_hours_per_unit=D("0"),
    )
    result = expand(norm, D("1"))
    assert result.labor_hours == D("0.1235")
    # Every figure carries exactly four decimal places in its string form.
    assert str(result.labor_hours) == "0.1235"
    assert str(result.machine_hours) == "0.0000"


def test_expand_result_values_are_decimal_not_float() -> None:
    result = expand(_plastering(), D("2"))
    assert isinstance(result.labor_hours, Decimal)
    assert isinstance(result.machine_hours, Decimal)
    assert all(isinstance(m.qty, Decimal) for m in result.materials)


def test_expand_accepts_string_and_int_quantity() -> None:
    from_str = expand(_plastering(), "10")
    from_int = expand(_plastering(), 10)
    from_dec = expand(_plastering(), D("10"))
    assert from_str.labor_hours == from_dec.labor_hours == from_int.labor_hours


def test_expand_is_deterministic() -> None:
    norm = _plastering()
    first = expand(norm, D("7.5"))
    second = expand(norm, D("7.5"))
    assert first.as_dict() == second.as_dict()


def test_expand_zero_quantity_yields_all_zeros() -> None:
    result = expand(_plastering(), D("0"))
    assert result.labor_hours == D("0.0000")
    assert result.machine_hours == D("0.0000")
    assert all(m.qty == D("0.0000") for m in result.materials)


def test_expand_norm_with_no_materials() -> None:
    norm = NormCoefficients(labor_hours_per_unit=D("1.5"), machine_hours_per_unit=D("0.25"))
    result = expand(norm, D("4"))
    assert result.labor_hours == D("6.0000")
    assert result.machine_hours == D("1.0000")
    assert result.materials == ()


def test_expand_rejects_negative_quantity() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        expand(_plastering(), D("-1"))


def test_expand_rejects_float_quantity() -> None:
    # Money / rates / factors must never enter the pipeline as binary floats.
    with pytest.raises(TypeError):
        expand(_plastering(), 10.5)  # type: ignore[arg-type]


def test_expand_rejects_float_coefficient() -> None:
    norm = NormCoefficients(
        labor_hours_per_unit=0.45,  # type: ignore[arg-type]
        machine_hours_per_unit=D("0"),
    )
    with pytest.raises(TypeError):
        expand(norm, D("1"))


def test_expand_rejects_non_finite_quantity() -> None:
    with pytest.raises(ValueError, match="finite"):
        expand(_plastering(), D("Infinity"))


def test_expand_large_quantity_stays_exact() -> None:
    # A big takeoff must not drift: 1250.5 m2 * 12 kg/m2 = 15006.0 kg exactly.
    result = expand(_plastering(), D("1250.5"))
    assert result.materials[0].qty == D("15006.0000")


def test_as_dict_renders_fixed_point_strings() -> None:
    result = expand(_plastering(), D("10"))
    payload = result.as_dict()
    assert payload["labor_hours"] == "4.5000"
    assert payload["machine_hours"] == "0.2000"
    assert payload["materials"] == [
        {"name": "Gypsum plaster", "unit": "kg", "qty": "120.0000"},
        {"name": "Water", "unit": "l", "qty": "60.0000"},
    ]


def test_expand_many_preserves_order() -> None:
    norm = _plastering()
    results = expand_many([(norm, D("1")), (norm, D("2")), (norm, D("3"))])
    assert [r.labor_hours for r in results] == [D("0.4500"), D("0.9000"), D("1.3500")]
