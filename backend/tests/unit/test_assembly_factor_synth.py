"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the assembly factor synthesizer (DB-free).

Covers the whole grounded factor-synthesis path that replaces the naive
``quantity = 1.0`` AI-generate generation:

1.  Unit-family classification.
2.  Dimension parsing (thickness / grade / element / rebar ratio / height).
3.  Material-kind and resource-type (M/L/E) classification.
4.  Dimension-driven per-unit factor formulas (concrete / rebar / formwork).
5.  Labour / equipment productivity factors and non-hours fallback.
6.  Factor clamping (never non-finite, never absurd).
7.  Typed waste / burden metadata defaults.
8.  End-to-end preview builder ``synthesize_ai_components`` on the canonical
    reinforced-concrete-wall recipe, plus robustness on bad input.

All pure functions - no database, no async, runs in-process.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.assemblies.formula_engine import (
    DimensionProfile,
    classify_material_kind,
    classify_resource_type,
    default_component_metadata,
    parse_dimensions,
    synthesize_factor,
    unit_family,
)
from app.modules.assemblies.service import (
    _safe_item_rate_decimal,
    synthesize_ai_components,
)

# ── Unit families ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("unit", "family"),
    [
        ("m3", "volume"),
        ("m³", "volume"),
        ("M3", "volume"),
        ("m2", "area"),
        ("m²", "area"),
        ("t", "mass_t"),
        ("kg", "mass_kg"),
        ("h", "hours"),
        ("m", "length"),
        ("pcs", "other"),
        ("", "other"),
    ],
)
def test_unit_family(unit, family):
    assert unit_family(unit) == family


# ── Dimension parsing ─────────────────────────────────────────────────────


def test_parse_dimensions_rc_wall():
    profile = parse_dimensions("reinforced concrete wall C30/37, 240mm")
    assert profile.thickness_m == pytest.approx(0.24)
    assert profile.concrete_grade == "C30/37"
    assert profile.element_hint == "wall"


def test_parse_dimensions_d_equals_and_slab():
    profile = parse_dimensions("C25/30 floor slab d=200")
    assert profile.thickness_m == pytest.approx(0.20)
    assert profile.concrete_grade == "C25/30"
    assert profile.element_hint == "slab"


def test_parse_dimensions_cm_ratio_and_height():
    profile = parse_dimensions("wall 24 cm thick, 120 kg/m3, 3.0 m high")
    assert profile.thickness_m == pytest.approx(0.24)
    assert profile.rebar_kg_per_m3 == pytest.approx(120.0)
    assert profile.height_m == pytest.approx(3.0)


def test_parse_dimensions_empty_is_all_none():
    profile = parse_dimensions("waterproofing works")
    assert profile.thickness_m is None
    assert profile.element_hint is None
    assert profile.rebar_kg_per_m3 is None


def test_dimension_profile_defaults():
    # An empty profile still yields grounded, element-aware defaults.
    empty = DimensionProfile()
    assert empty.effective_thickness() == pytest.approx(0.20)
    assert empty.effective_rebar_ratio() == pytest.approx(100.0)
    assert empty.face_count == 2
    wall = DimensionProfile(element_hint="wall")
    assert wall.effective_rebar_ratio() == pytest.approx(110.0)
    assert wall.face_count == 2
    column = DimensionProfile(element_hint="column")
    assert column.face_count == 4


# ── Classification ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("description", "kind"),
    [
        ("Concrete C30/37 ready-mix", "concrete"),
        ("Reinforcing steel B500B", "rebar"),
        ("Reinforcement bar mesh", "rebar"),
        ("Wall formwork panels", "formwork"),
        ("Clay brick masonry", "masonry"),
        ("Cement plaster render", "finish"),
        ("Waterproof membrane", "generic"),
        # "reinforced concrete" must stay concrete, never rebar
        ("Reinforced concrete pour", "concrete"),
    ],
)
def test_classify_material_kind(description, kind):
    assert classify_material_kind(description) == kind


@pytest.mark.parametrize(
    ("description", "tags", "item_type", "expected"),
    [
        ("Mason labor crew", None, None, "labor"),
        ("Tower crane", None, None, "equipment"),
        ("Concrete C30/37", None, None, "material"),
        ("Widget", None, "labor", "labor"),
        ("Widget", ["equipment"], None, "equipment"),
    ],
)
def test_classify_resource_type(description, tags, item_type, expected):
    assert classify_resource_type(description, tags, item_type) == expected


# ── Factor synthesis: materials ───────────────────────────────────────────


def _wall_dims() -> DimensionProfile:
    return DimensionProfile(thickness_m=0.24, element_hint="wall")


