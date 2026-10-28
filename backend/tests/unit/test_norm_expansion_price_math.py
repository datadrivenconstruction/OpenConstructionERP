# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure production-norm pricing math.

These exercise :mod:`app.modules.norm_expansion.price_math` directly with plain
``Decimal`` inputs - no database, FastAPI or ORM - so they run on any
interpreter, exactly like the other pure-engine tests in this suite.

They pin: the per-unit build-up (coefficients are priced per unit, never
expanded), the four-decimal-place half-up quantisation, ``unit_rate`` equal to
the sum of the line totals, the canonical resource-type / kind mapping, the
unpriced fallback for a missing labour / machine / material price, the omission
of zero-coefficient labour and machine lines, the float rejection (money and
rates never enter as binary floats), the non-finite guard, and the
material-price alignment guard.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.norm_expansion.expand_math import MaterialCoefficient, NormCoefficients
from app.modules.norm_expansion.price_math import (
    MaterialPrice,
    PricedBuildUp,
    price_build_up,
)

D = Decimal


def _plastering() -> NormCoefficients:
    """0.45 labour-h, 0.02 machine-h, 12 kg plaster + 6 l water per m2."""
    return NormCoefficients(
        labor_hours_per_unit=D("0.45"),
        machine_hours_per_unit=D("0.02"),
        materials=(
            MaterialCoefficient(name="Gypsum plaster", unit="kg", qty_per_unit=D("12.0")),
            MaterialCoefficient(name="Water", unit="l", qty_per_unit=D("6.0")),
        ),
    )


def _priced_plastering() -> PricedBuildUp:
    """The plastering norm priced with clean, round rates."""
    return price_build_up(
        _plastering(),
        labor_rate=D("40"),
        machine_rate=D("25"),
        material_prices=[
            MaterialPrice(unit_cost=D("0.50"), cost_item_id="ci-gypsum"),
            MaterialPrice(unit_cost=D("0.01"), cost_item_id="ci-water"),
        ],
        currency="EUR",
    )


def test_build_up_prices_every_line_per_unit() -> None:
    build = _priced_plastering()
    # quantity stays the per-unit coefficient (not an expanded total).
    totals = {line.description: line.total for line in build.lines}
    assert totals["Labour"] == D("18.0000")  # 0.45 h * 40
    assert totals["Machine / equipment"] == D("0.5000")  # 0.02 h * 25
    assert totals["Gypsum plaster"] == D("6.0000")  # 12 kg * 0.50
    assert totals["Water"] == D("0.0600")  # 6 l * 0.01


def test_unit_rate_is_the_sum_of_line_totals() -> None:
    build = _priced_plastering()
    assert build.unit_rate == D("24.5600")
    assert build.unit_rate == sum((line.total for line in build.lines), D("0"))
    assert build.labor_cost == D("18.0000")
    assert build.machine_cost == D("0.5000")
    assert build.material_cost == D("6.0600")


def test_line_quantity_equals_the_coefficient() -> None:
    build = _priced_plastering()
    by_desc = {line.description: line for line in build.lines}
    assert by_desc["Labour"].quantity == D("0.4500")
    assert by_desc["Gypsum plaster"].quantity == D("12.0000")


def test_resource_type_and_kind_mapping() -> None:
    build = _priced_plastering()
    by_desc = {line.description: line for line in build.lines}
    assert by_desc["Labour"].resource_type == "labor"
    assert by_desc["Labour"].kind == "labor"
    assert by_desc["Labour"].kind_i18n_key == "price_breakdown.kind.labor"
    assert by_desc["Machine / equipment"].resource_type == "equipment"
    assert by_desc["Machine / equipment"].kind == "equipment"
    assert by_desc["Gypsum plaster"].resource_type == "material"
    assert by_desc["Gypsum plaster"].kind == "material"


def test_line_order_is_labour_machine_then_materials_in_order() -> None:
    build = _priced_plastering()
    assert [line.description for line in build.lines] == [
        "Labour",
        "Machine / equipment",
        "Gypsum plaster",
        "Water",
    ]


def test_quantisation_is_four_dp_half_up() -> None:
    norm = NormCoefficients(labor_hours_per_unit=D("0.3333"), machine_hours_per_unit=D("0"))
    build = price_build_up(norm, labor_rate=D("33.33"), machine_rate=None, material_prices=[])
    # 0.3333 * 33.33 = 11.108889 -> half-up at the 4th dp -> 11.1089.
    assert build.lines[0].total == D("11.1089")
    assert str(build.lines[0].total) == "11.1089"
    assert build.unit_rate == D("11.1089")


def test_values_are_decimal_not_float() -> None:
    build = _priced_plastering()
    assert isinstance(build.unit_rate, Decimal)
    for line in build.lines:
        assert isinstance(line.quantity, Decimal)
        assert isinstance(line.unit_cost, Decimal)
        assert isinstance(line.total, Decimal)


