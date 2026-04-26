# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Test fixtures for EAC v2 schema parity tests.

Per RFC 35 EAC-1.2 acceptance criterion: ≥30 valid and ≥30 invalid
fixtures with coverage of every selector kind, attribute kind, and
constraint operator (FR-1.4 / FR-1.5 / FR-1.6).
"""

from __future__ import annotations

from typing import Any


def _wrap(
    output_mode: str,
    selector: dict[str, Any],
    *,
    name: str,
    predicate: dict[str, Any] | None = None,
    formula: str | None = None,
    result_unit: str | None = None,
    clash_config: dict[str, Any] | None = None,
    issue_template: dict[str, Any] | None = None,
    local_variables: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a minimally-complete EacRuleDefinition body."""
    body: dict[str, Any] = {
        "schema_version": "2.0",
        "name": name,
        "output_mode": output_mode,
        "selector": selector,
    }
    if predicate is not None:
        body["predicate"] = predicate
    if formula is not None:
        body["formula"] = formula
    if result_unit is not None:
        body["result_unit"] = result_unit
    if clash_config is not None:
        body["clash_config"] = clash_config
    if issue_template is not None:
        body["issue_template"] = issue_template
    if local_variables is not None:
        body["local_variables"] = local_variables
    return body


def _triplet(
    attribute: dict[str, Any], constraint: dict[str, Any]
) -> dict[str, Any]:
    return {
        "kind": "triplet",
        "attribute": attribute,
        "constraint": constraint,
    }


def _exact(name: str, pset: str | None = None) -> dict[str, Any]:
    return {"kind": "exact", "name": name, "pset_name": pset}


# Default predicate used when a fixture only needs to satisfy "boolean
# rules require a predicate" — it never affects schema acceptance.
_DEFAULT_PRED = _triplet(_exact("Mark"), {"operator": "exists"})


# ── Valid fixtures (≥30) ────────────────────────────────────────────────


