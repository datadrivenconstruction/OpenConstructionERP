# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure unit tests for the parametric assembly engine (Issue #365).

Database-free: exercises the parameter graph (unique names, references,
cycles), Decimal-exact resolution in dependency order, the allow-listed
round/min/max functions, and component expansion with static fallback.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.modules.assemblies.parametric import (
    expand_assembly,
    resolve_parameters,
    validate_parameter_graph,
)


def _p(name: str, kind: str, value: Any = None, formula: str | None = None) -> dict[str, Any]:
    return {"name": name, "kind": kind, "value": value, "formula": formula}


def _codes(errors: list[Any]) -> list[str]:
    return sorted(e.code for e in errors)


def test_linear_chain_resolves_in_order() -> None:
    scope, errors = resolve_parameters(
        [_p("a", "input", 2), _p("b", "calculated", formula="a + 1"), _p("c", "calculated", formula="b * 2")]
    )
    assert not errors
    assert scope["a"] == Decimal(2)
    assert scope["b"] == Decimal(3)
    assert scope["c"] == Decimal(6)


def test_diamond_dependency_evaluates_shared_node_once() -> None:
    scope, errors = resolve_parameters(
        [
            _p("a", "input", 2),
            _p("b", "calculated", formula="a + 1"),
            _p("c", "calculated", formula="a + 2"),
            _p("d", "calculated", formula="b + c"),
        ]
    )
    assert not errors
    assert scope["d"] == Decimal(7)


def test_cycle_is_detected() -> None:
    errors = validate_parameter_graph([_p("a", "calculated", formula="b + 1"), _p("b", "calculated", formula="a + 1")])
    assert "cycle" in _codes(errors)


def test_division_by_zero_is_reported() -> None:
    _scope, errors = resolve_parameters([_p("a", "input", 1), _p("b", "calculated", formula="1 / (a - 1)")])
    assert "div_by_zero" in _codes(errors)


def test_invalid_reference_is_reported() -> None:
    errors = validate_parameter_graph([_p("a", "calculated", formula="x + 1")])
    assert "invalid_ref" in _codes(errors)


def test_duplicate_name_is_reported() -> None:
    errors = validate_parameter_graph([_p("a", "input", 1), _p("a", "input", 2)])
    assert "duplicate" in _codes(errors)


def test_missing_value_and_formula_reported() -> None:
    errors = validate_parameter_graph([_p("bad", "input", None), _p("calc", "calculated", formula="")])
    assert "invalid_value" in _codes(errors)
    assert "missing_formula" in _codes(errors)


def test_round_min_max_in_formulas() -> None:
    scope, errors = resolve_parameters(
        [
            _p("a", "input", 12.5),
            _p("r", "input", 0.83),
            _p("kg", "calculated", formula="round(a * r, 1)"),
            _p("cap", "calculated", formula="min(kg, 10)"),
        ]
    )
    assert not errors
    assert scope["kg"] == Decimal("10.4")
    assert scope["cap"] == Decimal(10)


def test_decimal_precision_is_exact() -> None:
    scope, errors = resolve_parameters(
        [_p("a", "input", "0.1"), _p("b", "input", "0.2"), _p("c", "calculated", formula="a + b")]
    )
    assert not errors
    assert scope["c"] == Decimal("0.3")


def test_constant_parameter_is_usable() -> None:
    scope, errors = resolve_parameters([_p("k", "constant", "2.5"), _p("out", "calculated", formula="k * 4")])
    assert not errors
    assert scope["out"] == Decimal(10)


def test_expand_uses_formula_or_static_quantity_and_honours_overrides() -> None:
    result = expand_assembly(
        [_p("wall_area", "input", 20), _p("ratio", "input", 0.5)],
        [
            {"id": "c1", "description": "Rebar", "quantity_formula": "wall_area * ratio", "quantity": "0"},
            {"id": "c2", "description": "Concrete", "quantity_formula": None, "quantity": "3.5"},
        ],
        overrides={"wall_area": 30},
    )
    assert not result.errors
    by_id = {line.component_id: line for line in result.lines}
    assert by_id["c1"].computed_quantity == Decimal(15)
    assert by_id["c1"].has_formula
    assert by_id["c2"].computed_quantity == Decimal("3.5")
    assert not by_id["c2"].has_formula
    assert result.resolved_parameters["wall_area"] == Decimal(30)


def test_component_formula_error_falls_back_to_static_quantity() -> None:
    result = expand_assembly(
        [_p("a", "input", 2)],
        [{"id": "c1", "description": "X", "quantity_formula": "a / 0", "quantity": "9"}],
    )
    assert any(e.scope == "component" and e.code == "div_by_zero" for e in result.errors)
    assert result.lines[0].computed_quantity == Decimal(9)
