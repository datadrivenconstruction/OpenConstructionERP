# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tests for the canonical-format Smart View rule engine.

Coverage:
- Boolean logic (AND / OR / nested groups)
- Every operator (=, !=, contains, starts/ends_with, regex, >, <,
  >=, <=, between, in, not_in, is_empty, is_not_empty)
- Numeric vs string coercion
- Identity / Geometry / Quantities / Properties field resolution
- Safety guards (depth, leaf count, regex length, regex compile errors)
- Legacy filter_criteria → rule_tree adapter
- Property catalog grouping and source-format badging
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.modules.bim_hub.smart_views import (
    MAX_DEPTH,
    MAX_LEAVES,
    MAX_REGEX_LEN,
    build_property_catalog,
    evaluate,
    legacy_criteria_to_tree,
    validate_rule_tree,
)

# ── Fixtures: hand-rolled canonical element rows ──────────────────────────


def _el(
    name: str,
    element_type: str,
    storey: str | None = None,
    properties: dict | None = None,
    quantities: dict | None = None,
    discipline: str | None = None,
):
    """Return a dict that quacks like a BIMElement for the evaluator."""
    return {
        "id": f"el-{name}",
        "name": name,
        "element_type": element_type,
        "discipline": discipline,
        "storey": storey,
        "properties": properties or {},
        "quantities": quantities or {},
    }


@pytest.fixture
def elements() -> list[dict]:
    """A tiny multi-format model so we can exercise IFC + RVT + DWG paths."""
    return [
        _el(
            "Wall A1",
            "IfcWall",
            "L01",
            properties={
                "material": "Concrete",
                "fire_rating": "F90",
                "classification": {"din276": "330", "masterformat": "03 30 00"},
            },
            quantities={"Area": 12.5, "Volume": 3.0, "Length": 5.0},
            discipline="arch",
        ),
        _el(
            "Wall A2",
            "IfcWall",
            "L01",
            properties={
                "material": "Brick",
                "fire_rating": "F30",
                "classification": {"din276": "330"},
            },
            quantities={"Area": 25.0, "Volume": 6.0, "Length": 10.0},
            discipline="arch",
        ),
        _el(
            "Door D1",
            "IfcDoor",
            "L02",
            properties={"material": "Steel"},
            quantities={"Width": 0.9, "Height": 2.1},
        ),
        _el(
            "Floor F1",
            "Floors",  # Revit category style
            "L01",
            properties={
                "family": "Generic 200mm",
                "type_name": "Generic 200mm",
                "material": "Concrete",
            },
            quantities={"area_m2": 200.0, "volume_m3": 40.0},
            discipline="struct",
        ),
        _el(
            "Line L1",
            "Lines",
            None,
            properties={"layer": "A-WALL", "block": "DOOR"},
            quantities={"length_m": 7.5},
        ),
    ]


# ── 1. Rule tree validation + safety guards ───────────────────────────────


def test_validate_empty_tree_returns_match_all():
    """None / empty input is normalised to an empty AND group (match-all)."""
    assert validate_rule_tree(None) == {"op": "AND", "rules": []}
    assert validate_rule_tree({}) == {"op": "AND", "rules": []}


def test_validate_leaf_wraps_in_and_group():
    """A bare leaf at the root is wrapped in a single-leaf AND group."""
    tree = validate_rule_tree({"field": "element_type", "op": "=", "value": "IfcWall"})
    assert tree["op"] == "AND"
    assert len(tree["rules"]) == 1


def test_validate_rejects_unknown_field():
    with pytest.raises(HTTPException) as exc:
        validate_rule_tree({"field": "secret_internal", "op": "=", "value": "x"})
    assert exc.value.status_code == 400


def test_validate_rejects_unknown_operator():
    with pytest.raises(HTTPException) as exc:
        validate_rule_tree(
            {"field": "element_type", "op": "FROBNICATE", "value": "x"},
        )
    assert exc.value.status_code == 400


def test_validate_rejects_depth_overflow():
    """Building a >MAX_DEPTH chain of nested AND groups must 400."""
    # Wrap a leaf in MAX_DEPTH + 2 nested groups.
    leaf = {"field": "element_type", "op": "=", "value": "X"}
    tree = leaf
    for _ in range(MAX_DEPTH + 2):
        tree = {"op": "AND", "rules": [tree]}
    with pytest.raises(HTTPException) as exc:
        validate_rule_tree(tree)
    assert exc.value.status_code == 400