def test_missing_labour_rate_leaves_line_unpriced_and_flagged() -> None:
    build = price_build_up(
        _plastering(),
        labor_rate=None,
        machine_rate=D("25"),
        material_prices=[
            MaterialPrice(unit_cost=D("0.50")),
            MaterialPrice(unit_cost=D("0.01")),
        ],
    )
    labour = next(line for line in build.lines if line.description == "Labour")
    assert labour.priced is False
    assert labour.unit_cost == D("0.0000")
    assert labour.total == D("0.0000")
    assert labour.quantity == D("0.4500")  # demand still shown
    assert "Labour" in build.unpriced
    # The unit rate no longer includes the unpriced labour contribution.
    assert build.labor_cost == D("0.0000")


def test_missing_machine_rate_leaves_line_unpriced_and_flagged() -> None:
    build = price_build_up(
        _plastering(),
        labor_rate=D("40"),
        machine_rate=None,
        material_prices=[MaterialPrice(unit_cost=D("0.50")), MaterialPrice(unit_cost=D("0.01"))],
    )
    machine = next(line for line in build.lines if line.resource_type == "equipment")
    assert machine.priced is False
    assert machine.total == D("0.0000")
    assert "Machine / equipment" in build.unpriced


def test_unmatched_material_is_unpriced_and_flagged() -> None:
    build = price_build_up(
        _plastering(),
        labor_rate=D("40"),
        machine_rate=D("25"),
        material_prices=[
            MaterialPrice(unit_cost=None),  # no cost item matched
            MaterialPrice(unit_cost=D("0.01")),
        ],
    )
    gypsum = next(line for line in build.lines if line.description == "Gypsum plaster")
    assert gypsum.priced is False
    assert gypsum.unit_cost == D("0.0000")
    assert gypsum.total == D("0.0000")
    assert gypsum.quantity == D("12.0000")  # takeoff still complete
    assert "Gypsum plaster" in build.unpriced
    # Only the priced water line contributes to the material subtotal.
    assert build.material_cost == D("0.0600")


def test_zero_coefficient_labour_and_machine_lines_are_omitted() -> None:
    norm = NormCoefficients(
        labor_hours_per_unit=D("0"),
        machine_hours_per_unit=D("0"),
        materials=(MaterialCoefficient(name="Sealant", unit="l", qty_per_unit=D("2")),),
    )
    build = price_build_up(
        norm,
        labor_rate=D("40"),
        machine_rate=D("25"),
        material_prices=[MaterialPrice(unit_cost=D("5"))],
    )
    assert [line.resource_type for line in build.lines] == ["material"]
    assert build.unit_rate == D("10.0000")


def test_cost_item_id_is_carried_onto_priced_material_line() -> None:
    build = _priced_plastering()
    gypsum = next(line for line in build.lines if line.description == "Gypsum plaster")
    assert gypsum.cost_item_id == "ci-gypsum"


def test_material_prices_must_align_with_materials() -> None:
    with pytest.raises(ValueError, match="align"):
        price_build_up(
            _plastering(),
            labor_rate=D("40"),
            machine_rate=D("25"),
            material_prices=[MaterialPrice(unit_cost=D("0.50"))],  # only one, norm has two
        )


def test_rejects_float_rate() -> None:
    # Money / rates must never enter the pipeline as binary floats.
    with pytest.raises(TypeError):
        price_build_up(
            _plastering(),
            labor_rate=40.5,  # type: ignore[arg-type]
            machine_rate=D("25"),
            material_prices=[MaterialPrice(unit_cost=D("0.50")), MaterialPrice(unit_cost=D("0.01"))],
        )


def test_rejects_float_material_cost() -> None:
    with pytest.raises(TypeError):
        price_build_up(
            _plastering(),
            labor_rate=D("40"),
            machine_rate=D("25"),
            material_prices=[
                MaterialPrice(unit_cost=0.5),  # type: ignore[arg-type]
                MaterialPrice(unit_cost=D("0.01")),
            ],
        )


def test_rejects_non_finite_rate() -> None:
    with pytest.raises(ValueError, match="finite"):
        price_build_up(
            _plastering(),
            labor_rate=D("Infinity"),
            machine_rate=D("25"),
            material_prices=[MaterialPrice(unit_cost=D("0.50")), MaterialPrice(unit_cost=D("0.01"))],
        )


def test_accepts_string_and_int_rates() -> None:
    from_str = price_build_up(
        _plastering(),
        labor_rate="40",
        machine_rate="25",
        material_prices=[MaterialPrice(unit_cost="0.50"), MaterialPrice(unit_cost="0.01")],
    )
    assert from_str.unit_rate == _priced_plastering().unit_rate


def test_as_dict_renders_fixed_point_strings() -> None:
    payload = _priced_plastering().as_dict()
    assert payload["currency"] == "EUR"
    assert payload["unit_rate"] == "24.5600"
    assert payload["labor_cost"] == "18.0000"
    first = payload["lines"][0]
    assert first["description"] == "Labour"
    assert first["quantity"] == "0.4500"
    assert first["unit_cost"] == "40.0000"
    assert first["total"] == "18.0000"
    assert first["priced"] is True