def valid_fixtures() -> list[tuple[str, dict[str, Any]]]:
    """Return ``[(label, body), ...]`` of schema-valid rule bodies.

    Coverage:

    * 13 selector leaves + 3 combinators (16)
    * 3 attribute kinds (3)
    * 25 constraint operators (25)
    * 4 output modes (boolean / aggregate / clash / issue)
    """
    fixtures: list[tuple[str, dict[str, Any]]] = []

    # ── Selector leaves ──
    fixtures.extend([
        (
            "selector.category",
            _wrap(
                "boolean",
                {"kind": "category", "values": ["Walls"]},
                name="cat",
                predicate=_DEFAULT_PRED,
            ),
        ),
        (
            "selector.ifc_class",
            _wrap(
                "boolean",
                {"kind": "ifc_class", "values": ["IfcWall", "IfcWallStandardCase"]},
                name="ifc",
                predicate=_DEFAULT_PRED,
            ),
        ),
        (
            "selector.family",
            _wrap(
                "boolean",
                {"kind": "family", "values": ["Basic Wall"]},
                name="fam",
                predicate=_DEFAULT_PRED,
            ),
        ),
        (
            "selector.type",
            _wrap(
                "boolean",
                {"kind": "type", "values": ["Generic - 200mm"]},
                name="type",
                predicate=_DEFAULT_PRED,
            ),
        ),
        (
            "selector.level",
            _wrap(
                "boolean",
                {"kind": "level", "values": ["L01", "L02"]},
                name="lvl",
                predicate=_DEFAULT_PRED,
            ),
        ),
        (
            "selector.discipline",
            _wrap(
                "boolean",
                {"kind": "discipline", "values": ["Architectural"]},
                name="disc",
                predicate=_DEFAULT_PRED,
            ),
        ),
        (
            "selector.classification_code",
            _wrap(
                "boolean",
                {
                    "kind": "classification_code",
                    "system": "din276",
                    "values": ["330"],
                },
                name="cls",
                predicate=_DEFAULT_PRED,
            ),
        ),
        (
            "selector.psets_present",
            _wrap(
                "boolean",
                {"kind": "psets_present", "values": ["Pset_WallCommon"]},
                name="pset",
                predicate=_DEFAULT_PRED,
            ),
        ),
        (
            "selector.named_group",
            _wrap(
                "boolean",
                {"kind": "named_group", "values": ["external_walls"]},
                name="grp",
                predicate=_DEFAULT_PRED,
            ),
        ),
        (
            "selector.geometry_filter",
            _wrap(
                "boolean",
                {
                    "kind": "geometry_filter",
                    "min_volume_m3": 0.5,
                    "max_volume_m3": 100.0,
                    "min_area_m2": 1.0,
                },
                name="geom",
                predicate=_DEFAULT_PRED,
            ),
        ),
    ])

    # ── Selector combinators ──
    fixtures.extend([
        (
            "selector.and",
            _wrap(
                "boolean",
                {
                    "kind": "and",
                    "children": [
                        {"kind": "category", "values": ["Walls"]},
                        {"kind": "level", "values": ["L01"]},
                    ],
                },
                name="and_combinator",
                predicate=_DEFAULT_PRED,
            ),
        ),
        (
            "selector.or",
            _wrap(
                "boolean",
                {
                    "kind": "or",
                    "children": [
                        {"kind": "category", "values": ["Walls"]},
                        {"kind": "category", "values": ["Floors"]},
                    ],
                },
                name="or_combinator",
                predicate=_DEFAULT_PRED,
            ),
        ),
        (
            "selector.not",
            _wrap(
                "boolean",
                {
                    "kind": "not",
                    "child": {"kind": "category", "values": ["Furniture"]},
                },
                name="not_combinator",
                predicate=_DEFAULT_PRED,
            ),
        ),
    ])

    # ── Attribute kinds ──
    base_sel = {"kind": "category", "values": ["Walls"]}
    fixtures.extend([
        (
            "attribute.exact",
            _wrap(
                "boolean",
                base_sel,
                name="attr_exact",
                predicate=_triplet(
                    _exact("Thickness", pset="Pset_WallCommon"),
                    {"operator": "gt", "value": 100},
                ),
            ),
        ),
        (
            "attribute.alias",
            _wrap(
                "boolean",
                base_sel,
                name="attr_alias",
                predicate=_triplet(
                    {"kind": "alias", "alias_id": "alias-thickness"},
                    {"operator": "gte", "value": 100},
                ),
            ),
        ),
        (
            "attribute.regex",
            _wrap(
                "boolean",
                base_sel,
                name="attr_regex",
                predicate=_triplet(
                    {
                        "kind": "regex",
                        "pattern": r"^Thick.*$",
                        "case_sensitive": False,
                    },
                    {"operator": "exists"},
                ),
            ),
        ),
    ])

    # ── Constraint operators (25) ──
    operators_simple_value: list[tuple[str, Any]] = [
        ("eq", 200),
        ("neq", 100),
        ("lt", 250),
        ("lte", 250),
        ("gt", 100),
        ("gte", 100),
    ]
    for op, value in operators_simple_value:
        fixtures.append((
            f"constraint.{op}",
            _wrap(
                "boolean",
                base_sel,
                name=f"c_{op}",
                predicate=_triplet(
                    _exact("Thickness"),
                    {"operator": op, "value": value},
                ),
            ),
        ))

    operators_range: list[str] = ["between", "not_between"]
    for op in operators_range:
        fixtures.append((
            f"constraint.{op}",
            _wrap(
                "boolean",
                base_sel,
                name=f"c_{op}",
                predicate=_triplet(
                    _exact("Thickness"),
                    {"operator": op, "min": 100, "max": 250, "inclusive": True},
                ),
            ),
        ))

    operators_list: list[str] = ["in", "not_in"]
    for op in operators_list:
        fixtures.append((
            f"constraint.{op}",
            _wrap(
                "boolean",
                base_sel,
                name=f"c_{op}",
                predicate=_triplet(
                    _exact("FireRating"),
                    {"operator": op, "values": ["F30", "F60", "F90"]},
                ),
            ),
        ))

    operators_string: list[str] = [
        "contains",
        "not_contains",
        "starts_with",
        "ends_with",
    ]
    for op in operators_string:
        fixtures.append((
            f"constraint.{op}",
            _wrap(
                "boolean",
                base_sel,
                name=f"c_{op}",
                predicate=_triplet(
                    _exact("Comment"),
                    {"operator": op, "value": "fire", "case_sensitive": False},
                ),
            ),
        ))

    operators_pattern: list[str] = ["matches", "not_matches"]
    for op in operators_pattern:
        fixtures.append((
            f"constraint.{op}",
            _wrap(
                "boolean",
                base_sel,
                name=f"c_{op}",
                predicate=_triplet(
                    _exact("Mark"),
                    {"operator": op, "pattern": r"^[A-Z]{2}-\d+$"},
                ),
            ),
        ))

    operators_unary: list[str] = [
        "exists",
        "not_exists",
        "is_null",
        "is_not_null",
        "is_empty",
        "is_not_empty",
        "is_numeric",
        "is_boolean",
        "is_date",
    ]
    for op in operators_unary:
        fixtures.append((
            f"constraint.{op}",
            _wrap(
                "boolean",
                base_sel,
                name=f"c_{op}",
                predicate=_triplet(
                    _exact("CustomField"),
                    {"operator": op},
                ),
            ),
        ))

    # ── Output modes ──
    fixtures.extend([
        (
            "output_mode.aggregate",
            _wrap(
                "aggregate",
                base_sel,
                name="agg_volume",
                formula="Volume",
                result_unit="m3",
            ),
        ),
        (
            "output_mode.issue",
            _wrap(
                "issue",
                base_sel,
                name="issue_thickness",
                predicate=_triplet(
                    _exact("Thickness"),
                    {"operator": "lt", "value": 100},
                ),
                issue_template={
                    "title": "Thin wall ${Mark}",
                    "description": "Thickness ${Thickness}mm < 100mm",
                    "topic_type": "issue",
                    "priority": "high",
                    "labels": ["thickness", "wall"],
                },
            ),
        ),
        (
            "output_mode.clash",
            _wrap(
                "clash",
                base_sel,
                name="clash_walls_pipes",
                clash_config={
                    "set_a": {"kind": "category", "values": ["Walls"]},
                    "set_b": {"kind": "category", "values": ["Pipes"]},
                    "method": "obb",
                    "test": "intersection_volume",
                    "min_intersection_volume_m3": 0.001,
                },
            ),
        ),
        (
            "extras.local_variables",
            _wrap(
                "aggregate",
                base_sel,
                name="agg_with_locals",
                formula="Mass",
                result_unit="kg",
                local_variables=[
                    {
                        "name": "Density",
                        "expression": "2400",
                        "result_unit": "kg/m3",
                    },
                    {
                        "name": "Mass",
                        "expression": "Volume * Density",
                        "result_unit": "kg",
                    },
                ],
            ),
        ),
    ])

    # Sanity — must have ≥30
    assert len(fixtures) >= 30, f"only {len(fixtures)} valid fixtures"
    return fixtures


