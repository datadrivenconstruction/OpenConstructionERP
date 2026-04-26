# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for the EAC v2 rule executor (EAC-1.4).

Covers selector matching, predicate evaluation, attribute resolution,
and the three implemented output modes (``boolean``, ``issue``,
``aggregate``). Clash mode is intentionally exercised only as the
"raises UnsupportedOutputModeError" path — the geometry kernel work
lives in a follow-up ticket (RFC 35 §1.6.4).
"""

from __future__ import annotations

import pytest

from app.modules.eac.engine.executor import (
    ExecutionError,
    ExecutionResult,
    UnsupportedOutputModeError,
    execute_rule,
)
from app.modules.eac.schemas import EacRuleDefinition


def _rule(body: dict) -> EacRuleDefinition:
    return EacRuleDefinition.model_validate(body)


# ── Sample canonical elements ─────────────────────────────────────────


@pytest.fixture
def walls() -> list[dict]:
    """Three walls: one passing, one failing, one missing the attribute."""
    return [
        {
            "stable_id": "wall_001",
            "element_type": "Wall",
            "ifc_class": "IfcWall",
            "level": "Level 1",
            "discipline": "ARC",
            "properties": {"FireRating": "F90", "Mark": "W-01"},
            "quantities": {"area_m2": 25.0, "volume_m3": 6.0, "length_m": 10.0},
        },
        {
            "stable_id": "wall_002",
            "element_type": "Wall",
            "ifc_class": "IfcWall",
            "level": "Level 1",
            "discipline": "ARC",
            "properties": {"FireRating": "F30", "Mark": "W-02"},
            "quantities": {"area_m2": 12.5, "volume_m3": 3.0, "length_m": 5.0},
        },
        {
            "stable_id": "wall_003",
            "element_type": "Wall",
            "ifc_class": "IfcWall",
            "level": "Level 2",
            "discipline": "ARC",
            "properties": {"Mark": "W-03"},  # FireRating missing
            "quantities": {"area_m2": 8.0, "volume_m3": 1.9, "length_m": 4.0},
        },
        {
            "stable_id": "door_001",
            "element_type": "Door",
            "ifc_class": "IfcDoor",
            "level": "Level 1",
            "discipline": "ARC",
            "properties": {"FireRating": "F30"},
            "quantities": {"area_m2": 2.1},
        },
    ]


# ── Selector pass ─────────────────────────────────────────────────────


def test_category_selector_filters_to_walls(walls: list[dict]) -> None:
    rule = _rule(
        {
            "schema_version": "2.0",
            "name": "all walls",
            "output_mode": "boolean",
            "selector": {"kind": "category", "values": ["Wall"]},
        }
    )
    result = execute_rule(rule, walls)
    assert result.elements_matched == 3
    assert result.elements_passed == 3  # no predicate => all pass


def test_ifc_class_selector_filters_doors_only(walls: list[dict]) -> None:
    rule = _rule(
        {
            "schema_version": "2.0",
            "name": "doors",
            "output_mode": "boolean",
            "selector": {"kind": "ifc_class", "values": ["IfcDoor"]},
        }
    )
    result = execute_rule(rule, walls)
    assert result.elements_matched == 1


def test_level_selector_picks_storey(walls: list[dict]) -> None:
    rule = _rule(
        {
            "schema_version": "2.0",
            "name": "level_2_only",
            "output_mode": "boolean",
            "selector": {"kind": "level", "values": ["Level 2"]},
        }
    )
    result = execute_rule(rule, walls)
    assert result.elements_matched == 1
    assert result.boolean_results[0].element_id == "wall_003"


def test_geometry_filter_min_volume(walls: list[dict]) -> None:
    rule = _rule(
        {
            "schema_version": "2.0",
            "name": "big_walls",
            "output_mode": "boolean",
            "selector": {"kind": "geometry_filter", "min_volume_m3": 5.0},
        }
    )
    result = execute_rule(rule, walls)
    assert result.elements_matched == 1  # only wall_001 has volume >= 5


def test_combinator_and(walls: list[dict]) -> None:
    rule = _rule(
        {
            "schema_version": "2.0",
            "name": "level1_walls",
            "output_mode": "boolean",
            "selector": {
                "kind": "and",
                "children": [
                    {"kind": "category", "values": ["Wall"]},
                    {"kind": "level", "values": ["Level 1"]},
                ],
            },
        }
    )
    result = execute_rule(rule, walls)
    assert result.elements_matched == 2


# ── Boolean mode + predicates ─────────────────────────────────────────


def test_boolean_mode_predicate_eq(walls: list[dict]) -> None:
    rule = _rule(
        {
            "schema_version": "2.0",
            "name": "walls_F90",
            "output_mode": "boolean",
            "selector": {"kind": "category", "values": ["Wall"]},
            "predicate": {
                "kind": "triplet",
                "attribute": {"kind": "exact", "name": "FireRating"},
                "constraint": {"operator": "eq", "value": "F90"},
            },
        }
    )
    result = execute_rule(rule, walls)
    assert result.elements_matched == 3
    assert result.elements_passed == 1
    by_id = {r.element_id: r for r in result.boolean_results}
    assert by_id["wall_001"].passed is True
    assert by_id["wall_002"].passed is False
    assert by_id["wall_003"].passed is False  # missing => fail by default


def test_boolean_mode_treat_missing_as_pass(walls: list[dict]) -> None:
    rule = _rule(
        {
            "schema_version": "2.0",
            "name": "walls_F90_missing_ok",
            "output_mode": "boolean",
            "selector": {"kind": "category", "values": ["Wall"]},
            "predicate": {
                "kind": "triplet",
                "attribute": {"kind": "exact", "name": "FireRating"},
                "constraint": {"operator": "eq", "value": "F90"},
                "treat_missing_as_fail": False,
            },
        }
    )
    result = execute_rule(rule, walls)
    by_id = {r.element_id: r for r in result.boolean_results}
    assert by_id["wall_003"].passed is True  # missing => pass when flag flipped


def test_boolean_mode_predicate_combinators(walls: list[dict]) -> None:
    rule = _rule(
        {
            "schema_version": "2.0",
            "name": "small_or_F90",
            "output_mode": "boolean",
            "selector": {"kind": "category", "values": ["Wall"]},
            "predicate": {
                "kind": "or",
                "children": [
                    {
                        "kind": "triplet",
                        "attribute": {"kind": "exact", "name": "volume_m3"},
                        "constraint": {"operator": "lt", "value": 2.0},
                    },
                    {
                        "kind": "triplet",
                        "attribute": {"kind": "exact", "name": "FireRating"},
                        "constraint": {"operator": "eq", "value": "F90"},
                    },
                ],
            },
        }
    )
    result = execute_rule(rule, walls)
    # wall_001 passes (F90), wall_003 passes (volume < 2), wall_002 fails.
    assert result.elements_passed == 2


def test_boolean_mode_attribute_snapshot_recorded(walls: list[dict]) -> None:
    rule = _rule(
        {
            "schema_version": "2.0",
            "name": "snapshot_test",
            "output_mode": "boolean",
            "selector": {"kind": "ifc_class", "values": ["IfcWall"]},
            "predicate": {
                "kind": "triplet",
                "attribute": {"kind": "exact", "name": "FireRating"},
                "constraint": {"operator": "exists"},
            },
        }
    )
    result = execute_rule(rule, walls)
    by_id = {r.element_id: r for r in result.boolean_results}
    assert by_id["wall_001"].attribute_snapshot["FireRating"] == "F90"
    assert by_id["wall_003"].attribute_snapshot["FireRating"] is None


# ── Issue mode ────────────────────────────────────────────────────────


def test_issue_mode_renders_template(walls: list[dict]) -> None:
    rule = _rule(
        {
            "schema_version": "2.0",
            "name": "missing F90",
            "output_mode": "issue",
            "selector": {"kind": "category", "values": ["Wall"]},
            "predicate": {
                "kind": "triplet",
                "attribute": {"kind": "exact", "name": "FireRating"},
                "constraint": {"operator": "eq", "value": "F90"},
            },
            "issue_template": {
                "title": "Wall {stable_id} fails F90 ({FireRating})",
                "description": "Expected F90 fire rating",
                "topic_type": "issue",
                "priority": "high",
                "labels": ["compliance", "fire"],
            },
        }
    )
    result = execute_rule(rule, walls)
    assert result.elements_matched == 3
    assert result.elements_passed == 1
    assert len(result.issue_results) == 2

    titles = {i.element_id: i.title for i in result.issue_results}
    assert "wall_002 fails F90" in titles["wall_002"]
    assert "(F30)" in titles["wall_002"]
    # wall_003 has no FireRating; placeholder remains as a token marker.
    assert "wall_003" in titles["wall_003"]
    assert all(i.priority == "high" for i in result.issue_results)


def test_issue_mode_requires_template() -> None:
    rule = _rule(
        {
            "schema_version": "2.0",
            "name": "no template",
            "output_mode": "issue",
            "selector": {"kind": "category", "values": ["Wall"]},
        }
    )
    with pytest.raises(ExecutionError, match="issue_template"):
        execute_rule(rule, [])


# ── Aggregate mode ────────────────────────────────────────────────────


def test_aggregate_mode_sum_volume(walls: list[dict]) -> None:
    rule = _rule(
        {
            "schema_version": "2.0",
            "name": "total_wall_volume",
            "output_mode": "aggregate",
            "result_unit": "m3",
            "selector": {"kind": "category", "values": ["Wall"]},
            "formula": "SUM(volume_m3)",
        }
    )
    result = execute_rule(rule, walls)
    assert result.aggregate_result is not None
    assert result.aggregate_result.value == pytest.approx(10.9)
    assert result.aggregate_result.result_unit == "m3"


def test_aggregate_mode_count_with_predicate(walls: list[dict]) -> None:
    rule = _rule(
        {
            "schema_version": "2.0",
            "name": "F90_walls_count",
            "output_mode": "aggregate",
            "selector": {"kind": "category", "values": ["Wall"]},
            "predicate": {
                "kind": "triplet",
                "attribute": {"kind": "exact", "name": "FireRating"},
                "constraint": {"operator": "eq", "value": "F90"},
            },
            "formula": "SUM(elements)",
        }
    )
    result = execute_rule(rule, walls)
    assert result.aggregate_result is not None
    assert result.aggregate_result.value == 1


def test_aggregate_mode_empty_set_returns_zero() -> None:
    """Empty matched set must not crash — SUM([]) collapses to 0.

    Previously the formula's free variable was unbound when no element
    matched, raising NameNotDefined. The fix binds every name the
    formula references to an empty list so SUM/COUNT collapse cleanly.
    """
    rule = _rule(
        {
            "schema_version": "2.0",
            "name": "no_match",
            "output_mode": "aggregate",
            "selector": {"kind": "category", "values": ["Slab"]},
            "formula": "SUM(volume_m3)",
        }
    )
    elements = [
        {
            "stable_id": "wall_x",
            "element_type": "Wall",
            "quantities": {"volume_m3": 5.0},
        }
    ]
    result = execute_rule(rule, elements)
    assert result.elements_matched == 0
    assert result.aggregate_result is not None
    assert result.aggregate_result.value == 0


def test_aggregate_mode_requires_formula(walls: list[dict]) -> None:
    rule = _rule(
        {
            "schema_version": "2.0",
            "name": "no_formula",
            "output_mode": "aggregate",
            "selector": {"kind": "category", "values": ["Wall"]},
        }
    )
    with pytest.raises(ExecutionError, match="formula"):
        execute_rule(rule, walls)


# ── Clash mode (deferred) ─────────────────────────────────────────────


def test_clash_mode_raises_unsupported() -> None:
    rule = _rule(
        {
            "schema_version": "2.0",
            "name": "wall_door_clash",
            "output_mode": "clash",
            "selector": {"kind": "category", "values": ["Wall"]},
            "clash_config": {
                "set_a": {"kind": "category", "values": ["Wall"]},
                "set_b": {"kind": "category", "values": ["Door"]},
                "method": "obb",
                "test": "intersection_volume",
            },
        }
    )
    with pytest.raises(UnsupportedOutputModeError):
        execute_rule(rule, [])


# ── Constraint coverage smoke tests ───────────────────────────────────


@pytest.mark.parametrize(
    ("operator", "value", "expected"),
    [
        ({"operator": "neq", "value": "F90"}, "F90", False),
        ({"operator": "neq", "value": "F30"}, "F90", True),
        ({"operator": "in", "values": ["F60", "F90"]}, "F90", True),
        ({"operator": "in", "values": ["F60"]}, "F90", False),
        ({"operator": "contains", "value": "90"}, "F90", True),
        ({"operator": "starts_with", "value": "f"}, "F90", True),
        ({"operator": "ends_with", "value": "0"}, "F90", True),
        ({"operator": "matches", "pattern": r"^F\d+$"}, "F90", True),
        ({"operator": "between", "min": 50, "max": 100}, 90, True),
        ({"operator": "between", "min": 50, "max": 100}, 30, False),
    ],
)
def test_constraint_operators(operator: dict, value: object, expected: bool) -> None:
    elements = [
        {
            "stable_id": "elem_1",
            "element_type": "Wall",
            "properties": {"X": value},
            "quantities": {},
        }
    ]
    rule = _rule(
        {
            "schema_version": "2.0",
            "name": "constraint_test",
            "output_mode": "boolean",
            "selector": {"kind": "category", "values": ["Wall"]},
            "predicate": {
                "kind": "triplet",
                "attribute": {"kind": "exact", "name": "X"},
                "constraint": operator,
            },
        }
    )
    result: ExecutionResult = execute_rule(rule, elements)
    assert result.boolean_results[0].passed is expected