def test_build_up_is_deterministic() -> None:
    assert _priced_plastering().as_dict() == _priced_plastering().as_dict()


# ── Waste factors (net -> gross) ─────────────────────────────────────────────


def _one_material_norm(name: str, qty: str) -> NormCoefficients:
    """A norm with no hours and a single material coefficient."""
    return NormCoefficients(
        labor_hours_per_unit=D("0"),
        machine_hours_per_unit=D("0"),
        materials=(MaterialCoefficient(name=name, unit="m2", qty_per_unit=D(qty)),),
    )


def test_material_waste_grosses_up_net_to_gross() -> None:
    build = price_build_up(
        _one_material_norm("Tiling", "100"),
        labor_rate=None,
        machine_rate=None,
        material_prices=[MaterialPrice(unit_cost=D("2"), waste_factor=D("1.10"), waste_matched=True)],
    )
    line = build.lines[0]
    assert line.net_qty == D("100.0000")
    assert line.quantity == D("100.0000")  # displayed quantity stays net
    assert line.waste_pct == D("10.0000")  # (1.10 - 1) * 100
    assert line.gross_qty == D("110.0000")  # 100 * 1.10
    assert line.unit_cost == D("2.0000")
    assert line.total == D("220.0000")  # priced on the GROSS: 110 * 2
    assert line.waste_matched is True
    # The build-up subtotals reflect the grossed material cost.
    assert build.material_cost == D("220.0000")
    assert build.unit_rate == D("220.0000")


def test_default_material_price_applies_zero_waste() -> None:
    build = price_build_up(
        _one_material_norm("Water", "6"),
        labor_rate=None,
        machine_rate=None,
        material_prices=[MaterialPrice(unit_cost=D("0.01"))],  # no waste_factor -> 1.0
    )
    line = build.lines[0]
    assert line.waste_pct == D("0.0000")
    assert line.gross_qty == line.net_qty == D("6.0000")
    assert line.total == D("0.0600")  # 6 * 0.01, no gross-up
    assert line.waste_matched is False


def test_waste_gross_qty_rounds_half_up_at_four_dp() -> None:
    build = price_build_up(
        _one_material_norm("Membrane", "1.5"),
        labor_rate=None,
        machine_rate=None,
        material_prices=[MaterialPrice(unit_cost=D("1"), waste_factor=D("1.0001"))],
    )
    # 1.5000 * 1.0001 = 1.50015 -> half-up at the 4th dp -> 1.5002.
    assert build.lines[0].gross_qty == D("1.5002")
    assert build.lines[0].waste_pct == D("0.0100")


def test_waste_gross_up_matches_waste_factors_engine() -> None:
    # The pure build-up must gross up exactly as the waste-factors engine does.
    from app.modules.waste_factors.waste_math import apply as waste_apply

    build = price_build_up(
        _one_material_norm("Screed", "12.5"),
        labor_rate=None,
        machine_rate=None,
        material_prices=[MaterialPrice(unit_cost=D("3"), waste_factor=D("1.03"))],
    )
    assert build.lines[0].gross_qty == waste_apply(D("12.5"), D("1.03"))  # 12.8750
    assert build.lines[0].total == D("38.6250")  # 12.8750 * 3


def test_labour_and_machine_lines_carry_no_waste() -> None:
    build = _priced_plastering()
    for desc in ("Labour", "Machine / equipment"):
        line = next(ln for ln in build.lines if ln.description == desc)
        assert line.waste_pct == D("0.0000")
        assert line.gross_qty == line.net_qty == line.quantity
        assert line.waste_matched is False


def test_unmatched_material_stays_net_when_priced() -> None:
    # A priced material with no library factor: gross == net, flagged unmatched.
    build = price_build_up(
        _one_material_norm("Granite slab", "4"),
        labor_rate=None,
        machine_rate=None,
        material_prices=[MaterialPrice(unit_cost=D("50"), waste_matched=False)],
    )
    line = build.lines[0]
    assert line.gross_qty == line.net_qty == D("4.0000")
    assert line.total == D("200.0000")  # 4 * 50, no gross-up
    assert line.waste_matched is False


def test_as_dict_exposes_waste_fields() -> None:
    build = price_build_up(
        _one_material_norm("Tiling", "100"),
        labor_rate=None,
        machine_rate=None,
        material_prices=[MaterialPrice(unit_cost=D("2"), waste_factor=D("1.10"), waste_matched=True)],
    )
    line = build.as_dict()["lines"][0]
    assert line["net_qty"] == "100.0000"
    assert line["waste_pct"] == "10.0000"
    assert line["gross_qty"] == "110.0000"
    assert line["waste_matched"] is True
    assert line["total"] == "220.0000"


def test_rejects_float_waste_factor() -> None:
    # Factors must never enter the pipeline as binary floats.
    with pytest.raises(TypeError):
        price_build_up(
            _one_material_norm("Tiling", "100"),
            labor_rate=None,
            machine_rate=None,
            material_prices=[MaterialPrice(unit_cost=D("2"), waste_factor=1.10)],  # type: ignore[arg-type]
        )