# ── Invalid fixtures (≥30) ──────────────────────────────────────────────


def invalid_fixtures() -> list[tuple[str, dict[str, Any]]]:
    """Return ``[(label, body), ...]`` of schema-INVALID rule bodies."""
    base_sel = {"kind": "category", "values": ["Walls"]}
    fixtures: list[tuple[str, dict[str, Any]]] = []

    fixtures.append((
        "missing.schema_version",
        {
            "name": "x",
            "output_mode": "boolean",
            "selector": base_sel,
        },
    ))
    fixtures.append((
        "missing.name",
        {
            "schema_version": "2.0",
            "output_mode": "boolean",
            "selector": base_sel,
        },
    ))
    fixtures.append((
        "missing.output_mode",
        {
            "schema_version": "2.0",
            "name": "x",
            "selector": base_sel,
        },
    ))
    fixtures.append((
        "missing.selector",
        {
            "schema_version": "2.0",
            "name": "x",
            "output_mode": "boolean",
        },
    ))
    fixtures.append((
        "wrong.schema_version",
        _wrap("boolean", base_sel, name="x", predicate=_DEFAULT_PRED) | {"schema_version": "1.0"},
    ))
    fixtures.append((
        "wrong.output_mode",
        {
            "schema_version": "2.0",
            "name": "x",
            "output_mode": "FOO",
            "selector": base_sel,
        },
    ))
    fixtures.append((
        "selector.unknown_kind",
        {
            "schema_version": "2.0",
            "name": "x",
            "output_mode": "boolean",
            "selector": {"kind": "made_up_kind", "values": ["a"]},
            "predicate": _DEFAULT_PRED,
        },
    ))
    fixtures.append((
        "selector.empty_values",
        {
            "schema_version": "2.0",
            "name": "x",
            "output_mode": "boolean",
            "selector": {"kind": "category", "values": []},
            "predicate": _DEFAULT_PRED,
        },
    ))
    fixtures.append((
        "selector.and.empty_children",
        {
            "schema_version": "2.0",
            "name": "x",
            "output_mode": "boolean",
            "selector": {"kind": "and", "children": []},
            "predicate": _DEFAULT_PRED,
        },
    ))
    fixtures.append((
        "selector.not.missing_child",
        {
            "schema_version": "2.0",
            "name": "x",
            "output_mode": "boolean",
            "selector": {"kind": "not"},
            "predicate": _DEFAULT_PRED,
        },
    ))
    fixtures.append((
        "selector.geometry.negative_volume",
        {
            "schema_version": "2.0",
            "name": "x",
            "output_mode": "boolean",
            "selector": {"kind": "geometry_filter", "min_volume_m3": -1.0},
            "predicate": _DEFAULT_PRED,
        },
    ))
    fixtures.append((
        "selector.extra_field",
        {
            "schema_version": "2.0",
            "name": "x",
            "output_mode": "boolean",
            "selector": {
                "kind": "category",
                "values": ["Walls"],
                "stowaway": True,  # additionalProperties: false
            },
            "predicate": _DEFAULT_PRED,
        },
    ))
    fixtures.append((
        "predicate.unknown_kind",
        {
            "schema_version": "2.0",
            "name": "x",
            "output_mode": "boolean",
            "selector": base_sel,
            "predicate": {"kind": "xor", "children": [_DEFAULT_PRED]},
        },
    ))
    fixtures.append((
        "predicate.triplet.missing_attribute",
        {
            "schema_version": "2.0",
            "name": "x",
            "output_mode": "boolean",
            "selector": base_sel,
            "predicate": {
                "kind": "triplet",
                "constraint": {"operator": "exists"},
            },
        },
    ))
    fixtures.append((
        "predicate.triplet.missing_constraint",
        {
            "schema_version": "2.0",
            "name": "x",
            "output_mode": "boolean",
            "selector": base_sel,
            "predicate": {
                "kind": "triplet",
                "attribute": _exact("Thickness"),
            },
        },
    ))
    fixtures.append((
        "attribute.unknown_kind",
        {
            "schema_version": "2.0",
            "name": "x",
            "output_mode": "boolean",
            "selector": base_sel,
            "predicate": _triplet(
                {"kind": "magic", "name": "x"},
                {"operator": "exists"},
            ),
        },
    ))
    fixtures.append((
        "attribute.exact.missing_name",
        {
            "schema_version": "2.0",
            "name": "x",
            "output_mode": "boolean",
            "selector": base_sel,
            "predicate": _triplet(
                {"kind": "exact"},
                {"operator": "exists"},
            ),
        },
    ))
    fixtures.append((
        "attribute.alias.missing_alias_id",
        {
            "schema_version": "2.0",
            "name": "x",
            "output_mode": "boolean",
            "selector": base_sel,
            "predicate": _triplet(
                {"kind": "alias"},
                {"operator": "exists"},
            ),
        },
    ))
    fixtures.append((
        "constraint.unknown_operator",
        {
            "schema_version": "2.0",
            "name": "x",
            "output_mode": "boolean",
            "selector": base_sel,
            "predicate": _triplet(
                _exact("Thickness"),
                {"operator": "almost_equals", "value": 100},
            ),
        },
    ))
    fixtures.append((
        "constraint.eq.missing_value",
        {
            "schema_version": "2.0",
            "name": "x",
            "output_mode": "boolean",
            "selector": base_sel,
            "predicate": _triplet(
                _exact("Thickness"),
                {"operator": "eq"},
            ),
        },
    ))
    fixtures.append((
        "constraint.between.missing_max",
        {
            "schema_version": "2.0",
            "name": "x",
            "output_mode": "boolean",
            "selector": base_sel,
            "predicate": _triplet(
                _exact("Thickness"),
                {"operator": "between", "min": 100},
            ),
        },
    ))
    fixtures.append((
        "constraint.in.empty_values",
        {
            "schema_version": "2.0",
            "name": "x",
            "output_mode": "boolean",
            "selector": base_sel,
            "predicate": _triplet(
                _exact("Mark"),
                {"operator": "in", "values": []},
            ),
        },
    ))
    fixtures.append((
        "constraint.exists.unexpected_value",
        {
            "schema_version": "2.0",
            "name": "x",
            "output_mode": "boolean",
            "selector": base_sel,
            "predicate": _triplet(
                _exact("Mark"),
                {"operator": "exists", "value": "boom"},
            ),
        },
    ))
    fixtures.append((
        "local_variables.invalid_name",
        _wrap(
            "aggregate",
            base_sel,
            name="x",
            formula="Volume",
            result_unit="m3",
            local_variables=[
                {"name": "1Bad", "expression": "1"},
            ],
        ),
    ))
    fixtures.append((
        "issue_template.missing_title",
        _wrap(
            "issue",
            base_sel,
            name="x",
            predicate=_DEFAULT_PRED,
            issue_template={"description": "no title here"},
        ),
    ))
    fixtures.append((
        "issue_template.bad_priority",
        _wrap(
            "issue",
            base_sel,
            name="x",
            predicate=_DEFAULT_PRED,
            issue_template={"title": "T", "priority": "PANIC"},
        ),
    ))
    fixtures.append((
        "clash_config.bad_method",
        _wrap(
            "clash",
            base_sel,
            name="x",
            clash_config={
                "set_a": base_sel,
                "set_b": base_sel,
                "method": "fuzzy",
                "test": "min_distance",
            },
        ),
    ))
    fixtures.append((
        "clash_config.missing_set_b",
        _wrap(
            "clash",
            base_sel,
            name="x",
            clash_config={
                "set_a": base_sel,
                "method": "obb",
                "test": "min_distance",
            },
        ),
    ))
    fixtures.append((
        "clash_config.bad_test",
        _wrap(
            "clash",
            base_sel,
            name="x",
            clash_config={
                "set_a": base_sel,
                "set_b": base_sel,
                "method": "obb",
                "test": "warm_hug",
            },
        ),
    ))
    fixtures.append((
        "top_level.extra_field",
        _wrap("boolean", base_sel, name="x", predicate=_DEFAULT_PRED) | {"hacks": True},
    ))
    fixtures.append((
        "top_level.empty_name",
        {
            "schema_version": "2.0",
            "name": "",
            "output_mode": "boolean",
            "selector": base_sel,
            "predicate": _DEFAULT_PRED,
        },
    ))
    fixtures.append((
        "tags.wrong_type",
        {
            "schema_version": "2.0",
            "name": "x",
            "output_mode": "boolean",
            "selector": base_sel,
            "predicate": _DEFAULT_PRED,
            "tags": "should-be-array",
        },
    ))

    # Sanity — must have ≥30
    assert len(fixtures) >= 30, f"only {len(fixtures)} invalid fixtures"
    return fixtures