def test_concrete_factor_per_volume_is_one():
    result = synthesize_factor(
        resource_type="material",
        component_unit="m3",
        assembly_unit="m3",
        dims=_wall_dims(),
        description="Concrete C30/37",
    )
    assert result.factor == pytest.approx(1.0)
    assert result.basis == "concrete volume per unit"


def test_concrete_factor_per_area_is_thickness():
    result = synthesize_factor(
        resource_type="material",
        component_unit="m3",
        assembly_unit="m2",
        dims=_wall_dims(),
        description="Concrete C30/37",
    )
    assert result.factor == pytest.approx(0.24)


def test_rebar_factor_per_volume_tonnes():
    # Wall default 110 kg/m3 → 0.11 t per m3.
    result = synthesize_factor(
        resource_type="material",
        component_unit="t",
        assembly_unit="m3",
        dims=_wall_dims(),
        description="Reinforcing steel",
    )
    assert result.factor == pytest.approx(0.11)
    assert result.basis == "rebar ratio x concrete volume"


def test_rebar_factor_per_area_tonnes():
    # 110 kg/m3 * 0.24 m / 1000 = 0.0264 t per m2.
    result = synthesize_factor(
        resource_type="material",
        component_unit="t",
        assembly_unit="m2",
        dims=_wall_dims(),
        description="Reinforcing steel",
    )
    assert result.factor == pytest.approx(0.0264)


def test_rebar_factor_kg_unit():
    result = synthesize_factor(
        resource_type="material",
        component_unit="kg",
        assembly_unit="m3",
        dims=_wall_dims(),
        description="Rebar",
    )
    assert result.factor == pytest.approx(110.0)


def test_rebar_factor_uses_explicit_ratio():
    dims = DimensionProfile(thickness_m=0.24, rebar_kg_per_m3=120.0, element_hint="wall")
    result = synthesize_factor(
        resource_type="material",
        component_unit="t",
        assembly_unit="m3",
        dims=dims,
        description="Reinforcement",
    )
    assert result.factor == pytest.approx(0.12)


def test_formwork_factor_per_volume():
    # Two faces / 0.24 m thickness = 8.3333 m2 per m3.
    result = synthesize_factor(
        resource_type="material",
        component_unit="m2",
        assembly_unit="m3",
        dims=_wall_dims(),
        description="Wall formwork",
    )
    assert result.factor == pytest.approx(8.3333, rel=1e-3)


def test_formwork_factor_per_area_is_faces():
    result = synthesize_factor(
        resource_type="material",
        component_unit="m2",
        assembly_unit="m2",
        dims=_wall_dims(),
        description="Wall formwork",
    )
    assert result.factor == pytest.approx(2.0)


def test_factor_is_clamped_to_sane_maximum():
    # A 1 mm thickness would give 2000 m2/m3 of formwork; clamp guards it.
    dims = DimensionProfile(thickness_m=0.001, element_hint="wall")
    result = synthesize_factor(
        resource_type="material",
        component_unit="m2",
        assembly_unit="m3",
        dims=dims,
        description="Wall formwork",
    )
    assert result.factor == pytest.approx(1000.0)


def test_assumed_thickness_is_flagged():
    # No thickness in the profile → concrete-per-area assumes a default and
    # records the assumption for the estimator to review.
    dims = DimensionProfile(element_hint="wall")
    result = synthesize_factor(
        resource_type="material",
        component_unit="m3",
        assembly_unit="m2",
        dims=dims,
        description="Concrete C30/37",
    )
    assert result.factor == pytest.approx(0.20)
    assert any("thickness" in note for note in result.assumptions)


# ── Factor synthesis: labour / equipment ──────────────────────────────────


def test_labour_factor_hours_per_volume():
    result = synthesize_factor(
        resource_type="labor",
        component_unit="h",
        assembly_unit="m3",
        dims=_wall_dims(),
        description="Concrete placing labour",
    )
    assert result.factor == pytest.approx(2.5)
    assert result.basis == "labour productivity norm"


def test_equipment_factor_hours_per_volume():
    result = synthesize_factor(
        resource_type="equipment",
        component_unit="h",
        assembly_unit="m3",
        dims=_wall_dims(),
        description="Concrete pump",
    )
    assert result.factor == pytest.approx(0.35)


def test_labour_non_hours_falls_back_to_unit_match():
    result = synthesize_factor(
        resource_type="labor",
        component_unit="m2",
        assembly_unit="m2",
        dims=_wall_dims(),
        description="Finishing labour",
    )
    assert result.factor == pytest.approx(1.0)
    assert result.basis == "unit-match"