def test_validate_rejects_leaf_overflow():
    """MAX_LEAVES + 1 leaves must 400."""
    leaves = [{"field": "element_type", "op": "=", "value": f"X{i}"} for i in range(MAX_LEAVES + 1)]
    with pytest.raises(HTTPException) as exc:
        validate_rule_tree({"op": "AND", "rules": leaves})
    assert exc.value.status_code == 400


def test_validate_rejects_long_regex():
    bad = "a" * (MAX_REGEX_LEN + 1)
    with pytest.raises(HTTPException):
        validate_rule_tree({"field": "name", "op": "regex", "value": bad})


def test_validate_rejects_invalid_regex():
    with pytest.raises(HTTPException):
        validate_rule_tree({"field": "name", "op": "regex", "value": "([unclosed"})


def test_validate_between_requires_pair():
    with pytest.raises(HTTPException):
        validate_rule_tree({"field": "geometry.area_m2", "op": "between", "value": [1]})


# ── 2. Evaluator — boolean logic ──────────────────────────────────────────


def test_empty_and_matches_all(elements):
    tree = validate_rule_tree({"op": "AND", "rules": []})
    assert len(evaluate(tree, elements)) == len(elements)


def test_empty_or_matches_none(elements):
    tree = validate_rule_tree({"op": "OR", "rules": []})
    assert evaluate(tree, elements) == []


def test_and_combines_predicates(elements):
    tree = validate_rule_tree(
        {
            "op": "AND",
            "rules": [
                {"field": "element_type", "op": "=", "value": "IfcWall"},
                {"field": "storey", "op": "=", "value": "L01"},
            ],
        }
    )
    matched = evaluate(tree, elements)
    assert {e["name"] for e in matched} == {"Wall A1", "Wall A2"}


def test_or_combines_predicates(elements):
    tree = validate_rule_tree(
        {
            "op": "OR",
            "rules": [
                {"field": "element_type", "op": "=", "value": "IfcDoor"},
                {"field": "element_type", "op": "=", "value": "Floors"},
            ],
        }
    )
    matched = evaluate(tree, elements)
    assert {e["name"] for e in matched} == {"Door D1", "Floor F1"}


def test_nested_groups(elements):
    """(IfcWall AND material=Concrete) OR storey=L02."""
    tree = validate_rule_tree(
        {
            "op": "OR",
            "rules": [
                {
                    "op": "AND",
                    "rules": [
                        {"field": "element_type", "op": "=", "value": "IfcWall"},
                        {
                            "field": "properties.material",
                            "op": "=",
                            "value": "Concrete",
                        },
                    ],
                },
                {"field": "storey", "op": "=", "value": "L02"},
            ],
        }
    )
    matched = evaluate(tree, elements)
    assert {e["name"] for e in matched} == {"Wall A1", "Door D1"}


# ── 3. Operators ──────────────────────────────────────────────────────────


def test_op_contains_case_insensitive(elements):
    tree = validate_rule_tree({"field": "properties.material", "op": "contains", "value": "concr"})
    matched = evaluate(tree, elements)
    assert {e["name"] for e in matched} == {"Wall A1", "Floor F1"}


def test_op_starts_with_and_ends_with(elements):
    tree = validate_rule_tree({"field": "name", "op": "starts_with", "value": "Wall"})
    assert {e["name"] for e in evaluate(tree, elements)} == {"Wall A1", "Wall A2"}

    tree = validate_rule_tree({"field": "name", "op": "ends_with", "value": "1"})
    assert {e["name"] for e in evaluate(tree, elements)} == {
        "Wall A1",
        "Door D1",
        "Floor F1",
        "Line L1",
    }


def test_op_regex(elements):
    tree = validate_rule_tree({"field": "name", "op": "regex", "value": r"^Wall A\d$"})
    assert {e["name"] for e in evaluate(tree, elements)} == {"Wall A1", "Wall A2"}


def test_op_in_and_not_in(elements):
    tree = validate_rule_tree({"field": "element_type", "op": "in", "value": ["IfcWall", "Floors"]})
    assert {e["name"] for e in evaluate(tree, elements)} == {
        "Wall A1",
        "Wall A2",
        "Floor F1",
    }
    tree = validate_rule_tree({"field": "element_type", "op": "not_in", "value": ["IfcWall"]})
    assert {e["name"] for e in evaluate(tree, elements)} == {
        "Door D1",
        "Floor F1",
        "Line L1",
    }


