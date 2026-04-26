# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for the EAC execution planner (EAC-1.3 §5).

The planner compiles an ``EacRuleDefinition`` into an
``ExecutionPlan`` whose ``duckdb_sql`` field is well-formed SQL with
bind parameters. Real execution against canonical Parquet is EAC-1.4.
"""

from __future__ import annotations

import re

import pytest

from app.modules.eac.engine.planner import ExecutionPlan, plan_rule
from app.modules.eac.schemas import EacRuleDefinition


def _rule(body: dict) -> EacRuleDefinition:
    return EacRuleDefinition.model_validate(body)


# ── Simple selector → SELECT ────────────────────────────────────────────


def test_planner_emits_select_for_category_selector() -> None:
    rule = _rule(
        {
            "schema_version": "2.0",
            "name": "walls",
            "output_mode": "boolean",
            "selector": {"kind": "category", "values": ["Walls"]},
            "predicate": {
                "kind": "triplet",
                "attribute": {"kind": "exact", "name": "Mark"},
                "constraint": {"operator": "exists"},
            },
        }
    )
    plan = plan_rule(rule)
    assert isinstance(plan, ExecutionPlan)
    assert plan.duckdb_sql.upper().startswith("SELECT")
    assert "FROM" in plan.duckdb_sql.upper()
    # Category lookup should appear in projection or where clause.
    assert "category" in plan.duckdb_sql.lower()


def test_planner_emits_select_for_ifc_class_selector() -> None:
    rule = _rule(
        {
            "schema_version": "2.0",
            "name": "ifc_walls",
            "output_mode": "boolean",
            "selector": {"kind": "ifc_class", "values": ["IfcWall"]},
            "predicate": {
                "kind": "triplet",
                "attribute": {"kind": "exact", "name": "Mark"},
                "constraint": {"operator": "exists"},
            },
        }
    )
    plan = plan_rule(rule)
    assert "ifc_class" in plan.duckdb_sql.lower()


# ── AND / OR / NOT combinators ──────────────────────────────────────────


def test_planner_compiles_and_combinator() -> None:
    rule = _rule(
        {
            "schema_version": "2.0",
            "name": "walls_and_levels",
            "output_mode": "boolean",
            "selector": {
                "kind": "and",
                "children": [
                    {"kind": "category", "values": ["Walls"]},
                    {"kind": "level", "values": ["L01"]},
                ],
            },
            "predicate": {
                "kind": "triplet",
                "attribute": {"kind": "exact", "name": "Mark"},
                "constraint": {"operator": "exists"},
            },
        }
    )
    plan = plan_rule(rule)
    sql = plan.duckdb_sql.upper()
    assert " AND " in sql


def test_planner_compiles_or_combinator() -> None:
    rule = _rule(
        {
            "schema_version": "2.0",
            "name": "walls_or_floors",
            "output_mode": "boolean",
            "selector": {
                "kind": "or",
                "children": [
                    {"kind": "category", "values": ["Walls"]},
                    {"kind": "category", "values": ["Floors"]},
                ],
            },
            "predicate": {
                "kind": "triplet",
                "attribute": {"kind": "exact", "name": "Mark"},
                "constraint": {"operator": "exists"},
            },
        }
    )
    plan = plan_rule(rule)
    sql = plan.duckdb_sql.upper()
    assert " OR " in sql


def test_planner_compiles_not_combinator() -> None:
    rule = _rule(
        {
            "schema_version": "2.0",
            "name": "not_furniture",
            "output_mode": "boolean",
            "selector": {
                "kind": "not",
                "child": {"kind": "category", "values": ["Furniture"]},
            },
            "predicate": {
                "kind": "triplet",
                "attribute": {"kind": "exact", "name": "Mark"},
                "constraint": {"operator": "exists"},
            },
        }
    )
    plan = plan_rule(rule)
    sql = plan.duckdb_sql.upper()
    assert "NOT " in sql


# ── classification_code & psets_present ─────────────────────────────────


def test_planner_compiles_classification_code_selector() -> None:
    rule = _rule(
        {
            "schema_version": "2.0",
            "name": "din_330",
            "output_mode": "boolean",
            "selector": {
                "kind": "classification_code",
                "system": "din276",
                "values": ["330"],
            },
            "predicate": {
                "kind": "triplet",
                "attribute": {"kind": "exact", "name": "Mark"},
                "constraint": {"operator": "exists"},
            },
        }
    )
    plan = plan_rule(rule)
    assert "classification" in plan.duckdb_sql.lower()


def test_planner_compiles_psets_present_selector() -> None:
    rule = _rule(
        {
            "schema_version": "2.0",
            "name": "has_pset",
            "output_mode": "boolean",
            "selector": {
                "kind": "psets_present",
                "values": ["Pset_WallCommon"],
            },
            "predicate": {
                "kind": "triplet",
                "attribute": {"kind": "exact", "name": "Mark"},
                "constraint": {"operator": "exists"},
            },
        }
    )
    plan = plan_rule(rule)
    sql = plan.duckdb_sql.lower()
    assert "pset" in sql or "psets" in sql


# ── Predicate Triplet → JSON path expression ────────────────────────────


def test_planner_triplet_compiles_to_json_path() -> None:
    """A Triplet on an exact attribute should compile to a DuckDB JSON
    path access (``properties->>'IsExternal'``)."""
    rule = _rule(
        {
            "schema_version": "2.0",
            "name": "is_external",
            "output_mode": "boolean",
            "selector": {"kind": "category", "values": ["Walls"]},
            "predicate": {
                "kind": "triplet",
                "attribute": {"kind": "exact", "name": "IsExternal"},
                "constraint": {"operator": "eq", "value": True},
            },
        }
    )
    plan = plan_rule(rule)
    # Expect a JSON path access against properties for IsExternal.
    assert re.search(r"properties->>?\s*'IsExternal'", plan.duckdb_sql) is not None


# ── Bind parameters (no string interpolation of values) ─────────────────


def test_planner_uses_bind_parameters_for_values() -> None:
    """Values from constraints must NOT be string-concatenated into the SQL.

    Confirms we sit behind DuckDB's bind layer (FR-1.10 / SQL-injection
    hardening). String values that *would* require quoting in raw SQL
    appear in ``parameters`` rather than inline.
    """
    rule = _rule(
        {
            "schema_version": "2.0",
            "name": "name_eq",
            "output_mode": "boolean",
            "selector": {"kind": "category", "values": ["Walls"]},
            "predicate": {
                "kind": "triplet",
                "attribute": {"kind": "exact", "name": "Comment"},
                "constraint": {"operator": "eq", "value": "FIRE"},
            },
        }
    )
    plan = plan_rule(rule)
    # The literal "FIRE" must NOT appear quoted inline in the SQL string.
    assert "'FIRE'" not in plan.duckdb_sql
    # It must be present in the bind parameters dict.
    assert "FIRE" in plan.parameters.values()


# ── Estimated cost grows with branches ──────────────────────────────────


def test_planner_estimated_cost_grows_with_branches() -> None:
    simple = _rule(
        {
            "schema_version": "2.0",
            "name": "simple",
            "output_mode": "boolean",
            "selector": {"kind": "category", "values": ["Walls"]},
            "predicate": {
                "kind": "triplet",
                "attribute": {"kind": "exact", "name": "Mark"},
                "constraint": {"operator": "exists"},
            },
        }
    )
    complex_rule = _rule(
        {
            "schema_version": "2.0",
            "name": "complex",
            "output_mode": "boolean",
            "selector": {
                "kind": "and",
                "children": [
                    {"kind": "category", "values": ["Walls"]},
                    {
                        "kind": "or",
                        "children": [
                            {"kind": "level", "values": ["L01"]},
                            {"kind": "level", "values": ["L02"]},
                        ],
                    },
                    {
                        "kind": "not",
                        "child": {"kind": "category", "values": ["Furniture"]},
                    },
                ],
            },
            "predicate": {
                "kind": "triplet",
                "attribute": {"kind": "exact", "name": "Mark"},
                "constraint": {"operator": "exists"},
            },
        }
    )
    p_simple = plan_rule(simple)
    p_complex = plan_rule(complex_rule)
    assert p_complex.estimated_cost > p_simple.estimated_cost


# ── Projection columns sanity ───────────────────────────────────────────


def test_planner_returns_projection_columns() -> None:
    rule = _rule(
        {
            "schema_version": "2.0",
            "name": "p",
            "output_mode": "aggregate",
            "result_unit": "m3",
            "selector": {"kind": "ifc_class", "values": ["IfcWall"]},
            "formula": "Volume",
        }
    )
    plan = plan_rule(rule)
    assert isinstance(plan.projection_columns, list)
    assert len(plan.projection_columns) > 0


@pytest.mark.parametrize("formula_present", [True, False])
def test_planner_handles_aggregate_and_boolean_modes(formula_present: bool) -> None:
    body = {
        "schema_version": "2.0",
        "name": "agg" if formula_present else "boo",
        "output_mode": "aggregate" if formula_present else "boolean",
        "selector": {"kind": "ifc_class", "values": ["IfcWall"]},
    }
    if formula_present:
        body["formula"] = "Volume"
        body["result_unit"] = "m3"
    else:
        body["predicate"] = {
            "kind": "triplet",
            "attribute": {"kind": "exact", "name": "Mark"},
            "constraint": {"operator": "exists"},
        }
    rule = _rule(body)
    plan = plan_rule(rule)
    assert plan.duckdb_sql