def test_generic_material_cross_unit_falls_back():
    result = synthesize_factor(
        resource_type="material",
        component_unit="kg",
        assembly_unit="m2",
        dims=DimensionProfile(),
        description="Waterproofing membrane",
    )
    assert result.factor == pytest.approx(1.0)
    assert result.basis == "fallback"


# ── Typed metadata defaults ───────────────────────────────────────────────


def test_default_metadata_material_waste():
    assert default_component_metadata("material", "concrete") == {"waste_pct": 3.0}
    assert default_component_metadata("material", "finish") == {"waste_pct": 10.0}


def test_default_metadata_labour_burden():
    meta = default_component_metadata("labor", "concrete")
    assert meta["crew_size"] == pytest.approx(1.0)
    assert meta["burden_pct"] == pytest.approx(25.0)


def test_default_metadata_equipment():
    assert default_component_metadata("equipment", "generic") == {
        "rental_days": 0.0,
        "fuel_cost": 0.0,
    }


# ── Rate parsing helper ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("95.00", Decimal("95.00")),
        ("abc", Decimal("0")),
        (None, Decimal("0")),
        ("-5", Decimal("0")),
    ],
)
def test_safe_item_rate_decimal(raw, expected):
    assert _safe_item_rate_decimal(SimpleNamespace(rate=raw)) == expected


def test_safe_item_rate_decimal_missing_attr():
    assert _safe_item_rate_decimal(SimpleNamespace()) == Decimal("0")


# ── End-to-end preview builder ────────────────────────────────────────────


def _item(description, code, unit, rate, item_id):
    return SimpleNamespace(
        description=description,
        code=code,
        unit=unit,
        rate=rate,
        id=item_id,
        region=None,
        tags=[],
        metadata_={},
    )


def test_synthesize_ai_components_rc_wall():
    items = [
        _item("Concrete C30/37 ready-mix", "C001", "m3", "95.00", "i1"),
        _item("Reinforcing steel B500B bar", "R001", "t", "750.00", "i2"),
        _item("Wall formwork plywood", "F001", "m2", "18.00", "i3"),
    ]
    comps = synthesize_ai_components("reinforced concrete wall C30/37, 240mm", "m3", items)
    assert len(comps) == 3
    by_code = {c["code"]: c for c in comps}
    concrete = by_code["C001"]
    rebar = by_code["R001"]
    formwork = by_code["F001"]

    # Grounded per-unit factors carried in ``quantity`` (what the editor saves).
    assert concrete["quantity"] == pytest.approx(1.0)
    assert rebar["quantity"] == pytest.approx(0.11)
    assert formwork["quantity"] == pytest.approx(8.3333, rel=1e-3)

    # total = quantity * rate; the catalogue rate itself is preserved.
    assert concrete["total"] == pytest.approx(95.0)
    assert rebar["total"] == pytest.approx(82.5)
    assert formwork["total"] == pytest.approx(150.0, rel=1e-3)
    assert concrete["unit_rate"] == pytest.approx(95.0)

    # This is the whole point: not the naive 1.0 for every line.
    assert rebar["quantity"] < 1.0 < formwork["quantity"]

    # Resource typing + typed metadata + audit trail.
    assert concrete["type"] == "material"
    assert concrete["metadata"]["waste_pct"] == 3.0
    assert rebar["metadata"]["factor_basis"] == "rebar ratio x concrete volume"
    assert "factor_formula" in formwork["metadata"]

    # Cost item id threaded through so the confirmed save keeps the link.
    assert concrete["cost_item_id"] == "i1"


def test_synthesize_ai_components_labour_line():
    items = [_item("Concrete placing labor crew", "L1", "h", "42.00", "l1")]
    comps = synthesize_ai_components("concrete slab 200mm", "m3", items)
    line = comps[0]
    assert line["type"] == "labor"
    assert line["quantity"] == pytest.approx(2.5)
    assert line["total"] == pytest.approx(105.0)  # 2.5 h * 42
    assert line["metadata"]["burden_pct"] == 25.0


def test_synthesize_ai_components_bad_rate_is_safe():
    items = [_item("Mystery item", "M1", "", "oops", "m1")]
    comps = synthesize_ai_components("generic works", "m2", items)
    line = comps[0]
    assert line["unit"] == "m2"  # empty unit falls back to the assembly unit
    assert line["unit_rate"] == 0.0
    assert line["total"] == 0.0
    assert line["quantity"] >= 0.0


def test_synthesize_ai_components_respects_cap():
    items = [_item(f"item {i}", str(i), "m2", "1", str(i)) for i in range(20)]
    comps = synthesize_ai_components("x", "m2", items, max_components=5)
    assert len(comps) == 5