def test_op_between_numeric(elements):
    tree = validate_rule_tree({"field": "geometry.area_m2", "op": "between", "value": [10, 30]})
    matched = evaluate(tree, elements)
    # Wall A1 (12.5) and Wall A2 (25) match; Floor F1 (200) is too large.
    assert {e["name"] for e in matched} == {"Wall A1", "Wall A2"}


def test_op_gt_lt(elements):
    tree = validate_rule_tree({"field": "geometry.volume_m3", "op": ">", "value": 5})
    assert {e["name"] for e in evaluate(tree, elements)} == {"Wall A2", "Floor F1"}

    tree = validate_rule_tree({"field": "geometry.length_m", "op": "<=", "value": 7.5})
    assert {e["name"] for e in evaluate(tree, elements)} == {
        "Wall A1",
        "Line L1",
    }


def test_op_is_empty_and_not_empty(elements):
    tree = validate_rule_tree({"field": "storey", "op": "is_empty"})
    assert {e["name"] for e in evaluate(tree, elements)} == {"Line L1"}

    tree = validate_rule_tree({"field": "properties.fire_rating", "op": "is_not_empty"})
    assert {e["name"] for e in evaluate(tree, elements)} == {"Wall A1", "Wall A2"}


# ── 4. Field resolution — Identity / Geometry / Properties paths ──────────


def test_identity_classification_field(elements):
    """``identity.din276`` resolves through properties.classification."""
    tree = validate_rule_tree({"field": "identity.din276", "op": "=", "value": "330"})
    assert {e["name"] for e in evaluate(tree, elements)} == {"Wall A1", "Wall A2"}


def test_geometry_alias_resolution(elements):
    """``geometry.area_m2`` should pick up either "Area" or "area_m2"."""
    tree = validate_rule_tree({"field": "geometry.area_m2", "op": ">", "value": 100})
    assert {e["name"] for e in evaluate(tree, elements)} == {"Floor F1"}


def test_dwg_layer_property(elements):
    """DWG-source element with properties.layer is fully queryable."""
    tree = validate_rule_tree({"field": "properties.layer", "op": "=", "value": "A-WALL"})
    assert {e["name"] for e in evaluate(tree, elements)} == {"Line L1"}


# ── 5. Legacy adapter ─────────────────────────────────────────────────────


def test_legacy_criteria_to_tree_roundtrip(elements):
    """The legacy filter_criteria shape converts faithfully to a rule tree."""
    legacy = {
        "element_type": ["IfcWall"],
        "storey": "L01",
        "name_contains": "A1",
        "property_filter": {"material": "Concrete"},
    }
    tree = legacy_criteria_to_tree(legacy)
    validated = validate_rule_tree(tree)
    matched = evaluate(validated, elements)
    assert [e["name"] for e in matched] == ["Wall A1"]


def test_legacy_pass_through_rule_tree(elements):
    """legacy_criteria with a rule_tree subkey passes through verbatim."""
    legacy = {
        "rule_tree": {
            "op": "AND",
            "rules": [{"field": "element_type", "op": "=", "value": "IfcDoor"}],
        }
    }
    tree = legacy_criteria_to_tree(legacy)
    matched = evaluate(validate_rule_tree(tree), elements)
    assert [e["name"] for e in matched] == ["Door D1"]


# ── 6. Property catalog ───────────────────────────────────────────────────


def test_property_catalog_groups_entries(elements):
    catalog = build_property_catalog(elements, model_format="rvt")
    by_group: dict[str, list[str]] = {}
    for entry in catalog:
        by_group.setdefault(entry.group, []).append(entry.field)

    # Identity fields should be present.
    assert "element_type" in by_group["identity"]
    assert "storey" in by_group["identity"]
    # Properties group should include material + fire_rating + layer.
    prop_fields = set(by_group["properties"])
    assert "properties.material" in prop_fields
    assert "properties.fire_rating" in prop_fields
    assert "properties.layer" in prop_fields
    # Geometry group should pick up the area_m2 alias.
    assert "geometry.area_m2" in by_group["geometry"]


def test_property_catalog_source_format_badge(elements):
    catalog = build_property_catalog(elements, model_format="ifc")
    for entry in catalog:
        # Source-format is IFC for an IFC model.
        assert entry.source_formats == ["IFC"]
